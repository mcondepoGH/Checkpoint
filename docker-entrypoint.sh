#!/bin/sh
# Arranca como root solo para preparar carpetas (los bind mounts vacíos los crea Docker como root)
# y baja a savesync con su-exec. Si ya corre sin root (user: en compose), ejecuta directamente.
set -e
if [ "$(id -u)" = "0" ]; then
  for d in /config /keys /data; do
    mkdir -p "$d"
    find "$d" ! -user savesync -exec chown savesync:savesync {} + 2>/dev/null || true
  done
  chmod 700 /keys 2>/dev/null || true
  exec su-exec savesync:savesync "$@"
fi
exec "$@"
