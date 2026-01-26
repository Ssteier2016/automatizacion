import os
import pandas as pd
import smtplib
import time
import random
import googlemaps
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, jsonify, Response, stream_with_context

app = Flask(__name__)

# Configuración
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# CONFIGURACIÓN GOOGLE MAPS - Reemplaza con tu clave real
# Nota: La API de Google Maps es necesaria para la búsqueda por zona
GOOGLE_MAPS_KEY = 'TU_API_KEY_AQUI'
try:
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)
except:
    gmaps = None

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
        return True, "Enviado correctamente"
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search_places', methods=['POST'])
def search_places():
    """Busca lugares en Google Maps y crea un CSV temporal."""
    if not gmaps:
        return jsonify({'error': 'Google Maps API no configurada en el servidor'}), 500
    
    data = request.json
    zona = data.get('zona')
    if not zona:
        return jsonify({'error': 'Debes ingresar una zona'}), 400

    query = f"dieteticas en {zona}"
    
    try:
        # Buscar lugares
        places_result = gmaps.places(query=query)
        
        lista_dieteticas = []
        for place in places_result.get('results', []):
            info = {
                'nombre': place.get('name'),
                'direccion': place.get('formatted_address'),
                # Google Maps no da emails. Ponemos un placeholder para que el usuario sepa que falta.
                'email': '' 
            }
            lista_dieteticas.append(info)
        
        if not lista_dieteticas:
            return jsonify({'error': 'No se encontraron resultados en esa zona'}), 404

        df = pd.DataFrame(lista_dieteticas)
        filename = f"busqueda_{int(time.time())}.csv"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        df.to_csv(filepath, index=False)
        
        return jsonify({
            'success': True, 
            'filepath': filepath, 
            'total_rows': len(df),
            'filename': filename,
            'message': 'Búsqueda completada. IMPORTANTE: Google Maps no provee emails, debes editarlos en el archivo o usar un buscador de mails.'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/preview_csv', methods=['POST'])
def preview_csv():
    if 'file' not in request.files:
        return jsonify({'error': 'No se subió ningún archivo'}), 400
    
    file = request.files['file']
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(filepath)

    try:
        df = pd.read_csv(filepath) if filepath.endswith('.csv') else pd.read_excel(filepath)
        df.columns = [c.lower().strip() for c in df.columns]
        
        if 'email' not in df.columns:
            return jsonify({'error': 'Falta la columna "email"'}), 400

        return jsonify({
            'success': True, 
            'filepath': filepath, 
            'total_rows': len(df)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/start_campaign', methods=['POST'])
def start_campaign():
    data = request.form
    filepath = data.get('filepath')
    email_user = data.get('email_user')
    email_pass = data.get('email_pass')
    smtp_host = data.get('smtp_host', 'smtp.gmail.com')
    smtp_port = int(data.get('smtp_port', 587))
    subject_template = data.get('subject')
    body_template = data.get('body')

    def generate():
        try:
            df = pd.read_csv(filepath) if filepath.endswith('.csv') else pd.read_excel(filepath)
            df.columns = [c.lower().strip() for c in df.columns]
            total = len(df)

            yield f"data: {{'status': 'start', 'total': {total}}}\n\n"

            success_count = 0
            fail_count = 0

            for index, row in df.iterrows():
                destinatario = row.get('email')
                nombre = row.get('nombre', 'Cliente')
                
                if pd.isna(destinatario) or destinatario == '':
                    log_html = f"<div class='mb-2 p-2 border-b border-gray-700 text-sm text-yellow-500 font-mono'>[{index+1}] Saltado: Sin email</div>"
                    yield f"data: {{'progress': {index + 1}, 'log': \"{log_html}\"}}\n\n"
                    continue

                # --- Lógica de Pausa Anti-Spam ---
                # Esperamos un tiempo aleatorio antes de cada envío para parecer humanos
                tiempo_espera = random.randint(20, 45) # Segundos
                
                cuerpo_final = body_template.replace('{nombre}', str(nombre))

                # MODO PRODUCCIÓN
                sent_ok, msg_status = enviar_correo_real(smtp_host, smtp_port, email_user, email_pass, destinatario, subject_template, cuerpo_final)
                
                if sent_ok:
                    success_count += 1
                    status_color = "text-green-400"
                else:
                    fail_count += 1
                    status_color = "text-red-400"

                log_html = f"<div class='mb-2 p-2 border-b border-gray-700 text-sm font-mono'><span class='text-gray-500'>[{index+1}/{total}]</span> {destinatario}: <span class='{status_color}'>{msg_status}</span> <span class='text-xs text-gray-600'>(Pausa: {tiempo_espera}s)</span></div>"
                yield f"data: {{'progress': {index + 1}, 'log': \"{log_html}\"}}\n\n"
                
                # Pausamos la ejecución del hilo para este envío
                time.sleep(tiempo_espera)

            yield f"data: {{'status': 'finished', 'success': {success_count}, 'fail': {fail_count}}}\n\n"

        except Exception as e:
             yield f"data: {{'error': \"{str(e)}\"}}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
