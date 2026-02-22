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

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Clave secreta desde variable de entorno
app.secret_key = os.environ.get('SECRET_KEY', 'clave-por-defecto-cambiar')
CORS(app)

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

# Logging de configuración (sin mostrar las claves completas)
logger.info("=" * 50)
logger.info("CONFIGURACIÓN DE API KEYS:")
logger.info(f"📌 Maps_KEY: {'✅ Configurada' if GOOGLE_MAPS_KEY else '❌ NO CONFIGURADA'}")
logger.info(f"📌 GEMINI_API_KEY: {'✅ Configurada' if GEMINI_API_KEY else '❌ NO CONFIGURADA'}")
logger.info(f"📌 GMAIL_CLIENT_ID: {'✅ Configurada' if GOOGLE_CLIENT_ID else '❌ NO CONFIGURADA'}")
logger.info(f"📌 REDIRECT_URI: {REDIRECT_URI}")
logger.info("=" * 50)

# Inicializar Google Maps client
try:
    if GOOGLE_MAPS_KEY:
        gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY, timeout=10)
        # Test rápido
        try:
            test = gmaps.geocode("Buenos Aires")
            logger.info("✅ Google Maps API funcionando correctamente")
        except Exception as e:
            logger.error(f"❌ Google Maps API test falló: {e}")
            gmaps = None
    else:
        gmaps = None
        logger.error("❌ Maps_KEY no está configurada")
except Exception as e:
    logger.error(f"❌ Error inicializando Google Maps: {e}")
    gmaps = None

# ========== FUNCIONES AUXILIARES ==========
def validar_email(email):
    """Valida formato de email."""
    if not email:
        return False
    patron = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(patron, email))

def scraping_profundo_contacto(url_base, exhaustivo=False):
    """Busca emails y redes sociales con timeout corto."""
    info = {"email": "", "facebook": "", "instagram": ""}
    if not url_base or not url_base.startswith('http'):
        return info
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'es-ES,es;q=0.9',
        'Connection': 'keep-alive',
    }
    
    try:
        res = requests.get(url_base, timeout=3, headers=headers, allow_redirects=True)
        if res.status_code != 200: 
            return info
        
        texto_pagina = res.text
        
        # Buscar emails
        email_patterns = [
            r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
            r'email["\s:=]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            r'mail["\s:=]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            r'contacto["\s:=]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
        ]
        
        for pattern in email_patterns:
            found_emails = re.findall(pattern, texto_pagina, re.IGNORECASE)
            for e in found_emails:
                if validar_email(e) and not any(ext in e.lower() for ext in ['.png', '.jpg', '.gif', '.css', '.js']):
                    info["email"] = e.lower()
                    break
            if info["email"]:
                break
        
        # Buscar redes sociales
        soup = BeautifulSoup(texto_pagina, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'facebook.com' in href and not info["facebook"]:
                info["facebook"] = a['href']
            if 'instagram.com' in href and not info["instagram"]:
                info["instagram"] = a['href']
            if info["facebook"] and info["instagram"]:
                break
                
    except requests.Timeout:
        logger.debug(f"Timeout en scraping: {url_base}")
    except Exception as e:
        logger.debug(f"Error en scraping: {e}")
    
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
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=15)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, destino, msg.as_string())
        server.quit()
        return True, "Enviado"
    except smtplib.SMTPAuthenticationError:
        return False, "Error: Verifica 2FA y contraseña"
    except Exception as e:
        return False, f"Error: {str(e)[:30]}"

