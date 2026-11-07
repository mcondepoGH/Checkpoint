"""CLI: checkpoint sync <juego> [--dry-run] [--resolve newest|hub|device:<dispositivo>] | list | versions <juego>
     | serve [--host H] [--port P]   (arranque sin Docker; en Docker lo hace uvicorn directamente)

<juego> y <dispositivo> aceptan el id interno o el nombre."""
import argparse
import sys
from datetime import datetime

from . import runtime, settings
from .config import load_config
from .sync import SyncAbort, list_versions, resolve_game, run_sync, valid_resolution


def serve(host=None, port=None) -> int:
    """Arranca la app con uvicorn. Exige CHECKPOINT_USER y CHECKPOINT_PASSWORD (como en Docker)."""
    if not settings.env("USER") or not settings.env("PASSWORD"):
        print("faltan CHECKPOINT_USER y CHECKPOINT_PASSWORD (variables de entorno)", file=sys.stderr)
        return 2
    host = host or settings.env("HOST", "127.0.0.1")
    port = port if port is not None else int(settings.env("PORT", "8088"))
    if not 1 <= port <= 65535:
        print("puerto fuera de rango", file=sys.stderr)
        return 2
    import uvicorn
    print(f"Checkpoint ({runtime.runtime_name()}, {runtime.platform_name()}) en http://{host}:{port}\n"
          f"  config: {settings.CONFIG_PATH}\n  datos:  {settings.DATA_DIR}\n  web:    {settings.STATIC_DIR}",
          file=sys.stderr)
    uvicorn.run("app.main:app_factory", factory=True, host=host, port=port, server_header=False)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="checkpoint")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("game")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--resolve", metavar="newest|hub|device:<dispositivo>",
                   help="resuelve un conflicto: gana el más reciente, el hub o el save de un dispositivo")
    sv = sub.add_parser("serve", help="arranca la web (modo nativo, sin Docker)")
    sv.add_argument("--host", default=None, help="por defecto CHECKPOINT_HOST o 127.0.0.1")
    sv.add_argument("--port", type=int, default=None, help="por defecto CHECKPOINT_PORT o 8088")
    sub.add_parser("list")
    v = sub.add_parser("versions")
    v.add_argument("game")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        return serve(a.host, a.port)
    try:
        cfg = load_config(settings.CONFIG_PATH)
    except ValueError as e:  # incluye ValidationError de pydantic
        print(f"config inválida: {e}", file=sys.stderr)
        return 1
    if a.cmd == "list":
        for g in cfg.games.values():
            print(f"{g.name}: {cfg.devices[g.devices[0]].name} <-> {cfg.devices[g.devices[1]].name}")
        return 0
    try:
        gid = resolve_game(cfg, a.game)
    except SyncAbort as e:
        print(f"ABORTADO: {e}", file=sys.stderr)
        return 2
    if a.cmd == "versions":
        names = {k: d.name for k, d in cfg.devices.items()}
        for v_ in list_versions(settings.DATA_DIR, gid, names):
            print(v_["version"], ", ".join(f"{x['name']}({x['files']})" for x in v_["sources"]))
        return 0
    if a.resolve is not None and not valid_resolution(a.resolve):
        print("--resolve debe ser newest, hub o device:<dispositivo>", file=sys.stderr)
        return 2
    try:
        st = run_sync(cfg, gid, a.dry_run, resolution=a.resolve)
    except SyncAbort as e:
        print(f"ABORTADO: {e}", file=sys.stderr)
        return 2
    if st["result"] == "conflict":
        print(f"CONFLICTO en {cfg.games[gid].name}: {st['message']}", file=sys.stderr)
        for s_ in st.get("conflict", {}).get("sides", []):
            when = datetime.fromtimestamp(s_["mtime"]).strftime("%Y-%m-%d %H:%M:%S") if s_["mtime"] else "-"
            print(f"  {s_['name']}: {when}, {s_['size']} bytes, {s_['files']} ficheros", file=sys.stderr)
        print("Nada se ha modificado. Resuélvelo con: checkpoint sync <juego> --resolve "
              "newest|hub|device:<dispositivo>", file=sys.stderr)
        return 3
    return 0 if st["result"] in ("ok", "dry-run") else 1


if __name__ == "__main__":
    sys.exit(main())
