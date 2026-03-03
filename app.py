import os
import smtplib
import time
import random
import re
import requests
import googlemaps
import json
import pickle
import base64
import sys
import logging
import urllib.parse
import csv
import pandas as pd
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.message import EmailMessage
from flask import Flask, request, jsonify, Response, stream_with_context, send_file, render_template, session, redirect, url_for
from urllib.parse import urljoin
from flask_cors import CORS
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import traceback

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Clave secreta desde variable de entorno
app.secret_key = os.environ.get('SECRET_KEY', 'clave-por-defecto-cambiar')
# Configurar CORS
CORS(app, supports_credentials=True)

app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ========== CONFIGURACIÓN DESDE VARIABLES DE ENTORNO ==========
# Configuración OAuth de Gmail
SCOPES = ['https://www.googleapis.com/auth/gmail.send']
REDIRECT_URI = os.environ.get('REDIRECT_URI', 'https://yerbamate.onrender.com/oauth2callback')

# Credenciales de Google desde variables de entorno
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
GOOGLE_PROJECT_ID = os.environ.get('GOOGLE_PROJECT_ID', 'automatizacion-485503')

# ========== API KEYS ==========
GOOGLE_MAPS_KEY = (
    os.environ.get('Maps_KEY') or
    os.environ.get('GOOGLE_MAPS_KEY') or
    os.environ.get('GMAPS_API_KEY') or
    ''
)

GEMINI_API_KEY = (
    os.environ.get('GEMINI_API_KEY') or
    os.environ.get('GEMINI_KEY') or
    ''
)

# Logging de configuración
logger.info("=" * 50)
logger.info("CONFIGURACIÓN DE API KEYS:")
logger.info(f"📌 Maps_KEY: {'✅ Configurada' if GOOGLE_MAPS_KEY else '❌ NO CONFIGURADA'}")
logger.info(f"📌 GEMINI_API_KEY: {'✅ Configurada' if GEMINI_API_KEY else '❌ NO CONFIGURADA'}")
logger.info(f"📌 GMAIL_CLIENT_ID: {'✅ Configurada' if GOOGLE_CLIENT_ID else '❌ NO CONFIGURADA'}")
logger.info("=" * 50)

# Inicializar Google Maps client (solo si hay key)
gmaps = None
if GOOGLE_MAPS_KEY:
    try:
        gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY, timeout=5)
        logger.info("✅ Google Maps Client inicializado")
    except Exception as e:
        logger.error(f"❌ Error inicializando Google Maps: {e}")

# ========== FUNCIONES AUXILIARES ==========
def validar_email(email):
    """Valida formato de email."""
    if not email or not isinstance(email, str):
        return False
    email = email.strip()
    patron = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(patron, email))

def scraping_basico_contacto(url_base):
    """
    Versión simplificada de scraping que solo busca emails con regex.
    Sin IA para evitar timeouts.
    """
    info = {"email": "", "facebook": "", "instagram": ""}
    if not url_base or not isinstance(url_base, str) or not url_base.startswith(('http://', 'https://')):
        return info
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html',
        'Accept-Language': 'es-ES,es;q=0.9',
        'Connection': 'close',  # Cerrar conexión después
    }
    
    try:
        # Timeout muy corto
        res = requests.get(url_base, timeout=2, headers=headers, allow_redirects=True)
        if res.status_code != 200:
            return info
        
        texto_pagina = res.text[:10000]  # Solo primeros 10000 caracteres
        
        # Buscar emails con regex simple
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        found_emails = re.findall(email_pattern, texto_pagina, re.IGNORECASE)
        
        for e in found_emails:
            if validar_email(e) and not any(ext in e.lower() for ext in ['.png', '.jpg', '.gif', '.css', '.js']):
                info["email"] = e.lower()
                break
        
        # Buscar redes sociales básicas
        soup = BeautifulSoup(texto_pagina, 'html.parser')
        for a in soup.find_all('a', href=True)[:20]:  # Limitar búsqueda
            href = a['href'].lower()
            if 'facebook.com' in href and 'sharer' not in href and not info["facebook"]:
                info["facebook"] = a['href']
            if 'instagram.com' in href and '/p/' not in href and not info["instagram"]:
                info["instagram"] = a['href']
        
    except Exception as e:
        logger.debug(f"Error en scraping básico: {e}")
    
    return info