# ========== RUTAS DE AUTENTICACIÓN GMAIL API ==========
@app.route('/connect_gmail')
def connect_gmail():
    """Inicia el flujo de autorización de Gmail."""
    try:
        # Verificar que las credenciales están configuradas
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            logger.error("Credenciales de Google no configuradas en variables de entorno")
            return jsonify({'error': 'Configuración de Gmail no encontrada'}), 500
        
        # Configuración OAuth desde variables de entorno
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
        logger.info(f"Redirigiendo a autorización Gmail")
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
            logger.error("No hay state en sesión")
            return redirect('/?error=no_state')
        
        # Configuración OAuth desde variables de entorno
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
        
        # Obtener el código de autorización de la URL
        flow.fetch_token(authorization_response=request.url)
        
        # Guardar credenciales
        credentials = flow.credentials
        session['credentials'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        
        logger.info("✅ Autorización de Gmail exitosa")
        return redirect('/?auth_success=true')
        
    except Exception as e:
        logger.error(f"Error en oauth2callback: {e}")
        return redirect(f'/?error={str(e)}')

@app.route('/check_gmail_auth')
def check_gmail_auth():
    """Verifica si el usuario ya autorizó Gmail."""
    return jsonify({
        'authenticated': 'credentials' in session
    })

@app.route('/logout_gmail')
def logout_gmail():
    """Elimina las credenciales de Gmail de la sesión."""
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
    selected = data.get('leads', [])
    subject = data.get('subject', 'Oferta Mayorista - Yerba Mate Soberanía')
    body = data.get('body', '')
    attach_img = data.get('attach_image', False)
    
    # Cargar credenciales
    creds_data = session['credentials']
    creds = Credentials(
        token=creds_data['token'],
        refresh_token=creds_data.get('refresh_token'),
        token_uri=creds_data['token_uri'],
        client_id=creds_data['client_id'],
        client_secret=creds_data['client_secret'],
        scopes=creds_data['scopes']
    )
    
    # Refrescar token si es necesario
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            session['credentials'] = {
                'token': creds.token,
                'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri,
                'client_id': creds.client_id,
                'client_secret': creds.client_secret,
                'scopes': creds.scopes
            }
        except Exception as e:
            logger.error(f"Error refrescando token: {e}")
            return jsonify({
                'success': False,
                'error': 'Sesión expirada',
                'needs_auth': True,
                'auth_url': '/connect_gmail'
            })
    
    def generate():
        total = len(selected)
        yield f"data: {json.dumps({'status': 'start', 'total': total})}\n\n"
        
        try:
            service = build('gmail', 'v1', credentials=creds)
            
            for i, lead in enumerate(selected):
                if i > 0:
                    time.sleep(random.uniform(2, 4))  # Pausa entre emails para evitar límites
                
                try:
                    if not lead.get('email'):
                        yield f"data: {json.dumps({'progress': i+1, 'msg': 'Sin email', 'index': lead.get('original_index'), 'success': False})}\n\n"
                        continue
                    
                    # Crear mensaje
                    message = EmailMessage()
                    
                    # Personalizar cuerpo
                    cuerpo_personalizado = body
                    if '{nombre}' in cuerpo_personalizado:
                        cuerpo_personalizado = cuerpo_personalizado.replace('{nombre}', lead.get('nombre', ''))
                    if '{direccion}' in cuerpo_personalizado:
                        cuerpo_personalizado = cuerpo_personalizado.replace('{direccion}', lead.get('direccion', ''))
                    
                    message.set_content(cuerpo_personalizado)
                    message['To'] = lead['email']
                    message['From'] = 'me'  # Gmail usará el email autorizado
                    message['Subject'] = subject
                    
                    # Adjuntar imagen si existe
                    if attach_img and os.path.exists('producto.png'):
                        with open('producto.png', 'rb') as f:
                            image_data = f.read()
                        message.add_attachment(image_data, maintype='image', 
                                             subtype='png', 
                                             filename='producto_soberania.png')
                    
                    # Codificar para API de Gmail
                    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
                    create_message = {'raw': encoded_message}
                    
                    # Enviar
                    send_message = service.users().messages().send(
                        userId='me', 
                        body=create_message
                    ).execute()
                    
                    logger.info(f"✅ Email enviado a: {lead.get('email')}")
                    yield f"data: {json.dumps({'progress': i+1, 'msg': 'Enviado', 'index': lead.get('original_index'), 'success': True})}\n\n"
                    
                except HttpError as e:
                    error_msg = str(e)
                    logger.error(f"Error HTTP enviando a {lead.get('email')}: {error_msg}")
                    if 'quota' in error_msg.lower():
                        yield f"data: {json.dumps({'progress': i+1, 'msg': 'Límite de envíos excedido', 'index': lead.get('original_index'), 'success': False})}\n\n"
                        time.sleep(10)
                    else:
                        yield f"data: {json.dumps({'progress': i+1, 'msg': f'Error: {error_msg[:30]}', 'index': lead.get('original_index'), 'success': False})}\n\n"
                        
                except Exception as e:
                    logger.error(f"Error enviando a {lead.get('email')}: {e}")
                    yield f"data: {json.dumps({'progress': i+1, 'msg': f'Error: {str(e)[:30]}', 'index': lead.get('original_index'), 'success': False})}\n\n"
                
                sys.stdout.flush()
            
            yield f"data: {json.dumps({'status': 'finished'})}\n\n"
            
        except Exception as e:
            logger.error(f"Error en campaña: {e}")
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
    
    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Content-Type'] = 'text/event-stream'
    return response

# ========== RUTAS DE RESPALDO (SMTP) ==========
@app.route('/start_email_campaign', methods=['POST'])
def start_email_campaign():
    """Campaña de emails con SSE (Método SMTP original)."""
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
            if i > 0:
                time.sleep(random.uniform(1, 2))
            
            try:
                cuerpo_personalizado = body
                if '{nombre}' in cuerpo_personalizado:
                    cuerpo_personalizado = cuerpo_personalizado.replace('{nombre}', lead.get('nombre', ''))
                if '{direccion}' in cuerpo_personalizado:
                    cuerpo_personalizado = cuerpo_personalizado.replace('{direccion}', lead.get('direccion', ''))
                
                ok, msg = enviar_mail_soberania(
                    user, password, 
                    lead.get('email'), 
                    subject, 
                    cuerpo_personalizado, 
                    attach_img
                )
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

# ========== RUTAS PRINCIPALES ==========
@app.route('/')
def index():
    """Página principal."""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error cargando index.html: {e}")
        return "Bienvenido a Yerba Soberanía API", 200

@app.route('/producto.png')
def get_producto_image():
    """Sirve la imagen del producto."""
    if os.path.exists('producto.png'):
        return send_file('producto.png', mimetype='image/png')
    return "Archivo producto.png no encontrado", 404

# ========== RUTA DE BÚSQUEDA ==========
@app.route('/search_places', methods=['POST'])
def search_places():
    """Busca dietéticas en Google Maps."""
    data = request.json
    zona = data.get('zona')
    
    if not gmaps:
        logger.error("Google Maps client no inicializado")
        return jsonify({
            'success': False, 
            'error': 'Google Maps no configurado',
            'leads': []
        }), 200
    
    if not zona:
        return jsonify({
            'success': False,
            'error': 'Zona no especificada',
            'leads': []
        }), 200
    
    try:
        logger.info(f"🔍 Buscando dietéticas en: {zona}")
        
        queries = [
            f"dietetica en {zona}",
            f"dietética {zona}",
            f"health food store {zona}",
            f"natural products {zona}"
        ]
        
        leads = []
        response = None
        all_results = []  # Para acumular resultados de múltiples queries
        
        for query in queries:
            try:
                response = gmaps.places(query=query)
                if response.get('results'):
                    # Agregar resultados que no estén ya en all_results
                    for result in response.get('results', []):
                        # Evitar duplicados basados en place_id
                        if not any(r.get('place_id') == result.get('place_id') for r in all_results):
                            all_results.append(result)
                    
                    logger.info(f"✅ Encontrados {len(response['results'])} con: '{query}' (Total acumulado: {len(all_results)})")
            except Exception as e:
                logger.debug(f"Error con query '{query}': {e}")
                continue
        
        if not all_results:
            return jsonify({'success': True, 'leads': [], 'total': 0}), 200
        
        # Procesar hasta 50 resultados (límite máximo de Google Places API por página)
        results = all_results[:50]
        logger.info(f"Procesando {len(results)} resultados...")
        
        for p in results:
            try:
                det = gmaps.place(
                    place_id=p['place_id'], 
                    fields=['name', 'formatted_address', 'formatted_phone_number', 'website']
                )['result']
                
                tel_raw = det.get('formatted_phone_number', '')
                tel_clean = re.sub(r'\D', '', tel_raw)
                
                if tel_clean:
                    if tel_clean.startswith('549'):
                        tel_clean = tel_clean
                    elif tel_clean.startswith('54'):
                        tel_clean = tel_clean
                    elif tel_clean.startswith('0'):
                        tel_clean = '54' + tel_clean[1:]
                    else:
                        tel_clean = '54' + tel_clean
                
                web = det.get('website', '')
                contacto = {"email": "", "facebook": "", "instagram": ""}
                
                if web:
                    try:
                        contacto = scraping_profundo_contacto(web, False)
                    except:
                        pass

                leads.append({
                    'nombre': det.get('name', 'Sin nombre'),
                    'direccion': det.get('formatted_address', 'Sin dirección'),
                    'telefono': tel_clean[:15] if tel_clean else '',
                    'tel_display': tel_raw[:20] if tel_raw else 'No disponible',
                    'email': contacto["email"] or '',
                    'facebook': contacto["facebook"] or '',
                    'instagram': contacto["instagram"] or '',
                    'web': web or ''
                })
                
            except Exception as e:
                logger.error(f"Error procesando lugar: {e}")
                continue

        logger.info(f"✅ Total leads procesados: {len(leads)}")
        
        return jsonify({
            'success': True, 
            'leads': leads,
            'total': len(leads)
        }), 200
        
    except Exception as e:
        logger.error(f"Error en search_places: {e}")
        return jsonify({
            'success': False,
            'error': f'Error: {str(e)[:50]}',
            'leads': []
        }), 200

# ========== RUTA DE GENERACIÓN CSV ==========
@app.route('/generate_csv', methods=['POST'])
def generate_csv():
    """Genera un archivo CSV con los leads seleccionados."""
    data = request.json
    selected = data.get('leads', [])
    
    df = pd.DataFrame(selected)
    csv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'leads_seleccionados.csv')
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    
    return jsonify({
        'success': True,
        'csv_url': '/download_csv',
        'total': len(selected)
    })

