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

# ========== API KEYS - CORREGIDO PARA RENDER ==========
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

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

# Logging de configuración
logger.info("=" * 50)
logger.info("CONFIGURACIÓN DE API KEYS:")
logger.info(f"📌 Maps_KEY: {'✅ Configurada' if GOOGLE_MAPS_KEY else '❌ NO CONFIGURADA'}")
logger.info(f"📌 GEMINI_API_KEY: {'✅ Configurada' if GEMINI_API_KEY else '❌ NO CONFIGURADA'}")
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
    """Envía email vía Gmail con adjunto."""
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

# ========== RUTAS PRINCIPALES ==========
@app.route('/')
def index():
    """Página principal."""
    try:
        return render_template('index.html')
    except:
        return "Bienvenido a Yerba Soberanía API", 200

@app.route('/producto.png')
def get_producto_image():
    """Sirve la imagen del producto."""
    if os.path.exists('producto.png'):
        return send_file('producto.png', mimetype='image/png')
    return "Archivo producto.png no encontrado", 404

# ========== RUTA DE BÚSQUEDA CORREGIDA ==========
@app.route('/search_places', methods=['POST'])
def search_places():
    """Busca dietéticas en Google Maps."""
    data = request.json
    zona = data.get('zona')
    
    # VERIFICACIÓN CRÍTICA
    if not gmaps:
        logger.error("Google Maps client no inicializado")
        return jsonify({
            'success': False, 
            'error': 'Google Maps no configurado. Verifica Maps_KEY en Render',
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
        
        # Intentar con diferentes términos
        queries = [
            f"dietetica en {zona}",
            f"dietética {zona}",
            f"health food store {zona}",
            f"natural products {zona}"
        ]
        
        leads = []
        response = None
        
        for query in queries:
            try:
                response = gmaps.places(query=query)
                if response.get('results'):
                    logger.info(f"✅ Encontrados {len(response['results'])} con: '{query}'")
                    break
            except Exception as e:
                logger.debug(f"Error con query '{query}': {e}")
                continue
        
        if not response:
            return jsonify({'success': True, 'leads': [], 'total': 0}), 200
        
        results = response.get('results', [])[:10]
        
        for p in results:
            try:
                det = gmaps.place(
                    place_id=p['place_id'], 
                    fields=['name', 'formatted_address', 'formatted_phone_number', 'website']
                )['result']
                
                # Procesar teléfono
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

        logger.info(f"✅ Total leads: {len(leads)}")
        
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

# ========== RUTA DE EMAIL CAMPAIGN ==========
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
    response.headers['Content-Type'] = 'text/event-stream'
    return response

# ========== RUTA DE IA - CORREGIDA Y AGREGADA ==========
@app.route('/api/ai_query', methods=['POST'])
def ai_query():
    """Proxy para Gemini API."""
    if not GEMINI_API_KEY:
        return jsonify({'error': 'API key no configurada', 'text': None}), 200
    
    data = request.json
    prompt = data.get('prompt')
    system_instruction = data.get('systemInstruction', 'Asistente comercial.')
    timeout = data.get('timeout', 8)

    # Respuesta por defecto si falla
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
        'maps_key_prefix': GOOGLE_MAPS_KEY[:8] + '...' if GOOGLE_MAPS_KEY else None,
        'gemini_key_configured': bool(GEMINI_API_KEY),
        'gmaps_client_initialized': gmaps is not None,
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
        'gemini': 'ok' if GEMINI_API_KEY else 'missing'
    }), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
