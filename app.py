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
from datetime import datetime, timedelta
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

# ========== SISTEMA DE CONTROL DE LÍMITES DE GEMINI ==========
class GeminiRateLimiter:
    """
    Controla el rate limiting de la API de Gemini
    Límites gratuitos: 60 consultas por minuto, 1 millón de tokens por minuto
    """
    
    def __init__(self):
        self.queries_this_minute = 0
        self.minute_start = time.time()
        self.total_queries_today = 0
        self.last_reset_day = datetime.now().date()
        
        # Archivo para persistir el contador
        self.counter_file = '/tmp/gemini_counter.json'
        self.load_counter()
        
        # Límites de seguridad (80% del límite real para tener margen)
        self.MAX_QUERIES_PER_MINUTE = 48  # 80% de 60
        self.MAX_QUERIES_PER_DAY = 1440   # Aproximadamente 48 * 30 minutos de uso
        
        logger.info("=" * 50)
        logger.info("SISTEMA DE CONTROL DE LÍMITES DE GEMINI INICIALIZADO")
        logger.info(f"📊 Límite por minuto: {self.MAX_QUERIES_PER_MINUTE} consultas")
        logger.info(f"📊 Límite por día: {self.MAX_QUERIES_PER_DAY} consultas")
        logger.info("=" * 50)
    
    def load_counter(self):
        """Carga el contador desde archivo"""
        try:
            if os.path.exists(self.counter_file):
                with open(self.counter_file, 'r') as f:
                    data = json.load(f)
                    saved_date = datetime.fromisoformat(data['date']).date()
                    if saved_date == datetime.now().date():
                        self.total_queries_today = data['total']
                        logger.info(f"📊 Contador cargado: {self.total_queries_today} consultas hoy")
        except Exception as e:
            logger.error(f"Error cargando contador: {e}")
    
    def save_counter(self):
        """Guarda el contador en archivo"""
        try:
            data = {
                'date': datetime.now().isoformat(),
                'total': self.total_queries_today
            }
            with open(self.counter_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"Error guardando contador: {e}")
    
    def reset_minute_counter(self):
        """Reinicia el contador por minuto si pasó más de un minuto"""
        current_time = time.time()
        if current_time - self.minute_start >= 60:
            self.queries_this_minute = 0
            self.minute_start = current_time
            logger.debug("🔄 Contador por minuto reiniciado")
    
    def check_daily_reset(self):
        """Reinicia el contador diario si es un nuevo día"""
        today = datetime.now().date()
        if today > self.last_reset_day:
            self.total_queries_today = 0
            self.last_reset_day = today
            logger.info("📅 Nuevo día - Contador diario reiniciado")
            self.save_counter()
    
    def can_make_request(self):
        """Verifica si podemos hacer una consulta"""
        self.reset_minute_counter()
        self.check_daily_reset()
        
        if self.queries_this_minute >= self.MAX_QUERIES_PER_MINUTE:
            wait_time = 60 - (time.time() - self.minute_start)
            logger.warning(f"⚠️ Límite por minuto alcanzado. Esperar {wait_time:.1f} segundos")
            return False, wait_time
        
        if self.total_queries_today >= self.MAX_QUERIES_PER_DAY:
            logger.error("❌ Límite diario alcanzado")
            return False, None
        
        return True, None
    
    def record_request(self):
        """Registra una consulta realizada"""
        self.queries_this_minute += 1
        self.total_queries_today += 1
        self.save_counter()
        
        # Log de uso
        percent_minute = (self.queries_this_minute / self.MAX_QUERIES_PER_MINUTE) * 100
        percent_day = (self.total_queries_today / self.MAX_QUERIES_PER_DAY) * 100
        
        logger.info(f"📊 Uso Gemini: {self.queries_this_minute}/{self.MAX_QUERIES_PER_MINUTE} por minuto ({percent_minute:.1f}%)")
        logger.info(f"📊 Uso diario: {self.total_queries_today}/{self.MAX_QUERIES_PER_DAY} ({percent_day:.1f}%)")
        
        # Advertencias si estamos cerca del límite
        if percent_minute > 80:
            logger.warning(f"⚠️ Cerca del límite por minuto: {percent_minute:.1f}%")
        if percent_day > 80:
            logger.warning(f"⚠️ Cerca del límite diario: {percent_day:.1f}%")
    
    def get_status(self):
        """Devuelve el estado actual del rate limiter"""
        self.reset_minute_counter()
        self.check_daily_reset()
        
        return {
            'queries_this_minute': self.queries_this_minute,
            'max_per_minute': self.MAX_QUERIES_PER_MINUTE,
            'percent_minute': (self.queries_this_minute / self.MAX_QUERIES_PER_MINUTE) * 100,
            'total_today': self.total_queries_today,
            'max_per_day': self.MAX_QUERIES_PER_DAY,
            'percent_day': (self.total_queries_today / self.MAX_QUERIES_PER_DAY) * 100,
            'can_make_request': self.queries_this_minute < self.MAX_QUERIES_PER_MINUTE and self.total_queries_today < self.MAX_QUERIES_PER_DAY
        }

