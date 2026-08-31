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

def deep_email_scraper(url_base):
    """Escanea la web y subpáginas buscando emails de contacto y redes sociales."""
    if not url_base or not url_base.startswith('http'):
        return {"email": "", "socials": []}
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'}
    emails_found = set()
    social_links = []
    
    try:
        res = requests.get(url_base, timeout=10, headers=headers)
        if res.status_code != 200: return {"email": "", "socials": []}
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Buscar mails en el texto de la Home
        raw_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', res.text)
        emails_found.update(raw_emails)

        # Buscar enlaces de interés (Contacto, Instagram, FB)
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            # Detectar Redes
            if 'instagram.com' in href: social_links.append({"platform": "ig", "url": a['href']})
            if 'facebook.com' in href: social_links.append({"platform": "fb", "url": a['href']})
            
            # Buscar página de contacto para profundizar
            if any(term in href for term in ['contacto', 'contact', 'nosotros', 'about']):
                full_url = urljoin(url_base, a['href'])
                try:
                    res_c = requests.get(full_url, timeout=5, headers=headers)
                    emails_found.update(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', res_c.text))
                except: continue

        # Limpiar falsos positivos (imágenes que parecen mails)
        valid_emails = [e for e in emails_found if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'))]
        
        return {
            "email": valid_emails[0] if valid_emails else "",
            "socials": social_links[:2] # Limitar a 2 links principales
        }
    except:
        return {"email": "", "socials": []}

def send_soberania_email(smtp_user, smtp_pass, target_email, client_name, image_url):
    """Lógica de envío SMTP con adjunto."""
    subject = f"Propuesta Mayorista: Yerba Mate Soberanía para {client_name}"
    body = f"""Hola {client_name}, buen día:

Mi nombre es Juan Ignacio Lewczuk y me comunico para ofrecerles Yerba Mate Soberanía para venta por mayor en dietéticas y comercios naturales.

Trabajamos con una yerba de origen misionero, de excelente calidad, estacionada, con muy buena aceptación por parte de los consumidores que buscan un producto tradicional y confiable.

Ofrecemos:

✅ Precios mayoristas competitivos
✅ Abastecimiento constante
✅ Formatos ideales para dietéticas
✅ Posibilidad de compras recurrentes

Quedo a disposición para enviarles lista de precios, condiciones de venta o coordinar un primer pedido de prueba.

Muchas gracias por su tiempo.

Saludos cordiales,
Juan Ignacio Lewczuk
📱 WhatsApp: 11 3134-4552
✉️ Email: lewczukjuani@gmail.com"""

    msg = MIMEMultipart()
    msg['From'] = f"Juan Ignacio Lewczuk <{smtp_user}>"
    msg['To'] = target_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    if image_url:
        try:
            # Forzar link RAW de GitHub
            raw_img_url = image_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
            img_content = requests.get(raw_img_url, timeout=10).content
            image = MIMEImage(img_content)
            image.add_header('Content-Disposition', 'attachment', filename="Yerba_Soberania.png")
            msg.attach(image)
        except: pass

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, target_email, msg.as_string())
        server.quit()
        return True, "Enviado"
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search_places', methods=['POST'])
def search_places():
    if not gmaps: return jsonify({'error': 'Error de API Key'}), 500
    zona = request.json.get('zona')
    try:
        results = gmaps.places(query=f"dieteticas en {zona}")['results']
        leads = []
        for p in results[:15]:
            details = gmaps.place(place_id=p['place_id'], fields=['name', 'formatted_address', 'website'])['result']
            web = details.get('website', '')
            
            # Busqueda profunda de contacto
            contact_info = deep_email_scraper(web) if web else {"email": "", "socials": []}
            
            leads.append({
                'id': p['place_id'],
                'nombre': details.get('name'),
                'direccion': details.get('formatted_address'),
                'email': contact_info['email'],
                'web': web,
                'socials': contact_info['socials']
            })
        
        # Guardar estado temporal
        df = pd.DataFrame(leads)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], "current_leads.csv")
        df.to_csv(filepath, index=False)
        
        return jsonify({'success': True, 'leads': leads, 'filepath': filepath})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/start_campaign', methods=['POST'])
def start_campaign():
    """Recibe la lista de IDs seleccionados y envía el correo."""
    selected_data = json.loads(request.form.get('selected_leads'))
    user = request.form.get('email_user')
    password = request.form.get('email_pass')
    image = request.form.get('image_url')

    def generate():
        total = len(selected_data)
        yield f"data: {{'status': 'start', 'total': {total}}}\n\n"
        
        for i, lead in enumerate(selected_data):
            if i > 0: time.sleep(random.randint(20, 45)) # Delay anti-spam
            
            ok, msg = send_soberania_email(user, password, lead['email'], lead['nombre'], image)
            color = "text-green-400" if ok else "text-red-400"
            yield f"data: {{'progress': {i+1}, 'log': \"<div class='{color}'>#{i+1} {lead['email']}: {msg}</div>\"}}\n\n"
            
        yield f"data: {{'status': 'finished'}}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

