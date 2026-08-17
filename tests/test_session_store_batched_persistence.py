"""Session persistence must coalesce writes without losing turns.

One change rewrites the entire session map, and every turn of every conversation
is one change, so a busy pool used to rewrite up to 1000 sessions' worth of JSON
per turn. These tests pin the trade: bursts collapse into one write, but nothing
is dropped -- a flush (explicit, timed, or at exit) always lands, and a failed
write stays pending instead of silently discarding everything since the last one.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.session_store import PersistentSessionStore


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_default_is_write_through(tmp_path):
    """No interval configured means the historical behaviour, byte for byte."""
    path = tmp_path / "sessions.json"
    store = PersistentSessionStore(persist_path=path)

    session = store.get("t:model:magic")
    session.reserve_turn()

    assert path.exists()
    assert store.stats()["writes"] >= 2  # creation + turn, each on its own
    assert store.stats()["pending"] is False
    # The turn is on disk right away, which is what the existing Responses-state
    # test relies on when it reopens the same path.
    reopened = PersistentSessionStore(persist_path=path)
    assert reopened.get("t:model:magic").turn_count == 1


def test_a_burst_of_turns_costs_one_write(tmp_path):
    path = tmp_path / "sessions.json"
    store = PersistentSessionStore(persist_path=path, flush_interval=30.0)

    session = store.get("t:model:magic")
    for _ in range(20):
        session.reserve_turn()

    pending = store.stats()
    assert pending["writes"] == 0 and pending["pending"] is True
    assert pending["changes"] == 21  # 1 creation + 20 turns
    assert not path.exists()

    store.flush()

    after = store.stats()
    assert after["writes"] == 1
    assert after["coalesced"] == 20
    assert after["pending"] is False
    assert PersistentSessionStore(persist_path=path).get("t:model:magic").turn_count == 20


def test_the_timer_writes_without_being_asked(tmp_path):
    """Nobody calls flush() on a live server, so the window must fire by itself."""
    path = tmp_path / "sessions.json"
    store = PersistentSessionStore(persist_path=path, flush_interval=0.05)

    store.get("t:model:magic").reserve_turn()

    assert _wait_for(lambda: store.stats()["writes"] >= 1)
    assert PersistentSessionStore(persist_path=path).get("t:model:magic").turn_count == 1
    # And the window re-arms: a later change is not stranded by the first flush.
    store.get("t:model:magic").reserve_turn()
    assert _wait_for(lambda: store.stats()["writes"] >= 2)


def test_flush_is_a_no_op_when_nothing_changed(tmp_path):
    store = PersistentSessionStore(persist_path=tmp_path / "sessions.json", flush_interval=30.0)
    store.get("t:model:magic")
    store.flush()

    writes = store.stats()["writes"]
    store.flush()
    store.flush()

    assert store.stats()["writes"] == writes


def test_a_failed_write_stays_pending(tmp_path):
    """A full/read-only disk must not swallow every turn since the last write."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    store = PersistentSessionStore(persist_path=blocker / "sessions.json", flush_interval=30.0)

    store.get("t:model:magic").reserve_turn()
    store.flush()

    assert store.stats()["writes"] == 0
    assert store.stats()["pending"] is True  # retried on the next change or flush


def test_removals_and_prunes_are_persisted_too(tmp_path):
    """Coalescing must not turn a delete into a write that never happens."""
    path = tmp_path / "sessions.json"
    store = PersistentSessionStore(persist_path=path, flush_interval=30.0)
    store.get("t:model:keep")
    store.get("t:model:drop")
    store.flush()

    assert store.remove("t:model:drop") is True
    store.flush()

    reopened = PersistentSessionStore(persist_path=path)
    assert [key for key, _ in reopened.items()] == ["t:model:keep"]


def test_stats_reports_the_configured_window(tmp_path):
    store = PersistentSessionStore(
        max_sessions=7, persist_path=tmp_path / "sessions.json", flush_interval=2.0
    )
    store.get("t:model:magic")

    stats = store.stats()
    assert stats["flush_interval"] == 2.0
    assert stats["max_sessions"] == 7
    assert stats["sessions"] == 1


def test_a_store_without_a_path_never_writes(tmp_path):
    store = PersistentSessionStore(flush_interval=30.0)

    store.get("t:model:magic").reserve_turn()
    store.flush()

    assert list(tmp_path.iterdir()) == []
    assert store.stats()["changes"] == 0


def test_app_shutdown_flushes_before_the_window_would_have_fired(tmp_path):
    """A container restart is a graceful stop; it must not resume a turn behind."""
    from fastapi.testclient import TestClient

    from m365_copilot_openai_proxy.app import create_app
    from m365_copilot_openai_proxy.config import Settings

    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    interval = app.state.session_store.stats()["flush_interval"]
    assert interval > 0, "production coalesces writes; otherwise this test proves nothing"

    with TestClient(app):
        app.state.session_store.get("t:model:magic").reserve_turn()
        started = time.monotonic()

    elapsed = time.monotonic() - started
    assert elapsed < interval  # the shutdown hook wrote it, not the timer
    assert PersistentSessionStore(persist_path=tmp_path / "sessions.json").get(
        "t:model:magic"
    ).turn_count == 1
