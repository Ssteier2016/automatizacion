import os
import smtplib
import time
import random
import re
import requests
import googlemaps
import json
import logging
from typing import Dict, List
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, send_file
from urllib.parse import urljoin

# Configurar logging
logging.basicConfig(level=logging.DEBUG)
app = Flask(__name__)

# --- CONFIGURACIÓN DE SEGURIDAD ---
GOOGLE_MAPS_KEY = os.environ.get('GOOGLE_MAPS_KEY')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

app.logger.info(f"GOOGLE_MAPS_KEY configurada: {bool(GOOGLE_MAPS_KEY)}")
app.logger.info(f"OPENAI_API_KEY configurada: {bool(OPENAI_API_KEY)}")

# Configurar Google Maps
try:
    if GOOGLE_MAPS_KEY:
        gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)
        app.logger.info("✅ Google Maps configurado correctamente")
    else:
        gmaps = None
        app.logger.warning("⚠️ GOOGLE_MAPS_KEY no encontrada. Añádela en Render Dashboard → Environment")
except Exception as e:
    gmaps = None
    app.logger.error(f"❌ Error al inicializar Google Maps: {e}")

# Configurar OpenAI (versión 0.28.1)
openai_client = None
try:
    if OPENAI_API_KEY:
        import openai
        openai.api_key = OPENAI_API_KEY
        openai_client = openai
        app.logger.info("✅ OpenAI configurado correctamente (v0.28.1)")
    else:
        app.logger.warning("⚠️ OPENAI_API_KEY no encontrada. Añádela en Render Dashboard → Environment")
except Exception as e:
    app.logger.error(f"❌ Error al configurar OpenAI: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/producto.png')
def get_producto_image():
    if os.path.exists('producto.png'):
        return send_file('producto.png', mimetype='image/png')
    return "Imagen no encontrada", 404

def validar_email(email):
    patron = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(patron, email))

def scraping_profundo_contacto(url_base, exhaustivo=False):
    info = {"email": "", "facebook": "", "instagram": ""}
    if not url_base or not url_base.startswith('http'):
        return info
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'}
    try:
        res = requests.get(url_base, timeout=12, headers=headers)
        if res.status_code != 200: 
            return info
        
        texto_pagina = res.text
        found_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', texto_pagina)
        soup = BeautifulSoup(texto_pagina, 'html.parser')
        
        links_to_check = []
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'facebook.com' in href and not info["facebook"]: 
                info["facebook"] = a['href']
            if 'instagram.com' in href and not info["instagram"]: 
                info["instagram"] = a['href']
            
            if exhaustivo and any(term in href for term in ['contacto', 'contact', 'nosotros', 'info']):
                links_to_check.append(urljoin(url_base, a['href']))

        if exhaustivo:
            for link in list(set(links_to_check))[:3]:
                try:
                    r_sub = requests.get(link, timeout=6, headers=headers)
                    found_emails.extend(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', r_sub.text))
                except: 
                    pass

        for e in found_emails:
            if validar_email(e) and not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.pdf', '.css')):
                info["email"] = e.lower()
                break
    except Exception as e:
        app.logger.debug(f"Error en scraping: {e}")
    return info

def analizar_con_ia(zona: str, negocios: List[Dict]) -> str:
    """Analiza negocios con IA para encontrar dietéticas relevantes."""
    if not openai_client or not negocios:
        return "Análisis IA no disponible o sin datos."
    
    try:
        # Crear un resumen de los negocios encontrados
        resumen = "\n".join([f"- {n.get('nombre', 'Sin nombre')} ({n.get('direccion', 'Sin dirección')})" 
                           for n in negocios[:10]])
        
        prompt = f"""
        Soy un vendedor de yerba mate para dietéticas. 
        He buscado en Google Maps comercios en {zona} y encontré estos resultados:
        
        {resumen}
        
        Analiza estos negocios y dime:
        1. ¿Cuáles parecen ser dietéticas, naturistas o comercios de productos naturales?
        2. ¿Cuáles podrían estar interesados en vender yerba mate orgánica?
        3. Sugiere una estrategia de venta personalizada para esta zona.
        
        Responde en español, máximo 300 caracteres.
        """
        
        response = openai_client.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Eres un experto en marketing B2B para productos naturales."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.7
        )
        
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        app.logger.error(f"Error en análisis IA: {e}")
        return f"Análisis IA temporalmente no disponible."

def enviar_mail_soberania(smtp_user, smtp_pass, destino, asunto, cuerpo, adjuntar_imagen):
    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = destino
    msg['Subject'] = asunto
    
    msg.attach(MIMEText(cuerpo, 'plain'))

    if adjuntar_imagen and os.path.exists('producto.png'):
        try:
            with open('producto.png', 'rb') as f:
                img_data = f.read()
            adjunto = MIMEImage(img_data)
            adjunto.add_header('Content-Disposition', 'attachment', filename="Yerba_Soberania_Producto.png")
            msg.attach(adjunto)
        except: 
            pass

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, destino, msg.as_string())
        server.quit()
        return True, "Enviado con éxito"
    except Exception as e:
        return False, str(e)

