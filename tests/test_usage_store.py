from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.call_log_store import record_response_text
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotError

from m365_copilot_openai_proxy.usage_store import (
    UsageStore,
    anthropic_usage,
    estimate_text_tokens,
    estimate_upstream_input_tokens,
    openai_usage,
    responses_usage,
    usage_for_record,
)


def test_estimate_text_tokens_is_empty_safe_and_utf8_aware():
    assert estimate_text_tokens("") == 0
    assert estimate_text_tokens("abcd") == 1
    assert estimate_text_tokens("你好") == 2


def test_estimate_upstream_input_tokens_counts_prompt_and_context_once():
    assert estimate_upstream_input_tokens("abcd", ["efgh", ""]) == 2


def test_usage_store_records_one_completed_call_and_persists(tmp_path):
    path = tmp_path / "usage_stats.json"
    store = UsageStore(path)

    usage = store.record("gpt-5.6", input_tokens=12, output_tokens=5)

    assert usage == {
        "input_tokens": 12,
        "output_tokens": 5,
        "total_tokens": 17,
        "estimated": True,
    }
    assert UsageStore(path).summary() == {
        "calls_total": 1,
        "input_tokens": 12,
        "output_tokens": 5,
        "total_tokens": 17,
        "estimated": True,
        "model_counts": {"gpt-5.6": 1},
    }
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["models"]["gpt-5.6"]["total_tokens"] == 17


def test_usage_store_normalizes_missing_model_and_can_clear(tmp_path):
    store = UsageStore(tmp_path / "usage_stats.json")
    store.record("", input_tokens=1, output_tokens=2)

    assert store.summary()["model_counts"] == {"unknown": 1}

    store.clear()

    assert store.summary()["calls_total"] == 0
    assert store.summary()["total_tokens"] == 0
    assert store.summary()["model_counts"] == {}


def test_usage_store_recovers_from_non_utf8_corrupt_file(tmp_path):
    path = tmp_path / "usage_stats.json"
    path.write_bytes(b"\xff\xfe\x00")

    assert UsageStore(path).summary()["calls_total"] == 0


def test_usage_write_failure_does_not_break_a_completed_api_response(tmp_path, monkeypatch):
    class FakeClient:
        _tone = "Magic"

        async def chat(self, prompt, context=None, session=None, images=None):
            return "abcdefgh"

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **kwargs: FakeClient(),
    )

    def fail_save():
        raise PermissionError("read-only usage file")

    monkeypatch.setattr(app.state.usage_store, "_save", fail_save)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/v1/chat/completions",
        json={"model": "gpt-5.6", "messages": [{"role": "user", "content": "abcd"}]},
        headers={"Authorization": "Bearer k"},
    )

    assert response.status_code == 200
    assert response.json()["usage"]["total_tokens"] == 3
    assert app.state.usage_store.summary()["calls_total"] == 1


def test_usage_store_normalizes_and_bounds_model_buckets(tmp_path):
    store = UsageStore(tmp_path / "usage_stats.json")

    store.record("  GPT   5.6\n", input_tokens=1)
    for index in range(100):
        store.record(f"untrusted-model-{index}-" + ("x" * 200), input_tokens=1)

    summary = store.summary()
    assert summary["calls_total"] == 101
    assert sum(summary["model_counts"].values()) == 101
    assert summary["model_counts"]["GPT 5.6"] == 1
    assert len(summary["model_counts"]) <= 25
    assert max(map(len, summary["model_counts"])) <= 80
    assert summary["model_counts"]["other"] > 0


def test_usage_store_compacts_legacy_high_cardinality_file_on_load(tmp_path):
    path = tmp_path / "usage_stats.json"
    models = {
        f" legacy   model {index} ": {
            "calls": 1,
            "input_tokens": 1,
            "output_tokens": 0,
        }
        for index in range(100)
    }
    path.write_text(
        json.dumps(
            {
                "calls_total": 100,
                "input_tokens": 100,
                "output_tokens": 0,
                "total_tokens": 100,
                "models": models,
            }
        ),
        encoding="utf-8",
    )

    summary = UsageStore(path).summary()

    assert summary["calls_total"] == 100
    assert sum(summary["model_counts"].values()) == 100
    assert len(summary["model_counts"]) <= 25
    assert summary["model_counts"]["other"] > 0


