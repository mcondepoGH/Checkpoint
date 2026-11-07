"""Modelo y validación de config.yaml; escritura atómica."""
import hashlib
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator, model_validator

# Formato antiguo de nombre; sigue siendo válido y su slug es el propio nombre.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
NAME_MAX = 64
NAME_HELP = (f"1 a {NAME_MAX} caracteres: se admiten espacios (sin dobles ni al principio/final), "
             "símbolos, acentos y emojis; no se admiten / \\ ni caracteres de control")
RESERVED_SLUGS = ("hub",)  # el hub se guarda con ese nombre junto a los dispositivos
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:\-]{0,252}$")
USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,31}$")
PROC_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_. \-]{0,63}$")
# Caracteres permitidos en rutas: nada de metacaracteres de shell/cmd.
PATH_CHARS_RE = re.compile(r"^[\w .\-/()\[\]+,@~=#{}]+$")
# "steamos" es un alias heredado de "linux": se sigue aceptando para no romper configs existentes, pero la UI ya no lo ofrece.
OSES = ("windows", "steamos", "linux")
ON_CONFLICT_VALUES = ("skip", "newest")
# Versiones guardadas por juego: 0 = sin límite.
DEFAULT_MAX_VERSIONS = 20
MAX_VERSIONS_LIMIT = 1000
MAX_VERSIONS_MSG = f"debe ser un número entero entre 0 y {MAX_VERSIONS_LIMIT} (0 = sin límite)"


class ConfigError(ValueError):
    pass


def name_error(name) -> Optional[str]:
    """Mensaje de error si `name` no es un nombre visible válido; None si lo es."""
    if not isinstance(name, str):
        return f"nombre inválido: debe ser texto ({NAME_HELP})"
    if not name.strip():
        return "el nombre es obligatorio"
    if name != name.strip() or "  " in name:
        return "nombre inválido: sin espacios al principio ni al final ni dobles"
    if len(name) > NAME_MAX:
        return f"nombre demasiado largo (máx. {NAME_MAX} caracteres)"
    if "/" in name or "\\" in name:
        return "nombre inválido: no se admiten / ni \\"
    for ch in name:
        cat = unicodedata.category(ch)
        if ch == "\u200d":  # unión de emojis compuestos
            continue
        if cat[0] == "C" or cat in ("Zl", "Zp") or (cat == "Zs" and ch != " "):
            return "nombre inválido: sin caracteres de control ni espacios especiales"
    if not name.strip("."):
        return "nombre inválido: no puede ser solo puntos"
    return None


def slug_for(name: str) -> str:
    """Identificador seguro para rutas de disco y ficheros del hub.

    Nombre antiguo válido (letras, números, _ y -) -> el propio nombre (conserva datos existentes).
    Resto -> parte ASCII + hash corto del nombre original (estable, sin colisiones "A B" vs "A-B").
    """
    if NAME_RE.fullmatch(name):
        return name
    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", base)[:40].strip("-_")
    digest = hashlib.sha1(unicodedata.normalize("NFC", name).encode("utf-8")).hexdigest()[:8]
    return f"{base or 'item'}-{digest}"


def normalize_path(os_name: str, p: str) -> str:
    if not isinstance(p, str):
        raise ValueError("ruta debe ser texto")
    p = p.strip()
    if os_name == "windows":
        p = p.replace("\\", "/")
    if os_name == "windows":
        m = re.match(r"^([A-Za-z]):/(.*)$", p)
        if not m:
            raise ValueError("ruta Windows debe ser absoluta tipo C:/Users/...")
        prefix, rest = f"{m.group(1)}:/", m.group(2)
    else:
        if not p.startswith("/"):
            raise ValueError("ruta debe ser absoluta (empieza por /)")
        prefix, rest = "/", p[1:]
    if rest and not PATH_CHARS_RE.match(rest):
        raise ValueError(f"ruta con caracteres no permitidos: {p!r}")
    parts = [s for s in rest.split("/") if s not in ("", ".")]
    if ".." in parts:
        raise ValueError("'..' no permitido en rutas")
    if not parts:
        raise ValueError("ruta demasiado general (raíz)")
    return prefix + "/".join(parts)


