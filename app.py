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
    """Intenta encontrar un email raspando la página principal del sitio web."""
    if not url or not url.startswith('http'):
        return ""
    try:
        response = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
        if response.status_code == 200:
            # Buscar patrones de email con Regex
            emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', response.text)
            if emails:
                # Retornar el primero encontrado que no sea una imagen común
                for e in emails:
                    if not e.endswith(('.png', '.jpg', '.jpeg', '.gif')):
                        return e
    except:
        pass
    return ""

def enviar_correo_real(servidor_smtp, puerto, usuario, password, destinatario, asunto, cuerpo):
    msg = MIMEMultipart()
    msg['From'] = usuario
    msg['To'] = destinatario
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo, 'plain'))
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
        # 1. Búsqueda inicial
        places_result = gmaps.places(query=f"dieteticas en {zona}")
        results = places_result.get('results', [])
        
        lista_completa = []
        
        # 2. Enriquecimiento (Obtener detalles de cada lugar)
        # Limitamos a los primeros 10 para no agotar la cuota de la API y que no tarde tanto
        for place in results[:15]:
            place_id = place['place_id']
            
            # Pedimos detalles específicos: teléfono y sitio web
            details = gmaps.place(place_id=place_id, fields=['name', 'formatted_address', 'formatted_phone_number', 'website'])
            res = details.get('result', {})
            
            nombre = res.get('name', 'Sin nombre')
            web = res.get('website', '')
            tel = res.get('formatted_phone_number', 'Sin teléfono')
            
            # Intentar buscar email si hay web
            email_encontrado = extraer_email_de_web(web) if web else ""
            
            # Crear Link de WhatsApp (limpiando el teléfono de caracteres no numéricos)
            tel_limpio = re.sub(r'\D', '', tel)
            wa_link = f"https://wa.me/{tel_limpio}" if tel_limpio else ""

            lista_completa.append({
                'nombre': nombre,
                'direccion': res.get('formatted_address', 'Sin dirección'),
                'telefono': tel,
                'whatsapp_link': wa_link,
                'website': web,
                'email': email_encontrado
            })
        
        if not lista_completa:
            return jsonify({'error': 'No se encontraron resultados.'}), 404

        df = pd.DataFrame(lista_completa)
        filename = f"leads_PRO_{zona.replace(' ', '_')}_{int(time.time())}.csv"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        
        return jsonify({
            'success': True, 
            'filename': filename,
            'total_rows': len(df),
            'filepath': filepath
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/preview_csv', methods=['POST'])
def preview_csv():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(filepath)
    try:
        df = pd.read_csv(filepath) if filepath.endswith('.csv') else pd.read_excel(filepath)
        df.columns = [c.lower().strip() for c in df.columns]
        return jsonify({'success': True, 'filepath': filepath, 'total_rows': len(df)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/start_campaign', methods=['POST'])
def start_campaign():
    data = request.form
    filepath = data.get('filepath')
    def generate():
        try:
            df = pd.read_csv(filepath) if filepath.endswith('.csv') else pd.read_excel(filepath)
            df.columns = [c.lower().strip() for c in df.columns]
            yield f"data: {{'status': 'start', 'total': {len(df)}}}\n\n"
            
            for index, row in df.iterrows():
                dest = row.get('email')
                if pd.isna(dest) or not str(dest).strip():
                    yield f"data: {{'progress': {index+1}, 'log': '<div>Fila {index+1} sin email (Prueba contactar por WhatsApp)</div>'}}\n\n"
                    continue
                
                if index > 0: time.sleep(random.randint(20, 45))
                
                ok, status = enviar_correo_real(
                    data.get('smtp_host'), int(data.get('smtp_port')), 
                    data.get('email_user'), data.get('email_pass'), 
                    dest, data.get('subject'), 
                    data.get('body').replace('{nombre}', str(row.get('nombre', 'Cliente')))
                )
                
                color = "text-green-400" if ok else "text-red-400"
                yield f"data: {{'progress': {index + 1}, 'log': \"<div class='{color}'>#{index+1} {dest}: {status}</div>\"}}\n\n"
            
            yield f"data: {{'status': 'finished'}}\n\n"
        except Exception as e:
            yield f"data: {{'error': \"{str(e)}\"}}\n\n"
            
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