def test_usage_write_failure_does_not_break_completed_call(monkeypatch, tmp_path):
    store = UsageStore(tmp_path / "usage_stats.json")
    monkeypatch.setattr(store, "_save", lambda: (_ for _ in ()).throw(OSError("full")))

    usage = store.record("gpt-5.6", input_tokens=3, output_tokens=2)

    assert usage["total_tokens"] == 5
    assert store.summary()["calls_total"] == 1


def test_call_record_finalizes_usage_only_once(tmp_path):
    store = UsageStore(tmp_path / "usage_stats.json")
    state = SimpleNamespace(usage_store=store)
    record = {
        "model": "gpt-5.6",
        "usage_input_tokens": 10,
        "response_text": "abcdefgh",
    }

    first = store.finalize_record(record)
    second = store.finalize_record(record)

    assert first == {
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
        "estimated": True,
    }
    assert second == first
    assert record["usage"] == first
    assert record["usage_recorded"] is True
    assert state.usage_store.summary()["calls_total"] == 1


def test_protocol_usage_shapes_share_the_same_estimated_counts():
    usage = {"input_tokens": 8, "output_tokens": 3, "total_tokens": 11, "estimated": True}

    assert openai_usage(usage) == {
        "prompt_tokens": 8,
        "completion_tokens": 3,
        "total_tokens": 11,
        "estimated": True,
    }
    assert anthropic_usage(usage) == {"input_tokens": 8, "output_tokens": 3, "estimated": True}
    assert responses_usage(usage) == {
        "input_tokens": 8,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": 3,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 11,
        "estimated": True,
    }


def test_response_helpers_accept_record_usage_without_recomputing():
    from m365_copilot_openai_proxy.response_helpers import _responses_usage

    usage = {"input_tokens": 9, "output_tokens": 4, "total_tokens": 13, "estimated": True}

    assert _responses_usage(usage) == {
        "input_tokens": 9,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": 4,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 13,
        "estimated": True,
    }


def test_usage_for_record_exposes_input_before_stream_finishes():
    assert usage_for_record({"usage_input_tokens": 9}) == {
        "input_tokens": 9,
        "output_tokens": 0,
        "total_tokens": 9,
        "estimated": True,
    }


def test_chat_response_usage_and_site_total_share_one_record(tmp_path):
    class FakeClient:
        _tone = "Magic"

        async def chat(self, prompt, context=None, session=None, images=None):
            return "abcdefgh"

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **kwargs: FakeClient(),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.6", "messages": [{"role": "user", "content": "abcd"}]},
        headers={"Authorization": "Bearer k"},
    )

    assert response.status_code == 200
    usage = response.json()["usage"]
    assert usage["prompt_tokens"] >= 1
    assert usage["completion_tokens"] == 2
    assert usage["total_tokens"] == usage["prompt_tokens"] + 2
    assert usage["estimated"] is True
    assert app.state.usage_store.summary()["total_tokens"] == usage["total_tokens"]
    assert app.state.usage_store.summary()["model_counts"] == {"gpt-5.6": 1}


