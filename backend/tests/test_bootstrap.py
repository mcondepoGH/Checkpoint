import stat
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import bootstrap, settings
from app.auth import Auth
from app.config import load_config
from app.main import create_app
from app.transport import PosixTransport, TransportError, _err
from app.config import Device


# ---- config vacío ----
def test_ensure_config_creates_valid_empty(tmp_path):
    p = tmp_path / "config" / "config.yaml"
    assert bootstrap.ensure_config(p) is True
    assert p.read_text() == "devices: {}\ngames: {}\n"
    cfg = load_config(p)
    assert cfg.devices == {} and cfg.games == {}


def test_ensure_config_keeps_existing(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("devices: {}\ngames: {}\n# mío\n")
    assert bootstrap.ensure_config(p) is False
    assert "# mío" in p.read_text()


# ---- clave SSH ----
def test_ssh_key_generated_once_and_never_regenerated(tmp_path):
    key = tmp_path / "keys" / "id_ed25519"
    assert bootstrap.ensure_ssh_key(key) is True
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    priv = key.read_bytes()
    pub = bootstrap.public_key(key)
    assert pub.startswith("ssh-ed25519 ") and "PRIVATE" not in pub
    assert bootstrap.ensure_ssh_key(key) is False
    assert key.read_bytes() == priv and bootstrap.public_key(key) == pub


def test_public_key_derived_when_pub_missing(tmp_path):
    key = tmp_path / "id_ed25519"
    bootstrap.ensure_ssh_key(key)
    pub = bootstrap.public_key(key)
    (tmp_path / "id_ed25519.pub").unlink()
    assert bootstrap.public_key(key) == pub


def test_public_key_none_without_key(tmp_path):
    assert bootstrap.public_key(tmp_path / "nope") is None


# ---- known_hosts TOFU ----
SCAN = "10.0.0.5 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n"


def test_tofu_saves_first_use_then_does_not_rescan(tmp_path, monkeypatch):
    kh = tmp_path / "known_hosts"
    calls = []
    monkeypatch.setattr(bootstrap, "_keyscan", lambda h, p: calls.append((h, p)) or SCAN)
    assert bootstrap.ensure_host_key("10.0.0.5", 22, kh) is True
    assert kh.read_text() == SCAN and stat.S_IMODE(kh.stat().st_mode) == 0o600
    assert bootstrap.ensure_host_key("10.0.0.5", 22, kh) is False
    assert calls == [("10.0.0.5", 22)]


def test_tofu_never_overwrites_when_key_changes(tmp_path, monkeypatch):
    kh = tmp_path / "known_hosts"
    monkeypatch.setattr(bootstrap, "_keyscan", lambda h, p: SCAN)
    bootstrap.ensure_host_key("10.0.0.5", 22, kh)
    before = kh.read_text()
    # el host ahora presentaría otra clave: ni se consulta ni se toca el fichero
    monkeypatch.setattr(bootstrap, "_keyscan", lambda h, p: pytest.fail("no debe reescanear"))
    assert bootstrap.ensure_host_key("10.0.0.5", 22, kh) is False
    assert kh.read_text() == before


def test_tofu_non_default_port_entry(tmp_path, monkeypatch):
    kh = tmp_path / "known_hosts"
    monkeypatch.setattr(bootstrap, "_keyscan",
                        lambda h, p: SCAN.replace("10.0.0.5", "[10.0.0.5]:2222"))
    assert bootstrap.ensure_host_key("10.0.0.5", 2222, kh) is True
    assert bootstrap.has_host_entry("10.0.0.5", 2222, kh)
    assert not bootstrap.has_host_entry("10.0.0.5", 22, kh)


@pytest.mark.parametrize("host,port", [("-oProxyCommand=x", 22), ("a b", 22), ("h;rm", 22),
                                       ("10.0.0.1", 0), ("10.0.0.1", 70000), ("10.0.0.1", "x")])
def test_tofu_rejects_injection(tmp_path, host, port):
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.ensure_host_key(host, port, tmp_path / "kh")


def test_keyscan_uses_arg_list_no_shell(monkeypatch):
    seen = {}

    def fake_run(args, **kw):
        seen["args"], seen["kw"] = args, kw
        return subprocess.CompletedProcess(args, 0, stdout=SCAN.encode(), stderr=b"")
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    bootstrap._keyscan("10.0.0.5", 22)
    assert isinstance(seen["args"], list) and not seen["kw"].get("shell")
    assert seen["args"][-1] == "10.0.0.5"


def test_changed_host_key_gives_clear_error():
    p = subprocess.CompletedProcess(
        [], 255, b"", b"@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @@@\nHost key verification failed.")
    msg = _err(p, Device(host="10.0.0.5", user="u", os="linux"))
    assert "CAMBIADO" in msg and "No se sobrescribe" in msg


def test_check_marks_first_use_and_fails_if_keyscan_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "KNOWN_HOSTS", str(tmp_path / "known_hosts"))
    dev = Device(host="10.0.0.5", user="u", os="linux")
    monkeypatch.setattr(bootstrap, "_keyscan", lambda h, p: SCAN)
    monkeypatch.setattr("app.transport._run",
                        lambda a, timeout=0, stdin=None: subprocess.CompletedProcess(a, 0, b"ok", b""))
    t = PosixTransport(dev)
    t.check()
    assert t.first_use is True
    t.check()
    assert t.first_use is False

    def boom(h, p):
        raise bootstrap.BootstrapError("sin respuesta")
    monkeypatch.setattr(settings, "KNOWN_HOSTS", str(tmp_path / "otro"))
    monkeypatch.setattr(bootstrap, "_keyscan", boom)
    with pytest.raises(TransportError):
        PosixTransport(dev).check()


