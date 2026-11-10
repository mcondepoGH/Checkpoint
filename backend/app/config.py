"""Modelo y validación de config.yaml; escritura atómica."""
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from pydantic_core import PydanticCustomError

from .apierror import error_body
from .runtime import running_in_docker
from pydantic import (BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError, field_validator, model_serializer,
                      model_validator)

NAME_MAX = 64
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


class ConfigError(ValueError):
    """Error de config con contrato i18n: `code` (`err.config.<causa>`) + `params`. Sin texto en español:
    la UI traduce. `str(e)` es técnico (código y parámetros), para logs y CLI."""

    def __init__(self, code: str, **params):
        super().__init__(code + (" " + " ".join(f"{k}={v!r}" for k, v in params.items()) if params else ""))
        self.code, self.params = code, params

    def body(self) -> dict:
        return error_body(self.code, **self.params)


def _pyd(code: str, template: Optional[str] = None, **params) -> PydanticCustomError:
    """Error de validador pydantic que conserva code+params (en `err["type"]` y `err["ctx"]`)."""
    return PydanticCustomError(code, template or code, params)


def describe(err: Optional[dict]) -> str:
    """Texto técnico (no traducido) de un {code, params} para logs y CLI."""
    if not err:
        return ""
    return err["code"] + "".join(f" {k}={v!r}" for k, v in err.get("params", {}).items())


def errors_to_causes(errors: Dict[str, dict]) -> List[dict]:
    """{ruta: {code, params}} -> [{path, code, params}] (lista que la UI sabe pintar como «ruta: texto»)."""
    return [{"path": k, **v} for k, v in errors.items()]


def yaml_error(e: Exception) -> ConfigError:
    """ConfigError de un fallo de lectura YAML (sintaxis o clave repetida)."""
    if isinstance(e, DuplicateKeyError):
        return ConfigError("err.config.yaml_duplicate_key", key=str(e.key))
    problem = getattr(e, "problem", None)
    return ConfigError("err.config.yaml_syntax", problem=problem) if problem else ConfigError("err.config.yaml_malformed")


def name_error(name) -> Optional[dict]:
    """{code, params} de error si `name` no es un nombre visible válido; None si lo es."""
    if name is None:
        return error_body("err.config.name_missing")
    if not isinstance(name, str):
        return error_body("err.config.name_not_text")
    if not name.strip():
        return error_body("err.config.name_empty")
    if name != name.strip() or "  " in name:
        return error_body("err.config.name_spaces")
    if len(name) > NAME_MAX:
        return error_body("err.config.name_too_long", max=NAME_MAX)
    if "/" in name or "\\" in name:
        return error_body("err.config.name_slash")
    for ch in name:
        cat = unicodedata.category(ch)
        if ch == "\u200d":  # unión de emojis compuestos
            continue
        if cat[0] == "C" or cat in ("Zl", "Zp") or (cat == "Zs" and ch != " "):
            return error_body("err.config.name_control")
    if not name.strip("."):
        return error_body("err.config.name_dots")
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
        raise ConfigError("err.config.ref_ambiguous", ref=ref, matches=", ".join(
            f"{getattr(items[i], 'name', i)!r} ({i})" for i in hits))
    return hits[0] if hits else None


def normalize_path(os_name: str, p: str) -> str:
    if not isinstance(p, str):
        raise ConfigError("err.config.path_text")
    p = p.strip()
    if os_name == "windows":
        p = p.replace("\\", "/")
    if os_name == "windows":
        m = re.match(r"^([A-Za-z]):/(.*)$", p)
        if not m:
            raise ConfigError("err.config.path_windows")
        prefix, rest = f"{m.group(1)}:/", m.group(2)
    else:
        if not p.startswith("/"):
            raise ConfigError("err.config.path_absolute")
        prefix, rest = "/", p[1:]
    if rest and not PATH_CHARS_RE.match(rest):
        raise ConfigError("err.config.path_chars", path=p)
    parts = [s for s in rest.split("/") if s not in ("", ".")]
    if ".." in parts:
        raise ConfigError("err.config.path_dotdot")
    if not parts:
        raise ConfigError("err.config.path_root")
    return prefix + "/".join(parts)


