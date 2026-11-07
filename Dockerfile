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
RUN addgroup -g ${PGID} savesync && adduser -D -u ${PUID} -G savesync -h /home/savesync savesync \
 && mkdir -p /config /keys /data /app && chown savesync:savesync /config /keys /data
WORKDIR /app
COPY backend/requirements.txt ./
# bcrypt, pyyaml y pydantic-core publican wheels musllinux (x86_64 y arm64)
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=web /web/dist ./static
# La CLI baja a savesync si se invoca como root (docker exec), para no crear ficheros de root en /data.
RUN printf '#!/bin/sh\nif [ "$(id -u)" = "0" ]; then exec su-exec savesync python -m app.cli "$@"; fi\nexec python -m app.cli "$@"\n' > /usr/local/bin/savesync && chmod +x /usr/local/bin/savesync
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENV HOME=/home/savesync PYTHONUNBUFFERED=1 \
    SAVESYNC_CONFIG=/config/config.yaml SAVESYNC_DATA=/data \
    SAVESYNC_SSH_KEY=/keys/id_ed25519 SAVESYNC_KNOWN_HOSTS=/keys/known_hosts \
    SAVESYNC_STATIC=/app/static
# Sin USER: el entrypoint arranca como root, prepara carpetas y baja a savesync.
EXPOSE 8088
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8088", "--no-server-header"]
