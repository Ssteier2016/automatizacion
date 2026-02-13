import os
import smtplib
import time
import random
import re
import requests
import googlemaps
import json
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from flask import Flask, request, jsonify, Response, stream_with_context, send_file, render_template
from urllib.parse import urljoin
from flask_cors import CORS

app = Flask(__name__)
# Habilitar CORS para permitir que el navegador se comunique con el servidor en Render
CORS(app)

app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# API KEYS - Se obtienen de las variables de entorno configuradas en Render
GOOGLE_MAPS_KEY = os.environ.get('GOOGLE_MAPS_KEY', 'AIzaSyBGJ8B2z9p52LM-x9vEwxO9pmx8V9w7Ws4')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

try:
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)
except Exception as e:
    print(f"Error inicializando Google Maps: {e}")
    gmaps = None

@app.route('/producto.png')
def get_producto_image():
    """Sirve la imagen del producto si existe en la raíz del proyecto."""
    if os.path.exists('producto.png'):
        return send_file('producto.png', mimetype='image/png')
    return "Archivo producto.png no encontrado en la raíz", 404

def validar_email(email):
    """Valida el formato de un correo electrónico mediante expresiones regulares."""
    patron = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(patron, email))

def scraping_profundo_contacto(url_base, exhaustivo=False):
    """Busca correos electrónicos y redes sociales realizando un análisis del sitio web."""
    info = {"email": "", "facebook": "", "instagram": ""}
    if not url_base or not url_base.startswith('http'):
        return info
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'}
    try:
        # Timeout bajo para evitar bloqueos del worker en Render (Error 502)
        res = requests.get(url_base, timeout=5, headers=headers)
        if res.status_code != 200: return info
        
        texto_pagina = res.text
        found_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', texto_pagina)
        soup = BeautifulSoup(texto_pagina, 'html.parser')
        
        links_to_check = []
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            h_full = urljoin(url_base, a['href'])
            
            if 'facebook.com' in href and not info["facebook"]:
                info["facebook"] = a['href']
            if 'instagram.com' in href and not info["instagram"]:
                info["instagram"] = a['href']
            
            # Si es exhaustivo, buscamos páginas de contacto
            if exhaustivo and any(term in href for term in ['contacto', 'contact', 'nosotros', 'about', 'info']):
                links_to_check.append(h_full)

        if exhaustivo:
            for link in list(set(links_to_check))[:2]: # Limitado para evitar Timeouts
                try:
                    r_sub = requests.get(link, timeout=4, headers=headers)
                    found_emails.extend(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', r_sub.text))
                except:
                    pass

        for e in found_emails:
            if validar_email(e) and not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.pdf', '.css')):
                info["email"] = e.lower()
                break
    except:
        pass
    return info

def enviar_mail_soberania(smtp_user, smtp_pass, destino, asunto, cuerpo, adjuntar_imagen):
    """Lógica para el envío de correos electrónicos vía Gmail con soporte de adjuntos."""
    msg = MIMEMultipart()
    msg['From'] = f"Juan Ignacio Lewczuk <{smtp_user}>"
    msg['To'] = destino
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo, 'plain'))

    if adjuntar_imagen and os.path.exists('producto.png'):
        try:
            with open('producto.png', 'rb') as f:
                img_data = f.read()
            adjunto = MIMEImage(img_data)
            adjunto.add_header('Content-Disposition', 'attachment', filename="producto_soberania.png")
            msg.attach(adjunto)
        except Exception as e:
            print(f"Error adjuntando imagen: {e}")

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, destino, msg.as_string())
        server.quit()
        return True, "Enviado"
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    """Sirve la interfaz principal de la aplicación."""
    return render_template('index.html')

