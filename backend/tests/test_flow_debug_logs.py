"""Logs de trazabilidad apertura -> vigilancia -> cierre -> sync: DEBUG visible con DEBUG, ausente con INFO y sin secretos.
Con INFO solo cambia el log `hook ... resultado=` (ahora con `code=` y `duración=`)."""
import logging
import re

import pytest

from app.users import history
from test_hook_close import cl, hist, hopen, mk, wait_for, watches  # noqa: F401 (fixtures)

FLOW = ("checkpoint.watcher", "checkpoint.hook", "checkpoint.sync", "checkpoint.transport")


def flow_records(caplog):
    return [r for r in caplog.records if r.name in FLOW]


def run_cycle(c):
    hopen(c)
    c.proc.running = True
    assert wait_for(lambda: watches(c).json() and watches(c).json()[0]["state"] == "running")
    c.proc.running = False
    assert wait_for(lambda: hist("hook_closed"))
    assert wait_for(lambda: watches(c).json() == [])


def test_debug_traces_whole_flow(cl, caplog):
    caplog.set_level(logging.DEBUG, logger="checkpoint")
    run_cycle(cl)
    text = "\n".join(f"{r.name} {r.getMessage()}" for r in flow_records(caplog))
    for frag in ("armar: juego=g1", "sondeo: juego=g1", "waiting -> running", "running -> settling",
                 "iniciando checkpoint", "cierre detectado, lanzando checkpoint", "inicio run=", "fin duración=",
                 "historial_guardado=True", "run_sync inicio", "run_sync fin", "conexión OK en", "decisión:"):
        assert frag in text, frag


def test_debug_replace_and_cancel(cl, caplog):
    caplog.set_level(logging.DEBUG, logger="checkpoint.watcher")
    hopen(cl)
    hopen(cl)
    m = [r.getMessage() for r in caplog.records]
    assert any("reemplaza una vigilancia previa" in x for x in m) and any(x.startswith("cancelar:") for x in m)


def test_debug_silent_exit_unknown_game(cl, caplog):
    import asyncio
    caplog.set_level(logging.DEBUG, logger="checkpoint.hook")
    w = cl.app.state.watcher
    asyncio.run(w.checkpoint("no-existe", "dev-1"))
    m = [r.getMessage() for r in caplog.records]
    assert any("cierre detectado" in x for x in m) and any("ya no está en la configuración" in x for x in m)


def test_info_closed_line_has_code_and_duration_and_no_debug(cl, caplog):
    caplog.set_level(logging.INFO, logger="checkpoint")
    run_cycle(cl)
    recs = flow_records(caplog)
    assert all(r.levelno >= logging.INFO for r in recs)
    res = [r.getMessage() for r in recs if "resultado=" in r.getMessage()]
    assert any(re.fullmatch(r"hook hook_closed juego=\S+.* resultado=ok code=\S+ duración=\d+\.\d s", x) for x in res), res
    assert any(x.startswith("hook hook juego=") and "duración=" in x for x in res)


def test_history_failure_leaves_trace_without_breaking(cl, caplog, monkeypatch):
    def boom(*a, **k):
        raise OSError("disco lleno /secreto")
    monkeypatch.setattr(history, "append", boom)
    caplog.set_level(logging.INFO, logger="checkpoint.hook")
    assert hopen(cl).json()["outcome"] == "ok"
    m = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("no se pudo guardar en el historial (OSError)" in x for x in m)
    assert not any("secreto" in x for x in m)


def test_no_secrets_in_flow_logs(cl, caplog):
    caplog.set_level(logging.DEBUG, logger="checkpoint")
    run_cycle(cl)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert cl.key not in text and "Bearer" not in text
    assert "BEGIN" not in text and "PRIVATE KEY" not in text


def test_transport_run_logs_duration_not_args(caplog, monkeypatch):
    import subprocess
    from app import transport
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, b"", b""))
    caplog.set_level(logging.DEBUG, logger="checkpoint.transport")
    transport._run(["ssh", "-i", "/clave/privada", "u@h", "true"])
    m = [r.getMessage() for r in caplog.records]
    assert any(x.startswith("ssh: rc=0 en ") for x in m) and not any("/clave/privada" in x for x in m)
    caplog.clear()
    caplog.set_level(logging.INFO, logger="checkpoint.transport")
    transport._run(["ssh", "u@h", "true"])
    assert caplog.records == []


def hook_msgs(caplog, level=logging.DEBUG):
    return [r.getMessage() for r in caplog.records if r.name == "checkpoint.hook" and r.levelno == level]


def test_debug_history_entry_for_skipped_never_seen(cl, caplog):
    caplog.set_level(logging.DEBUG, logger="checkpoint.hook")
    hopen(cl)
    assert wait_for(lambda: hist("hook_closed"))
    m = [x for x in hook_msgs(caplog) if "entrada de historial" in x]
    assert len(m) == 1, m
    for frag in ("hook hook_closed", "juego=", "dispositivo=dev-1", "resultado=skipped", "code=err.hook.never_seen",
                 "historial_guardado=True"):
        assert frag in m[0], (frag, m[0])


def test_debug_history_entry_not_saved_and_error_without_message(cl, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG, logger="checkpoint.hook")
    monkeypatch.setattr(history, "append", lambda *a, **k: (_ for _ in ()).throw(OSError("disco lleno /secreto")))
    hopen(cl)
    assert wait_for(lambda: any("entrada de historial" in x for x in hook_msgs(caplog)))
    m = [x for x in hook_msgs(caplog) if "entrada de historial" in x][0]
    assert "historial_guardado=False" in m and "resultado=skipped" in m
    assert not any("secreto" in r.getMessage() for r in caplog.records)


def test_debug_history_entry_absent_with_info(cl, caplog):
    caplog.set_level(logging.INFO, logger="checkpoint")
    hopen(cl)
    assert wait_for(lambda: hist("hook_closed"))
    assert not any("entrada de historial" in r.getMessage() for r in caplog.records)
    assert all(r.levelno >= logging.INFO for r in flow_records(caplog))
