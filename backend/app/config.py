"""Modelo y validación de config.yaml; escritura atómica."""
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from .runtime import running_in_docker
from pydantic import (BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError, field_validator, model_serializer,
                      model_validator)

NAME_MAX = 64
NAME_HELP = (f"1 a {NAME_MAX} caracteres: se admiten espacios (sin dobles ni al principio/final), "
             "símbolos, acentos y emojis; no se admiten / \\ ni caracteres de control")
RESERVED_SLUGS = ("hub",)  # el hub se guarda con ese nombre junto a los dispositivos
# Identificador interno (clave en config.yaml): estable e inmutable; nunca se deriva del nombre tras crearlo.
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:\-]{0,252}$")
USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,31}$")
PROC_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_. \-]{0,63}$")
# Caracteres permitidos en rutas: nada de metacaracteres de shell/cmd.
PATH_CHARS_RE = re.compile(r"^[\w .\-/()\[\]+,@~=#{}]+$")
OSES = ("windows", "linux")
ON_CONFLICT = ("skip", "newest")  # política ante conflictos de la sync automática
# Versiones guardadas por juego: 0 = sin límite.
DEFAULT_MAX_VERSIONS = 20
MAX_VERSIONS_LIMIT = 1000
MAX_VERSIONS_MSG = f"debe ser un número entero entre 0 y {MAX_VERSIONS_LIMIT} (0 = sin límite)"


class ConfigError(ValueError):
    pass


MISSING_NAME_MSG = "falta el campo name (obligatorio): el nombre visible del elemento"


def name_error(name) -> Optional[str]:
    """Mensaje de error si `name` no es un nombre visible válido; None si lo es."""
    if name is None:
        return MISSING_NAME_MSG
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


def resolve_ref(items, ref):
    """Id del elemento de `items` ({id: objeto con .name}) al que apunta `ref` (id o nombre).

    None si no existe. Lanza ConfigError si `ref` es ambiguo (coincide con varios elementos)."""
    if not isinstance(ref, str) or not ref:
        return None
    hits = [i for i, it in items.items() if i == ref or getattr(it, "name", None) == ref]
    if not hits:
        low = ref.casefold()
        hits = [i for i, it in items.items() if str(getattr(it, "name", "")).casefold() == low]
    if len(hits) > 1:
        raise ConfigError(f"{ref!r} es ambiguo: coincide con " + ", ".join(
            f"{getattr(items[i], 'name', i)!r} (id {i})" for i in hits) + "; usa el id")
    return hits[0] if hits else None


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


LOCAL_DOCKER_MSG = "“Este equipo” solo está disponible cuando Checkpoint se ejecuta sin Docker"
LOCAL_ONE_MSG = "solo puede haber un dispositivo “Este equipo”"
LOCAL_NO_REMOTE_MSG = "no aplica a “Este equipo” (se accede directamente al sistema de ficheros local)"


