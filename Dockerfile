FROM python:3.12-slim

LABEL maintainer="Hermes Agent"
LABEL description="Dashboard Streamlit de tickets de compra"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY run_pipeline.py .

RUN mkdir -p /app/data/raw_pdfs

VOLUME ["/app/data"]

EXPOSE 8050

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8050/tickets/_stcore/health || exit 1

CMD ["streamlit", "run", "src/dashboard_streamlit.py", \
     "--server.port=8050", "--server.address=0.0.0.0", \
     "--server.enableCORS=false", "--server.enableXsrfProtection=false", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false", \
     "--server.baseUrlPath=tickets"]