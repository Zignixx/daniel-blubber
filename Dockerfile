# Blubberzähler 🫧 – Streamlit-App im Container
FROM python:3.12-slim

# Sinnvolle Defaults für Python + Streamlit im Container
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# Abhängigkeiten zuerst -> bessere Layer-Caches bei Code-Änderungen
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Anwendungscode
COPY blubber_core.py blubberzaehler.py ./

# Als Nicht-Root laufen
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8501

# Streamlit-eigener Health-Endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4).status==200 else 1)"

CMD ["streamlit", "run", "blubberzaehler.py"]
