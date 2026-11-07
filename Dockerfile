# --- 1) build del frontend (React + SCSS con sass) ---
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2) runtime ---
FROM python:3.12-alpine
RUN apk add --no-cache openssh-client rsync tar bash tzdata su-exec \
 && pip install --no-cache-dir --upgrade pip
ARG PUID=1000
ARG PGID=1000
RUN addgroup -g ${PGID} checkpoint && adduser -D -u ${PUID} -G checkpoint -h /home/checkpoint checkpoint \
 && mkdir -p /config /keys /data /app && chown checkpoint:checkpoint /config /keys /data
WORKDIR /app
COPY backend/requirements.txt ./
# bcrypt, pyyaml y pydantic-core publican wheels musllinux (x86_64 y arm64)
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=web /web/dist ./static
# La CLI baja a checkpoint si se invoca como root (docker exec), para no crear ficheros de root en /data.
RUN printf '#!/bin/sh\nif [ "$(id -u)" = "0" ]; then exec su-exec checkpoint python -m app.cli "$@"; fi\nexec python -m app.cli "$@"\n' > /usr/local/bin/checkpoint && chmod +x /usr/local/bin/checkpoint \
 && ln -s checkpoint /usr/local/bin/savesync   # compat: `docker exec ... savesync` (nombre antiguo)
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENV HOME=/home/checkpoint PYTHONUNBUFFERED=1 \
    CHECKPOINT_CONFIG=/config/config.yaml CHECKPOINT_DATA=/data \
    CHECKPOINT_SSH_KEY=/keys/id_ed25519 CHECKPOINT_KNOWN_HOSTS=/keys/known_hosts \
    CHECKPOINT_STATIC=/app/static
# Sin USER: el entrypoint arranca como root, prepara carpetas y baja a checkpoint.
EXPOSE 8088
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8088", "--no-server-header"]
