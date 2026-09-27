# --- 프론트 빌드 ---
# 리포와 같은 층위를 만든다. vite 의 outDir 이 '../backend/static' 이라
# WORKDIR 이 /build 면 산출물이 /backend/static 으로 튀어나간다.
FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
# → /build/backend/static

# --- 런타임 ---
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# ffmpeg: DASH 무손실 mux 전용 (재인코딩 없음)
# gosu:   볼륨 소유권을 맞춘 뒤 권한을 내려놓기 위해
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl gosu \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# 소스를 먼저 넣고 설치한다. 패키지 디렉터리가 없는 상태의 editable 설치는
# 빈 설치가 될 수 있다.
COPY backend/ ./backend/
RUN pip install --no-cache-dir -e ./backend
COPY --from=frontend /build/backend/static ./backend/static
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN useradd -m -u 10001 archgrab \
 && mkdir -p /data /secrets \
 && chown -R archgrab /data /secrets /app \
 && chmod +x /usr/local/bin/entrypoint.sh

ENV ARCHGRAB_DATA_DIR=/data \
    ARCHGRAB_SECRETS_DIR=/secrets \
    ARCHGRAB_DB_PATH=/data/archgrab.db \
    ARCHGRAB_STATIC_DIR=/app/backend/static

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# root 로 시작해 볼륨 소유권을 맞춘 뒤 archgrab 으로 내려간다 (entrypoint 참고)
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
