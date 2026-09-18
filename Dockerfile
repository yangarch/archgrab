# --- 프론트 빌드 ---
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 런타임 ---
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# ffmpeg 은 유튜브 DASH 무손실 mux 에만 쓴다 (재인코딩 없음)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/pyproject.toml ./backend/
RUN pip install --no-cache-dir -e ./backend

COPY backend/ ./backend/
COPY --from=frontend /build/dist ./backend/static

RUN useradd -m -u 10001 archgrab && mkdir -p /data /secrets && chown -R archgrab /data /secrets /app
USER archgrab

ENV ARCHGRAB_DATA_DIR=/data \
    ARCHGRAB_SECRETS_DIR=/secrets \
    ARCHGRAB_DB_PATH=/data/archgrab.db \
    ARCHGRAB_STATIC_DIR=/app/backend/static

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
