import os
import pandas as pd
import smtplib
import time
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, jsonify, Response, stream_with_context

app = Flask(__name__)

# Configuración básica (Idealmente esto iría en variables de entorno en producción)
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def enviar_correo_real(servidor_smtp, puerto, usuario, password, destinatario, asunto, cuerpo):
    """
    Función auxiliar para conectar con el servidor SMTP y enviar el correo.
    """
    msg = MIMEMultipart()
    msg['From'] = usuario
    msg['To'] = destinatario
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo, 'plain'))

    try:
        # Detectar si es Gmail o Outlook/Otros para seguridad
        server = smtplib.SMTP(servidor_smtp, puerto)
        server.starttls() # Seguridad TLS
        server.login(usuario, password)
        server.sendmail(usuario, destinatario, msg.as_string())
        server.quit()
        return True, "Enviado correctamente"
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/preview_csv', methods=['POST'])
def preview_csv():
    """Lee el archivo subido y devuelve las primeras filas para confirmar que está bien."""
    if 'file' not in request.files:
        return jsonify({'error': 'No se subió ningún archivo'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nombre de archivo vacío'}), 400

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(filepath)

    try:
        # Detectar formato
        if filepath.endswith('.csv'):
            df = pd.read_csv(filepath)
        elif filepath.endswith('.xlsx'):
            df = pd.read_excel(filepath)
        else:
            return jsonify({'error': 'Formato no soportado. Usa CSV o Excel.'}), 400

        # Normalizar nombres de columnas a minúsculas para evitar errores
        df.columns = [c.lower().strip() for c in df.columns]
        
        # Validar columnas requeridas
        if 'email' not in df.columns:
            return jsonify({'error': 'No se encontró la columna "email" en el archivo.'}), 400

        # Guardar ruta en sesión o devolverla para usarla en el envío
        return jsonify({
            'success': True, 
            'columns': list(df.columns),
            'preview': df.head(5).to_dict(orient='records'),
            'filepath': filepath,
            'total_rows': len(df)
        })

    except Exception as e:
        return jsonify({'error': f'Error al leer archivo: {str(e)}'}), 500

@app.route('/start_campaign', methods=['POST'])
def start_campaign():
    """
    Endpoint de Streaming. 
    Mantiene la conexión abierta y envía actualizaciones línea por línea al navegador.
    """
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
            if filepath.endswith('.csv'):
                df = pd.read_csv(filepath)
            else:
                df = pd.read_excel(filepath)
            
            df.columns = [c.lower().strip() for c in df.columns]
            total = len(df)

            yield f"data: {{'status': 'start', 'total': {total}}}\n\n"

            success_count = 0
            fail_count = 0

            for index, row in df.iterrows():
                destinatario = row.get('email')
                nombre = row.get('nombre', 'Cliente') # Fallback si no hay nombre
                
                if pd.isna(destinatario):
                    continue

                # Personalización básica
                try:
                    cuerpo_final = body_template.replace('{nombre}', str(nombre))
                    # Aquí podrías agregar más reemplazos, ej: {empresa}
                except:
                    cuerpo_final = body_template

                # Simulación de envío (COMENTA ESTO Y DESCOMENTA LO DE ABAJO PARA PRODUCCIÓN)
                # En producción, usa la función enviar_correo_real
                time.sleep(1) # Simula retraso de red
                sent_ok = True 
                msg_status = "Simulación OK"

                # --- MODO PRODUCCIÓN (Descomentar para usar) ---
                # sent_ok, msg_status = enviar_correo_real(smtp_host, smtp_port, email_user, email_pass, destinatario, subject_template, cuerpo_final)
                # time.sleep(random.randint(5, 15)) # Anti-spam delay importante
                
                if sent_ok:
                    success_count += 1
                    status_color = "text-green-600"
                else:
                    fail_count += 1
                    status_color = "text-red-600"
                    msg_status = f"Error: {msg_status}"

                # Enviar log al frontend
                log_html = f"<div class='mb-2 p-2 border-b border-gray-100 text-sm'><span class='font-bold'>{index + 1}/{total}</span> - {destinatario}: <span class='{status_color}'>{msg_status}</span></div>"
                
                # Formato SSE (Server Sent Events) simple
                yield f"data: {{'progress': {index + 1}, 'log': \"{log_html}\"}}\n\n"

            yield f"data: {{'status': 'finished', 'success': {success_count}, 'fail': {fail_count}}}\n\n"

        except Exception as e:
             yield f"data: {{'error': \"{str(e)}\"}}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
