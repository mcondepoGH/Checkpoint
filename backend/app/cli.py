"""CLI: checkpoint sync <juego> [--dry-run] [--resolve newest|hub|device:<nombre>] | list | versions <juego>"""
import argparse
import sys
from datetime import datetime

from . import settings
from .config import load_config
from .sync import SyncAbort, list_versions, run_sync, valid_resolution


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="checkpoint")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("game")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--resolve", metavar="newest|hub|device:<nombre>",
                   help="resuelve un conflicto: gana el más reciente, el hub o el save de un dispositivo")
    sub.add_parser("list")
    v = sub.add_parser("versions")
    v.add_argument("game")
    a = ap.parse_args(argv)

    try:
        cfg = load_config(settings.CONFIG_PATH)
    except ValueError as e:  # incluye ValidationError de pydantic
        print(f"config inválida: {e}", file=sys.stderr)
        return 1
    if a.cmd == "list":
        for n, g in cfg.games.items():
            print(f"{n}: {g.devices[0]} <-> {g.devices[1]}")
        return 0
    if a.cmd == "versions":
        for v_ in list_versions(settings.DATA_DIR, a.game):
            print(v_["version"], ", ".join(f"{x['source']}({x['files']})" for x in v_["sources"]))
        return 0
    if a.resolve is not None and not valid_resolution(a.resolve):
        print("--resolve debe ser newest, hub o device:<nombre>", file=sys.stderr)
        return 2
    try:
        st = run_sync(cfg, a.game, a.dry_run, resolution=a.resolve)
    except SyncAbort as e:
        print(f"ABORTADO: {e}", file=sys.stderr)
        return 2
    if st["result"] == "conflict":
        print(f"CONFLICTO en {a.game}: {st['message']}", file=sys.stderr)
        for s_ in st.get("conflict", {}).get("sides", []):
            when = datetime.fromtimestamp(s_["mtime"]).strftime("%Y-%m-%d %H:%M:%S") if s_["mtime"] else "-"
            print(f"  {s_['name']}: {when}, {s_['size']} bytes, {s_['files']} ficheros", file=sys.stderr)
        print("Nada se ha modificado. Resuélvelo con: checkpoint sync <juego> --resolve "
              "newest|hub|device:<nombre>", file=sys.stderr)
        return 3
    return 0 if st["result"] in ("ok", "dry-run") else 1


if __name__ == "__main__":
    sys.exit(main())
