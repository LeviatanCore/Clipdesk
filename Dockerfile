FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8765 \
    DOWNLOAD_DIR=/downloads \
    DOCKER=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates unzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/.tools \
    && curl -fsSL -o /tmp/deno.zip \
      https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip \
    && python -m zipfile -e /tmp/deno.zip /app/.tools \
    && chmod +x /app/.tools/deno \
    && rm -f /tmp/deno.zip

COPY app.py download.py ./
COPY templates ./templates
COPY static ./static

RUN mkdir -p /downloads \
    && useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app /downloads

USER appuser

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/meta', timeout=3)"

CMD ["python", "app.py"]
