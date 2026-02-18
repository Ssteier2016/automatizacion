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
app.secret_key = os.environ.get('SECRET_KEY', 'clave-por-defecto-cambiar')
CORS(app)

app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ========== CONFIGURACIÓN DESDE VARIABLES DE ENTORNO ==========
SCOPES = ['https://www.googleapis.com/auth/gmail.send']
REDIRECT_URI = os.environ.get('REDIRECT_URI', 'https://yerbamate.onrender.com/oauth2callback')

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

# Inicializar Google Maps client
try:
    if GOOGLE_MAPS_KEY:
        gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY, timeout=10)
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

def scraping_profundo_contacto(url_base, usar_ia=False):
    """
    Busca emails y redes sociales con timeout corto.
    Si usar_ia=True, intenta usar Gemini para encontrar emails en la web.
    """
    info = {"email": "", "facebook": "", "instagram": "", "twitter": "", "linkedin": ""}
    
    if not url_base or not url_base.startswith('http'):
        return info
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'es-ES,es;q=0.9',
        'Connection': 'keep-alive',
    }
    
    try:
        # Intentar obtener la página principal
        res = requests.get(url_base, timeout=3, headers=headers, allow_redirects=True)
        if res.status_code != 200: 
            return info
        
        texto_pagina = res.text
        
        # 1. BUSCAR EMAILS - Patrones básicos
        email_patterns = [
            r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
            r'email["\s:=]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            r'mail["\s:=]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            r'contacto["\s:=]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            r'contact["\s:=]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
        ]
        
        for pattern in email_patterns:
            found_emails = re.findall(pattern, texto_pagina, re.IGNORECASE)
            for e in found_emails:
                if validar_email(e) and not any(ext in e.lower() for ext in ['.png', '.jpg', '.gif', '.css', '.js']):
                    info["email"] = e.lower()
                    break
            if info["email"]:
                break
        
        # 2. BUSCAR REDES SOCIALES
        soup = BeautifulSoup(texto_pagina, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'facebook.com' in href and not info["facebook"]:
                info["facebook"] = a['href']
            if 'instagram.com' in href and not info["instagram"]:
                info["instagram"] = a['href']
            if 'twitter.com' in href or 'x.com' in href:
                if not info["twitter"]:
                    info["twitter"] = a['href']
            if 'linkedin.com' in href and not info["linkedin"]:
                info["linkedin"] = a['href']
        
        # 3. Si no encontramos email y tenemos Gemini, intentar con IA
        if not info["email"] and usar_ia and GEMINI_API_KEY:
            try:
                # Buscar enlaces a contacto
                contact_links = []
                for a in soup.find_all('a', href=True):
                    text = a.get_text().lower()
                    href = a['href'].lower()
                    if 'contact' in text or 'contacto' in text or 'contactenos' in text:
                        contact_links.append(a['href'])
                
                # Probar primeros 2 enlaces de contacto
                for link in contact_links[:2]:
                    if link.startswith('http'):
                        contact_url = link
                    elif link.startswith('/'):
                        contact_url = urljoin(url_base, link)
                    else:
                        contact_url = urljoin(url_base, '/' + link)
                    
                    time.sleep(0.5)
                    try:
                        res_contact = requests.get(contact_url, timeout=3, headers=headers)
                        if res_contact.status_code == 200:
                            contact_text = res_contact.text
                            for pattern in email_patterns:
                                found = re.findall(pattern, contact_text, re.IGNORECASE)
                                for e in found:
                                    if validar_email(e):
                                        info["email"] = e.lower()
                                        break
                                if info["email"]:
                                    break
                    except:
                        continue
                    
                    if info["email"]:
                        break
            except:
                pass
                
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
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            logger.error("Credenciales de Google no configuradas")
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
    
    creds_data = session['credentials']
    creds = Credentials(
        token=creds_data['token'],
        refresh_token=creds_data.get('refresh_token'),
        token_uri=creds_data['token_uri'],
        client_id=creds_data['client_id'],
        client_secret=creds_data['client_secret'],
        scopes=creds_data['scopes']
    )
    
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
                    time.sleep(random.uniform(2, 4))
                
                try:
                    if not lead.get('email'):
                        yield f"data: {json.dumps({'progress': i+1, 'msg': 'Sin email', 'index': lead.get('original_index'), 'success': False})}\n\n"
                        continue
                    
                    message = EmailMessage()
                    
                    cuerpo_personalizado = body
                    if '{nombre}' in cuerpo_personalizado:
                        cuerpo_personalizado = cuerpo_personalizado.replace('{nombre}', lead.get('nombre', ''))
                    if '{direccion}' in cuerpo_personalizado:
                        cuerpo_personalizado = cuerpo_personalizado.replace('{direccion}', lead.get('direccion', ''))
                    
                    message.set_content(cuerpo_personalizado)
                    message['To'] = lead['email']
                    message['From'] = 'me'
                    message['Subject'] = subject
                    
                    if attach_img and os.path.exists('producto.png'):
                        with open('producto.png', 'rb') as f:
                            image_data = f.read()
                        message.add_attachment(image_data, maintype='image', 
                                             subtype='png', 
                                             filename='producto_soberania.png')
                    
                    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
                    create_message = {'raw': encoded_message}
                    
                    send_message = service.users().messages().send(
                        userId='me', 
                        body=create_message
                    ).execute()
                    
                    yield f"data: {json.dumps({'progress': i+1, 'msg': 'Enviado', 'index': lead.get('original_index'), 'success': True})}\n\n"
                    
                except Exception as e:
                    yield f"data: {json.dumps({'progress': i+1, 'msg': f'Error', 'index': lead.get('original_index'), 'success': False})}\n\n"
                
                sys.stdout.flush()
            
            yield f"data: {json.dumps({'status': 'finished'})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
    
    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Cache-Control'] = 'no-cache'
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
        return "Bienvenido a Yerba Soberanía API", 200

@app.route('/producto.png')
def get_producto_image():
    """Sirve la imagen del producto."""
    if os.path.exists('producto.png'):
        return send_file('producto.png', mimetype='image/png')
    return "Archivo producto.png no encontrado", 404

# ========== RUTA DE BÚSQUEDA CON STREAMING EN VIVO ==========
@app.route('/search_places_stream', methods=['POST'])
def search_places_stream():
    """
    Busca dietéticas en Google Maps y devuelve resultados en STREAMING.
    HASTA 40 RESULTADOS - Muestra cada uno apenas se encuentra.
    """
    data = request.json
    zona = data.get('zona')
    
    if not gmaps:
        return jsonify({'success': False, 'error': 'Google Maps no configurado'}), 200
    
    if not zona:
        return jsonify({'success': False, 'error': 'Zona no especificada'}), 200
    
    def generate():
        yield f"data: {json.dumps({'status': 'start', 'message': f'Buscando en {zona}...'})}\n\n"
        
        try:
            # Intentar con diferentes términos de búsqueda
            queries = [
                f"dietetica en {zona}",
                f"dietética {zona}",
                f"health food store {zona}",
                f"natural products {zona}",
                f"tienda natural {zona}",
                f"alimentos saludables {zona}"
            ]
            
            response = None
            query_usada = ""
            
            # Probar cada query
            for query in queries:
                yield f"data: {json.dumps({'status': 'query', 'query': query})}\n\n"
                try:
                    response = gmaps.places(query=query)
                    if response.get('results'):
                        query_usada = query
                        yield f"data: {json.dumps({'status': 'found', 'count': len(response['results']), 'query': query})}\n\n"
                        break
                except Exception as e:
                    yield f"data: {json.dumps({'status': 'error', 'message': f'Error con query: {str(e)[:50]}'})}\n\n"
                    continue
            
            if not response:
                yield f"data: {json.dumps({'status': 'complete', 'total': 0})}\n\n"
                return
            
            # Recolectar todos los resultados con paginación
            todos_los_places = []
            resultados_pagina1 = response.get('results', [])
            todos_los_places.extend(resultados_pagina1)
            
            yield f"data: {json.dumps({'status': 'page', 'page': 1, 'count': len(resultados_pagina1)})}\n\n"
            
            # Intentar segunda página
            if 'next_page_token' in response:
                yield f"data: {json.dumps({'status': 'waiting', 'message': 'Esperando 2 segundos para siguiente página...'})}\n\n"
                time.sleep(2)
                
                try:
                    response2 = gmaps.places(
                        query=query_usada,
                        page_token=response['next_page_token']
                    )
                    resultados_pagina2 = response2.get('results', [])
                    todos_los_places.extend(resultados_pagina2)
                    yield f"data: {json.dumps({'status': 'page', 'page': 2, 'count': len(resultados_pagina2)})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'status': 'error', 'message': f'Error en página 2: {str(e)[:50]}'})}\n\n"
            
            total_places = len(todos_los_places)
            yield f"data: {json.dumps({'status': 'processing', 'total': total_places})}\n\n"
            
            # Procesar cada lugar UNO POR UNO y enviarlo al frontend
            procesados = 0
            exitosos = 0
            
            for idx, p in enumerate(todos_los_places):
                try:
                    nombre_actual = p.get('name', 'Sin nombre')
                    yield f"data: {json.dumps({'status': 'processing_one', 'current': idx+1, 'total': total_places, 'name': nombre_actual})}\n\n"
                    
                    # Obtener detalles del lugar
                    det = gmaps.place(
                        place_id=p['place_id'], 
                        fields=[
                            'name', 
                            'formatted_address', 
                            'formatted_phone_number', 
                            'website',
                            'rating',
                            'user_ratings_total',
                            'opening_hours',
                            'price_level',
                            'business_status'
                        ]
                    )['result']
                    
                    # Procesar teléfono
                    tel_raw = det.get('formatted_phone_number', '')
                    tel_clean = re.sub(r'\D', '', tel_raw)
                    
                    if tel_clean and not tel_clean.startswith('54'):
                        if not tel_clean.startswith('549'):
                            if tel_clean.startswith('0'):
                                tel_clean = '54' + tel_clean[1:]
                            else:
                                tel_clean = '54' + tel_clean
                    
                    web = det.get('website', '')
                    contacto = {"email": "", "facebook": "", "instagram": "", "twitter": "", "linkedin": ""}
                    
                    # Si tiene web, buscar contacto
                    if web:
                        try:
                            contacto = scraping_profundo_contacto(web, usar_ia=True)
                        except:
                            pass
                    
                    # Horario
                    horario = ""
                    if 'opening_hours' in det and 'weekday_text' in det['opening_hours']:
                        horario = ", ".join(det['opening_hours']['weekday_text'][:3])
                    
                    lead = {
                        'nombre': det.get('name', 'Sin nombre'),
                        'direccion': det.get('formatted_address', 'Sin dirección'),
                        'telefono': tel_clean[:15] if tel_clean else '',
                        'tel_display': tel_raw[:20] if tel_raw else 'No disponible',
                        'email': contacto["email"] or '',
                        'facebook': contacto["facebook"] or '',
                        'instagram': contacto["instagram"] or '',
                        'twitter': contacto["twitter"] or '',
                        'linkedin': contacto["linkedin"] or '',
                        'web': web or '',
                        'rating': det.get('rating', 'N/A'),
                        'total_reviews': det.get('user_ratings_total', 0),
                        'horario': horario,
                        'business_status': det.get('business_status', 'OPERATIONAL')
                    }
                    
                    # Enviar este lead al frontend INMEDIATAMENTE
                    yield f"data: {json.dumps({'status': 'lead', 'lead': lead, 'index': idx})}\n\n"
                    
                    procesados += 1
                    exitosos += 1
                    
                    # Pequeña pausa entre lugares para no saturar
                    time.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"Error procesando lugar: {e}")
                    yield f"data: {json.dumps({'status': 'error', 'message': f'Error en {p.get("name", "lugar")}: {str(e)[:50]}'})}\n\n"
                    procesados += 1
                    continue
            
            # Finalizar
            yield f"data: {json.dumps({'status': 'complete', 'total': exitosos, 'procesados': procesados})}\n\n"
            
        except Exception as e:
            logger.error(f"Error general: {e}")
            yield f"data: {json.dumps({'status': 'error', 'message': f'Error general: {str(e)[:50]}'})}\n\n"
    
    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Cache-Control'] = 'no-cache'
    return response

