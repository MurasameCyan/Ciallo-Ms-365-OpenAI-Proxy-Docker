from __future__ import annotations

import importlib.util
from pathlib import Path


_PATH = Path(__file__).parents[1] / ".probe" / "studio_ab" / "studio_direct_diagnose.py"
_SPEC = importlib.util.spec_from_file_location("studio_direct_diagnose", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_classify_upstream_error_uses_closed_categories_without_detail():
    assert _MODULE.classify_error("M365 Copilot refused this turn (agent=secret)") == "refused"
    assert _MODULE.classify_error("M365 Copilot returned an empty response twice") == "empty"
    assert _MODULE.classify_error("Upstream stopped sending data (idle timeout)") == "timeout"
    assert _MODULE.classify_error("Access token is not a substrate.office.com token") == "auth"
    assert _MODULE.classify_error("arbitrary private response body") == "other"


def test_public_result_has_no_raw_error_or_identifiers():
    result = _MODULE.public_result(
        category="refused",
        chunks=0,
        chars=0,
        agent_id="secret-agent-id",
        error_detail="private response body",
    )
    assert result == {"ok": False, "category": "refused", "chunks": 0, "chars": 0}


def test_runtime_config_matches_http_studio_resolution():
    class Key:
        tool_prompt = "key tool"
        system_prompt = "key system"
        time_zone = "Europe/London"
        ws_idle_timeout_minutes = 2

    runtime = {
        "tone_options": [{"value": "Gpt_5_6_Reasoning", "label": "gpt-5.6"}],
        "current_tone": "Magic",
        "global_tool_prompt": "global tool",
        "system_prompt": "global system",
        "time_zone": "Asia/Shanghai",
        "ws_idle_timeout_minutes": 5,
    }
    assert _MODULE.effective_runtime_config(Key(), runtime, model="gpt-5.6") == {
        "tone": "Gpt_5_6_Reasoning",
        "tool_prompt": "global tool\n\nkey tool",
        "system_override": "key system",
        "time_zone": "Europe/London",
        "idle_timeout": 120,
    }
