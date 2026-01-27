import os
import pandas as pd
import smtplib
import time
import random
import re
import requests
import googlemaps
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, send_from_directory

app = Flask(__name__)

# Configuración de carpetas temporales
app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Clave de API de Google Maps
GOOGLE_MAPS_KEY = os.environ.get('GOOGLE_MAPS_KEY', 'AIzaSyBGJ8B2z9p52LM-x9vEwxO9pmx8V9w7Ws4')

try:
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)
except Exception as e:
    gmaps = None

def extraer_email_de_web(url):
    """Busca correos electrónicos raspando la web del local."""
    if not url or not url.startswith('http'):
        return ""
    try:
        response = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
        if response.status_code == 200:
            emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', response.text)
            if emails:
                for e in emails:
                    if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg')):
                        return e
    except:
        pass
    return ""

def enviar_correo_completo(servidor_smtp, puerto, usuario, password, destinatario, asunto, cuerpo, imagen_url=None):
    """Envía correo con soporte opcional para imagen adjunta desde URL."""
    msg = MIMEMultipart()
    msg['From'] = usuario
    msg['To'] = destinatario
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo, 'plain'))

    if imagen_url and imagen_url.startswith('http'):
        try:
            img_data = requests.get(imagen_url).content
            image = MIMEImage(img_data, name=os.path.basename(imagen_url))
            msg.attach(image)
        except:
            pass # Si falla la imagen, envía el texto solo

    try:
        server = smtplib.SMTP(servidor_smtp, puerto)
        server.starttls()
        server.login(usuario, password)
        server.sendmail(usuario, destinatario, msg.as_string())
        server.quit()
        return True, "Enviado"
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search_places', methods=['POST'])
def search_places():
    if not gmaps:
        return jsonify({'error': 'API de Google Maps no configurada.'}), 500
    
    data = request.json
    zona = data.get('zona')
    if not zona:
        return jsonify({'error': 'Ingresa una zona.'}), 400

    try:
        places_result = gmaps.places(query=f"dieteticas en {zona}")
        results = places_result.get('results', [])
        
        lista_completa = []
        # Limitamos a 20 para balancear velocidad y cantidad
        for place in results[:20]:
            place_id = place['place_id']
            details = gmaps.place(place_id=place_id, fields=['name', 'formatted_address', 'formatted_phone_number', 'website'])
            res = details.get('result', {})
            
            web = res.get('website', '')
            tel = res.get('formatted_phone_number', '')
            tel_limpio = re.sub(r'\D', '', tel)
            
            # Formatear número para WhatsApp (asumiendo Argentina +54 si no tiene código)
            if tel_limpio and not tel_limpio.startswith('54'):
                tel_limpio = '54' + tel_limpio

            lista_completa.append({
                'nombre': res.get('name', 'Sin nombre'),
                'direccion': res.get('formatted_address', 'Sin dirección'),
                'telefono': tel_limpio,
                'website': web,
                'email': extraer_email_de_web(web) if web else ""
            })
        
        if not lista_completa:
            return jsonify({'error': 'No se encontraron resultados.'}), 404

        df = pd.DataFrame(lista_completa)
        filename = f"leads_{zona.replace(' ', '_')}.csv"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        
        return jsonify({
            'success': True, 
            'leads': lista_completa,
            'filename': filename,
            'filepath': filepath
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/start_campaign', methods=['POST'])
def start_campaign():
    data = request.form
    filepath = data.get('filepath')
    img_url = data.get('image_url')

    def generate():
        try:
            df = pd.read_csv(filepath)
            df.columns = [c.lower().strip() for c in df.columns]
            yield f"data: {{'status': 'start', 'total': {len(df)}}}\n\n"
            
            for index, row in df.iterrows():
                dest = row.get('email')
                if pd.isna(dest) or not str(dest).strip():
                    yield f"data: {{'progress': {index+1}, 'log': '<div>Fila {index+1} sin email</div>'}}\n\n"
                    continue
                
                if index > 0: time.sleep(random.randint(15, 30))
                
                cuerpo = data.get('body').replace('{nombre}', str(row.get('nombre', 'Cliente')))
                
                ok, status = enviar_correo_completo(
                    'smtp.gmail.com', 587, 
                    data.get('email_user'), data.get('email_pass'), 
                    dest, data.get('subject'), cuerpo, img_url
                )
                
                color = "text-green-400" if ok else "text-red-400"
                yield f"data: {{'progress': {index + 1}, 'log': \"<div class='{color}'>#{index+1} {dest}: {status}</div>\"}}\n\n"
            
            yield f"data: {{'status': 'finished'}}\n\n"
        except Exception as e:
            yield f"data: {{'error': \"{str(e)}\"}}\n\n"
            
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