# ========== RUTA DE BÚSQUEDA ORIGINAL (para compatibilidad) ==========
@app.route('/search_places', methods=['POST'])
def search_places():
    """Versión original - mantiene compatibilidad con código existente."""
    data = request.json
    zona = data.get('zona')
    
    if not gmaps:
        return jsonify({'success': False, 'error': 'Google Maps no configurado', 'leads': []}), 200
    
    if not zona:
        return jsonify({'success': False, 'error': 'Zona no especificada', 'leads': []}), 200
    
    try:
        queries = [
            f"dietetica en {zona}",
            f"dietética {zona}",
            f"health food store {zona}",
            f"natural products {zona}"
        ]
        
        response = None
        for query in queries:
            try:
                response = gmaps.places(query=query)
                if response.get('results'):
                    break
            except:
                continue
        
        if not response:
            return jsonify({'success': True, 'leads': [], 'total': 0}), 200
        
        results = response.get('results', [])[:10]
        leads = []
        
        for p in results:
            try:
                det = gmaps.place(
                    place_id=p['place_id'], 
                    fields=['name', 'formatted_address', 'formatted_phone_number', 'website']
                )['result']
                
                tel_raw = det.get('formatted_phone_number', '')
                tel_clean = re.sub(r'\D', '', tel_raw)
                
                if tel_clean and not tel_clean.startswith('54'):
                    if not tel_clean.startswith('549'):
                        if tel_clean.startswith('0'):
                            tel_clean = '54' + tel_clean[1:]
                        else:
                            tel_clean = '54' + tel_clean
                
                web = det.get('website', '')
                contacto = {"email": "", "facebook": "", "instagram": ""}
                
                if web:
                    try:
                        contacto = scraping_profundo_contacto(web, usar_ia=False)
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
                
            except:
                continue

        return jsonify({'success': True, 'leads': leads, 'total': len(leads)}), 200
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error: {str(e)[:50]}', 'leads': []}), 200

# ========== RUTA DE GENERACIÓN CSV ==========
@app.route('/generate_csv', methods=['POST'])
def generate_csv():
    """Genera un archivo CSV con los leads seleccionados."""
    data = request.json
    selected = data.get('leads', [])
    
    df = pd.DataFrame(selected)
    csv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'leads_seleccionados.csv')
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    
    return jsonify({'success': True, 'csv_url': '/download_csv', 'total': len(selected)})

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
        res = requests.post(url, json=payload, timeout=timeout)
        
        if res.status_code == 200:
            result = res.json()
            if 'candidates' in result and len(result['candidates']) > 0:
                text = result['candidates'][0]['content']['parts'][0]['text']
                return jsonify({'text': text})
        
        return jsonify({'text': default_response})
        
    except Exception as e:
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