# ---- contraseña ----
def test_login_ok_and_wrong_password():
    a = Auth("admin", "s3cret pass", 1, rounds=4)
    assert a.login("1.1.1.1", "admin", "s3cret pass")
    assert a.login("1.1.1.2", "admin", "otra") is None
    assert a.login("1.1.1.3", "otro", "s3cret pass") is None


def test_plain_password_not_kept():
    a = Auth("admin", "s3cret pass", 1, rounds=4)
    assert a.pw_hash.startswith(b"$2") and b"s3cret" not in a.pw_hash
    assert "s3cret pass" not in repr(vars(a))


@pytest.mark.parametrize("env", [{}, {"CHECKPOINT_USER": "admin"}, {"CHECKPOINT_PASSWORD": "x"},
                                 {"CHECKPOINT_USER": "", "CHECKPOINT_PASSWORD": "x"}])
def test_missing_var_gives_clear_error(env):
    with pytest.raises(RuntimeError, match="Faltan CHECKPOINT_USER / CHECKPOINT_PASSWORD"):
        Auth.from_env(env, rounds=4)


def test_create_app_from_env(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_USER", "admin")
    monkeypatch.setenv("CHECKPOINT_PASSWORD", "claro-123")
    c = TestClient(create_app())
    assert c.post("/api/login", json={"user": "admin", "password": "claro-123"}).status_code == 200
    assert c.post("/api/login", json={"user": "admin", "password": "mala"}).status_code == 401


def test_create_app_without_vars_fails(monkeypatch):
    monkeypatch.delenv("CHECKPOINT_USER", raising=False)
    monkeypatch.delenv("CHECKPOINT_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="Faltan CHECKPOINT_USER"):
        create_app()


def test_savesync_prefix_is_ignored(monkeypatch):
    from app import settings
    for k in ("USER", "PASSWORD", "PORT"):
        monkeypatch.delenv("CHECKPOINT_" + k, raising=False)
    monkeypatch.setenv("SAVESYNC_PORT", "9000")
    assert settings.env("PORT", "8088") == "8088"
    monkeypatch.setenv("SAVESYNC_USER", "viejo")
    monkeypatch.setenv("SAVESYNC_PASSWORD", "clave-vieja")
    with pytest.raises(RuntimeError, match="Faltan CHECKPOINT_USER"):
        create_app()
    monkeypatch.setenv("CHECKPOINT_PORT", "9100")
    assert settings.env("PORT", "8088") == "9100"


def test_password_not_logged(monkeypatch, caplog, capsys):
    from app.redact import redact
    monkeypatch.setenv("CHECKPOINT_USER", "admin")
    monkeypatch.setenv("CHECKPOINT_PASSWORD", "claro-123456")
    with caplog.at_level("DEBUG"):
        c = TestClient(create_app())
        c.post("/api/login", json={"user": "admin", "password": "claro-123456"})
        c.post("/api/login", json={"user": "admin", "password": "mala-pass"})
    out = capsys.readouterr()
    assert "claro-123456" not in caplog.text + out.out + out.err
    assert "claro-123456" not in redact("pw claro-123456 fin")


# ---- endpoint clave pública ----
def test_public_key_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SSH_KEY", str(tmp_path / "k" / "id_ed25519"))
    c = TestClient(create_app(Auth("admin", "pw", 1, rounds=4)))
    assert c.get("/api/ssh/public-key").status_code == 401
    c.post("/api/login", json={"user": "admin", "password": "pw"})
    assert c.get("/api/ssh/public-key").status_code == 404
    bootstrap.ensure_ssh_key()
    r = c.get("/api/ssh/public-key")
    assert r.status_code == 200
    body = r.text
    assert r.json()["public_key"].startswith("ssh-ed25519 ")
    assert "PRIVATE" not in body
    priv = open(settings.SSH_KEY).read().strip().splitlines()[1]
    assert priv not in body