class Device(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str
    user: str
    os: str
    port: int = 22

    @field_validator("host")
    @classmethod
    def _host(cls, v):
        if not HOST_RE.match(v):
            raise ValueError("host inválido")
        return v

    @field_validator("user")
    @classmethod
    def _user(cls, v):
        if not USER_RE.match(v):
            raise ValueError("user inválido")
        return v

    @field_validator("os")
    @classmethod
    def _os(cls, v):
        if v not in OSES:
            raise ValueError(f"os debe ser uno de {', '.join(OSES)}")
        return v

    @field_validator("port")
    @classmethod
    def _port(cls, v):
        if not 1 <= v <= 65535:
            raise ValueError("puerto fuera de rango")
        return v


class Game(BaseModel):
    model_config = ConfigDict(extra="forbid")
    devices: List[str]
    paths: Dict[str, str]
    process: Optional[str] = None
    # Override del máximo global `max_versions` para este juego; ausente = usar el global. 0 = sin límite.
    keep_versions: Optional[StrictInt] = None
    # Override por juego de la política de la sync automática ante conflictos; ausente = ajuste global.
    on_conflict: Optional[str] = None

    @field_validator("on_conflict")
    @classmethod
    def _onc(cls, v):
        if v is not None and v not in ON_CONFLICT_VALUES:
            raise ValueError("on_conflict debe ser 'skip' o 'newest'")
        return v

    @field_validator("process")
    @classmethod
    def _proc(cls, v):
        if v in (None, ""):
            return None
        if not PROC_RE.match(v):
            raise ValueError("process inválido")
        return v

    @field_validator("keep_versions")
    @classmethod
    def _keep(cls, v):
        if v is not None and not 0 <= v <= MAX_VERSIONS_LIMIT:
            raise ValueError(f"keep_versions {MAX_VERSIONS_MSG}")
        return v


def semantic_errors(devices, games) -> List[Tuple[str, str]]:
    """Reglas cruzadas sobre datos crudos (dicts). Devuelve [(ruta_de_campo, mensaje)].

    Trabaja sobre datos sin validar a propósito: así el validador en vivo informa de
    estos errores aunque otro campo ya falle en el esquema.
    """
    errs: List[Tuple[str, str]] = []
    devices = devices if isinstance(devices, dict) else {}
    games = games if isinstance(games, dict) else {}
    def check_names(names, prefix, reserved=()):
        seen_n, seen_s = {}, {}
        for n in names:
            e = name_error(n)
            if e:
                errs.append((f"{prefix}.{n}", e))
                continue
            sl = slug_for(n)
            if sl.casefold() in reserved:
                errs.append((f"{prefix}.{n}", "nombre reservado"))
                continue
            key = n.casefold()
            other = seen_n.get(key) or seen_s.get(sl.casefold())
            if other:
                errs.append((f"{prefix}.{n}", f"nombre repetido o demasiado parecido a {other!r}"))
                continue
            seen_n[key] = n
            seen_s[sl.casefold()] = n

    check_names(devices, "devices", RESERVED_SLUGS)
    check_names(games, "games")
    for gname, g in games.items():
        gp = f"games.{gname}"
        if not isinstance(g, dict):
            continue
        devs = g.get("devices")
        paths = g.get("paths")
        if not isinstance(devs, list) or len(devs) != 2:
            errs.append((f"{gp}.devices", "elige exactamente dos dispositivos"))
            continue
        ok_devs = []
        for i, d in enumerate(devs):
            if not d:
                errs.append((f"{gp}.devices.{i}", "elige un dispositivo"))
            elif d not in devices:
                errs.append((f"{gp}.devices.{i}", f"dispositivo desconocido: {d!r}"))
            else:
                ok_devs.append(d)
        if devs[0] and devs[0] == devs[1]:
            errs.append((f"{gp}.devices.1", "debe ser distinto del dispositivo 1"))
        if not isinstance(paths, dict):
            if paths is not None:
                errs.append((f"{gp}.paths", "paths debe ser un mapa dispositivo -> ruta"))
            paths = {}
        for k in paths:
            if k not in devs:
                errs.append((f"{gp}.paths.{k}", "sobra: este dispositivo no es del juego"))
        for d in ok_devs:
            if d not in paths or paths[d] in (None, ""):
                errs.append((f"{gp}.paths.{d}", "falta la ruta del save"))
                continue
            dev = devices[d]
            os_name = dev.get("os") if isinstance(dev, dict) else None
            if os_name not in OSES:
                continue  # el error ya sale en devices.<d>.os
            try:
                normalize_path(os_name, paths[d])
            except ValueError as e:
                errs.append((f"{gp}.paths.{d}", str(e)))
    return errs


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_versions: StrictInt = DEFAULT_MAX_VERSIONS  # máximo de versiones por juego (global)
    devices: Dict[str, Device] = {}
    games: Dict[str, Game] = {}

    @field_validator("max_versions")
    @classmethod
    def _maxv(cls, v):
        if not 0 <= v <= MAX_VERSIONS_LIMIT:
            raise ValueError(f"max_versions {MAX_VERSIONS_MSG}")
        return v

    def versions_limit(self, game: str) -> int:
        """Límite efectivo de versiones del juego: su override o el global. 0 = sin límite."""
        k = self.games[game].keep_versions
        return self.max_versions if k is None else k

    @model_validator(mode="after")
    def _cross(self):
        errs = semantic_errors({k: v.model_dump() for k, v in self.devices.items()},
                               {k: v.model_dump() for k, v in self.games.items()})
        if errs:
            raise ValueError("; ".join(f"{p}: {m}" for p, m in errs))
        for g in self.games.values():
            for d in g.devices:
                g.paths[d] = normalize_path(self.devices[d].os, g.paths[d])
        return self


def parse_config(data) -> Config:
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError("config debe ser un mapa YAML")
    return Config.model_validate(data)


_PYD_MSG = {
    "missing": "campo obligatorio",
    "int_parsing": "debe ser un número entero",
    "int_type": "debe ser un número entero",
    "int_from_float": "debe ser un número entero",
    "string_type": "debe ser texto",
    "extra_forbidden": "campo no permitido",
    "dict_type": "debe ser un mapa",
    "list_type": "debe ser una lista",
}


def validate_config(data) -> Tuple[Optional[Config], Dict[str, str]]:
    """Valida con las mismas reglas que la carga. Devuelve (config|None, {ruta_de_campo: mensaje})."""
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, {"": "config debe ser un mapa YAML"}
    errors: Dict[str, str] = {}
    cfg = None
    try:
        cfg = Config.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            if err["loc"]:
                path = ".".join(str(x) for x in err["loc"])
                msg = _PYD_MSG.get(err["type"]) or err["msg"].removeprefix("Value error, ")
                errors.setdefault(path, msg)
        # reglas cruzadas aunque el esquema falle en otro campo
        for path, msg in semantic_errors(data.get("devices"), data.get("games")):
            errors.setdefault(path, msg)
        if not errors:
            errors[""] = "; ".join(x["msg"] for x in e.errors())
    return (cfg if not errors else None), errors


def load_config(path: Path) -> Config:
    path = Path(path)
    if not path.exists():
        return Config()
    return parse_config(yaml.safe_load(path.read_text(encoding="utf-8")))


def atomic_write(path: Path, text: str, mode: Optional[int] = None) -> None:
    """Escritura atómica: temporal en el mismo directorio + fsync + rename. Conserva el modo del fichero previo."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        try:
            mode = path.stat().st_mode & 0o777
        except FileNotFoundError:
            mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save_config(path: Path, cfg: Config) -> None:
    text = yaml.safe_dump(cfg.model_dump(exclude_none=True), sort_keys=False, allow_unicode=True)
    atomic_write(path, text)