# ========== SISTEMA DE CONTROL DE LÍMITES DE GOOGLE MAPS ==========
class GoogleMapsRateLimiter:
    """
    Controla el rate limiting de la API de Google Maps
    Límites gratuitos: 
    - Places API: 1000 solicitudes por día (versión gratuita)
    - Place Details: variable pero lo limitamos conservadoramente
    """
    
    def __init__(self):
        # Contadores por minuto
        self.place_searches_this_minute = 0
        self.place_details_this_minute = 0
        self.minute_start = time.time()
        
        # Contadores por día
        self.total_searches_today = 0
        self.total_details_today = 0
        self.last_reset_day = datetime.now().date()
        
        # Archivo para persistir el contador
        self.counter_file = '/tmp/gmaps_counter.json'
        self.load_counter()
        
        # Límites conservadores (70% del límite real para tener margen)
        # Places API: 1000/día -> 700/día
        # Place Details: asumimos 10-20 por búsqueda, limitamos a 350/día
        self.MAX_SEARCHES_PER_DAY = 700  # 70% de 1000
        self.MAX_DETAILS_PER_DAY = 350   # Aproximadamente 350 detalles
        
        # Límites por minuto (para evitar picos)
        self.MAX_SEARCHES_PER_MINUTE = 30
        self.MAX_DETAILS_PER_MINUTE = 60
        
        # Cooldown entre solicitudes
        self.MIN_DELAY_BETWEEN_REQUESTS = 0.2  # 200ms mínimo
        self.last_request_time = 0
        
        logger.info("=" * 50)
        logger.info("SISTEMA DE CONTROL DE LÍMITES DE GOOGLE MAPS INICIALIZADO")
        logger.info(f"📊 Límite búsquedas/día: {self.MAX_SEARCHES_PER_DAY}")
        logger.info(f"📊 Límite detalles/día: {self.MAX_DETAILS_PER_DAY}")
        logger.info(f"📊 Límite búsquedas/minuto: {self.MAX_SEARCHES_PER_MINUTE}")
        logger.info(f"📊 Límite detalles/minuto: {self.MAX_DETAILS_PER_MINUTE}")
        logger.info("=" * 50)
    
    def load_counter(self):
        """Carga el contador desde archivo"""
        try:
            if os.path.exists(self.counter_file):
                with open(self.counter_file, 'r') as f:
                    data = json.load(f)
                    saved_date = datetime.fromisoformat(data['date']).date()
                    if saved_date == datetime.now().date():
                        self.total_searches_today = data.get('searches', 0)
                        self.total_details_today = data.get('details', 0)
                        logger.info(f"📊 Contador Maps cargado: {self.total_searches_today} búsquedas, {self.total_details_today} detalles hoy")
        except Exception as e:
            logger.error(f"Error cargando contador Maps: {e}")
    
    def save_counter(self):
        """Guarda el contador en archivo"""
        try:
            data = {
                'date': datetime.now().isoformat(),
                'searches': self.total_searches_today,
                'details': self.total_details_today
            }
            with open(self.counter_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"Error guardando contador Maps: {e}")
    
    def reset_minute_counter(self):
        """Reinicia los contadores por minuto si pasó más de un minuto"""
        current_time = time.time()
        if current_time - self.minute_start >= 60:
            self.place_searches_this_minute = 0
            self.place_details_this_minute = 0
            self.minute_start = current_time
            logger.debug("🔄 Contadores por minuto de Maps reiniciados")
    
    def check_daily_reset(self):
        """Reinicia los contadores diarios si es un nuevo día"""
        today = datetime.now().date()
        if today > self.last_reset_day:
            self.total_searches_today = 0
            self.total_details_today = 0
            self.last_reset_day = today
            logger.info("📅 Nuevo día - Contadores diarios de Maps reiniciados")
            self.save_counter()
    
    def can_make_search(self):
        """Verifica si podemos hacer una búsqueda de places"""
        self.reset_minute_counter()
        self.check_daily_reset()
        
        # Verificar límite por minuto
        if self.place_searches_this_minute >= self.MAX_SEARCHES_PER_MINUTE:
            wait_time = 60 - (time.time() - self.minute_start)
            logger.warning(f"⚠️ Límite de búsquedas por minuto alcanzado. Esperar {wait_time:.1f}s")
            return False, wait_time, 'minute'
        
        # Verificar límite por día
        if self.total_searches_today >= self.MAX_SEARCHES_PER_DAY:
            logger.error("❌ Límite diario de búsquedas alcanzado")
            return False, None, 'day'
        
        # Verificar cooldown entre solicitudes
        time_since_last = time.time() - self.last_request_time
        if time_since_last < self.MIN_DELAY_BETWEEN_REQUESTS:
            wait_time = self.MIN_DELAY_BETWEEN_REQUESTS - time_since_last
            return False, wait_time, 'cooldown'
        
        return True, None, None
    
    def can_make_detail(self):
        """Verifica si podemos hacer una solicitud de details"""
        self.reset_minute_counter()
        self.check_daily_reset()
        
        # Verificar límite por minuto
        if self.place_details_this_minute >= self.MAX_DETAILS_PER_MINUTE:
            wait_time = 60 - (time.time() - self.minute_start)
            logger.warning(f"⚠️ Límite de detalles por minuto alcanzado. Esperar {wait_time:.1f}s")
            return False, wait_time, 'minute'
        
        # Verificar límite por día
        if self.total_details_today >= self.MAX_DETAILS_PER_DAY:
            logger.error("❌ Límite diario de detalles alcanzado")
            return False, None, 'day'
        
        # Verificar cooldown entre solicitudes
        time_since_last = time.time() - self.last_request_time
        if time_since_last < self.MIN_DELAY_BETWEEN_REQUESTS:
            wait_time = self.MIN_DELAY_BETWEEN_REQUESTS - time_since_last
            return False, wait_time, 'cooldown'
        
        return True, None, None
    
    def record_search(self):
        """Registra una búsqueda realizada"""
        self.place_searches_this_minute += 1
        self.total_searches_today += 1
        self.last_request_time = time.time()
        self.save_counter()
        
        # Log de uso
        percent_day = (self.total_searches_today / self.MAX_SEARCHES_PER_DAY) * 100
        logger.info(f"📊 Búsqueda Maps #{self.total_searches_today}/{self.MAX_SEARCHES_PER_DAY} ({percent_day:.1f}%)")
        
        if percent_day > 80:
            logger.warning(f"⚠️ Cerca del límite diario de búsquedas: {percent_day:.1f}%")
    
    def record_detail(self):
        """Registra un detalle realizado"""
        self.place_details_this_minute += 1
        self.total_details_today += 1
        self.last_request_time = time.time()
        self.save_counter()
        
        # Log de uso
        percent_day = (self.total_details_today / self.MAX_DETAILS_PER_DAY) * 100
        logger.info(f"📊 Detalle Maps #{self.total_details_today}/{self.MAX_DETAILS_PER_DAY} ({percent_day:.1f}%)")
        
        if percent_day > 80:
            logger.warning(f"⚠️ Cerca del límite diario de detalles: {percent_day:.1f}%")
    
    def get_status(self):
        """Devuelve el estado actual del rate limiter"""
        self.reset_minute_counter()
        self.check_daily_reset()
        
        return {
            'searches': {
                'minute': self.place_searches_this_minute,
                'max_minute': self.MAX_SEARCHES_PER_MINUTE,
                'percent_minute': (self.place_searches_this_minute / self.MAX_SEARCHES_PER_MINUTE) * 100 if self.MAX_SEARCHES_PER_MINUTE > 0 else 0,
                'day': self.total_searches_today,
                'max_day': self.MAX_SEARCHES_PER_DAY,
                'percent_day': (self.total_searches_today / self.MAX_SEARCHES_PER_DAY) * 100 if self.MAX_SEARCHES_PER_DAY > 0 else 0
            },
            'details': {
                'minute': self.place_details_this_minute,
                'max_minute': self.MAX_DETAILS_PER_MINUTE,
                'percent_minute': (self.place_details_this_minute / self.MAX_DETAILS_PER_MINUTE) * 100 if self.MAX_DETAILS_PER_MINUTE > 0 else 0,
                'day': self.total_details_today,
                'max_day': self.MAX_DETAILS_PER_DAY,
                'percent_day': (self.total_details_today / self.MAX_DETAILS_PER_DAY) * 100 if self.MAX_DETAILS_PER_DAY > 0 else 0
            },
            'can_make_search': self.place_searches_this_minute < self.MAX_SEARCHES_PER_MINUTE and self.total_searches_today < self.MAX_SEARCHES_PER_DAY,
            'can_make_detail': self.place_details_this_minute < self.MAX_DETAILS_PER_MINUTE and self.total_details_today < self.MAX_DETAILS_PER_DAY
        }