@app.route('/search_places', methods=['POST'])
def search_places():
    """Endpoint para buscar dietéticas en Google Maps y extraer información de contacto."""
    data = request.json
    zona = data.get('zona')
    exhaustivo = data.get('exhaustivo', False)
    
    if not gmaps:
        return jsonify({'error': 'Google Maps API Key no configurada'}), 500
    
    try:
        # Búsqueda inicial en Google Maps
        response = gmaps.places(query=f"dieteticas en {zona}")
        results = response.get('results', [])
        
        leads = []
        # Limitamos a 20 resultados para garantizar respuesta antes de los 30s de Render
        for p in results[:20]:
            try:
                # Obtener detalles profundos de cada lugar
                det = gmaps.place(place_id=p['place_id'], 
                                  fields=['name', 'formatted_address', 'formatted_phone_number', 'website'])['result']
                
                tel_raw = det.get('formatted_phone_number', '')
                tel_clean = re.sub(r'\D', '', tel_raw)
                if tel_clean and not tel_clean.startswith('54'):
                    tel_clean = '54' + tel_clean
                
                web = det.get('website', '')
                # Realizar scraping para encontrar email y redes sociales
                contacto = scraping_profundo_contacto(web, exhaustivo) if web else {"email": "", "facebook": "", "instagram": ""}

                leads.append({
                    'nombre': det.get('name'),
                    'direccion': det.get('formatted_address'),
                    'telefono': tel_clean,
                    'tel_display': tel_raw,
                    'email': contacto["email"],
                    'facebook': contacto["facebook"],
                    'instagram': contacto["instagram"],
                    'web': web
                })
            except:
                continue

        return jsonify({'success': True, 'leads': leads})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/start_email_campaign', methods=['POST'])
def start_email_campaign():
    """Endpoint que procesa la campaña de emails y transmite el progreso en tiempo real (SSE)."""
    data = request.json
    selected = data.get('leads', [])
    user = data.get('email_user')
    password = data.get('email_pass')
    subject = data.get('subject', 'Yerba Mate Soberanía - Oferta Mayorista')
    body = data.get('body')
    attach_img = str(data.get('attach_image')).lower() == 'true'

    def generate():
        total = len(selected)
        yield f"data: {json.dumps({'status': 'start', 'total': total})}\n\n"
        
        for i, lead in enumerate(selected):
            # Pausa para evitar bloqueos de seguridad de Gmail
            if i > 0:
                time.sleep(random.randint(4, 7))
            
            cuerpo_personalizado = body.replace('{nombre}', lead['nombre'])
            ok, msg = enviar_mail_soberania(user, password, lead['email'], subject, cuerpo_personalizado, attach_img)
            
            # Diccionario de actualización separado para cumplir con sintaxis de Python 3.11 en f-strings
            progreso = {
                'progress': i+1, 
                'msg': msg, 
                'index': lead.get('original_index'), 
                'success': ok
            }
            yield f"data: {json.dumps(progreso)}\n\n"
        
        yield f"data: {json.dumps({'status': 'finished'})}\n\n"
        
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route('/api/ai_query', methods=['POST'])
def ai_query():
    """Proxy de seguridad para realizar consultas a la API de Gemini."""
    if not GEMINI_API_KEY:
        return jsonify({'error': 'Variable GEMINI_API_KEY no configurada en Render'}), 500
    
    data = request.json
    prompt = data.get('prompt')
    system_instruction = data.get('systemInstruction', 'Eres un asistente experto en prospección comercial.')

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system_instruction}]}
    }

    try:
        res = requests.post(url, json=payload, timeout=25)
        result = res.json()
        
        # Manejo de cuota agotada (Error 429)
        if res.status_code == 429:
            return jsonify({'error': 'QUOTA_EXCEEDED', 'retry_after': 10}), 429

        if 'candidates' in result and len(result['candidates']) > 0:
            text = result['candidates'][0]['content']['parts'][0]['text']
            return jsonify({'text': text})
            
        return jsonify({'error': 'No se obtuvo respuesta de la IA'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Configuración de puerto dinámico para despliegue en Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
