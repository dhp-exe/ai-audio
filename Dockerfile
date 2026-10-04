# Emvoox Studio in one image: the engine (FastAPI + agents + FFmpeg + headless Chromium) serving the built web client.
#   docker compose up --build        -> http://localhost:8765
# Keys come from .env (see .env.example); everything the engine writes lives in ./data on the host.

# ---- stage 1: build the web client (static export served by the engine) ----
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run export

# ---- stage 2: the engine ----
FROM python:3.12-slim AS engine
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/home/emvoox

# FFmpeg renders stems, masters and the QA measurements.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Dependencies first, against a stub package, so editing the engine does not reinstall them or re-download Chromium.
COPY pyproject.toml README.md ./
RUN mkdir emvoox && touch emvoox/__init__.py \
    && pip install -e ".[research,claude]" \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY emvoox/ ./emvoox/
COPY scripts/ ./scripts/
COPY --from=web /web/out ./web/out

# Run as a normal user so files written to the mounted ./data are not owned by root on Linux hosts.
RUN useradd --create-home --uid 1000 emvoox && mkdir -p /app/data && chown -R emvoox:emvoox /app/data /home/emvoox
USER emvoox

ENV EMVOOX_DATA_DIR=/app/data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/config', timeout=4)" || exit 1
CMD ["python", "-m", "emvoox", "serve", "--host", "0.0.0.0", "--port", "8765"]
