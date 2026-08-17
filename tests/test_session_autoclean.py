"""Background reclaim: what it drops, what it must never drop, and that one
broken account cannot stop the loop.

The dangerous half is the cloud pass -- it deletes conversations on a real
Microsoft account -- so the protection rule (every conversation a surviving local
session still points at) is pinned here, not just documented.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from m365_copilot_openai_proxy import runtime_flags, session_autoclean
from m365_copilot_openai_proxy.m365_cloud_client import CloudSessionError
from m365_copilot_openai_proxy.session_store import PersistentSessionStore


def _app(tmp_path, accounts=(), **state):
    store = PersistentSessionStore(persist_path=tmp_path / "sessions.json")
    return SimpleNamespace(
        state=SimpleNamespace(
            session_store=store,
            account_store=SimpleNamespace(list=lambda: list(accounts)),
            **state,
        )
    )


def _account(account_id: str, provider: str = "m365"):
    return SimpleNamespace(id=account_id, provider=provider)


def _session(app, key: str, *, idle_seconds: float = 0.0, conversation_id: str = ""):
    session = app.state.session_store.get(key)
    if conversation_id:
        session.conversation_id = conversation_id
    session.last_accessed = time.time() - idle_seconds
    return session


def _sweeps(monkeypatch, deleted_by_account: dict[str, list[str]] | None = None) -> list[dict]:
    """Record every cloud sweep instead of calling Microsoft."""
    calls: list[dict] = []

    async def _fake(accounts, account_id, older_than=0.0, keep_newest=0, protected=None):
        calls.append({
            "account_id": account_id,
            "older_than": older_than,
            "protected": set(protected or set()),
        })
        ids = (deleted_by_account or {}).get(account_id, [])
        if isinstance(ids, BaseException):
            raise ids
        return len(ids), list(ids)

    monkeypatch.setattr(session_autoclean, "cleanup_conversations", _fake)
    return calls


def test_idle_sessions_go_and_fresh_ones_stay(tmp_path):
    app = _app(tmp_path)
    _session(app, "keyA:auto:old", idle_seconds=7200)
    _session(app, "keyA:auto:new", idle_seconds=10)
    _session(app, "keyB:auto:old", idle_seconds=7200)

    removed, deleted = asyncio.run(
        session_autoclean.auto_cleanup_once(app, session_idle_seconds=3600, cloud_idle_seconds=0)
    )

    assert sorted(removed) == ["keyA:auto:old", "keyB:auto:old"]
    assert deleted == []
    assert [key for key, _ in app.state.session_store.items()] == ["keyA:auto:new"]


def test_zero_thresholds_touch_nothing(tmp_path, monkeypatch):
    app = _app(tmp_path, accounts=[_account("acct_1")])
    _session(app, "keyA:auto:ancient", idle_seconds=90 * 24 * 3600)
    calls = _sweeps(monkeypatch)

    removed, deleted = asyncio.run(
        session_autoclean.auto_cleanup_once(app, session_idle_seconds=0, cloud_idle_seconds=0)
    )

    assert (removed, deleted, calls) == ([], [], [])
    assert len(app.state.session_store.items()) == 1


def test_the_cloud_pass_protects_every_live_conversation(tmp_path, monkeypatch):
    app = _app(tmp_path, accounts=[_account("acct_1")])
    _session(app, "keyA:auto:live", idle_seconds=10, conversation_id="conv-live")
    _session(app, "keyA:auto:cold", idle_seconds=7200, conversation_id="conv-cold")
    calls = _sweeps(monkeypatch, {"acct_1": ["conv-cold", "conv-stranger"]})

    removed, deleted = asyncio.run(
        session_autoclean.auto_cleanup_once(app, session_idle_seconds=3600, cloud_idle_seconds=3600)
    )

    assert removed == ["keyA:auto:cold"]
    assert deleted == ["conv-cold", "conv-stranger"]
    # The pruned session's conversation is fair game; the live one never is.
    assert calls == [{"account_id": "acct_1", "older_than": 3600, "protected": {"conv-live"}}]


def test_a_live_conversation_survives_when_local_pruning_is_off(tmp_path, monkeypatch):
    app = _app(tmp_path, accounts=[_account("acct_1")])
    _session(app, "keyA:auto:cold", idle_seconds=90 * 24 * 3600, conversation_id="conv-cold")
    calls = _sweeps(monkeypatch)

    asyncio.run(
        session_autoclean.auto_cleanup_once(app, session_idle_seconds=0, cloud_idle_seconds=3600)
    )

    assert calls[0]["protected"] == {"conv-cold"}


def test_consumer_accounts_are_never_swept(tmp_path, monkeypatch):
    app = _app(tmp_path, accounts=[_account("acct_consumer", provider="consumer"), _account("acct_m365")])
    calls = _sweeps(monkeypatch)

    asyncio.run(
        session_autoclean.auto_cleanup_once(app, session_idle_seconds=0, cloud_idle_seconds=3600)
    )

    assert [call["account_id"] for call in calls] == ["acct_m365"]


def test_one_unusable_account_does_not_stop_the_others(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runtime_flags, "ERROR_USER_LOGS", True)
    app = _app(tmp_path, accounts=[_account("acct_broken"), _account("acct_ok")])
    calls = _sweeps(
        monkeypatch,
        {"acct_broken": CloudSessionError("该账户没有存储 refresh token"), "acct_ok": ["conv-old"]},
    )

    _removed, deleted = asyncio.run(
        session_autoclean.auto_cleanup_once(app, session_idle_seconds=0, cloud_idle_seconds=3600)
    )

    assert deleted == ["conv-old"]
    assert [call["account_id"] for call in calls] == ["acct_broken", "acct_ok"]
    logged = capsys.readouterr().out
    assert "acct_broken" in logged and "refresh token" in logged


def test_the_loop_runs_a_pass_and_stops_on_shutdown(tmp_path, monkeypatch):
    app = _app(
        tmp_path,
        auto_cleanup_minutes=0.001,  # 60ms, so the test does not sit on a real interval
        session_idle_hours=2,
        cloud_cleanup_idle_hours=48,
    )
    ran = asyncio.Event()
    seen: list[tuple[float, float]] = []

    async def _fake_pass(_app, *, session_idle_seconds, cloud_idle_seconds):
        seen.append((session_idle_seconds, cloud_idle_seconds))
        ran.set()
        return [], []

    monkeypatch.setattr(session_autoclean, "auto_cleanup_once", _fake_pass)

    async def _drive():
        session_autoclean.start_auto_cleanup(app)
        session_autoclean.start_auto_cleanup(app)  # idempotent
        await asyncio.wait_for(ran.wait(), timeout=5)
        await session_autoclean.stop_auto_cleanup(app)

    asyncio.run(_drive())

    assert seen[0] == (2 * 3600, 48 * 3600)  # hours -> seconds, read off app.state
    assert app.state.auto_cleanup_task is None


def test_a_disabled_interval_never_runs_a_pass(tmp_path, monkeypatch):
    app = _app(tmp_path, auto_cleanup_minutes=0)
    monkeypatch.setattr(session_autoclean, "_DISABLED_POLL_SECONDS", 0.01)
    calls: list[int] = []

    async def _fake_pass(*_args, **_kwargs):
        calls.append(1)
        return [], []

    monkeypatch.setattr(session_autoclean, "auto_cleanup_once", _fake_pass)

    async def _drive():
        session_autoclean.start_auto_cleanup(app)
        await asyncio.sleep(0.1)  # several disabled polls
        await session_autoclean.stop_auto_cleanup(app)

    asyncio.run(_drive())

    assert calls == []


def test_a_failing_pass_leaves_the_loop_alive(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runtime_flags, "ERROR_USER_LOGS", True)
    app = _app(tmp_path, auto_cleanup_minutes=0.001)
    attempts: list[int] = []
    twice = asyncio.Event()

    async def _boom(*_args, **_kwargs):
        attempts.append(1)
        if len(attempts) >= 2:
            twice.set()
        raise RuntimeError("upstream on fire")

    monkeypatch.setattr(session_autoclean, "auto_cleanup_once", _boom)

    async def _drive():
        session_autoclean.start_auto_cleanup(app)
        await asyncio.wait_for(twice.wait(), timeout=5)
        await session_autoclean.stop_auto_cleanup(app)

    asyncio.run(_drive())

    assert len(attempts) >= 2
    assert "upstream on fire" in capsys.readouterr().out


@pytest.mark.parametrize(
    "field, default",
    [("auto_cleanup_minutes", 30), ("session_idle_hours", 0), ("cloud_cleanup_idle_hours", 0)],
)
def test_the_reclaim_settings_default_to_doing_nothing(field, default):
    from m365_copilot_openai_proxy.runtime_settings import _RUNTIME_SETTINGS_DEFAULTS

    # The loop ships enabled but both thresholds ship at 0: an upgrade must not
    # start deleting an account's conversation history on its own.
    assert _RUNTIME_SETTINGS_DEFAULTS[field] == default
