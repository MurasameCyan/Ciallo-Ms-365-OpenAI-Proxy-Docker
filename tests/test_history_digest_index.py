"""Exact history digest index: which session an auto-detected conversation gets.

The legacy key hashes only the first user message, so an agent framework that
opens every conversation with the same templated message put all of them on one
session: each new conversation reset the session the others were running on, and
their next turn continued inside the wrong upstream thread. These tests pin the
disambiguation and its tenant isolation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.history_index import HistoryDigestIndex, normalize_history
from m365_copilot_openai_proxy.models import OpenAIChatRequest
from m365_copilot_openai_proxy.session_helpers import _persistent_session
from m365_copilot_openai_proxy.session_store import PersistentSessionStore


def _app() -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(
            session_store=PersistentSessionStore(),
            history_index=HistoryDigestIndex(),
        )
    )


def _raw_request(tenant: str = "key_a") -> SimpleNamespace:
    return SimpleNamespace(
        headers={},
        state=SimpleNamespace(api_key_obj=SimpleNamespace(id=tenant), account=None),
    )


def _chat(*messages: tuple[str, str]) -> OpenAIChatRequest:
    return OpenAIChatRequest(
        model="gpt-4o",
        messages=[{"role": role, "content": content} for role, content in messages],
    )


def _session(app, request, tenant="key_a"):
    return _persistent_session(app, _raw_request(tenant), "gpt-4o", request=request)


def test_continuation_lands_on_the_same_session():
    app = _app()
    first = _session(app, _chat(("user", "hello")))
    second = _session(app, _chat(("user", "hello"), ("assistant", "hi"), ("user", "more")))

    assert second is first


def test_second_conversation_with_the_same_opening_gets_its_own_session():
    app = _app()
    conv_a = _session(app, _chat(("user", "Analyze this repo.")))
    _session(app, _chat(("user", "Analyze this repo."), ("assistant", "a1"), ("user", "a2")))

    conv_b = _session(app, _chat(("user", "Analyze this repo.")))

    assert conv_b is not conv_a
    assert conv_b.conversation_id != conv_a.conversation_id
    # A's next turn must still continue A, not the conversation that just started.
    continued = _session(
        app,
        _chat(
            ("user", "Analyze this repo."),
            ("assistant", "a1"),
            ("user", "a2"),
            ("assistant", "a3"),
            ("user", "a4"),
        ),
    )
    assert continued is conv_a


def test_history_never_matches_across_tenants():
    app = _app()
    mine = _session(app, _chat(("user", "shared opening")))
    _session(app, _chat(("user", "shared opening"), ("assistant", "x"), ("user", "y")))

    theirs = _session(
        app,
        _chat(("user", "shared opening"), ("assistant", "x"), ("user", "y")),
        tenant="key_b",
    )

    assert theirs is not mine


def test_resending_the_same_first_turn_keeps_the_same_key():
    """A retried opening turn is the same conversation restarting, so it must not
    leak a new store key on every retry."""
    app = _app()
    _session(app, _chat(("user", "hi")))
    _session(app, _chat(("user", "hi")))

    assert len(app.state.session_store.items()) == 1


def test_match_ignores_the_full_history_and_finds_the_longest_prefix():
    index = HistoryDigestIndex()
    turn1 = normalize_history(_chat(("user", "a")).messages)
    turn2 = normalize_history(_chat(("user", "a"), ("assistant", "b"), ("user", "c")).messages)
    index.record("t", turn1, "session-1")
    index.record("t", turn2, "session-1")

    # Strict prefix only: the digest a turn just recorded is not a match for
    # itself, or a resend would look like a continuation.
    assert index.match("t", turn1) is None
    assert index.match("t", turn2) == "session-1"
    assert index.match("t", turn2 + [("assistant", "d"), ("user", "e")]) == "session-1"


def test_normalize_history_drops_system_messages_and_collapses_whitespace():
    pairs = normalize_history(
        _chat(("system", "now is 12:00"), ("user", "hello   \n world"), ("assistant", "")).messages
    )

    assert pairs == [("user", "hello world")]