@app.route('/download_csv', methods=['GET'])
def download_csv():
    """Descarga el archivo CSV generado."""
    csv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'leads_seleccionados.csv')
    if os.path.exists(csv_path):
        return send_file(csv_path, as_attachment=True, download_name='leads_seleccionados.csv')
    return "Archivo no encontrado", 404

# ========== RUTA DE IA ==========
@app.route('/api/ai_query', methods=['POST'])
def ai_query():
    """Proxy para Gemini API."""
    if not GEMINI_API_KEY:
        return jsonify({'error': 'API key no configurada', 'text': None}), 200
    
    data = request.json
    prompt = data.get('prompt')
    system_instruction = data.get('systemInstruction', 'Asistente comercial.')
    timeout = data.get('timeout', 8)

    default_response = "No encontrado"
    
    if "email" in prompt.lower() or "contacto" in prompt.lower():
        default_response = "No encontrado"
    elif "consejos" in prompt.lower():
        default_response = "1. Destaca origen misionero\n2. Precios competitivos\n3. Ofrece muestras"
    elif "mensaje" in prompt.lower():
        default_response = "Hola {nombre}, te comparto nuestra lista de precios mayorista de Yerba Mate Soberanía. ¿Te interesaría recibirla?"

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
        logger.info(f"Consultando Gemini API...")
        res = requests.post(url, json=payload, timeout=timeout)
        
        if res.status_code == 200:
            result = res.json()
            if 'candidates' in result and len(result['candidates']) > 0:
                text = result['candidates'][0]['content']['parts'][0]['text']
                logger.info("✅ Respuesta recibida de Gemini")
                return jsonify({'text': text})
        
        logger.warning(f"Gemini respondió con {res.status_code}")
        return jsonify({'text': default_response})
        
    except Exception as e:
        logger.error(f"Error en ai_query: {e}")
        return jsonify({'text': default_response})

# ========== RUTA DE DIAGNÓSTICO ==========
@app.route('/debug/keys', methods=['GET'])
def debug_keys():
    """Endpoint para verificar API keys."""
    return jsonify({
        'maps_key_configured': bool(GOOGLE_MAPS_KEY),
        'gemini_key_configured': bool(GEMINI_API_KEY),
        'gmaps_client_initialized': gmaps is not None,
        'gmail_auth_configured': bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
        'redirect_uri': REDIRECT_URI,
        'server_status': 'running',
        'timestamp': time.time()
    })

# ========== RUTA DE HEALTH CHECK ==========
@app.route('/health', methods=['GET'])
def health():
    """Health check para Render."""
    return jsonify({
        'status': 'healthy',
        'gmaps': 'ok' if gmaps else 'error',
        'gemini': 'ok' if GEMINI_API_KEY else 'missing',
        'gmail_config': 'ok' if (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET) else 'missing'
    }), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
