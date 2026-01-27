import os
import pandas as pd
import smtplib
import time
import random
import googlemaps
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, send_from_directory

app = Flask(__name__)

# Configuración de carpetas temporales para Render
app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Clave de API de Google Maps (Configurada en Render o valor directo)
GOOGLE_MAPS_KEY = os.environ.get('GOOGLE_MAPS_KEY', 'AIzaSyBGJ8B2z9p52LM-x9vEwxO9pmx8V9w7Ws4')

try:
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)
except Exception as e:
    print(f"Error al conectar con Google Maps: {e}")
    gmaps = None

def enviar_correo_real(servidor_smtp, puerto, usuario, password, destinatario, asunto, cuerpo):
    """Gestión de conexión SMTP y envío de correo."""
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
    """Busca en Google Maps y genera el CSV para descargar."""
    if not gmaps:
        return jsonify({'error': 'La API de Google Maps no está configurada.'}), 500
    
    data = request.json
    zona = data.get('zona')
    if not zona:
        return jsonify({'error': 'Debes ingresar una zona.'}), 400

    query = f"dieteticas en {zona}"
    
    try:
        places_result = gmaps.places(query=query)
        lista_dieteticas = []
        
        for place in places_result.get('results', []):
            lista_dieteticas.append({
                'nombre': place.get('name'),
                'direccion': place.get('formatted_address'),
                'email': '' # Espacio para completar
            })
        
        if not lista_dieteticas:
            return jsonify({'error': 'No se encontraron resultados.'}), 404

        df = pd.DataFrame(lista_dieteticas)
        # Nombre único con timestamp
        filename = f"dieteticas_{zona.replace(' ', '_')}_{int(time.time())}.csv"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Guardar con codificación para Excel
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
    """Ruta crítica: Permite descargar el archivo del servidor a tu Mac."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/preview_csv', methods=['POST'])
def preview_csv():
    """Procesa el archivo que el usuario sube con los emails ya escritos."""
    if 'file' not in request.files:
        return jsonify({'error': 'No se subió ningún archivo.'}), 400
    
    file = request.files['file']
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(filepath)

    try:
        df = pd.read_csv(filepath) if filepath.endswith('.csv') else pd.read_excel(filepath)
        df.columns = [c.lower().strip() for c in df.columns]
        
        if 'email' not in df.columns:
            return jsonify({'error': 'El archivo debe tener una columna "email".'}), 400

        return jsonify({'success': True, 'filepath': filepath, 'total_rows': len(df)})
    except Exception as e:
        return jsonify({'error': f"Error al leer: {str(e)}"}), 500

@app.route('/start_campaign', methods=['POST'])
def start_campaign():
    """Envío masivo con streaming de logs en tiempo real."""
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

            for index, row in df.iterrows():
                destinatario = row.get('email')
                nombre = row.get('nombre', 'Cliente')
                
                if pd.isna(destinatario) or not str(destinatario).strip():
                    log = f"<div class='text-amber-500'>[{index+1}] Fila saltada: Sin email</div>"
                    yield f"data: {{'progress': {index + 1}, 'log': \"{log}\"}}\n\n"
                    continue

                # Pausa Anti-Spam (Excepto en el primero)
                if index > 0:
                    pausa = random.randint(20, 45)
                    time.sleep(pausa)
                else:
                    pausa = 0

                cuerpo_final = body_template.replace('{nombre}', str(nombre))
                ok, status = enviar_correo_real(smtp_host, smtp_port, email_user, email_pass, destinatario, subject_template, cuerpo_final)
                
                color = "text-green-400" if ok else "text-red-400"
                log_html = f"<div class='mb-1 p-1 border-b border-slate-700 font-mono text-xs'><span class='text-slate-500'>#{index+1}</span> {destinatario}: <span class='{color}'>{status}</span> <span class='text-[10px] text-slate-600'>(Pausa: {pausa}s)</span></div>"
                yield f"data: {{'progress': {index + 1}, 'log': \"{log_html}\"}}\n\n"

            yield f"data: {{'status': 'finished'}}\n\n"

        except Exception as e:
             yield f"data: {{'error': \"{str(e)}\"}}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
