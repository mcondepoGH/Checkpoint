"""Error controlado de la sincronización."""

from ..core.errors import describe_code, error_body


class SyncAbort(Exception):
    """Fin controlado sin tocar nada (o error ya reportado). Contrato i18n: `code` (`err.sync.<causa>`) +
    `params`; sin texto en español (la UI traduce). `str(e)` es técnico, para logs y CLI."""

    def __init__(self, code: str, **params):
        super().__init__(describe_code(code, params))
        self.code, self.params = code, params

    def body(self) -> dict:
        return error_body(self.code, **self.params)
