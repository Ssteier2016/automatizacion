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

# Configuración de carpetas para Render
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
    Busca correos electrónicos visitando la Home y las sub-páginas de contacto.
    """
    if not url_base or not url_base.startswith('http'):
        return ""
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    emails_found = set()
    
    try:
        # 1. Analizar Home
        res = requests.get(url_base, timeout=8, headers=headers)
        if res.status_code != 200: return ""
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        def find_in_text(text):
            return re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)

        emails_found.update(find_in_text(res.text))

        # 2. Buscar enlaces de contacto o quienes somos
        contact_links = []
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if any(term in href for term in ['contacto', 'contact', 'nosotros', 'about', 'info', 'donde']):
                full_url = urljoin(url_base, a['href'])
                contact_links.append(full_url)
        
        # 3. Visitar los links encontrados (máximo 2 adicionales para velocidad)
        for link in list(set(contact_links))[:2]:
            try:
                res_c = requests.get(link, timeout=5, headers=headers)
                emails_found.update(find_in_text(res_c.text))
            except: continue

        # Filtrar extensiones de imagen comunes que el Regex puede capturar
        valid_emails = [e for e in emails_found if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'))]
        
        return valid_emails[0] if valid_emails else ""
    except:
        return ""

def enviar_correo_soberania(servidor_smtp, puerto, usuario, password, destinatario, asunto, cuerpo, imagen_url=None):
    """Envía el email profesional con el adjunto de la yerba."""
    msg = MIMEMultipart()
    msg['From'] = f"Juan Ignacio Lewczuk <{usuario}>"
    msg['To'] = destinatario
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo, 'plain'))

    if imagen_url:
        try:
            # Convertimos link de GitHub a Raw para que Python pueda descargarlo
            raw_url = imagen_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
            img_data = requests.get(raw_url, timeout=10).content
            image = MIMEImage(img_data)
            image.add_header('Content-Disposition', 'attachment', filename="Yerba_Mate_Soberania.png")
            msg.attach(image)
        except Exception as e:
            print(f"No se pudo adjuntar la imagen: {e}")

    try:
        server = smtplib.SMTP(servidor_smtp, puerto)
        server.starttls()
        server.login(usuario, password)
        server.sendmail(usuario, destinatario, msg.as_string())
        server.quit()
        return True, "Enviado correctamente"
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search_places', methods=['POST'])
def search_places():
    if not gmaps: return jsonify({'error': 'API de Google Maps no configurada.'}), 500
    
    zona = request.json.get('zona')
    if not zona: return jsonify({'error': 'Debes ingresar una ubicación.'}), 400

    try:
        places_result = gmaps.places(query=f"dieteticas en {zona}")
        results = places_result.get('results', [])
        
        leads = []
        # Escaneamos los primeros 15 resultados para asegurar profundidad
        for place in results[:15]:
            details = gmaps.place(place_id=place['place_id'], fields=['name', 'formatted_address', 'website'])['result']
            
            web = details.get('website', '')
            # Ejecutar scraping profundo
            email_scrap = extraer_emails_profundo(web) if web else ""

            leads.append({
                'nombre': details.get('name', 'Sin nombre'),
                'direccion': details.get('formatted_address', 'Sin dirección'),
                'email': email_scrap,
                'website': web
            })
        
        if not leads: return jsonify({'error': 'No se encontraron dietéticas en esta zona.'}), 404

        df = pd.DataFrame(leads)
        filename = f"prospectos_{zona.replace(' ', '_')}.csv"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        
        return jsonify({
            'success': True, 
            'leads': leads, 
            'filename': filename, 
            'filepath': filepath
        })
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
                    yield f"data: {{'progress': {i+1}, 'log': '<div>Fila {i+1}: Saltada (Sin email detectado).</div>'}}\n\n"
                    continue
                
                # Pausa Anti-Spam dinámica
                if i > 0: time.sleep(random.randint(25, 50))
                
                cuerpo_personalizado = data.get('body').replace('{nombre}', str(row.get('nombre', 'Cliente')))
                
                ok, status = enviar_correo_soberania(
                    'smtp.gmail.com', 587, data.get('email_user'), data.get('email_pass'),
                    email, data.get('subject'), cuerpo_personalizado, image_url
                )
                
                color = "text-green-400" if ok else "text-red-400"
                yield f"data: {{'progress': {i+1}, 'log': \"<div class='{color} font-mono'>#{i+1} {email}: {status}</div>\"}}\n\n"
            
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