# Inicializar los rate limiters
gemini_limiter = GeminiRateLimiter()
gmaps_limiter = GoogleMapsRateLimiter()

# Logging de configuración
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

def buscar_email_con_ia(nombre, direccion, redes=None):
    """
    Usa Gemini para buscar email basado en nombre, dirección y redes.
    Controla el rate limiting automáticamente.
    """
    if not GEMINI_API_KEY:
        return ""
    
    # Verificar si podemos hacer la consulta
    can_request, wait_time = gemini_limiter.can_make_request()
    if not can_request:
        if wait_time:
            logger.info(f"⏳ Esperando {wait_time:.1f}s por límite de Gemini...")
            time.sleep(wait_time)
            # Verificar de nuevo después de esperar
            can_request, _ = gemini_limiter.can_make_request()
            if not can_request:
                logger.warning("❌ No se puede hacer consulta a Gemini después de esperar")
                return ""
        else:
            logger.warning("❌ Límite diario de Gemini alcanzado")
            return ""
    
    prompt = f"Negocio: {nombre}. Ubicación: {direccion}."
    if redes:
        if redes.get('instagram'):
            prompt += f" Instagram: {redes['instagram']}."
        if redes.get('facebook'):
            prompt += f" Facebook: {redes['facebook']}."
    
    prompt += " Basado en esta información, ¿cuál es el email de contacto para ventas mayoristas? Responde SOLO el email, o 'No encontrado' si no sabes."
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 50}
        }
        
        # Registrar que vamos a hacer la consulta
        gemini_limiter.record_request()
        
        res = requests.post(url, json=payload, timeout=5)
        if res.status_code == 200:
            result = res.json()
            if 'candidates' in result and len(result['candidates']) > 0:
                text = result['candidates'][0]['content']['parts'][0]['text'].strip()
                if '@' in text and validar_email(text):
                    logger.info(f"✅ Gemini encontró email: {text}")
                    return text.lower()
        else:
            logger.warning(f"⚠️ Gemini respondió con código {res.status_code}")
            
    except requests.Timeout:
        logger.warning("⏱️ Timeout en consulta a Gemini")
    except Exception as e:
        logger.error(f"❌ Error en consulta a Gemini: {e}")
    
    return ""

