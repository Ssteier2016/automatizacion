# Usar imagen oficial de Python
FROM python:3.11-slim

# Establecer directorio de trabajo
WORKDIR /app

# Copiar archivos de dependencias primero (para aprovechar caché de Docker)
COPY requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# Puerto que usará Cloud Run
EXPOSE 8080

# Variable de entorno para Flask
ENV FLASK_APP=app.py

# Comando para ejecutar la aplicación con Gunicorn (servidor de producción)
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 app:app
