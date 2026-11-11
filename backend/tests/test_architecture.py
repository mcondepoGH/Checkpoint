"""Reglas de dependencia entre capas del backend, comprobadas con `ast` (sin importar los módulos).

- `core` no importa de ninguna otra capa.
- `sync`, `config` y `users` no importan de `api` ni de `services`.
- `services` no importa de `api`.
- `api` puede importar de `config`, `users`, `sync`, `core` y `services`.
"""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
LAYERS = {"api", "services", "sync", "config", "users", "core"}

FORBIDDEN = {
    "core": LAYERS - {"core"},
    "sync": {"api", "services"},
    "config": {"api", "services"},
    "users": {"api", "services"},
    "services": {"api"},
}

# Excepciones explícitas (módulo importador, capa o módulo importado). Cada una debe tener motivo.
ALLOWED = {
    # El planificador registra en el historial de cada usuario el resultado de sus ejecuciones.
    ("sync.scheduler", "users.history"),
}


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(APP).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path):
    """Módulos importados (relativos a `app`, p. ej. 'users.history') por un fichero."""
    return _imports_of(path.read_text(), _module_name(path), path.name == "__init__.py")


def _imports_of(source: str, mod: str, is_package: bool = False):
    pkg = mod.split(".") if is_package else mod.split(".")[:-1]
    out = set()
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Import):
            out |= {a.name[len("app.") :] for a in n.names if a.name.startswith("app.")}
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                base = pkg[: len(pkg) - (n.level - 1)]
                prefix = base + (n.module.split(".") if n.module else [])
            elif n.module and (n.module == "app" or n.module.startswith("app.")):
                prefix = n.module.split(".")[1:]
            else:
                continue
            if prefix:
                out.add(".".join(prefix))
            # `from <pkg> import x`: x puede ser un submódulo; se anota también
            out |= {".".join(prefix + [a.name]) for a in n.names if a.name != "*"}
    return out


def _violations():
    found = []
    for layer, banned in FORBIDDEN.items():
        for path in sorted((APP / layer).rglob("*.py")):
            mod = _module_name(path)
            for imp in sorted(_imports(path)):
                target = imp.split(".")[0]
                if target in banned and (mod, imp) not in ALLOWED and (mod, target) not in ALLOWED:
                    found.append(f"{mod} importa {imp}")
    return found


def test_layers_do_not_import_upwards():
    assert _violations() == []


def test_documented_exception_still_needed():
    """Si la excepción deja de usarse, hay que borrarla de ALLOWED."""
    for mod, imp in ALLOWED:
        path = APP / (mod.replace(".", "/") + ".py")
        assert imp in _imports(path), f"{mod} ya no importa {imp}: quita la excepción"


def test_import_parser_resolves_relative_imports():
    src = (
        "from ..api import auth\nfrom . import x\nfrom ..services.runs import y\nimport app.users.history\nimport os\n"
    )
    assert _imports_of(src, "core.mod") == {
        "api",
        "api.auth",
        "core",
        "core.x",
        "services.runs",
        "services.runs.y",
        "users.history",
    }


def test_checker_flags_a_forbidden_import():
    assert {i.split(".")[0] for i in _imports_of("from ..api import auth", "core.mod")} & FORBIDDEN["core"]
