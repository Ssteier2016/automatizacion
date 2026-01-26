import streamlit as st
import pandas as pd
import time
import random

# Configuración de la página
st.set_page_config(page_title="YerbaMate Promoter", layout="wide")

st.title("🌱 Automatización de Ventas B2B - Yerba Mate")

# --- BARRA LATERAL (Configuración) ---
st.sidebar.header("Configuración de Envío")
email_user = st.sidebar.text_input("Tu Email (Gmail/Outlook)")
email_pass = st.sidebar.text_input("Contraseña de Aplicación", type="password")
st.sidebar.info("Nota: Usa 'Contraseñas de aplicación' de Google, no tu clave normal.")

# --- SECCIÓN 1: BASE DE DATOS ---
st.header("1. Cargar Base de Datos de Dietéticas")

# Opción A: Subir Excel
uploaded_file = st.file_uploader("Sube tu archivo Excel/CSV con columnas: 'Nombre', 'Email'", type=['csv', 'xlsx'])

if uploaded_file:
    # Lógica para leer el archivo
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
    
    st.write("Vista previa de dietéticas cargadas:")
    st.dataframe(df.head())
    
    # Validación simple
    if 'Email' not in df.columns or 'Nombre' not in df.columns:
        st.error("El archivo debe tener las columnas 'Nombre' y 'Email'.")
    else:
        st.success(f"¡Cargado! Se encontraron {len(df)} dietéticas potenciales.")

# --- SECCIÓN 2: REDACCIÓN DEL CORREO ---
st.divider()
st.header("2. Configurar Campaña")

subject = st.text_input("Asunto del Correo", "Propuesta comercial: Yerba Mate Premium para su dietética")
body_template = st.text_area("Cuerpo del mensaje (Usa {nombre} para personalizar)", 
"""Hola {nombre},

Espero que estén muy bien. Vi su dietética y me encantaría presentarles nuestra nueva marca de Yerba Mate...

Quedo a la espera de sus comentarios.
Saludos.""", height=200)

# --- SECCIÓN 3: MOTOR DE ENVÍO ---
st.divider()
st.header("3. Lanzar Automatización")

if st.button("🚀 Iniciar Envío a Dietéticas"):
    if not uploaded_file or not email_user or not email_pass:
        st.warning("Por favor completa la configuración del email y carga una base de datos.")
    else:
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Simulación de envío (Aquí iría el código smtplib real)
        for index, row in df.iterrows():
            dietetica_nombre = row['Nombre']
            dietetica_email = row['Email']
            
            # Personalización del mensaje
            mensaje_final = body_template.replace("{nombre}", str(dietetica_nombre))
            
            status_text.text(f"Enviando a: {dietetica_nombre} ({dietetica_email})...")
            
            # Aquí iría la función de envío real (SMTP)
            # send_email(dietetica_email, subject, mensaje_final)
            
            # TIEMPO DE ESPERA (Crucial para no ser SPAM)
            time.sleep(random.randint(2, 5)) 
            
            # Actualizar barra
            progress_bar.progress((index + 1) / len(df))
            
        st.success("✅ ¡Campaña finalizada con éxito!")