def test_response_estimate_uses_full_text_before_call_log_truncation(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    record = {"model": "gpt-5.6", "usage_input_tokens": 1}
    full_text = "a" * 12_000

    record_response_text(app.state, record, full_text)

    assert len(record["response_text"]) == 8_000
    assert record["usage"]["output_tokens"] == 3_000


def test_messages_and_responses_return_and_accumulate_estimated_usage(tmp_path):
    class FakeClient:
        _tone = "Magic"

        async def chat(self, prompt, context=None, session=None, images=None):
            return "abcdefgh"

        async def chat_stream(self, prompt, context=None, session=None, images=None):
            yield "abcdefgh"

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **kwargs: FakeClient(),
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer k"}

    messages = client.post(
        "/v1/messages",
        json={"model": "gpt-5.6", "max_tokens": 32, "messages": [{"role": "user", "content": "abcd"}]},
        headers=headers,
    )
    responses = client.post(
        "/v1/responses",
        json={"model": "gpt-5.6", "input": "abcd"},
        headers=headers,
    )

    assert messages.status_code == 200
    assert messages.json()["usage"]["input_tokens"] >= 1
    assert messages.json()["usage"]["output_tokens"] == 2
    assert messages.json()["usage"]["estimated"] is True
    assert responses.status_code == 200
    assert responses.json()["usage"]["input_tokens"] >= 1
    assert responses.json()["usage"]["output_tokens"] == 2
    assert responses.json()["usage"]["estimated"] is True
    summary = app.state.usage_store.summary()
    assert summary["calls_total"] == 2
    assert summary["total_tokens"] == (
        messages.json()["usage"]["input_tokens"]
        + messages.json()["usage"]["output_tokens"]
        + responses.json()["usage"]["total_tokens"]
    )


def test_streaming_messages_and_responses_emit_final_estimated_usage(tmp_path):
    class FakeClient:
        _tone = "Magic"

        async def chat_stream(self, prompt, context=None, session=None, images=None):
            yield "abcdefgh"

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **kwargs: FakeClient(),
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer k"}

    messages = client.post(
        "/v1/messages",
        json={"model": "gpt-5.6", "stream": True, "max_tokens": 32, "messages": [{"role": "user", "content": "abcd"}]},
        headers=headers,
    )
    responses = client.post(
        "/v1/responses",
        json={"model": "gpt-5.6", "stream": True, "input": "abcd"},
        headers=headers,
    )

    assert messages.status_code == 200
    assert '"input_tokens": 1' in messages.text
    assert '"output_tokens": 2' in messages.text
    assert responses.status_code == 200
    assert '"input_tokens": 1' in responses.text
    assert '"output_tokens": 2' in responses.text
    assert app.state.usage_store.summary()["calls_total"] == 2


def test_streaming_chat_emits_final_estimated_usage(tmp_path):
    class FakeClient:
        _tone = "Magic"

        async def chat_stream(self, prompt, context=None, session=None, images=None):
            yield "abcdefgh"

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **kwargs: FakeClient(),
    )
    response = TestClient(app).post(
        "/v1/chat/completions",
        json={"model": "gpt-5.6", "stream": True, "messages": [{"role": "user", "content": "abcd"}]},
        headers={"Authorization": "Bearer k"},
    )

    assert response.status_code == 200
    assert '"prompt_tokens": 1' in response.text
    assert '"completion_tokens": 2' in response.text
    assert app.state.usage_store.summary()["calls_total"] == 1


def test_nonstream_upstream_failures_count_input_once_across_all_protocols(tmp_path):
    class FailingClient:
        _tone = "Magic"

        async def chat(self, prompt, context=None, session=None, images=None):
            raise SubstrateCopilotError("upstream broke")

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **kwargs: FailingClient(),
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer k"}

    chat = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.6", "messages": [{"role": "user", "content": "abcd"}]},
        headers=headers,
    )
    messages = client.post(
        "/v1/messages",
        json={"model": "gpt-5.6", "max_tokens": 32, "messages": [{"role": "user", "content": "abcd"}]},
        headers=headers,
    )
    responses = client.post(
        "/v1/responses",
        json={"model": "gpt-5.6", "input": "abcd"},
        headers=headers,
    )

    assert [chat.status_code, messages.status_code, responses.status_code] == [502, 502, 502]
    summary = app.state.usage_store.summary()
    assert summary["calls_total"] == 3
    assert summary["input_tokens"] >= 3
    assert summary["output_tokens"] == 0
    assert summary["model_counts"] == {"gpt-5.6": 3}
    assert [entry["error"] for entry in app.state.call_log[-3:]] == [
        "upstream broke",
        "upstream broke",
        "upstream broke",
    ]
