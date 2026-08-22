"""Exact history digest index: which session an auto-detected conversation gets.

The legacy key hashes only the first user message, so an agent framework that
opens every conversation with the same templated message put all of them on one
session: each new conversation reset the session the others were running on, and
their next turn continued inside the wrong upstream thread. These tests pin the
disambiguation and its tenant isolation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.history_index import HistoryDigestIndex, normalize_history
from m365_copilot_openai_proxy.models import (
    AnthropicMessagesRequest,
    OpenAIChatRequest,
)
from m365_copilot_openai_proxy.session_helpers import _persistent_session
from m365_copilot_openai_proxy.session_store import PersistentSessionStore
from m365_copilot_openai_proxy.translator import translate_openai_request


def _app(persist_path: Path | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(
            session_store=PersistentSessionStore(
                persist_path=persist_path,
                flush_interval=0,
            ),
            history_index=HistoryDigestIndex(),
        )
    )


def _raw_request(
    tenant: str = "key_a", account_id: str | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        headers={},
        state=SimpleNamespace(
            api_key_obj=SimpleNamespace(id=tenant),
            account=(
                SimpleNamespace(id=account_id) if account_id is not None else None
            ),
        ),
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


def test_two_same_openers_before_either_continues_do_not_share_a_session():
    app = _app()
    conv_a = _session(app, _chat(("user", "Introduce yourself.")))
    conv_b = _session(app, _chat(("user", "Introduce yourself.")))

    assert conv_b is not conv_a
    assert conv_b.conversation_id != conv_a.conversation_id

    continued_a = _session(
        app,
        _chat(
            ("user", "Introduce yourself."),
            ("assistant", "I am conversation A."),
            ("user", "Compare model capabilities."),
        ),
    )
    continued_b = _session(
        app,
        _chat(
            ("user", "Introduce yourself."),
            ("assistant", "I am conversation B."),
            ("user", "Explain token billing."),
        ),
    )

    assert continued_a is not continued_b
    assert continued_a.turn_count == continued_b.turn_count == 0


@pytest.mark.parametrize("stream", [False, True])
def test_same_opener_routes_continue_their_own_upstream_sessions(tmp_path, stream):
    class RecordingClient:
        def __init__(self):
            self.outputs = [
                "I am conversation A.",
                "I am conversation B.",
                "Capability follow-up.",
                "Billing follow-up.",
            ]
            self.conversation_ids: list[str] = []

        async def chat(self, prompt, additional_context, session=None, images=None):
            return "".join([
                chunk
                async for chunk in self.chat_stream(
                    prompt, additional_context, session, images
                )
            ])

        async def chat_stream(
            self, prompt, additional_context, session=None, images=None
        ):
            assert session is not None
            self.conversation_ids.append(session.conversation_id)
            session.reserve_turn()
            yield self.outputs.pop(0)

    upstream = RecordingClient()
    app = create_app(
        Settings(
            TOKEN_DIR=str(tmp_path),
            API_KEY="admin-key",
            ADMIN_PASSWORD="admin-pass",
            M365_ACCESS_TOKEN="",
        ),
        copilot_client_factory=lambda **_kwargs: upstream,
    )
    account = app.state.account_store.add(
        name="Cherry Session Test",
        token="account-token",
        token_source="manual",
    )
    key = app.state.key_store.add(name="Cherry Key", account_id=account.id)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {key.key}"}

    def send(messages):
        response = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "model": "m365-copilot",
                "stream": stream,
                "messages": [
                    {"role": role, "content": content}
                    for role, content in messages
                ],
            },
        )
        assert response.status_code == 200

    send([("user", "Introduce yourself.")])
    send([("user", "Introduce yourself.")])
    send([
        ("user", "Introduce yourself."),
        ("assistant", "I am conversation A."),
        ("user", "Compare model capabilities."),
    ])
    send([
        ("user", "Introduce yourself."),
        ("assistant", "I am conversation B."),
        ("user", "Explain token billing."),
    ])

    assert upstream.conversation_ids[0] != upstream.conversation_ids[1]
    assert upstream.conversation_ids[2] == upstream.conversation_ids[0]
    assert upstream.conversation_ids[3] == upstream.conversation_ids[1]


@pytest.mark.parametrize("stream", [False, True])
def test_same_anthropic_opener_routes_continue_their_own_upstream_sessions(
    tmp_path, stream
):
    class RecordingClient:
        def __init__(self):
            self.outputs = [
                "I am conversation A.",
                "I am conversation B.",
                "Capability follow-up.",
                "Billing follow-up.",
            ]
            self.conversation_ids: list[str] = []

        async def chat(self, prompt, additional_context, session=None, images=None):
            return "".join([
                chunk
                async for chunk in self.chat_stream(
                    prompt, additional_context, session, images
                )
            ])

        async def chat_stream(
            self, prompt, additional_context, session=None, images=None
        ):
            assert session is not None
            self.conversation_ids.append(session.conversation_id)
            session.reserve_turn()
            yield self.outputs.pop(0)

    upstream = RecordingClient()
    app = create_app(
        Settings(
            TOKEN_DIR=str(tmp_path),
            API_KEY="admin-key",
            ADMIN_PASSWORD="admin-pass",
            M365_ACCESS_TOKEN="",
        ),
        copilot_client_factory=lambda **_kwargs: upstream,
    )
    account = app.state.account_store.add(
        name="Cherry Anthropic Session Test",
        token="account-token",
        token_source="manual",
    )
    key = app.state.key_store.add(name="Cherry Anthropic Key", account_id=account.id)
    client = TestClient(app)
    headers = {
        "x-api-key": key.key,
        "anthropic-version": "2023-06-01",
    }

    def send(messages):
        response = client.post(
            "/v1/messages",
            headers=headers,
            json={
                "model": "m365-copilot",
                "max_tokens": 256,
                "stream": stream,
                "messages": [
                    {"role": role, "content": content}
                    for role, content in messages
                ],
            },
        )
        assert response.status_code == 200

    send([("user", "Introduce yourself.")])
    send([("user", "Introduce yourself.")])
    send([
        ("user", "Introduce yourself."),
        ("assistant", "I am conversation A."),
        ("user", "Compare model capabilities."),
    ])
    send([
        ("user", "Introduce yourself."),
        ("assistant", "I am conversation B."),
        ("user", "Explain token billing."),
    ])

    assert upstream.conversation_ids[0] != upstream.conversation_ids[1]
    assert upstream.conversation_ids[2] == upstream.conversation_ids[0]
    assert upstream.conversation_ids[3] == upstream.conversation_ids[1]


@pytest.mark.parametrize("stream", [False, True])
def test_anthropic_tool_histories_continue_their_own_upstream_sessions(
    tmp_path, stream
):
    tool_replies = [
        (
            "```tool_call\n"
            '{"name":"Read","arguments":{"file_path":"/tmp/a.txt"}}'
            "\n```"
        ),
        (
            "```tool_call\n"
            '{"name":"Read","arguments":{"file_path":"/tmp/b.txt"}}'
            "\n```"
        ),
        "Capability follow-up.",
        "Billing follow-up.",
    ]

    class RecordingClient:
        def __init__(self):
            self.conversation_ids: list[str] = []

        async def chat(self, prompt, additional_context, session=None, images=None):
            return "".join([
                chunk
                async for chunk in self.chat_stream(
                    prompt, additional_context, session, images
                )
            ])

        async def chat_stream(
            self, prompt, additional_context, session=None, images=None
        ):
            assert session is not None
            self.conversation_ids.append(session.conversation_id)
            session.reserve_turn()
            yield tool_replies.pop(0)

    upstream = RecordingClient()
    app = create_app(
        Settings(
            TOKEN_DIR=str(tmp_path),
            API_KEY="admin-key",
            ADMIN_PASSWORD="admin-pass",
            M365_ACCESS_TOKEN="",
        ),
        copilot_client_factory=lambda **_kwargs: upstream,
    )
    account = app.state.account_store.add(
        name="Cherry Anthropic Tool Session Test",
        token="account-token",
        token_source="manual",
    )
    key = app.state.key_store.add(
        name="Cherry Anthropic Tool Key", account_id=account.id
    )
    app.state.key_store.update(key.id, tool_planning_mode="native")
    client = TestClient(app)
    headers = {
        "x-api-key": key.key,
        "anthropic-version": "2023-06-01",
    }
    tool = {
        "name": "Read",
        "description": "Read a file",
        "input_schema": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
    }

    def send(messages):
        response = client.post(
            "/v1/messages",
            headers=headers,
            json={
                "model": "m365-copilot",
                "max_tokens": 256,
                "stream": stream,
                "tools": [tool],
                "messages": messages,
            },
        )
        assert response.status_code == 200
        if not stream:
            return response.json()["content"]

        blocks: dict[int, dict] = {}
        for line in response.text.splitlines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line.removeprefix("data: "))
            index = event.get("index")
            if event.get("type") == "content_block_start":
                block = dict(event["content_block"])
                blocks[index] = block
            elif event.get("type") == "content_block_delta" and index in blocks:
                delta = event["delta"]
                if delta.get("type") == "text_delta":
                    blocks[index]["text"] = (
                        blocks[index].get("text", "") + delta.get("text", "")
                    )
                elif delta.get("type") == "input_json_delta":
                    blocks[index]["input"] = json.loads(delta["partial_json"])
        return [
            block
            for _index, block in sorted(blocks.items())
            if block.get("type") != "text" or block.get("text")
        ]

    opener = [{"role": "user", "content": "Read the selected file."}]
    content_a = send(opener)
    content_b = send(opener)
    tool_a = next(block for block in content_a if block["type"] == "tool_use")
    tool_b = next(block for block in content_b if block["type"] == "tool_use")

    send([
        *opener,
        {"role": "assistant", "content": content_a},
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_a["id"],
                "content": "contents of a.txt",
            }],
        },
    ])
    send([
        *opener,
        {"role": "assistant", "content": content_b},
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_b["id"],
                "content": "contents of b.txt",
            }],
        },
    ])

    assert upstream.conversation_ids[0] != upstream.conversation_ids[1]
    assert upstream.conversation_ids[2] == upstream.conversation_ids[0]
    assert upstream.conversation_ids[3] == upstream.conversation_ids[1]


def test_restart_does_not_merge_same_opener_continuations(tmp_path):
    persist_path = tmp_path / "sessions.json"
    app = _app(persist_path)

    conv_a = _session(app, _chat(("user", "Introduce yourself.")))
    conv_a.reserve_turn()
    conv_a = _session(
        app,
        _chat(
            ("user", "Introduce yourself."),
            ("assistant", "I am conversation A."),
            ("user", "Compare your model capabilities."),
        ),
    )
    conv_a.reserve_turn()

    conv_b = _session(app, _chat(("user", "Introduce yourself.")))
    conv_b.reserve_turn()
    conv_b = _session(
        app,
        _chat(
            ("user", "Introduce yourself."),
            ("assistant", "I am conversation B."),
            ("user", "Explain token billing."),
        ),
    )
    conv_b.reserve_turn()

    assert conv_a.conversation_id != conv_b.conversation_id

    restarted = _app(persist_path)
    resumed_a = _session(
        restarted,
        _chat(
            ("user", "Introduce yourself."),
            ("assistant", "I am conversation A."),
            ("user", "Compare your model capabilities."),
            ("assistant", "Capability answer."),
            ("user", "Continue that comparison."),
        ),
    )
    resumed_b = _session(
        restarted,
        _chat(
            ("user", "Introduce yourself."),
            ("assistant", "I am conversation B."),
            ("user", "Explain token billing."),
            ("assistant", "Billing answer."),
            ("user", "Continue the billing explanation."),
        ),
    )

    assert resumed_a is not resumed_b
    assert resumed_a.conversation_id != resumed_b.conversation_id
    assert resumed_a.turn_count == resumed_b.turn_count == 0
    resumed_a_view = translate_openai_request(
        _chat(
            ("user", "Introduce yourself."),
            ("assistant", "I am conversation A."),
            ("user", "Compare your model capabilities."),
            ("assistant", "Capability answer."),
            ("user", "Continue that comparison."),
        ),
        incremental=resumed_a.turn_count > 0,
    )
    assert "I am conversation A." in "\n".join(resumed_a_view.additional_context)


def test_anthropic_tool_blocks_keep_the_same_session_on_continuation():
    app = _app()
    first = _session(
        app,
        AnthropicMessagesRequest(
            model="m365-copilot",
            messages=[{"role": "user", "content": "read /tmp/a.txt"}],
        ),
    )
    first.reserve_turn()
    continued = _session(
        app,
        AnthropicMessagesRequest(
            model="m365-copilot",
            messages=[
                {"role": "user", "content": "read /tmp/a.txt"},
                {
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Read",
                        "input": {"file_path": "/tmp/a.txt"},
                    }],
                },
                {
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "contents of /tmp/a.txt",
                    }],
                },
            ],
        ),
    )

    assert continued is first


def test_openai_tool_messages_keep_the_same_session_on_continuation():
    app = _app()
    first = _session(app, _chat(("user", "read /tmp/a.txt")))
    first.reserve_turn()
    continued = _session(
        app,
        OpenAIChatRequest(
            model="m365-copilot",
            messages=[
                {"role": "user", "content": "read /tmp/a.txt"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "Read",
                            "arguments": '{"file_path":"/tmp/a.txt"}',
                        },
                    }],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "content": "contents of /tmp/a.txt",
                },
            ],
        ),
    )

    assert continued is first


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


def test_same_key_rebound_to_another_account_gets_a_distinct_session():
    app = _app()
    request = _chat(("user", "shared opening"))
    first_request = _raw_request("key_a", "account_a")
    first_request.headers["x-m365-session-id"] = "same-conversation"
    rebound_request = _raw_request("key_a", "account_b")
    rebound_request.headers["x-m365-session-id"] = "same-conversation"

    first = _persistent_session(
        app,
        first_request,
        "gpt-4o",
        request=request,
    )
    rebound = _persistent_session(
        app,
        rebound_request,
        "gpt-4o",
        request=request,
    )

    assert rebound is not first
    keys = [key for key, _session in app.state.session_store.items()]
    assert any(key.startswith("key_a:account_a:") for key in keys)
    assert any(key.startswith("key_a:account_b:") for key in keys)


def test_resending_an_unnamed_first_turn_gets_isolated_keys():
    """Identical unnamed openers cannot be classified as retries safely."""
    app = _app()
    first = _session(app, _chat(("user", "hi")))
    second = _session(app, _chat(("user", "hi")))

    assert second is not first
    assert len(app.state.session_store.items()) == 2


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


def test_match_rejects_a_shared_prefix_owned_by_multiple_sessions():
    index = HistoryDigestIndex()
    opener = normalize_history(_chat(("user", "same opener")).messages)
    shared_history = opener + [("assistant", "same answer")]
    continuation = shared_history + [("user", "next")]

    index.record("t", shared_history, "session-a")
    index.record("t", shared_history, "session-b")

    assert index.match("t", continuation) is None


def test_shared_prefix_owner_tracking_stays_bounded_after_ambiguity():
    index = HistoryDigestIndex()
    shared_history = normalize_history(_chat(("user", "same opener")).messages)

    for number in range(100):
        index.record("t", shared_history, f"session-{number}")

    owners = next(iter(index._entries.values()))
    assert len(owners) == 2
    assert index.match("t", shared_history + [("user", "next")]) is None


def test_normalize_history_drops_system_messages_and_collapses_whitespace():
    pairs = normalize_history(
        _chat(("system", "now is 12:00"), ("user", "hello   \n world"), ("assistant", "")).messages
    )

    assert pairs == [("user", "hello world")]


def test_stats_counts_lookups_so_the_admin_page_can_show_the_hit_rate():
    """A miss means a continuation must start a fresh upstream session."""
    index = HistoryDigestIndex(max_entries=9)
    turn1 = normalize_history(_chat(("user", "a")).messages)
    turn2 = normalize_history(_chat(("user", "a"), ("assistant", "b"), ("user", "c")).messages)

    assert index.stats() == {
        "entries": 0,
        "max_entries": 9,
        "hits": 0,
        "misses": 0,
        "hit_rate": None,
    }

    index.record("t", turn1, "session-1")
    index.match("t", turn2)  # hit: turn1 is a strict prefix
    index.match("t", turn1)  # miss: first turn of a conversation
    index.match("other", turn2)  # miss: another tenant cannot match into ours

    stats = index.stats()
    assert (stats["entries"], stats["hits"], stats["misses"]) == (1, 1, 2)
    assert stats["hit_rate"] == round(1 / 3, 4)
