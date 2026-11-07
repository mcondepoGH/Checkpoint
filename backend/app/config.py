"""Modelo y validación de config.yaml; escritura atómica."""
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:\-]{0,252}$")
USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,31}$")
PROC_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_. \-]{0,63}$")
# Caracteres permitidos en rutas: nada de metacaracteres de shell/cmd.
PATH_CHARS_RE = re.compile(r"^[\w .\-/()\[\]+,@~=#{}]+$")
OSES = ("windows", "steamos", "linux")


class ConfigError(ValueError):
    pass


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
    keep_versions: int = Field(default=5)

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
        if not 1 <= v <= 100:
            raise ValueError("keep_versions debe estar entre 1 y 100")
        return v


def semantic_errors(devices, games) -> List[Tuple[str, str]]:
    """Reglas cruzadas sobre datos crudos (dicts). Devuelve [(ruta_de_campo, mensaje)].

    Trabaja sobre datos sin validar a propósito: así el validador en vivo informa de
    estos errores aunque otro campo ya falle en el esquema.
    """
    errs: List[Tuple[str, str]] = []
    devices = devices if isinstance(devices, dict) else {}
    games = games if isinstance(games, dict) else {}
    for n in devices:
        if not isinstance(n, str) or not NAME_RE.match(n):
            errs.append((f"devices.{n}", "nombre inválido: letras, números, _ y - (máx. 32)"))
    for gname, g in games.items():
        gp = f"games.{gname}"
        if not isinstance(gname, str) or not NAME_RE.match(gname):
            errs.append((gp, "nombre inválido: letras, números, _ y - (máx. 32)"))
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
    devices: Dict[str, Device] = {}
    games: Dict[str, Game] = {}

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