def scraping_profundo_contacto(url_base, usar_ia=False, nombre="", direccion=""):
    """Busca emails y redes sociales con timeout corto. Puede usar IA para encontrar emails."""
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
        
        # Si no encontramos email pero tenemos IA, intentamos buscarlo con Gemini
        # Ahora va de a una por una y controla límites
        if not info["email"] and usar_ia and GEMINI_API_KEY:
            # Pequeña pausa entre consultas a Gemini para no saturar
            time.sleep(1)
            email_ia = buscar_email_con_ia(nombre, direccion, info)
            if email_ia:
                info["email"] = email_ia
                
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

# ========== RUTA PARA VER ESTADO DE LOS RATE LIMITERS ==========
@app.route('/api_status', methods=['GET'])
def api_status():
    """Devuelve el estado actual de los rate limiters"""
    return jsonify({
        'success': True,
        'gemini': gemini_limiter.get_status(),
        'google_maps': gmaps_limiter.get_status()
    })

# ========== NUEVA RUTA DE BÚSQUEDA CON STREAMING Y CONTROL DE LÍMITES ==========
@app.route('/search_places_stream', methods=['POST'])
def search_places_stream():
    """
    Busca dietéticas en Google Maps y devuelve resultados en STREAMING.
    HASTA 40 RESULTADOS - Procesa en lotes de 5 para evitar timeouts.
    Incluye control de límites de Gemini y Google Maps automático.
    """
    data = request.json
    zona = data.get('zona')

    if not gmaps:
        return jsonify({'success': False, 'error': 'Google Maps no configurado'}), 200

    if not zona:
        return jsonify({'success': False, 'error': 'Zona no especificada'}), 200

    def generate():
        yield f"data: {json.dumps({'status': 'start', 'message': f'Iniciando búsqueda en {zona}...'})}\n\n"
        
        # Enviar estado inicial de las APIs
        initial_status = {
            'status': 'api_status', 
            'gemini': gemini_limiter.get_status(),
            'google_maps': gmaps_limiter.get_status()
        }
        yield f"data: {json.dumps(initial_status)}\n\n"

        try:
            # ===== 1. VERIFICAR LÍMITES ANTES DE EMPEZAR =====
            # Verificar si podemos hacer búsquedas
            can_search, wait_time, reason = gmaps_limiter.can_make_search()
            if not can_search:
                if reason == 'day':
                    yield f"data: {json.dumps({'status': 'error', 'message': '❌ Límite diario de Google Maps alcanzado. Vuelve mañana.'})}\n\n"
                    return
                elif wait_time:
                    yield f"data: {json.dumps({'status': 'warning', 'message': f'⏳ Esperando {wait_time:.1f}s por límite de Google Maps...'})}\n\n"
                    time.sleep(wait_time)
            
            # ===== 2. BÚSQUEDA INICIAL CON MÚLTIPLES QUERIES =====
            queries = [
                f"dietetica en {zona}",
                f"dietética {zona}",
                f"health food store {zona}",
                f"natural products {zona}",
                f"tienda natural {zona}"
            ]

            response = None
            query_usada = ""
            todos_los_places = []

            # Probar queries hasta encontrar resultados
            for query in queries:
                yield f"data: {json.dumps({'status': 'query', 'query': query})}\n\n"
                
                # Verificar límites antes de cada query
                can_search, wait_time, reason = gmaps_limiter.can_make_search()
                if not can_search:
                    if reason == 'day':
                        yield f"data: {json.dumps({'status': 'error', 'message': '❌ Límite diario alcanzado durante búsqueda'})}\n\n"
                        return
                    elif wait_time:
                        yield f"data: {json.dumps({'status': 'waiting', 'message': f'⏳ Esperando {wait_time:.1f}s por límite...'})}\n\n"
                        time.sleep(wait_time)
                
                try:
                    response = gmaps.places(query=query)
                    gmaps_limiter.record_search()  # Registrar la búsqueda
                    
                    if response.get('results'):
                        query_usada = query
                        yield f"data: {json.dumps({'status': 'found', 'count': len(response['results']), 'query': query})}\n\n"
                        break
                except Exception as e:
                    yield f"data: {json.dumps({'status': 'error', 'message': f'Error en query: {str(e)[:50]}'})}\n\n"
                    time.sleep(2)
                    continue

            if not response:
                yield f"data: {json.dumps({'status': 'complete', 'total': 0})}\n\n"
                return

            # ===== 3. RECOLECTAR RESULTADOS CON PAGINACIÓN (HASTA 40) =====
            # Primera página
            todos_los_places = response.get('results', [])
            yield f"data: {json.dumps({'status': 'page', 'page': 1, 'count': len(todos_los_places)})}\n\n"

            # Segunda página (si existe)
            if 'next_page_token' in response and len(todos_los_places) < 40:
                yield f"data: {json.dumps({'status': 'waiting', 'message': 'Esperando 2 segundos para siguiente página...'})}\n\n"
                time.sleep(2)
                
                # Verificar límites antes de segunda página
                can_search, wait_time, reason = gmaps_limiter.can_make_search()
                if not can_search:
                    if reason == 'day':
                        yield f"data: {json.dumps({'status': 'warning', 'message': '⚠️ Límite diario alcanzado, continuando con página 1'})}\n\n"
                    elif wait_time:
                        yield f"data: {json.dumps({'status': 'waiting', 'message': f'⏳ Esperando {wait_time:.1f}s...'})}\n\n"
                        time.sleep(wait_time)
                
                if can_search:
                    try:
                        response2 = gmaps.places(
                            query=query_usada,
                            page_token=response['next_page_token']
                        )
                        gmaps_limiter.record_search()
                        page2_results = response2.get('results', [])
                        todos_los_places.extend(page2_results)
                        yield f"data: {json.dumps({'status': 'page', 'page': 2, 'count': len(page2_results)})}\n\n"
                    except Exception as e:
                        yield f"data: {json.dumps({'status': 'error', 'message': f'Error en página 2: {str(e)[:50]}'})}\n\n"

            # Limitar a máximo 40 resultados
            todos_los_places = todos_los_places[:40]
            total_places = len(todos_los_places)
            
            yield f"data: {json.dumps({'status': 'processing', 'total': total_places})}\n\n"

            # ===== 4. PROCESAR EN LOTES DE 5 =====
            BATCH_SIZE = 5
            procesados = 0
            gemini_consultas_realizadas = 0
            detalles_procesados = 0
            
            for batch_start in range(0, total_places, BATCH_SIZE):
                # Actualizar estado de las APIs
                api_update = {
                    'status': 'api_update', 
                    'gemini': gemini_limiter.get_status(),
                    'google_maps': gmaps_limiter.get_status()
                }
                yield f"data: {json.dumps(api_update)}\n\n"
                
                # Verificar límites de detalles antes del lote
                can_detail, wait_time, reason = gmaps_limiter.can_make_detail()
                if not can_detail:
                    if reason == 'day':
                        yield f"data: {json.dumps({'status': 'warning', 'message': '⚠️ Límite diario de detalles alcanzado. No se procesarán más.'})}\n\n"
                        break
                    elif wait_time:
                        yield f"data: {json.dumps({'status': 'waiting', 'message': f'⏳ Esperando {wait_time:.1f}s por límite de detalles...'})}\n\n"
                        time.sleep(wait_time)
                
                # Si Gemini está cerca del límite, advertir
                gemini_status = gemini_limiter.get_status()
                if gemini_status['percent_day'] > 90:
                    yield f"data: {json.dumps({'status': 'warning', 'message': '⚠️ Gemini cerca del límite diario (90%+)'})}\n\n"
                elif gemini_status['percent_minute'] > 90:
                    yield f"data: {json.dumps({'status': 'warning', 'message': '⚠️ Gemini cerca del límite por minuto, ralentizando...'})}\n\n"
                    time.sleep(3)
                
                batch_end = min(batch_start + BATCH_SIZE, total_places)
                yield f"data: {json.dumps({'status': 'batch', 'start': batch_start+1, 'end': batch_end})}\n\n"

                for idx in range(batch_start, batch_end):
                    p = todos_los_places[idx]
                    try:
                        nombre_actual = p.get('name', 'Sin nombre')
                        yield f"data: {json.dumps({'status': 'processing_one', 'current': idx+1, 'total': total_places, 'name': nombre_actual})}\n\n"

                        # Verificar límites antes de cada detalle
                        can_detail, wait_time, reason = gmaps_limiter.can_make_detail()
                        if not can_detail:
                            if reason == 'day':
                                yield f"data: {json.dumps({'status': 'warning', 'message': '⚠️ Límite diario de detalles alcanzado. Deteniendo procesamiento.'})}\n\n"
                                break
                            elif wait_time:
                                time.sleep(wait_time)
                        
                        # Obtener detalles del lugar
                        det = gmaps.place(
                            place_id=p['place_id'], 
                            fields=['name', 'formatted_address', 'formatted_phone_number', 'website']
                        )['result']
                        gmaps_limiter.record_detail()  # Registrar el detalle
                        detalles_procesados += 1
                        
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
                        
                        # Scraping para email y redes (con IA)
                        web = det.get('website', '')
                        contacto = {"email": "", "facebook": "", "instagram": ""}
                        
                        if web:
                            try:
                                # Pasar nombre y dirección para que la IA pueda ayudar
                                contacto = scraping_profundo_contacto(
                                    web, 
                                    usar_ia=True,
                                    nombre=det.get('name', ''),
                                    direccion=det.get('formatted_address', '')
                                )
                                if contacto.get('email'):
                                    gemini_consultas_realizadas += 1
                            except:
                                pass

                        lead = {
                            'nombre': det.get('name', 'Sin nombre'),
                            'direccion': det.get('formatted_address', 'Sin dirección'),
                            'telefono': tel_clean[:15] if tel_clean else '',
                            'tel_display': tel_raw[:20] if tel_raw else 'No disponible',
                            'email': contacto["email"] or '',
                            'facebook': contacto["facebook"] or '',
                            'instagram': contacto["instagram"] or '',
                            'web': web or ''
                        }

                        # Enviar lead al frontend
                        yield f"data: {json.dumps({'status': 'lead', 'lead': lead, 'index': idx})}\n\n"
                        procesados += 1

                        # Pausa adaptativa según carga
                        gemini_load = gemini_limiter.queries_this_minute / gemini_limiter.MAX_QUERIES_PER_MINUTE
                        maps_load = gmaps_limiter.place_details_this_minute / gmaps_limiter.MAX_DETAILS_PER_MINUTE
                        
                        if gemini_load > 0.7 or maps_load > 0.7:
                            time.sleep(2)  # Pausa más larga si estamos cerca del límite
                        else:
                            time.sleep(0.8)  # Pausa normal

                    except Exception as e:
                        logger.error(f"Error procesando lugar: {e}")
                        nombre_lugar = p.get("name", "lugar")
                        yield f"data: {json.dumps({'status': 'error', 'message': f'Error en {nombre_lugar}: {str(e)[:50]}', 'failed_index': idx})}\n\n"
                    
                    # Verificar si debemos continuar después de cada lugar
                    can_detail, _, _ = gmaps_limiter.can_make_detail()
                    if not can_detail:
                        yield f"data: {json.dumps({'status': 'warning', 'message': '⚠️ Límite de detalles alcanzado. Deteniendo procesamiento.'})}\n\n"
                        break
                
                # Verificar si debemos continuar después del lote
                can_detail, _, _ = gmaps_limiter.can_make_detail()
                if not can_detail:
                    break
                
                # Pausa entre lotes
                if batch_end < total_places:
                    yield f"data: {json.dumps({'status': 'pause', 'message': 'Pausa para evitar timeout...'})}\n\n"
                    time.sleep(3)

            # ===== 5. FINALIZAR =====
            final_status = {
                'status': 'complete', 
                'total': procesados,
                'detalles_procesados': detalles_procesados,
                'gemini_consultas': gemini_consultas_realizadas,
                'gemini_final': gemini_limiter.get_status(),
                'google_maps_final': gmaps_limiter.get_status()
            }
            yield f"data: {json.dumps(final_status)}\n\n"
            
            logger.info(f"✅ Búsqueda completada: {procesados} resultados, {detalles_procesados} detalles, {gemini_consultas_realizadas} consultas a Gemini")

        except Exception as e:
            logger.error(f"Error general en búsqueda: {e}")
            yield f"data: {json.dumps({'status': 'fatal_error', 'message': f'Error general: {str(e)[:50]}'})}\n\n"

    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Cache-Control'] = 'no-cache'
    return response