# Texto fijo que aún usa transport.py (tramo posterior); la UI recibe `err.config.local_docker`.


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
            raise _pyd("err.config.name_missing")
        return v

    @field_validator("host", "user", "port", mode="before")
    @classmethod
    def _remote_only(cls, v, info):
        if info.data.get("local") is True:
            if v not in (None, ""):
                raise _pyd("err.config.local_no_remote")
            return None
        if info.field_name == "port" and v is None:
            return 22
        if v is None:
            raise _pyd("err.config.required")
        return v

    @field_validator("host", "user", "port", mode="after")
    @classmethod
    def _check_remote(cls, v, info):
        if v is None:
            return v
        if info.field_name == "host" and not HOST_RE.match(v):
            raise _pyd("err.config.host_invalid")
        if info.field_name == "user" and not USER_RE.match(v):
            raise _pyd("err.config.user_invalid")
        if info.field_name == "port" and not 1 <= v <= 65535:
            raise _pyd("err.config.port_range")
        return v

    @field_validator("os")
    @classmethod
    def _os(cls, v):
        if v not in OSES:
            raise _pyd("err.config.os_invalid", options=", ".join(OSES))
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
    # Un juego desactivado no se sincroniza por ninguna vía (automática, manual, aviso de apertura/cierre).
    enabled: StrictBool = True

    @field_validator("name", mode="before")
    @classmethod
    def _name_required(cls, v):
        if v is None:
            raise _pyd("err.config.name_missing")
        return v

    @model_serializer(mode="wrap")
    def _ser(self, handler):
        d = handler(self)
        if self.enabled:  # solo se escribe `enabled: false`
            d.pop("enabled", None)
        return d

    @field_validator("on_conflict")
    @classmethod
    def _onc(cls, v):
        if v is not None and v not in ON_CONFLICT:
            raise _pyd("err.config.on_conflict_invalid")
        return v

    @field_validator("process")
    @classmethod
    def _proc(cls, v):
        if v in (None, ""):
            return None
        if not PROC_RE.match(v):
            raise _pyd("err.config.process_invalid")
        return v

    @field_validator("keep_versions")
    @classmethod
    def _keep(cls, v):
        if v is not None and not 0 <= v <= MAX_VERSIONS_LIMIT:
            raise _pyd("err.config.versions_range", max=MAX_VERSIONS_LIMIT)
        return v


