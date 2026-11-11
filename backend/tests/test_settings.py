"""Variables de entorno: solo la lista final; las eliminadas se ignoran."""
import os
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def _run(code, **env):
    e = {k: v for k, v in os.environ.items() if not k.startswith("CHECKPOINT_")}
    e.update(CHECKPOINT_RUNTIME="native", PYTHONPATH=str(APP), **env)
    return subprocess.run([sys.executable, "-c", code], env=e, capture_output=True, text=True)


def test_removed_variables_are_ignored(tmp_path):
    r = _run("from app.sync import scheduler\nfrom app.core import settings, updates\n"
             "print(settings.CONFIG_PATH, settings.DATA_DIR, settings.SSH_TIMEOUT)\n"
             "print(scheduler.default_settings())\n"
             "print(updates.REPO, updates.UpdateChecker().channel())",
             CHECKPOINT_HOME_DIR=str(tmp_path), CHECKPOINT_CONFIG="/otra/c.yaml", CHECKPOINT_DATA="/otra/d",
             CHECKPOINT_SSH_TIMEOUT="99", CHECKPOINT_AUTO_ENABLED="1", CHECKPOINT_AUTO_INTERVAL_HOURS="3",
             CHECKPOINT_UPDATE_CHANNEL="beta", CHECKPOINT_UPDATE_REPO="otro/repo", CHECKPOINT_IN_DOCKER="1")
    assert r.returncode == 0, r.stderr
    out = r.stdout.splitlines()
    assert out[0] == f"{tmp_path}/config/config.yaml {tmp_path}/data 8"
    assert "'enabled': False" in out[1] and "'interval_hours': 24.0" in out[1]
    assert out[2].endswith("stable") and "otro/repo" not in out[2]


def test_session_hours_invalid_is_clear_error():
    r = _run("from app.core import settings", CHECKPOINT_SESSION_HOURS="mucho")
    assert r.returncode != 0 and "CHECKPOINT_SESSION_HOURS" in r.stderr
