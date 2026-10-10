FROM python:3.14.0-slim-bookworm

# Install Tesseract OCR and common language packs
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-ita \
    tesseract-ocr-fra \
    tesseract-ocr-deu \
    tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first for caching
COPY requirements.txt pyproject.toml README.md ./
RUN pip install --no-cache-dir -r requirements.txt

# Install xTRACT package and copy application resources
COPY src ./src
COPY apps ./apps
COPY assets/branding ./assets/branding
COPY setup.py MANIFEST.in LICENSE ./
RUN pip install --no-cache-dir --no-deps .

COPY config ./config
COPY xtract.py ./

# Non-root service user
RUN useradd --create-home --uid 10001 xtract \
    && mkdir -p /data \
    && chown -R xtract:xtract /data /app

USER xtract

ENV XTRACT_HOST=0.0.0.0 \
    XTRACT_PORT=8000 \
    XTRACT_DATA_DIR=/data \
    XTRACT_PORTAL_DIR=/app/apps/operator-portal \
    PYTHONUNBUFFERED=1

EXPOSE 8000
VOLUME ["/data"]

CMD ["xtract", "serve"]
