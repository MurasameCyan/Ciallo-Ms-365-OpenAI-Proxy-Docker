"""Regressions for three defects found while testing a live deployment.

1. /healthz reported "Cannot decode access token: list index out of range" on a
   multi-account deployment, where the global token is legitimately unset.
2. A turn M365 refused was surfaced as 502, indistinguishable from a dead
   gateway, so clients retried a refusal no retry can fix.
3. The tool-call format instruction named only file operations, leaving every
   non-file tool with no instruction at all.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from m365_copilot_openai_proxy.consumer_client import AccountThrottled
from m365_copilot_openai_proxy.routes_api_common import upstream_http_error
from m365_copilot_openai_proxy.substrate_client import (
    _EMPTY_TURN_MARKER,
    _REFUSED_TURN_MARKER,
    SubstrateCopilotError,
)
from m365_copilot_openai_proxy.substrate_parse import _combine_text
from m365_copilot_openai_proxy.token_store import AccessTokenStore, decode_jwt_payload, init_token_dir


# --------------------------------------------------------------- token status
@pytest.mark.parametrize("bad", ["", "   ", "not-a-jwt", "onlyone", "a..c"])
def test_decode_jwt_payload_rejects_non_jwt_with_a_clear_message(bad):
    """The bare split raised IndexError, whose str() is "list index out of range"
    -- an error message that names nothing the operator can act on."""
    with pytest.raises(ValueError, match="not a JWT"):
        decode_jwt_payload(bad)


@pytest.fixture
def token_store(tmp_path):
    """init_token_dir is what app startup calls; without it the module-level
    token path is unset and AccessTokenStore cannot stat it."""
    init_token_dir(str(tmp_path))

    def _make(raw):
        return AccessTokenStore(raw, env_path=tmp_path / ".env")

    return _make


def test_status_reports_no_token_rather_than_a_decode_failure(token_store):
    status = token_store("").status()
    assert status["valid"] is False
    assert status["error"] == "No token"
    assert "index out of range" not in status["error"]


def test_status_still_explains_a_genuinely_malformed_token(token_store):
    """An unset token is normal; a garbage one is not, and must stay visible."""
    status = token_store("garbage-token").status()
    assert status["valid"] is False
    assert "Cannot decode access token" in status["error"]


# ------------------------------------------------------------- error mapping
def test_refused_turn_maps_to_400_not_502():
    exc = SubstrateCopilotError(
        f"M365 Copilot {_REFUSED_TURN_MARKER} instead of answering (conversation mode 'Magic')."
    )
    assert upstream_http_error(exc).status_code == 400


def test_empty_turn_maps_to_400_not_502():
    exc = SubstrateCopilotError(f"M365 Copilot returned an {_EMPTY_TURN_MARKER} (conversation mode 'Magic').")
    assert upstream_http_error(exc).status_code == 400


@pytest.mark.parametrize(
    "detail",
    [
        "Upstream stopped sending data (idle timeout).",
        "Access token is not a substrate.office.com token.",
        "Cannot decode access token: not a JWT",
    ],
)
def test_transport_and_credential_failures_stay_502(detail):
    """Only upstream declining the request is a 4xx; a broken pipe is still ours."""
    assert upstream_http_error(SubstrateCopilotError(detail)).status_code == 502


def test_detail_is_preserved_either_way():
    exc = SubstrateCopilotError(f"M365 Copilot {_REFUSED_TURN_MARKER} instead of answering")
    assert upstream_http_error(exc).detail == str(exc)


def test_account_throttle_maps_to_429_and_retry_after():
    exc = AccountThrottled(
        "This Copilot account spent its message quota.",
        "2026-08-13T15:17:13+00:00",
    )
    response = upstream_http_error(
        exc,
        now=datetime(2026, 8, 13, 15, 17, 3, tzinfo=timezone.utc),
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "10"
    assert response.detail == str(exc)


# ------------------------------------------------------------ format wording
def _tools_context():
    return ["System instructions:\nUse ```tool_call``` blocks.\n\nAvailable action types:\n- get_weather: ..."]


def test_format_block_covers_every_tool_not_just_file_actions():
    """The old wording said "for any file action", so a get_weather tool was
    never actually instructed and got answered from the model's own abilities."""
    combined = _combine_text("What is the weather in Tokyo?", _tools_context())
    assert "any tool listed above" in combined
    assert "for any file action" not in combined


def test_format_block_forbids_the_two_observed_substitutions():
    """Live, M365 answered a Write by generating a hosted attachment, and refused
    other tools as "not available in this conversation"."""
    combined = _combine_text("Write hello.txt", _tools_context())
    assert "Ignore any other tools" in combined
    assert "attach a file" in combined
    assert "Never claim a listed tool is unavailable" in combined


def test_no_format_block_without_tools():
    combined = _combine_text("Just chat", ["System instructions:\nBe brief."])
    assert "[FORMAT]" not in combined
