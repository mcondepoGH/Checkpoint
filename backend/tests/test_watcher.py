"""Vigilante de proceso (tras `opened`): reloj, sleep, sondeo y checkpoint inyectados; sin esperas reales."""
import asyncio

import pytest

from app.sync.watcher import Watcher

POLL, SETTLE, FIRST = 15, 10, 120


class Fake:
    """Reloj falso: `sleep` avanza el tiempo y cede el control. `states`: {segundo: bool | Exception} (el último vale hasta el siguiente)."""

    def __init__(self, states):
        self.t, self.states, self.checkpoints, self.notes = 0.0, sorted(states.items()), [], []

    def clock(self):
        return self.t

    async def sleep(self, s):
        self.t += s
        await asyncio.sleep(0)

    def probe(self, game, device):
        cur = False
        for at, v in self.states:
            if self.t >= at:
                cur = v
        if isinstance(cur, Exception):
            raise cur
        return cur

    async def checkpoint(self, game, device):
        self.checkpoints.append((game, device, self.t))

    def make(self, **kw):
        return Watcher(self.probe, self.checkpoint, clock=self.clock, sleep=self.sleep,
                       poll=POLL, settle=SETTLE, first_seen=FIRST, note=lambda *a: self.notes.append(a), **kw)


async def settle_all(w):
    await asyncio.gather(*list(w.tasks.values()), return_exceptions=True)


def run(coro):
    return asyncio.run(coro)


def test_never_seen_is_discarded_after_first_seen_limit():
    f = Fake({0: False})
    w = f.make()

    async def go():
        w.arm("g1", "dev-1")
        assert w.list()[0]["state"] == "waiting"
        await settle_all(w)

    run(go())
    assert f.checkpoints == [] and w.list() == []
    assert f.t >= FIRST and any(n[0] == "never_seen" for n in f.notes)


def test_seen_then_gone_waits_settle_then_single_checkpoint():
    f = Fake({0: False, 30: True, 100: False})
    w = f.make()

    async def go():
        w.arm("g1", "dev-1")
        await settle_all(w)

    run(go())
    assert len(f.checkpoints) == 1
    g, d, at = f.checkpoints[0]
    assert (g, d) == ("g1", "dev-1")
    assert 100 + SETTLE <= at <= 100 + POLL + SETTLE + 1  # >= 10 s tras dejar de verlo
    assert w.list() == []


def test_state_transitions_waiting_running_settling():
    seen = []

    class F(Fake):
        async def checkpoint(self, game, device):
            seen.append(w.list()[0]["state"])
            await super().checkpoint(game, device)

        def probe(self, game, device):
            r = super().probe(game, device)
            return r

    f = F({0: False, 15: True, 45: False})
    w = f.make()
    states = []
    orig = f.sleep

    async def spy(s):
        if w.list():
            states.append(w.list()[0]["state"])
        await orig(s)

    w.sleep = spy

    async def go():
        w.arm("g1", "dev-1")
        await settle_all(w)

    run(go())
    assert states[0] == "waiting" and "running" in states and "settling" in states
    assert seen == ["settling"]


def test_transport_error_after_seen_counts_as_closed():
    f = Fake({0: True, 40: RuntimeError("ssh caído")})
    w = f.make()

    async def go():
        w.arm("g1", "dev-1")
        await settle_all(w)

    run(go())
    assert len(f.checkpoints) == 1


def test_transport_error_before_seen_keeps_waiting_and_then_discards():
    f = Fake({0: RuntimeError("ssh caído")})
    w = f.make()

    async def go():
        w.arm("g1", "dev-1")
        await settle_all(w)

    run(go())
    assert f.checkpoints == [] and any(n[0] == "never_seen" for n in f.notes)


def test_second_arm_replaces_first_single_checkpoint():
    f = Fake({0: True, 60: False})
    w = f.make()

    async def go():
        w.arm("g1", "dev-1")
        await asyncio.sleep(0)
        w.arm("g1", "dev-2")  # reemplaza
        assert [x["device"] for x in w.list()] == ["dev-2"]
        await settle_all(w)

    run(go())
    assert [(g, d) for g, d, _ in f.checkpoints] == [("g1", "dev-2")]


def test_other_games_are_independent():
    f = Fake({0: True, 60: False})
    w = f.make()

    async def go():
        w.arm("g1", "dev-1")
        w.arm("g2", "dev-1")
        assert len(w.list()) == 2
        await settle_all(w)

    run(go())
    assert sorted(g for g, _, _ in f.checkpoints) == ["g1", "g2"]


def test_checkpoint_failure_is_not_retried():
    f = Fake({0: True, 60: False})
    calls = []

    async def boom(game, device):
        calls.append(1)
        raise RuntimeError("aborta")

    f.checkpoint = boom
    w = f.make()

    async def go():
        w.arm("g1", "dev-1")
        await settle_all(w)

    run(go())
    assert calls == [1] and w.list() == [] and any(n[0] == "checkpoint_error" for n in f.notes)


def test_cancel_all_on_shutdown():
    f = Fake({0: True})
    w = f.make()

    async def go():
        w.arm("g1", "dev-1")
        await asyncio.sleep(0)
        await w.cancel_all()
        assert w.list() == [] and w.tasks == {}

    run(go())
    assert f.checkpoints == []


def test_list_exposes_heartbeat_fields():
    f = Fake({0: False, 30: True})
    w = f.make()

    async def go():
        w.arm("g1", "dev-1")
        first = w.list()[0]
        assert first["poll"] == POLL and first["last_poll"] and first["since"]
        assert set(first) == {"game", "device", "state", "since", "last_poll", "poll"}
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return first

    first = run(go())
    assert first["last_poll"] >= first["since"]


def test_last_poll_advances_each_probe_even_on_transport_error():
    f = Fake({0: RuntimeError("ssh")})
    w = f.make()
    seen = []

    async def go():
        w.arm("g1", "dev-1")
        for _ in range(6):
            await asyncio.sleep(0)
            if w.list():
                seen.append(w.list()[0]["last_poll"])
        await settle_all(w)

    run(go())
    assert len(seen) >= 2 and seen == sorted(seen) and seen[-1] >= seen[0]
