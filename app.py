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
    """Busca correos electrónicos y redes sociales analizando la web."""
    info = {"email": "", "facebook": "", "instagram": ""}
    if not url_base or not url_base.startswith('http'):
        return info
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'}
    try:
        res = requests.get(url_base, timeout=6, headers=headers)
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
            
            if exhaustivo and any(term in href for term in ['contacto', 'contact', 'nosotros', 'about', 'info']):
                links_to_check.append(h_full)

        if exhaustivo:
            for link in list(set(links_to_check))[:2]:
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

def enviar_mail_soberania(smtp_user, smtp_pass, destino, asunto, cuerpo, imagen_url):
    """Lógica de envío SMTP con descarga de imagen adjunta y manejo de errores detallado."""
    try:
        msg = MIMEMultipart()
        msg['From'] = f"Juan Ignacio Lewczuk <{smtp_user}>"
        msg['To'] = destino
        msg['Subject'] = asunto
        msg.attach(MIMEText(cuerpo, 'plain'))

        img_data = None
        if imagen_url:
            try:
                raw_url = imagen_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                img_data = requests.get(raw_url, timeout=12).content
            except Exception as e:
                print(f"Error descargando imagen de GitHub: {e}")

        if not img_data and os.path.exists('producto.png'):
            try:
                with open('producto.png', 'rb') as f:
                    img_data = f.read()
            except: pass

        if img_data:
            try:
                adjunto = MIMEImage(img_data)
                adjunto.add_header('Content-Disposition', 'attachment', filename="Yerba_Mate_Soberania.png")
                msg.attach(adjunto)
            except: pass

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, destino, msg.as_string())
        server.quit()
        return True, "Enviado correctamente"
    except smtplib.SMTPAuthenticationError:
        return False, "Autenticación fallida: Revisa tu clave de 16 letras"
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search_places', methods=['POST'])
def search_places():
    data = request.json
    zona = data.get('zona')
    exhaustivo = data.get('exhaustivo', False)
    if not gmaps: return jsonify({'error': 'Google Maps API no configurada'}), 500
    try:
        response = gmaps.places(query=f"dieteticas en {zona}")
        results = response.get('results', [])
        leads = []
        for p in results[:15]: # Límite para evitar Timeouts
            try:
                det = gmaps.place(place_id=p['place_id'], fields=['name', 'formatted_address', 'formatted_phone_number', 'website'])['result']
                tel_raw = det.get('formatted_phone_number', '')
                tel_clean = re.sub(r'\D', '', tel_raw)
                if tel_clean and not tel_clean.startswith('54'): tel_clean = '54' + tel_clean
                web = det.get('website', '')
                contacto = scraping_profundo_contacto(web, exhaustivo) if web else {"email": "", "facebook": "", "instagram": ""}
                leads.append({
                    'id': p['place_id'], 'nombre': det.get('name'), 'direccion': det.get('formatted_address'),
                    'telefono': tel_clean, 'tel_display': tel_raw, 'email': contacto["email"],
                    'facebook': contacto["facebook"], 'instagram': contacto["instagram"], 'web': web
                })
            except: continue
        return jsonify({'success': True, 'leads': leads})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/start_email_campaign', methods=['POST'])
def start_email_campaign():
    data = request.json
    selected = data.get('leads', [])
    user = data.get('email_user')
    password = data.get('email_pass')
    subject = data.get('subject')
    body = data.get('body')
    image_url = data.get('image_url')

    def generate():
        total = len(selected)
        yield f"data: {json.dumps({'status': 'start', 'total': total})}\n\n"
        for i, lead in enumerate(selected):
            # Pausa para evitar que Gmail bloquee la cuenta
            if i > 0: time.sleep(random.randint(25, 40))
            
            cuerpo_final = body.replace('{nombre}', lead['nombre']).replace('{direccion}', lead['direccion'])
            asunto_final = subject.replace('{nombre}', lead['nombre'])
            
            ok, msg = enviar_mail_soberania(user, password, lead['email'], asunto_final, cuerpo_final, image_url)
            
            res_info = {'progress': i+1, 'msg': msg, 'index': lead.get('original_index'), 'success': ok}
            yield f"data: {json.dumps(res_info)}\n\n"
        yield f"data: {json.dumps({'status': 'finished'})}\n\n"
        
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route('/api/ai_query', methods=['POST'])
def ai_query():
    if not GEMINI_API_KEY: return jsonify({'error': 'Variable GEMINI_API_KEY no configurada'}), 500
    data = request.json
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": data.get('prompt')}]}],
        "systemInstruction": {"parts": [{"text": data.get('systemInstruction', 'Eres un experto en ventas.')}]}
    }
    try:
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code == 429: return jsonify({'error': 'QUOTA_EXCEEDED', 'retry_after': 20}), 429
        result = res.json()
        if 'candidates' in result:
            text = result['candidates'][0]['content']['parts'][0]['text']
            return jsonify({'text': text})
        return jsonify({'error': 'Sin respuesta de IA'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
