# Copiloto oncológico: una sola imagen con TODAS las dependencias (Python, navegador para EV-02 y las pruebas de
# NFR-03). La misma imagen prepara los datos (servicio «preparar») y atiende (servicio «app», N réplicas).
# Uso: docker compose up -d   (ver docs/docker.md)
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Dependencias primero: si solo cambia el código, Docker reutiliza esta capa.
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Sin privilegios de root. Datos y clave viven en volúmenes (docker-compose.yml), no en la imagen.
RUN useradd --create-home --uid 10001 copiloto \
    && mkdir -p /app/data /secretos \
    && chown -R copiloto:copiloto /app/data /secretos /ms-playwright
USER copiloto

# Todo lo que cambia queda en /app/data (volumen compartido por las réplicas); la clave de cifrado, aparte.
ENV COPILOTO_PACIENTES_DB=/app/data/pacientes.db \
    COPILOTO_VECTORIAL_DIR=/app/data/vectorial \
    COPILOTO_SESIONES_DB=/app/data/sesiones.db \
    COPILOTO_CERTS_DIR=/app/data/certs \
    COPILOTO_ARCHIVO_CLAVE=/secretos/clave_cifrado \
    COPILOTO_HOST=0.0.0.0 \
    COPILOTO_PUERTO=8443 \
    COPILOTO_WORKERS=2

VOLUME ["/app/data", "/secretos"]
EXPOSE 8443

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 CMD ["python", "docker/salud.py"]

CMD ["python", "-m", "frontend.real", "--sin-preparar"]
