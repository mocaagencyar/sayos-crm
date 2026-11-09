FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias primero (capa cacheada)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código del agente
COPY . .

# Puerto de la aplicación
EXPOSE 8000

# Arrancar el agente Max
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