@app.route('/search_combinado', methods=['POST'])
def search_combinado():
    """Búsqueda que combina Google Maps e IA en una sola llamada."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No se recibieron datos JSON'}), 400
        
        zona = data.get('zona')
        usar_ia = data.get('usar_ia', True)
        
        app.logger.info(f"🔍 Buscando en zona: {zona}, IA: {usar_ia}")
        
        if not zona:
            return jsonify({'error': 'Debe proporcionar una zona'}), 400
        
        if not gmaps:
            app.logger.error("❌ Google Maps no está configurado")
            return jsonify({
                'error': 'Google Maps no está configurado.',
                'detalle': 'Añade GOOGLE_MAPS_KEY en Render Dashboard → Environment'
            }), 500
        
        # Búsqueda en Google Maps
        all_results = []
        
        search_queries = [
            f"dietética en {zona}",
            f"naturista en {zona}",
            f"productos naturales en {zona}",
        ]
        
        for query in search_queries:
            try:
                response = gmaps.places(query=query)
                results = response.get('results', [])
                all_results.extend(results)
                app.logger.info(f"Query '{query}': {len(results)} resultados")
                
                if len(all_results) >= 15:
                    break
            except Exception as e:
                app.logger.warning(f"Error en query '{query}': {e}")
                continue
        
        # Si no hay resultados, intentar búsqueda más genérica
        if len(all_results) == 0:
            try:
                response = gmaps.places(query=f"comercios en {zona}")
                all_results = response.get('results', [])[:10]
                app.logger.info(f"Búsqueda genérica: {len(all_results)} resultados")
            except Exception as e:
                app.logger.error(f"Error en búsqueda genérica: {e}")
        
        # Eliminar duplicados
        seen_ids = set()
        unique_results = []
        for result in all_results:
            if result.get('place_id') and result['place_id'] not in seen_ids:
                seen_ids.add(result['place_id'])
                unique_results.append(result)
        
        app.logger.info(f"📊 Total resultados únicos: {len(unique_results)}")
        
        leads = []
        for p in unique_results[:20]:
            try:
                det = gmaps.place(
                    place_id=p['place_id'], 
                    fields=['name', 'formatted_address', 'formatted_phone_number', 'website', 'types']
                )['result']
                
                # Categorizar
                categoria = ""
                tipos = det.get('types', [])
                tipo_str = " ".join(tipos).lower()
                if any(word in tipo_str for word in ['health', 'food', 'grocery', 'store', 'market', 'diet']):
                    categoria = "Posible dietética"
                elif any(word in tipo_str for word in ['restaurant', 'cafe', 'food']):
                    categoria = "Cafetería/Restaurante"
                else:
                    categoria = "Comercio local"
                
                tel_raw = det.get('formatted_phone_number', '')
                tel_solo_numeros = re.sub(r'\D', '', tel_raw)
                if tel_solo_numeros and not tel_solo_numeros.startswith('54'):
                    tel_solo_numeros = '54' + tel_solo_numeros
                
                web = det.get('website', '')
                contacto = scraping_profundo_contacto(web, exhaustivo=True) if web else {"email": "", "facebook": "", "instagram": ""}
                
                leads.append({
                    'id': p['place_id'],
                    'nombre': det.get('name', 'Sin nombre'),
                    'direccion': det.get('formatted_address', 'Sin dirección'),
                    'telefono': tel_solo_numeros,
                    'tel_display': tel_raw,
                    'email': contacto["email"],
                    'facebook': contacto["facebook"],
                    'instagram': contacto["instagram"],
                    'web': web,
                    'categoria': categoria,
                    'tipos': tipos,
                    'email_verificado': bool(contacto["email"])
                })
                
                app.logger.debug(f"Procesado: {det.get('name')} - Email: {contacto['email']}")
                
            except Exception as e:
                app.logger.debug(f"Error procesando lugar: {e}")
                continue
        
        # Análisis IA
        ia_resultados = ""
        if usar_ia and openai_client and leads:
            try:
                ia_resultados = analizar_con_ia(zona, leads[:10])
                app.logger.info(f"🤖 Análisis IA generado")
            except Exception as e:
                app.logger.error(f"Error en análisis IA: {e}")
                ia_resultados = "Error en análisis IA"
        
        return jsonify({
            'success': True,
            'leads': leads,
            'ia_resultados': ia_resultados,
            'total': len(leads),
            'con_email': len([l for l in leads if l['email']]),
            'con_telefono': len([l for l in leads if l['telefono']]),
            'mensaje': f"Encontrados {len(leads)} comercios en {zona}"
        })
        
    except Exception as e:
        app.logger.error(f"❌ Error en search_combinado: {str(e)}", exc_info=True)
        return jsonify({
            'error': 'Error interno del servidor',
            'detalle': str(e)
        }), 500

@app.route('/test')
def test():
    """Ruta de prueba para verificar que el servidor funciona."""
    return jsonify({
        'status': 'online',
        'google_maps': 'configured' if gmaps else 'not_configured',
        'openai': 'configured' if openai_client else 'not_configured',
        'message': 'Servidor funcionando correctamente'
    })

@app.route('/test_search')
def test_search():
    """Ruta de prueba para Google Maps (sin API key)."""
    if not gmaps:
        return jsonify({'error': 'Google Maps no configurado'}), 500
    
    try:
        # Búsqueda de prueba simple
        response = gmaps.places(query="dietética en Buenos Aires")
        return jsonify({
            'success': True,
            'results_count': len(response.get('results', [])),
            'status': 'Google Maps funcionando'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ... (las otras rutas se mantienen igual)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
