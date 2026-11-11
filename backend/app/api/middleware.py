"""Middleware ASGI de la API."""
import logging
import time


class RequestDebugLog:
    """Middleware ASGI: a nivel DEBUG, una línea por petición /api (método, ruta, nombres de los parámetros de la
    query, estado, duración e IP del socket). Nunca mira cabeceras, cookies, cuerpo ni valores de la query, así que
    no puede filtrar la API key, la sesión ni contraseñas. Con otro nivel no hace nada."""

    def __init__(self, app, logger):
        self.app, self.log = app, logger

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/") or not self.log.isEnabledFor(logging.DEBUG):
            return await self.app(scope, receive, send)
        t0, status = time.monotonic(), [0]

        async def _send(message):
            if message["type"] == "http.response.start":
                status[0] = message["status"]
            await send(message)

        qs = scope.get("query_string", b"").decode("latin-1")
        params = ",".join(sorted({kv.split("=", 1)[0] for kv in qs.split("&") if kv}))
        ip = scope["client"][0] if scope.get("client") else "?"
        try:
            await self.app(scope, receive, _send)
        except Exception as e:
            self.log.debug("%s %s query=[%s] ip=%s excepción %s tras %.0f ms", scope["method"], scope["path"], params,
                           ip, type(e).__name__, (time.monotonic() - t0) * 1000)
            raise
        self.log.debug("%s %s query=[%s] ip=%s -> %s en %.0f ms", scope["method"], scope["path"], params, ip,
                       status[0], (time.monotonic() - t0) * 1000)
