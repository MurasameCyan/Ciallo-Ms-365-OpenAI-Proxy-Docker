from __future__ import annotations

import time

from m365_copilot_openai_proxy import runtime_flags
from m365_copilot_openai_proxy.session_store import PersistentSessionStore

# Sessions only leave the store three ways: an explicit delete, a prune rule, or
# LRU overflow. None of them used to leave a trace, so a session that vanished
# was indistinguishable from a bug -- production hit exactly that (18 rows gone,
# nothing in the log to attribute them to). Every path now says who went and why.


def _store(tmp_path, **kwargs) -> PersistentSessionStore:
    return PersistentSessionStore(persist_path=tmp_path / "sessions.json", **kwargs)


def test_prune_logs_scope_rule_count_and_keys(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(runtime_flags, "ERROR_USER_LOGS", True)
    store = _store(tmp_path)
    store.get("k1:auto:fresh")
    store.get("k1:auto:alsofresh")
    store.get("k1:auto:stale").last_accessed = time.time() - 7200
    capsys.readouterr()

    assert store.prune(prefix="k1:", older_than=3600) == ["k1:auto:stale"]

    out = capsys.readouterr().out
    assert "k1:auto:stale" in out, f"prune did not name the dropped key: {out!r}"
    assert "1/3" in out, f"prune did not log how many of how many: {out!r}"
    assert "k1:" in out and "idle>3600s" in out, f"prune did not log scope + rule: {out!r}"


def test_remove_logs_the_dropped_key(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(runtime_flags, "ERROR_USER_LOGS", True)
    store = _store(tmp_path)
    store.get("k1:auto:gone")
    capsys.readouterr()

    assert store.remove("k1:auto:gone") is True
    assert "k1:auto:gone" in capsys.readouterr().out

    # A no-op delete stays silent: it removed nothing.
    assert store.remove("k1:auto:gone") is False
    assert capsys.readouterr().out == ""


def test_lru_eviction_is_logged(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(runtime_flags, "ERROR_USER_LOGS", True)
    store = _store(tmp_path, max_sessions=1)
    store.get("k1:auto:first")
    capsys.readouterr()

    store.get("k1:auto:second")

    out = capsys.readouterr().out
    assert "k1:auto:first" in out and "LRU" in out, f"silent LRU eviction: {out!r}"
    assert store.get_existing("k1:auto:first") is None