# ========== RUTA DE BÚSQUEDA ORIGINAL (para compatibilidad) ==========
@app.route('/search_places', methods=['POST'])
def search_places():
    """Versión original que devuelve 10 resultados."""
    data = request.json
    zona = data.get('zona')
    
    if not gmaps:
        return jsonify({'success': False, 'error': 'Google Maps no configurado', 'leads': []}), 200
    
    if not zona:
        return jsonify({'success': False, 'error': 'Zona no especificada', 'leads': []}), 200
    
    try:
        # Verificar límites
        can_search, wait_time, _ = gmaps_limiter.can_make_search()
        if not can_search:
            return jsonify({'success': False, 'error': 'Límite de Google Maps alcanzado', 'leads': []}), 429
        
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
                gmaps_limiter.record_search()
                if response.get('results'):
                    break
            except:
                continue
        
        if not response:
            return jsonify({'success': True, 'leads': [], 'total': 0}), 200
        
        results = response.get('results', [])[:10]
        leads = []
        
        for p in results:
            # Verificar límites de detalles
            can_detail, wait_time, _ = gmaps_limiter.can_make_detail()
            if not can_detail:
                break
                
            try:
                det = gmaps.place(
                    place_id=p['place_id'], 
                    fields=['name', 'formatted_address', 'formatted_phone_number', 'website']
                )['result']
                gmaps_limiter.record_detail()
                
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

        return jsonify({
            'success': True, 
            'leads': leads, 
            'total': len(leads),
            'rate_limits': {
                'gemini': gemini_limiter.get_status(),
                'google_maps': gmaps_limiter.get_status()
            }
        }), 200
        
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

