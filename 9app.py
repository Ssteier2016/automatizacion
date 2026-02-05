import os
import pandas as pd
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
# Habilitamos CORS para que React pueda comunicarse con Flask sin problemas de seguridad
CORS(app)

app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# API KEY GOOGLE MAPS
GOOGLE_MAPS_KEY = os.environ.get('GOOGLE_MAPS_KEY', 'AIzaSyBGJ8B2z9p52LM-x9vEwxO9pmx8V9w7Ws4')
try:
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)
except:
    gmaps = None

@app.route('/producto.png')
def get_producto_image():
    if os.path.exists('producto.png'):
        return send_file('producto.png', mimetype='image/png')
    return "No encontrado", 404

def validar_email(email):
    patron_generico = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(patron_generico, email))

def scraping_profundo_contacto(url_base, exhaustivo=False):
    """Busca emails y redes sociales con mayor profundidad si se solicita."""
    info = {"email": "", "facebook": "", "instagram": ""}
    if not url_base or not url_base.startswith('http'):
        return info
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'}
    try:
        res = requests.get(url_base, timeout=10, headers=headers)
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
            
            if exhaustivo and any(term in href for term in ['contacto', 'contact', 'nosotros', 'about', 'info', 'donde']):
                links_to_check.append(h_full)

        if exhaustivo:
            for link in list(set(links_to_check))[:3]:
                try:
                    r_sub = requests.get(link, timeout=5, headers=headers)
                    found_emails.extend(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', r_sub.text))
                    s_sub = BeautifulSoup(r_sub.text, 'html.parser')
                    for a_sub in s_sub.find_all('a', href=True):
                        h_sub = a_sub['href'].lower()
                        if 'facebook.com' in h_sub and not info["facebook"]: info["facebook"] = a_sub['href']
                        if 'instagram.com' in h_sub and not info["instagram"]: info["instagram"] = a_sub['href']
                except: pass

        for e in found_emails:
            if validar_email(e) and not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.pdf', '.css')):
                info["email"] = e.lower()
                break
    except: pass
    return info

def enviar_mail_soberania(smtp_user, smtp_pass, destino, asunto, cuerpo, adjuntar_imagen):
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
        except: pass

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
    # Volvemos a servir el archivo HTML que cargará React
    return render_template('index.html')

@app.route('/search_places', methods=['POST'])
def search_places():
    data = request.json
    zona = data.get('zona')
    exhaustivo = data.get('exhaustivo', False)
    if not gmaps: return jsonify({'error': 'Configurar API Key'}), 500
    
    try:
        all_results = []
        response = gmaps.places(query=f"dieteticas en {zona}")
        all_results.extend(response.get('results', []))
        
        next_token = response.get('next_page_token')
        if next_token:
            time.sleep(2)
            response2 = gmaps.places(query=f"dieteticas en {zona}", page_token=next_token)
            all_results.extend(response2.get('results', []))

        leads = []
        for p in all_results[:40]:
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
    data = request.json
    selected = data.get('leads')
    user = data.get('email_user')
    password = data.get('email_pass')
    subject_template = data.get('subject')
    body_template = data.get('body')
    attach_img = data.get('attach_image') == True

    def generate():
        total = len(selected)
        yield f"data: {json.dumps({'status': 'start', 'total': total})}\n\n"
        for i, lead in enumerate(selected):
            if i > 0: 
                time.sleep(random.randint(10, 20))
            
            asunto_p = subject_template.replace('{nombre}', lead['nombre'])
            cuerpo_p = body_template.replace('{nombre}', lead['nombre'])
            ok, msg = enviar_mail_soberania(user, password, lead['email'], asunto_p, cuerpo_p, attach_img)
            
            yield f"data: {json.dumps({'progress': i+1, 'msg': msg, 'index': lead.get('original_index'), 'success': ok})}\n\n"
        
        yield f"data: {json.dumps({'status': 'finished'})}\n\n"
        
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
