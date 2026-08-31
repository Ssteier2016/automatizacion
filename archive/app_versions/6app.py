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
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, send_from_directory
from urllib.parse import urljoin

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# API KEY GOOGLE MAPS
GOOGLE_MAPS_KEY = os.environ.get('GOOGLE_MAPS_KEY', 'AIzaSyBGJ8B2z9p52LM-x9vEwxO9pmx8V9w7Ws4')
try:
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)
except:
    gmaps = None

def validar_email(email):
    """Verifica si el email tiene un formato válido."""
    patron_generico = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(patron_generico, email))

def scraping_profundo_contacto(url_base):
    """Busca emails en la web principal y subpáginas de contacto."""
    if not url_base or not url_base.startswith('http'):
        return ""
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'}
    try:
        res = requests.get(url_base, timeout=10, headers=headers)
        if res.status_code != 200: return ""
        
        found = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', res.text)
        
        soup = BeautifulSoup(res.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if any(term in href for term in ['contacto', 'contact', 'nosotros', 'info']):
                url_c = urljoin(url_base, a['href'])
                res_c = requests.get(url_c, timeout=5, headers=headers)
                found.extend(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', res_c.text))
        
        for e in found:
            if validar_email(e) and not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp')):
                return e.lower()
    except:
        pass
    return ""

def enviar_mail_soberania(smtp_user, smtp_pass, destino, asunto, cuerpo, imagen_url):
    """Envío de la propuesta oficial con adjunto de imagen desde GitHub."""
    msg = MIMEMultipart()
    msg['From'] = f"Juan Ignacio Lewczuk <{smtp_user}>"
    msg['To'] = destino
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo, 'plain'))

    if imagen_url:
        try:
            # Convertir link de GitHub blob a link Raw para descarga directa
            raw_url = imagen_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
            img_data = requests.get(raw_url, timeout=15).content
            adjunto = MIMEImage(img_data)
            adjunto.add_header('Content-Disposition', 'attachment', filename="Producto_Yerba_Soberania.png")
            msg.attach(adjunto)
        except Exception as e:
            print(f"Error adjuntando imagen: {e}")

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
    if not gmaps: return jsonify({'error': 'Google Maps API no configurada.'}), 500
    
    try:
        res_maps = gmaps.places(query=f"dieteticas en {zona}")['results']
        leads = []
        for p in res_maps[:15]:
            det = gmaps.place(place_id=p['place_id'], fields=['name', 'formatted_address', 'formatted_phone_number', 'website'])['result']
            tel_raw = det.get('formatted_phone_number', '')
            tel_solo_numeros = re.sub(r'\D', '', tel_raw)
            if tel_solo_numeros and not tel_solo_numeros.startswith('54'):
                tel_solo_numeros = '54' + tel_solo_numeros
            
            web = det.get('website', '')
            email_hallado = scraping_profundo_contacto(web) if web else ""

            leads.append({
                'id': p['place_id'],
                'nombre': det.get('name'),
                'direccion': det.get('formatted_address'),
                'telefono': tel_solo_numeros,
                'tel_display': tel_raw,
                'email': email_hallado,
                'web': web
            })
        
        return jsonify({'success': True, 'leads': leads})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/start_email_campaign', methods=['POST'])
def start_email_campaign():
    selected = json.loads(request.form.get('leads'))
    user = request.form.get('email_user')
    password = request.form.get('email_pass')
    image = request.form.get('image_url')
    subject_template = request.form.get('subject')
    body_template = request.form.get('body')

    def generate():
        total = len(selected)
        yield f"data: {{'status': 'start', 'total': {total}}}\n\n"
        for i, lead in enumerate(selected):
            if i > 0: time.sleep(random.randint(25, 45)) # Delay Anti-Spam
            
            # Personalización dinámica del mensaje por cada destinatario
            asunto_personalizado = subject_template.replace('{nombre}', lead['nombre'])
            cuerpo_personalizado = body_template.replace('{nombre}', lead['nombre'])
            
            ok, msg = enviar_mail_soberania(user, password, lead['email'], asunto_personalizado, cuerpo_personalizado, image)
            color = "text-green-400" if ok else "text-red-400"
            yield f"data: {{'progress': {i+1}, 'log': \"<div class='{color} font-mono text-[10px] border-b border-slate-800 pb-1'>[{i+1}/{total}] {lead['email']}: {msg}</div>\"}}\n\n"
            
        yield f"data: {{'status': 'finished'}}\n\n"
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

