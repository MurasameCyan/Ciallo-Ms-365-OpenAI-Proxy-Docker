"""Chat-frame fields taken from live M365 web traffic (see
docs/protocol-options-diff.md, 2026-08-18 round).

These are wire details nothing else asserts: a flag whose spelling drifts is
silently ignored upstream, and a timeZoneOffset that disagrees with the zone name
beside it just makes the model reason about the wrong local clock. Both fail
quietly in production, so they are pinned here.
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from m365_copilot_openai_proxy.substrate_client import (
    _OPTIONS_SETS,
    _VARIANTS,
    SubstrateCopilotClient,
)


def _argument(time_zone: str = "Asia/Shanghai") -> dict:
    client = object.__new__(SubstrateCopilotClient)
    client._tone = "Magic"
    client._extra_tool_prompt = ""
    client._time_zone = time_zone
    frame = client._chat_invoke("ping", "conversation-id", "session-id", "request-id", True)
    return json.loads(frame.rstrip("\x1e"))["arguments"][0]


@pytest.mark.parametrize("time_zone", ["Asia/Shanghai", "America/New_York", "UTC", "Europe/Berlin"])
def test_the_offset_we_send_matches_the_zone_we_name(time_zone):
    location = _argument(time_zone)["message"]["locationInfo"]

    # Derived, not hardcoded, so this stays right across DST.
    expected = int(datetime.now(ZoneInfo(time_zone)).utcoffset().total_seconds() // 3600)
    assert location == {"timeZoneOffset": expected, "timeZone": time_zone}


def test_an_unusable_zone_falls_back_to_the_default_offset():
    location = _argument("Not/AZone")["message"]["locationInfo"]

    assert location["timeZoneOffset"] == 8  # the default zone's offset


def test_the_frame_declares_the_office_thread_type():
    assert _argument()["productThreadType"] == "Office"


def test_the_inline_chart_flag_uses_the_spelling_the_browser_sends():
    assert "code_interpreter_interactive_charts_inline_image" in _OPTIONS_SETS
    # The cwc_-prefixed spelling matched no upstream flag, i.e. it did nothing.
    assert "cwc_code_interpreter_interactive_charts_inline_image" not in _OPTIONS_SETS


def test_the_work_tab_upsell_is_turned_off():
    assert "turnOffWorkTabUpsellFromClient" in _VARIANTS.split(",")
