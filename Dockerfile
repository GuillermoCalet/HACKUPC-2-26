FROM python:3.11-slim

# Evitar que Python faci fitxers temporals inútils
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Amagar el text demanant l'email a Streamlit
ENV STREAMLIT_SERVER_HEADLESS=true

WORKDIR /app

# Instal·lar dependències
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar tot el codi al contenidor
COPY . .

# Exposem només el port de Streamlit per parlar amb el públic
EXPOSE 8501

# Podem reutilitzar gairebé intacte el start.sh si el fem per a Docker
# Creem un script d'arrencada inline:
RUN echo '#!/bin/bash\n\
uvicorn agents.performance:app --port 8001 &\n\
uvicorn agents.fatigue:app --port 8002 &\n\
uvicorn agents.risk:app --port 8003 &\n\
uvicorn agents.visual:app --port 8004 &\n\
uvicorn agents.audience:app --port 8005 &\n\
uvicorn orchestrator.server:app --port 8000 &\n\
sleep 5\n\
streamlit run frontend/app.py\n' > run_docker.sh

RUN chmod +x run_docker.sh

CMD ["./run_docker.sh"]
