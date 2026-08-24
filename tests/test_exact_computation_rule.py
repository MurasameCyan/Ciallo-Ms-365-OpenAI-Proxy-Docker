"""The contract must keep the "no executor, no invented digest" rule.

Claude-family tones honour this tool contract but have no server-side interpreter
(tone_options.py records the mirror-image measurement). Asked for the SHA-256 of a
fresh nonce with only Read declared, they streamed a fabricated 64-hex digest and
retracted it later in the same reply -- the retraction does not help a client that
reads the first hex block. The rule below removed the fabricated value in every
measured round, so it is load-bearing wording, not decoration.

It has two halves that must both survive an edit: the CONDITION (only when nothing
declared can run code) and the INSTRUCTION (say so instead of answering from
memory). Dropping the condition would tell the model to refuse even when a `bash`
tool is right there, which measured as a working path and must not regress.
"""

from __future__ import annotations

import re

from m365_copilot_openai_proxy.models import OpenAIChatRequest
from m365_copilot_openai_proxy.templates import _USER_HTML
from m365_copilot_openai_proxy.translator import default_tool_system_prompt, translate_openai_request

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read a file from the local filesystem.",
            "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}},
        },
    }
]


def _injected(system_override=None):
    """What actually goes upstream for a tools-bearing turn."""
    req = OpenAIChatRequest(model="gpt-4o", messages=[{"role": "user", "content": "hi"}], tools=_TOOLS)
    result = translate_openai_request(req, system_override=system_override)
    return result.prompt + "\n".join(result.additional_context)


def test_prompt_forbids_answering_an_exact_computation_from_memory():
    prompt = default_tool_system_prompt()
    assert "exact computation" in prompt
    assert "instead of producing a value from memory" in prompt


def test_the_rule_is_conditional_on_nothing_being_able_to_run_code():
    """Unconditional wording would suppress the `bash` route that already works."""
    prompt = default_tool_system_prompt()
    assert "no tool listed below can run code" in prompt


def test_the_rule_reaches_the_injected_contract():
    """Wording only matters if it ships with the turn."""
    assert "exact computation" in _injected()


def test_an_admin_override_replaces_the_rule():
    """Documents the ceiling: the rule lives in the overridable base, so an admin who
    supplies their own system prompt owns this behaviour too (unlike NO_TOOL_NEEDED,
    which the proxy parses and therefore appends outside the override)."""
    injected = _injected("Only do what I say.")
    assert "exact computation" not in injected
    assert "NO_TOOL_NEEDED" in injected


# ------------------------------------------------------------------ /user hint
# The rule above can only fire on a turn that declares tools. A plain chat turn
# carries no contract at all, so a Claude tone asked for a hash there still answers
# from memory -- measured, with no retraction (.probe/compute_no_exec_tool.py, C1).
# Nothing in the pipeline can catch that (a wrong digest is shaped exactly like a
# right one), which leaves telling the user, on the page where they pick defaults.


def test_user_page_warns_that_claude_modes_cannot_compute():
    assert 'data-i18n="user_no_interpreter_hint"' in _USER_HTML
    values = re.findall(r"user_no_interpreter_hint:'([^']*)'", _USER_HTML)
    assert len(values) == 2, f"the hint must exist in both languages, got {values}"
    assert all(v.strip() for v in values)


def test_the_hint_names_the_way_out_not_just_the_problem():
    """A capability warning with no remedy just makes the mode look broken; the
    remedy is what the measurements found -- declare a tool that can run commands
    (the model then routes the hash to it) or use a mode that has the interpreter."""
    values = re.findall(r"user_no_interpreter_hint:'([^']*)'", _USER_HTML)
    assert any("Copilot" in v for v in values)
    assert any("声明" in v for v in values) and any("declare" in v.lower() for v in values)


def test_the_hint_sits_in_the_card_that_holds_the_mode_defaults():
    """#tone itself is deliberately hidden on /user (the mode travels in the model
    name), so the hint goes on the card that card-level hints already live on."""
    card = _USER_HTML[_USER_HTML.index('<div class="card mode-profile-card">') :]
    card = card[: card.index('id="my-sessions-details"')]
    assert 'data-i18n="user_no_interpreter_hint"' in card