# ========== RUTA DE IA CON CONTROL DE LÍMITES ==========
@app.route('/api/ai_query', methods=['POST'])
def ai_query():
    """Proxy para Gemini API con control de límites."""
    if not GEMINI_API_KEY:
        return jsonify({'error': 'API key no configurada', 'text': None}), 200
    
    # Verificar límites antes de procesar
    can_request, wait_time = gemini_limiter.can_make_request()
    if not can_request:
        if wait_time:
            return jsonify({
                'text': None,
                'error': f'Límite por minuto alcanzado. Esperar {wait_time:.0f} segundos',
                'rate_limited': True,
                'wait_time': wait_time,
                'rate_limit_status': gemini_limiter.get_status()
            }), 429
        else:
            return jsonify({
                'text': None,
                'error': 'Límite diario alcanzado',
                'rate_limited': True,
                'daily_limit': True,
                'rate_limit_status': gemini_limiter.get_status()
            }), 429
    
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
        
        # Registrar la consulta
        gemini_limiter.record_request()
        
        res = requests.post(url, json=payload, timeout=timeout)
        
        if res.status_code == 200:
            result = res.json()
            if 'candidates' in result and len(result['candidates']) > 0:
                text = result['candidates'][0]['content']['parts'][0]['text']
                logger.info("✅ Respuesta recibida de Gemini")
                return jsonify({
                    'text': text,
                    'rate_limit_status': gemini_limiter.get_status()
                })
        
        logger.warning(f"Gemini respondió con {res.status_code}")
        return jsonify({
            'text': default_response,
            'rate_limit_status': gemini_limiter.get_status()
        })
        
    except Exception as e:
        logger.error(f"Error en ai_query: {e}")
        return jsonify({
            'text': default_response,
            'rate_limit_status': gemini_limiter.get_status()
        })

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
        'timestamp': time.time(),
        'gemini_rate_limiter': gemini_limiter.get_status(),
        'google_maps_rate_limiter': gmaps_limiter.get_status()
    })

# ========== HEALTH CHECK ==========
@app.route('/health', methods=['GET'])
def health():
    """Health check para Render."""
    gemini_status = gemini_limiter.get_status()
    gmaps_status = gmaps_limiter.get_status()
    
    return jsonify({
        'status': 'healthy',
        'gmaps': 'ok' if gmaps else 'error',
        'gmaps_usage': f"{gmaps_status['searches']['day']}/{gmaps_status['searches']['max_day']} búsquedas, {gmaps_status['details']['day']}/{gmaps_status['details']['max_day']} detalles",
        'gemini': 'ok' if GEMINI_API_KEY else 'missing',
        'gemini_usage': f"{gemini_status['queries_this_minute']}/{gemini_status['max_per_minute']} por minuto, {gemini_status['total_today']}/{gemini_status['max_per_day']} hoy",
        'gmail_config': 'ok' if (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET) else 'missing'
    }), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
