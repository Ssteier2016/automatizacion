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
import sys
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# API KEYS - Variables de entorno
GOOGLE_MAPS_KEY = os.environ.get('GOOGLE_MAPS_KEY', '')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

# Verificar API keys
if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY no configurada en variables de entorno")
if not GOOGLE_MAPS_KEY:
    logger.error("GOOGLE_MAPS_KEY no configurada en variables de entorno")

try:
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY) if GOOGLE_MAPS_KEY else None
except Exception as e:
    logger.error(f"Error inicializando Google Maps: {e}")
    gmaps = None

@app.route('/producto.png')
def get_producto_image():
    """Sirve la imagen del producto."""
    if os.path.exists('producto.png'):
        return send_file('producto.png', mimetype='image/png')
    return "Archivo producto.png no encontrado", 404

def validar_email(email):
    """Valida formato de email."""
    patron = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(patron, email))

def scraping_profundo_contacto(url_base, exhaustivo=False):
    """Busca emails y redes sociales - OPTIMIZADO."""
    info = {"email": "", "facebook": "", "instagram": ""}
    if not url_base or not url_base.startswith('http'):
        return info
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        # Timeout corto para no bloquear
        res = requests.get(url_base, timeout=2, headers=headers)
        if res.status_code != 200: 
            return info
        
        texto_pagina = res.text
        # Buscar emails con regex
        found_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', texto_pagina)
        soup = BeautifulSoup(texto_pagina, 'html.parser')
        
        # Buscar redes sociales
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'facebook.com' in href and not info["facebook"]:
                info["facebook"] = a['href']
            if 'instagram.com' in href and not info["instagram"]:
                info["instagram"] = a['href']

        # Filtrar emails válidos
        for e in found_emails:
            if validar_email(e) and not e.lower().endswith(('.png', '.jpg', '.gif', '.css')):
                info["email"] = e.lower()
                break
    except Exception as e:
        logger.debug(f"Error en scraping: {e}")
    
    return info

def enviar_mail_soberania(smtp_user, smtp_pass, destino, asunto, cuerpo, adjuntar_imagen):
    """Envía email vía Gmail con adjunto."""
    msg = MIMEMultipart()
    msg['From'] = f"Juan Ignacio Lewczuk <{smtp_user}>"
    msg['To'] = destino
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo, 'plain', 'utf-8'))

    if adjuntar_imagen and os.path.exists('producto.png'):
        try:
            with open('producto.png', 'rb') as f:
                img_data = f.read()
            adjunto = MIMEImage(img_data)
            adjunto.add_header('Content-Disposition', 'attachment', filename="producto_soberania.png")
            msg.attach(adjunto)
        except Exception as e:
            logger.error(f"Error adjuntando imagen: {e}")

    try:
        # Timeout para evitar worker timeout
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=10)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, destino, msg.as_string())
        server.quit()
        return True, "Enviado"
    except smtplib.SMTPAuthenticationError:
        return False, "Error: Verifica 2FA y contraseña"
    except smtplib.SMTPException as e:
        return False, f"Error SMTP"
    except Exception as e:
        return False, f"Error"

@app.route('/')
def index():
    """Página principal."""
    return render_template('index.html')

@app.route('/search_places', methods=['POST'])
def search_places():
    """Busca dietéticas en Google Maps."""
    data = request.json
    zona = data.get('zona')
    
    if not gmaps:
        return jsonify({'error': 'Google Maps no configurado'}), 500
    
    try:
        response = gmaps.places(query=f"dieteticas en {zona}")
        results = response.get('results', [])
        
        leads = []
        # Limitar a 8 resultados para evitar timeout
        for p in results[:8]:
            try:
                det = gmaps.place(place_id=p['place_id'], 
                                  fields=['name', 'formatted_address', 'formatted_phone_number', 'website'])['result']
                
                tel_raw = det.get('formatted_phone_number', '')
                tel_clean = re.sub(r'\D', '', tel_raw)
                if tel_clean and not tel_clean.startswith('54'):
                    tel_clean = '54' + tel_clean
                
                web = det.get('website', '')
                contacto = scraping_profundo_contacto(web, False) if web else {"email": "", "facebook": "", "instagram": ""}

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
            except Exception as e:
                logger.error(f"Error procesando lugar: {e}")
                continue

        return jsonify({'success': True, 'leads': leads})
    except Exception as e:
        logger.error(f"Error en search_places: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/start_email_campaign', methods=['POST'])
def start_email_campaign():
    """Campaña de emails con SSE."""
    data = request.json
    selected = data.get('leads', [])
    user = data.get('email_user')
    password = data.get('email_pass')
    subject = data.get('subject', 'Oferta Mayorista - Yerba Mate Soberanía')
    body = data.get('body')
    attach_img = str(data.get('attach_image')).lower() == 'true'

    def generate():
        total = len(selected)
        yield f"data: {json.dumps({'status': 'start', 'total': total})}\n\n"
        
        for i, lead in enumerate(selected):
            # Pausa entre emails
            if i > 0:
                time.sleep(random.randint(2, 4))
            
            try:
                cuerpo_personalizado = body.replace('{nombre}', lead['nombre'])
                ok, msg = enviar_mail_soberania(user, password, lead['email'], subject, cuerpo_personalizado, attach_img)
            except Exception as e:
                ok = False
                msg = "Error"
            
            progreso = {
                'progress': i+1, 
                'msg': msg, 
                'index': lead.get('original_index'), 
                'success': ok
            }
            yield f"data: {json.dumps(progreso)}\n\n"
            sys.stdout.flush()
        
        yield f"data: {json.dumps({'status': 'finished'})}\n\n"
    
    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/api/ai_query', methods=['POST'])
def ai_query():
    """Proxy para Gemini API con manejo de errores."""
    if not GEMINI_API_KEY:
        return jsonify({'error': 'API key no configurada'}), 500
    
    data = request.json
    prompt = data.get('prompt')
    system_instruction = data.get('systemInstruction', 'Asistente comercial.')
    timeout = data.get('timeout', 8)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 150,
            "topP": 0.95
        }
    }
    
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    try:
        res = requests.post(url, json=payload, timeout=timeout)
        
        if res.status_code == 429:
            return jsonify({'error': 'QUOTA_EXCEEDED', 'retry_after': 10}), 429
        
        if res.status_code != 200:
            logger.error(f"Gemini error {res.status_code}: {res.text}")
            return jsonify({'error': 'API_ERROR'}), res.status_code

        result = res.json()
        
        if 'candidates' in result and len(result['candidates']) > 0:
            text = result['candidates'][0]['content']['parts'][0]['text']
            return jsonify({'text': text})
        
        return jsonify({'error': 'Sin respuesta'}), 500
        
    except requests.exceptions.Timeout:
        return jsonify({'error': 'TIMEOUT'}), 504
    except Exception as e:
        logger.error(f"Error en ai_query: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