def semantic_errors(devices, games) -> List[Tuple[str, dict]]:
    """Reglas cruzadas sobre datos crudos (dicts) ya en formato con ids. Devuelve [(ruta_de_campo, {code, params})].

    Trabaja sobre datos sin validar a propósito: así el validador en vivo informa de
    estos errores aunque otro campo ya falle en el esquema.
    """
    errs: List[Tuple[str, dict]] = []
    devices = devices if isinstance(devices, dict) else {}
    games = games if isinstance(games, dict) else {}

    def check_items(items, prefix, reserved=()):
        seen_n, seen_i = {}, {}
        for i, it in items.items():
            if not isinstance(i, str) or not ID_RE.fullmatch(i):
                errs.append((f"{prefix}.{i}", error_body("err.config.id_invalid")))
                continue
            if i.casefold() in reserved:
                errs.append((f"{prefix}.{i}", error_body("err.config.id_reserved")))
                continue
            if i.casefold() in seen_i:
                errs.append((f"{prefix}.{i}", error_body("err.config.id_duplicate", other=seen_i[i.casefold()])))
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
                errs.append((f"{prefix}.{i}.name", error_body("err.config.name_duplicate", other=other)))
                continue
            seen_n[n.casefold()] = n

    check_items(devices, "devices", RESERVED_SLUGS)
    check_items(games, "games")
    locals_ = [i for i, d in devices.items() if isinstance(d, dict) and d.get("local") is True]
    if locals_ and running_in_docker():
        for i in locals_:
            errs.append((f"devices.{i}.local", error_body("err.config.local_docker")))
    else:
        for i in locals_[1:]:
            errs.append((f"devices.{i}.local", error_body("err.config.local_one")))
    for i, d in devices.items():
        if isinstance(d, dict) and "local" in d and not isinstance(d["local"], bool):
            errs.append((f"devices.{i}.local", error_body("err.config.bool_required")))
    for gname, g in games.items():
        gp = f"games.{gname}"
        if not isinstance(g, dict):
            continue
        if "enabled" in g and not isinstance(g["enabled"], bool):
            errs.append((f"{gp}.enabled", error_body("err.config.bool_required")))
        devs = g.get("devices")
        paths = g.get("paths")
        if not isinstance(devs, list) or len(devs) not in (1, 2):
            errs.append((f"{gp}.devices", error_body("err.config.devices_count")))
            continue
        ok_devs = []
        for i, d in enumerate(devs):
            if not d:
                errs.append((f"{gp}.devices.{i}", error_body("err.config.device_required")))
            elif d not in devices:
                errs.append((f"{gp}.devices.{i}", error_body("err.config.device_unknown", id=d)))
            else:
                ok_devs.append(d)
        if len(devs) == 2 and devs[0] and devs[0] == devs[1]:
            errs.append((f"{gp}.devices.1", error_body("err.config.device_same")))
        if not isinstance(paths, dict):
            if paths is not None:
                errs.append((f"{gp}.paths", error_body("err.config.paths_map")))
            paths = {}
        for k in paths:
            if k not in devs:
                errs.append((f"{gp}.paths.{k}", error_body("err.config.path_extra" if k in devices else "err.config.path_device_unknown")))
        for d in ok_devs:
            if d not in paths or paths[d] in (None, ""):
                errs.append((f"{gp}.paths.{d}", error_body("err.config.path_missing")))
                continue
            dev = devices[d]
            os_name = dev.get("os") if isinstance(dev, dict) else None
            if os_name not in OSES:
                continue  # el error ya sale en devices.<d>.os
            try:
                normalize_path(os_name, paths[d])
            except ConfigError as e:
                errs.append((f"{gp}.paths.{d}", e.body()))
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
            raise _pyd("err.config.versions_range", max=MAX_VERSIONS_LIMIT)
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
            raise _pyd("err.config.inconsistent", "{errors}", errors="; ".join(f"{p}: {m['code']}" for p, m in errs))
        for g in self.games.values():
            for d in g.devices:
                g.paths[d] = normalize_path(self.devices[d].os, g.paths[d])
        return self


def parse_config(data) -> Config:
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError("err.config.not_map")
    return Config.model_validate(data)


# Tipos de error de pydantic -> código `err.config.*` (los validadores propios ya emiten su code vía _pyd).
_PYD_CODE = {
    "missing": "err.config.required",
    "int_parsing": "err.config.int",
    "int_type": "err.config.int",
    "int_from_float": "err.config.int",
    "string_type": "err.config.text",
    "extra_forbidden": "err.config.extra",
    "dict_type": "err.config.map",
    "list_type": "err.config.list",
    "bool_type": "err.config.bool_required",
}


def pyd_body(err: dict) -> dict:
    """{code, params} de un error de pydantic; lo desconocido va como `err.config.invalid` + `reason` (texto de pydantic)."""
    t = err["type"]
    if t.startswith("err.config."):
        return error_body(t, **(err.get("ctx") or {}))
    if t in _PYD_CODE:
        return error_body(_PYD_CODE[t])
    return error_body("err.config.invalid", reason=err["msg"])


def validate_config(data) -> Tuple[Optional[Config], Dict[str, dict]]:
    """Valida con las mismas reglas que la carga. Devuelve (config|None, {ruta_de_campo: {code, params}})."""
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, {"": error_body("err.config.not_map")}
    errors: Dict[str, dict] = {}
    cfg = None
    try:
        cfg = Config.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            if err["loc"]:
                errors.setdefault(".".join(str(x) for x in err["loc"]), pyd_body(err))
        # reglas cruzadas aunque el esquema falle en otro campo
        for path, body in semantic_errors(data.get("devices"), data.get("games")):
            errors.setdefault(path, body)
        if not errors:
            errors[""] = error_body("err.config.invalid", reason="; ".join(x["msg"] for x in e.errors()))
    return (cfg if not errors else None), errors


class DuplicateKeyError(yaml.constructor.ConstructorError):
    """Clave repetida en un mapa YAML; `key` es la clave."""

    def __init__(self, key, mark):
        super().__init__(None, None, f"duplicate key: {key!r}", mark)
        self.key = key


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
                raise DuplicateKeyError(k, k_node.start_mark)
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
        raise yaml_error(e)
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

