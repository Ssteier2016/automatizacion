import os
import pandas as pd
import smtplib
import time
import random
import re
import requests
import googlemaps
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, send_from_directory
from urllib.parse import urljoin

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Clave de API de Google Maps
GOOGLE_MAPS_KEY = os.environ.get('GOOGLE_MAPS_KEY', 'AIzaSyBGJ8B2z9p52LM-x9vEwxO9pmx8V9w7Ws4')

try:
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)
except:
    gmaps = None

def extraer_emails_profundo(url_base):
    """
    Realiza una búsqueda profunda visitando la Home y páginas de contacto.
    """
    if not url_base or not url_base.startswith('http'):
        return ""
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    emails_encontrados = set()
    
    try:
        # 1. Analizar página principal
        res = requests.get(url_base, timeout=7, headers=headers)
        if res.status_code != 200: return ""
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Función para buscar mails en texto
        def buscar_en_texto(texto):
            return re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', texto)

        emails_encontrados.update(buscar_en_texto(res.text))

        # 2. Buscar links a páginas de contacto o nosotros
        contact_links = []
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if any(term in href for term in ['contacto', 'contact', 'nosotros', 'about', 'info']):
                full_url = urljoin(url_base, a['href'])
                contact_links.append(full_url)
        
        # 3. Visitar las páginas de contacto encontradas (limitado a 2 para no tardar mucho)
        for link in list(set(contact_links))[:2]:
            try:
                res_c = requests.get(link, timeout=5, headers=headers)
                emails_encontrados.update(buscar_en_texto(res_c.text))
            except:
                continue

        # Limpiar resultados (quitar extensiones de imagen falsos positivos)
        valid_emails = [e for e in emails_encontrados if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'))]
        
        return valid_emails[0] if valid_emails else ""
    except:
        return ""

def enviar_correo_soberania(servidor_smtp, puerto, usuario, password, destinatario, asunto, cuerpo, imagen_url=None):
    """Envía el correo con el adjunto de Yerba Mate Soberanía."""
    msg = MIMEMultipart()
    msg['From'] = usuario
    msg['To'] = destinatario
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo, 'plain'))

    if imagen_url:
        try:
            # Convertir link de GitHub blob a Raw para descarga directa
            raw_url = imagen_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
            img_data = requests.get(raw_url, timeout=10).content
            image = MIMEImage(img_data)
            image.add_header('Content-Disposition', 'attachment', filename="Producto_Soberania.png")
            msg.attach(image)
        except Exception as e:
            print(f"Error adjuntando imagen: {e}")

    try:
        server = smtplib.SMTP(servidor_smtp, puerto)
        server.starttls()
        server.login(usuario, password)
        server.sendmail(usuario, destinatario, msg.as_string())
        server.quit()
        return True, "Enviado con éxito"
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search_places', methods=['POST'])
def search_places():
    if not gmaps: return jsonify({'error': 'Google Maps API no disponible.'}), 500
    
    zona = request.json.get('zona')
    if not zona: return jsonify({'error': 'Ingresa una zona.'}), 400

    try:
        # Búsqueda en Maps
        places_result = gmaps.places(query=f"dieteticas en {zona}")
        results = places_result.get('results', [])
        
        leads = []
        for place in results[:15]: # Procesamos 15 para mantener calidad y velocidad
            details = gmaps.place(place_id=place['place_id'], fields=['name', 'formatted_address', 'formatted_phone_number', 'website'])['result']
            
            web = details.get('website', '')
            tel = re.sub(r'\D', '', details.get('formatted_phone_number', ''))
            if tel and not tel.startswith('54'): tel = '54' + tel

            # Búsqueda profunda de email
            email_scrap = extraer_emails_profundo(web) if web else ""

            leads.append({
                'nombre': details.get('name', 'Sin nombre'),
                'direccion': details.get('formatted_address', 'Sin dirección'),
                'telefono': tel,
                'email': email_scrap,
                'website': web
            })
        
        if not leads: return jsonify({'error': 'No se hallaron resultados.'}), 404

        df = pd.DataFrame(leads)
        filename = f"leads_{zona.replace(' ', '_')}.csv"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        
        return jsonify({'success': True, 'leads': leads, 'filename': filename, 'filepath': filepath})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/start_campaign', methods=['POST'])
def start_campaign():
    data = request.form
    filepath = data.get('filepath')
    image_url = data.get('image_url')

    def generate():
        try:
            df = pd.read_csv(filepath)
            total = len(df)
            yield f"data: {{'status': 'start', 'total': {total}}}\n\n"
            
            for i, row in df.iterrows():
                email = row.get('email')
                if pd.isna(email) or not str(email).strip():
                    yield f"data: {{'progress': {i+1}, 'log': '<div>Fila {i+1} sin email encontrado.</div>'}}\n\n"
                    continue
                
                if i > 0: time.sleep(random.randint(20, 45))
                
                cuerpo = data.get('body').replace('{nombre}', str(row.get('nombre', 'Cliente')))
                ok, status = enviar_correo_soberania(
                    'smtp.gmail.com', 587, data.get('email_user'), data.get('email_pass'),
                    email, data.get('subject'), cuerpo, image_url
                )
                
                color = "text-green-400" if ok else "text-red-400"
                yield f"data: {{'progress': {i+1}, 'log': \"<div class='{color}'>#{i+1} {email}: {status}</div>\"}}\n\n"
            
            yield f"data: {{'status': 'finished'}}\n\n"
        except Exception as e:
            yield f"data: {{'error': \"{str(e)}\"}}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route('/download/<filename>')
def download(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

