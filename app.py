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
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, send_file
from urllib.parse import urljoin

app = Flask(__name__)

# --- CONFIGURACIÓN DE SEGURIDAD (LEER DESDE SECRETS/ENTORNO) ---
# Aquí NO ponemos las llaves reales. Python las tomará de los "Secrets" de GitHub o del sistema.
GOOGLE_MAPS_KEY = os.environ.get('GOOGLE_MAPS_KEY')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

try:
    if GOOGLE_MAPS_KEY:
        gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)
    else:
        gmaps = None
        print("Advertencia: No se encontró la variable GOOGLE_MAPS_KEY.")
except Exception as e:
    gmaps = None
    print(f"Error al inicializar el cliente de Google Maps: {e}")

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
        if res.status_code != 200: return info
        
        texto_pagina = res.text
        found_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', texto_pagina)
        soup = BeautifulSoup(texto_pagina, 'html.parser')
        
        links_to_check = []
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'facebook.com' in href and not info["facebook"]: info["facebook"] = a['href']
            if 'instagram.com' in href and not info["instagram"]: info["instagram"] = a['href']
            
            if exhaustivo and any(term in href for term in ['contacto', 'contact', 'nosotros', 'info']):
                links_to_check.append(urljoin(url_base, a['href']))

        if exhaustivo:
            for link in list(set(links_to_check))[:3]:
                try:
                    r_sub = requests.get(link, timeout=6, headers=headers)
                    found_emails.extend(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', r_sub.text))
                except: pass

        for e in found_emails:
            if validar_email(e) and not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.pdf', '.css')):
                info["email"] = e.lower()
                break
    except: pass
    return info

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
        except: pass

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, destino, msg.as_string())
        server.quit()
        return True, "Enviado con éxito"
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search_places', methods=['POST'])
def search_places():
    zona = request.json.get('zona')
    exhaustivo = request.json.get('exhaustivo', False)
    if not gmaps: return jsonify({'error': 'La API de Google Maps no está configurada correctamente en los Secrets.'}), 500
    
    try:
        all_results = []
        response = gmaps.places(query=f"dieteticas en {zona}")
        all_results.extend(response.get('results', []))
        
        while 'next_page_token' in response:
            token = response['next_page_token']
            time.sleep(2)
            response = gmaps.places(query=f"dieteticas en {zona}", page_token=token)
            all_results.extend(response.get('results', []))
            if len(all_results) >= 60: break

        leads = []
        for p in all_results:
            try:
                det = gmaps.place(place_id=p['place_id'], fields=['name', 'formatted_address', 'formatted_phone_number', 'website'])['result']
                tel_raw = det.get('formatted_phone_number', '')
                tel_solo_numeros = re.sub(r'\D', '', tel_raw)
                if tel_solo_numeros and not tel_solo_numeros.startswith('54'):
                    tel_solo_numeros = '54' + tel_solo_numeros
                
                web = det.get('website', '')
                contacto = scraping_profundo_contacto(web, exhaustivo) if web else {"email": "", "facebook": "", "instagram": ""}

                leads.append({
                    'id': p['place_id'],
                    'nombre': det.get('name'),
                    'direccion': det.get('formatted_address'),
                    'telefono': tel_solo_numeros,
                    'tel_display': tel_raw,
                    'email': contacto["email"],
                    'facebook': contacto["facebook"],
                    'instagram': contacto["instagram"],
                    'web': web
                })
            except: continue

        return jsonify({'success': True, 'leads': leads})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/start_email_campaign', methods=['POST'])
def start_email_campaign():
    selected = json.loads(request.form.get('leads'))
    user = request.form.get('email_user')
    password = request.form.get('email_pass')
    subject_template = request.form.get('subject')
    body_template = request.form.get('body')
    attach_img = request.form.get('attach_image') == 'true'

    def generate():
        total = len(selected)
        yield f"data: {json.dumps({'status': 'start', 'total': total})}\n\n"
        
        for i, lead in enumerate(selected):
            if i > 0: time.sleep(random.randint(25, 45))
            
            asunto_p = subject_template.replace('{nombre}', lead['nombre'])
            cuerpo_p = body_template.replace('{nombre}', lead['nombre'])
            
            ok, msg = enviar_mail_soberania(user, password, lead['email'], asunto_p, cuerpo_p, attach_img)
            
            res_class = 'text-green-400' if ok else 'text-red-400 font-bold'
            log_html = f"<div class='{res_class} text-[10px] border-b border-white/5 pb-1'>[{i+1}/{total}] {lead['email']}: {msg}</div>"
            
            yield f"data: {json.dumps({'progress': i+1, 'log': log_html})}\n\n"
            
        yield f"data: {json.dumps({'status': 'finished'})}\n\n"
        
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