class Device(BaseModel):
    """Dispositivo remoto (SSH: host, user, port) o `local: true` = el equipo donde corre Checkpoint
    (sin SSH; solo fuera de Docker). Un dispositivo local no lleva host/user/port."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(None, validate_default=True)  # obligatorio: etiqueta visible y editable; la clave del mapa es el id
    local: StrictBool = False
    host: Optional[str] = Field(None, validate_default=True)
    user: Optional[str] = Field(None, validate_default=True)
    os: str
    port: Optional[int] = Field(None, validate_default=True)

    @field_validator("name", mode="before")
    @classmethod
    def _name_required(cls, v):
        if v is None:
            raise ValueError(MISSING_NAME_MSG)
        return v

    @field_validator("host", "user", "port", mode="before")
    @classmethod
    def _remote_only(cls, v, info):
        if info.data.get("local") is True:
            if v not in (None, ""):
                raise ValueError(LOCAL_NO_REMOTE_MSG)
            return None
        if info.field_name == "port" and v is None:
            return 22
        if v is None:
            raise ValueError("campo obligatorio")
        return v

    @field_validator("host", "user", "port", mode="after")
    @classmethod
    def _check_remote(cls, v, info):
        if v is None:
            return v
        if info.field_name == "host" and not HOST_RE.match(v):
            raise ValueError("host inválido")
        if info.field_name == "user" and not USER_RE.match(v):
            raise ValueError("user inválido")
        if info.field_name == "port" and not 1 <= v <= 65535:
            raise ValueError("puerto fuera de rango")
        return v

    @field_validator("os")
    @classmethod
    def _os(cls, v):
        if v not in OSES:
            raise ValueError(f"os debe ser uno de {', '.join(OSES)}")
        return v

    @model_serializer(mode="wrap")
    def _ser(self, handler):
        d = handler(self)
        if self.local:  # sin host/user/port
            for k in ("host", "user", "port"):
                d.pop(k, None)
        else:  # los remotos no escriben `local: false`
            d.pop("local", None)
        return d


class Game(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(None, validate_default=True)  # obligatorio: etiqueta visible y editable; la clave es el id
    devices: List[str]  # ids de dispositivo
    paths: Dict[str, str]  # id de dispositivo -> ruta
    process: Optional[str] = None
    # Override del máximo global `max_versions` para este juego; ausente = usar el global. 0 = sin límite.
    keep_versions: Optional[StrictInt] = None
    # Override por juego de la política de la sync automática ante conflictos; ausente = ajuste global.
    on_conflict: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def _name_required(cls, v):
        if v is None:
            raise ValueError(MISSING_NAME_MSG)
        return v

    @field_validator("on_conflict")
    @classmethod
    def _onc(cls, v):
        if v is not None and v not in ON_CONFLICT:
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
    """Reglas cruzadas sobre datos crudos (dicts) ya en formato con ids. Devuelve [(ruta_de_campo, mensaje)].

    Trabaja sobre datos sin validar a propósito: así el validador en vivo informa de
    estos errores aunque otro campo ya falle en el esquema.
    """
    errs: List[Tuple[str, str]] = []
    devices = devices if isinstance(devices, dict) else {}
    games = games if isinstance(games, dict) else {}

    def check_items(items, prefix, reserved=()):
        seen_n, seen_i = {}, {}
        for i, it in items.items():
            if not isinstance(i, str) or not ID_RE.fullmatch(i):
                errs.append((f"{prefix}.{i}", "id interno inválido: 1 a 64 caracteres entre letras, números, _ y -"))
                continue
            if i.casefold() in reserved:
                errs.append((f"{prefix}.{i}", "id reservado"))
                continue
            if i.casefold() in seen_i:
                errs.append((f"{prefix}.{i}", f"id repetido o igual (sin distinguir mayúsculas) a {seen_i[i.casefold()]!r}"))
                continue
            seen_i[i.casefold()] = i
            n = it.get("name") if isinstance(it, dict) else None
            if not isinstance(it, dict):
                continue
            e = name_error(n)
            if e:
                errs.append((f"{prefix}.{i}.name", e))
                continue
            other = seen_n.get(n.casefold())
            if other:
                errs.append((f"{prefix}.{i}.name", f"nombre repetido (sin distinguir mayúsculas): {other!r}"))
                continue
            seen_n[n.casefold()] = n

    check_items(devices, "devices", RESERVED_SLUGS)
    check_items(games, "games")
    locals_ = [i for i, d in devices.items() if isinstance(d, dict) and d.get("local") is True]
    if locals_ and running_in_docker():
        for i in locals_:
            errs.append((f"devices.{i}.local", LOCAL_DOCKER_MSG))
    else:
        for i in locals_[1:]:
            errs.append((f"devices.{i}.local", LOCAL_ONE_MSG))
    for i, d in devices.items():
        if isinstance(d, dict) and "local" in d and not isinstance(d["local"], bool):
            errs.append((f"devices.{i}.local", "debe ser true o false"))
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
                errs.append((f"{gp}.devices.{i}", f"dispositivo desconocido (id inexistente): {d!r}"))
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
                errs.append((f"{gp}.paths.{k}", "sobra: este dispositivo no es del juego"
                             if k in devices else "id de dispositivo inexistente"))
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
        """Límite efectivo de versiones del juego (por id): su override o el global. 0 = sin límite."""
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


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader que rechaza claves repetidas en un mapa (PyYAML se queda en silencio con la última)."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for k_node, _v in node.value:
            k = self.construct_object(k_node, deep=True)
            try:
                dup = k in seen
            except TypeError:
                continue
            if dup:
                raise yaml.constructor.ConstructorError(
                    None, None, f"clave repetida: {k!r} (los ids no pueden repetirse)", k_node.start_mark)
            seen.add(k)
        return super().construct_mapping(node, deep)


def load_yaml(text: str):
    """yaml.safe_load con detección de claves repetidas."""
    return yaml.load(text, Loader=_UniqueKeyLoader)


def load_config(path: Path) -> Config:
    path = Path(path)
    if not path.exists():
        return Config()
    try:
        data = load_yaml(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML mal formado: {getattr(e, 'problem', None) or 'error de sintaxis'}")
    return parse_config(data)


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