def enviar_mail_soberania(smtp_user, smtp_pass, destino, asunto, cuerpo, adjuntar_imagen):
    """Envía email vía Gmail con adjunto (Método SMTP original)."""
    if not destino or not validar_email(destino):
        return False, "Email inválido"
    
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
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=10)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, destino, msg.as_string())
        server.quit()
        return True, "Enviado"
    except Exception as e:
        return False, f"Error: {str(e)[:30]}"

# ========== RUTAS DE AUTENTICACIÓN GMAIL API ==========
@app.route('/connect_gmail')
def connect_gmail():
    """Inicia el flujo de autorización de Gmail."""
    try:
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            return jsonify({'error': 'Configuración de Gmail no encontrada'}), 500
        
        client_config = {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "project_id": GOOGLE_PROJECT_ID,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uris": [REDIRECT_URI]
            }
        }
        
        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        session['state'] = state
        return redirect(authorization_url)
        
    except Exception as e:
        logger.error(f"Error en connect_gmail: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/oauth2callback')
def oauth2callback():
    """Callback después de autorizar la aplicación."""
    try:
        state = session.get('state')
        if not state:
            return redirect('/?error=no_state')
        
        client_config = {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "project_id": GOOGLE_PROJECT_ID,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uris": [REDIRECT_URI]
            }
        }
        
        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            state=state,
            redirect_uri=REDIRECT_URI
        )
        
        flow.fetch_token(authorization_response=request.url)
        
        credentials = flow.credentials
        session['credentials'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        
        return redirect('/?auth_success=true')
        
    except Exception as e:
        logger.error(f"Error en oauth2callback: {e}")
        return redirect(f'/?error={str(e)}')

@app.route('/check_gmail_auth')
def check_gmail_auth():
    return jsonify({'authenticated': 'credentials' in session})

@app.route('/logout_gmail')
def logout_gmail():
    if 'credentials' in session:
        del session['credentials']
    return jsonify({'success': True})

# ========== RUTA DE ENVÍO MASIVO POR API GMAIL ==========
@app.route('/send_bulk_emails_gmail', methods=['POST'])
def send_bulk_emails_gmail():
    """Envía emails masivos usando la API de Gmail."""
    if 'credentials' not in session:
        return jsonify({
            'success': False,
            'error': 'No autorizado',
            'needs_auth': True,
            'auth_url': '/connect_gmail'
        })
    
    data = request.json
    selected = data.get('leads', [])[:20]  # Limitar a 20 emails por lote
    subject = data.get('subject', 'Oferta Mayorista - Yerba Mate Soberanía')
    body = data.get('body', '')
    attach_img = data.get('attach_image', False)
    
    creds_data = session['credentials']
    creds = Credentials(
        token=creds_data['token'],
        refresh_token=creds_data.get('refresh_token'),
        token_uri=creds_data['token_uri'],
        client_id=creds_data['client_id'],
        client_secret=creds_data['client_secret'],
        scopes=creds_data['scopes']
    )
    
    def generate():
        total = len(selected)
        yield f"data: {json.dumps({'status': 'start', 'total': total})}\n\n"
        
        try:
            service = build('gmail', 'v1', credentials=creds)
            
            for i, lead in enumerate(selected):
                try:
                    if not lead.get('email'):
                        yield f"data: {json.dumps({'progress': i+1, 'msg': 'Sin email', 'index': lead.get('original_index'), 'success': False})}\n\n"
                        continue
                    
                    message = EmailMessage()
                    
                    cuerpo_personalizado = body
                    if '{nombre}' in cuerpo_personalizado:
                        cuerpo_personalizado = cuerpo_personalizado.replace('{nombre}', lead.get('nombre', '')[:50])
                    
                    message.set_content(cuerpo_personalizado)
                    message['To'] = lead['email']
                    message['From'] = 'me'
                    message['Subject'] = subject[:100]
                    
                    if attach_img and os.path.exists('producto.png'):
                        with open('producto.png', 'rb') as f:
                            image_data = f.read()
                        message.add_attachment(image_data, maintype='image', subtype='png', filename='producto.png')
                    
                    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
                    create_message = {'raw': encoded_message}
                    
                    service.users().messages().send(userId='me', body=create_message).execute()
                    
                    yield f"data: {json.dumps({'progress': i+1, 'msg': 'Enviado', 'index': lead.get('original_index'), 'success': True})}\n\n"
                    
                    if i < total - 1:
                        time.sleep(random.uniform(1, 2))
                    
                except Exception as e:
                    yield f"data: {json.dumps({'progress': i+1, 'msg': f'Error', 'index': lead.get('original_index'), 'success': False})}\n\n"
                
                sys.stdout.flush()
            
            yield f"data: {json.dumps({'status': 'finished'})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

# ========== RUTAS DE RESPALDO (SMTP) ==========
@app.route('/start_email_campaign', methods=['POST'])
def start_email_campaign():
    """Campaña de emails con SSE (Método SMTP original)."""
    data = request.json
    selected = data.get('leads', [])[:20]
    user = data.get('email_user')
    password = data.get('email_pass')
    subject = data.get('subject', 'Oferta Mayorista - Yerba Mate Soberanía')
    body = data.get('body')
    attach_img = str(data.get('attach_image')).lower() == 'true'

    def generate():
        total = len(selected)
        yield f"data: {json.dumps({'status': 'start', 'total': total})}\n\n"
        
        for i, lead in enumerate(selected):
            try:
                cuerpo_personalizado = body
                if '{nombre}' in cuerpo_personalizado:
                    cuerpo_personalizado = cuerpo_personalizado.replace('{nombre}', lead.get('nombre', '')[:50])
                
                ok, msg = enviar_mail_soberania(
                    user, password, lead.get('email'), subject, cuerpo_personalizado, attach_img
                )
            except:
                ok, msg = False, "Error"
            
            yield f"data: {json.dumps({'progress': i+1, 'msg': msg, 'index': lead.get('original_index'), 'success': ok})}\n\n"
            sys.stdout.flush()
        
        yield f"data: {json.dumps({'status': 'finished'})}\n\n"
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

# ========== RUTAS PRINCIPALES ==========
@app.route('/')
def index():
    try:
        return render_template('index.html')
    except:
        return "Bienvenido a Yerba Soberanía API", 200

@app.route('/producto.png')
def get_producto_image():
    if os.path.exists('producto.png'):
        return send_file('producto.png', mimetype='image/png')
    return "Archivo no encontrado", 404

# ========== RUTA DE BÚSQUEDA SIMPLIFICADA ==========
@app.route('/search_places', methods=['POST'])
def search_places():
    """Versión simplificada y rápida de búsqueda."""
    try:
        data = request.get_json(silent=True) or {}
        zona = data.get('zona', '').strip()
        
        # Validación rápida
        if not zona:
            return jsonify({'success': False, 'error': 'Zona no especificada', 'leads': []})
        
        if not gmaps:
            return jsonify({'success': False, 'error': 'Google Maps no configurado', 'leads': []})
        
        logger.info(f"Buscando en: {zona}")
        
        # Búsqueda simple - solo una query
        try:
            response = gmaps.places(query=f"dietetica {zona}", language='es')
        except Exception as e:
            logger.error(f"Error en places: {e}")
            return jsonify({'success': False, 'error': 'Error en búsqueda', 'leads': []})
        
        if not response or 'results' not in response:
            return jsonify({'success': True, 'leads': [], 'total': 0})
        
        # Limitar a 10 resultados para máxima velocidad
        results = response.get('results', [])[:10]
        leads = []
        
        for idx, place in enumerate(results):
            try:
                # Datos básicos del lugar (sin detalles adicionales para ahorrar tiempo)
                nombre = place.get('name', 'Sin nombre')[:100]
                direccion = place.get('formatted_address', 'Sin dirección')[:200]
                
                # Intentar obtener teléfono y web de los detalles básicos
                telefono = ''
                web = ''
                
                # Solo obtener detalles si es necesario (menos de 5 lugares para no demorar)
                if idx < 3 and place.get('place_id'):
                    try:
                        det = gmaps.place(place['place_id'], fields=['formatted_phone_number', 'website'])
                        if det and 'result' in det:
                            telefono = det['result'].get('formatted_phone_number', '')
                            web = det['result'].get('website', '')
                    except:
                        pass
                
                # Scrapping básico solo para los primeros 2 con web
                email = ''
                facebook = ''
                instagram = ''
                
                if web and idx < 2:  # Solo para los primeros 2 con web
                    contacto = scraping_basico_contacto(web)
                    email = contacto.get('email', '')
                    facebook = contacto.get('facebook', '')
                    instagram = contacto.get('instagram', '')
                
                leads.append({
                    'nombre': nombre,
                    'direccion': direccion,
                    'telefono': re.sub(r'\D', '', telefono)[:15] if telefono else '',
                    'tel_display': telefono[:30] if telefono else 'No disponible',
                    'email': email,
                    'facebook': facebook,
                    'instagram': instagram,
                    'web': web or ''
                })
                
            except Exception as e:
                logger.error(f"Error procesando lugar {idx}: {e}")
                continue
        
        logger.info(f"Encontrados {len(leads)} leads")
        
        return jsonify({
            'success': True,
            'leads': leads,
            'total': len(leads)
        })
        
    except Exception as e:
        logger.error(f"Error general: {e}")
        return jsonify({'success': False, 'error': str(e)[:100], 'leads': []})

# ========== RUTA DE GENERACIÓN CSV ==========
@app.route('/generate_csv', methods=['POST'])
def generate_csv():
    try:
        data = request.json
        selected = data.get('leads', [])
        
        if not selected:
            return jsonify({'success': False, 'error': 'No hay leads'})
        
        df = pd.DataFrame(selected)
        csv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'leads.csv')
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        
        return jsonify({'success': True, 'csv_url': '/download_csv'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/download_csv', methods=['GET'])
def download_csv():
    csv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'leads.csv')
    if os.path.exists(csv_path):
        return send_file(csv_path, as_attachment=True, download_name='leads.csv')
    return "Archivo no encontrado", 404

# ========== RUTA DE IA SIMPLIFICADA ==========
@app.route('/api/ai_query', methods=['POST'])
def ai_query():
    if not GEMINI_API_KEY:
        return jsonify({'text': 'IA no disponible'})
    
    try:
        data = request.json
        prompt = data.get('prompt', '')
        
        # Respuestas predefinidas para casos comunes
        if "consejos" in prompt.lower():
            return jsonify({'text': '1. Origen misionero\n2. Precios competitivos\n3. Ofrece muestras'})
        if "mensaje" in prompt.lower():
            return jsonify({'text': 'Hola {nombre}, te comparto precios mayoristas de Yerba Mate Soberanía.'})
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 100}
        }
        
        res = requests.post(url, json=payload, timeout=3)
        
        if res.status_code == 200:
            result = res.json()
            if 'candidates' in result:
                text = result['candidates'][0]['content']['parts'][0]['text']
                return jsonify({'text': text})
        
        return jsonify({'text': 'No pude procesar la solicitud'})
        
    except Exception as e:
        return jsonify({'text': 'Error en IA'})

# ========== RUTAS DE DIAGNÓSTICO ==========
@app.route('/debug/keys', methods=['GET'])
def debug_keys():
    return jsonify({
        'maps_key_configured': bool(GOOGLE_MAPS_KEY),
        'gemini_key_configured': bool(GEMINI_API_KEY),
        'gmaps_client_initialized': gmaps is not None,
        'gmail_auth_configured': bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
        'status': 'running'
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

