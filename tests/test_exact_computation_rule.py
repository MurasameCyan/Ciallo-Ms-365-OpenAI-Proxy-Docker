"""The contract must keep the "no executor, no invented digest" rule.

tone=Claude_Sonnet honours this tool contract but has no server-side interpreter
(tone_options.TONE_SERVER_INTERPRETER records which tones do; its sibling
Claude_Sonnet_Reasoning has both, so this is per-tone, not per-family). Asked for the
SHA-256 of a fresh nonce with only Read declared, it streamed a fabricated 64-hex
digest and retracted it later in the same reply -- the retraction does not help a
client that reads the first hex block. The rule below removed the fabricated value in
every measured round, so it is load-bearing wording, not decoration.

It has two halves that must both survive an edit: the CONDITION (only when nothing
declared can run code) and the INSTRUCTION (say so instead of answering from
memory). Dropping the condition would tell the model to refuse even when a `bash`
tool is right there, which measured as a working path and must not regress.
"""

from __future__ import annotations

import re

from m365_copilot_openai_proxy.models import (
    AnthropicMessagesRequest,
    OpenAIChatRequest,
    OpenAIResponsesRequest,
)
from m365_copilot_openai_proxy.substrate_parse import _NO_INTERPRETER_NOTE, _combine_text
from m365_copilot_openai_proxy.templates import _USER_HTML
from m365_copilot_openai_proxy.tone_options import TONE_SERVER_INTERPRETER
from m365_copilot_openai_proxy.translator import (
    default_tool_system_prompt,
    translate_anthropic_request,
    translate_openai_request,
    translate_responses_request,
)

_SCHEMA = {"type": "object", "properties": {"file_path": {"type": "string"}}}
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read a file from the local filesystem.",
            "parameters": _SCHEMA,
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


def test_all_three_m365_protocols_carry_the_rule():
    """The measurement was made through the Chat path, and the fix is only as wide as
    the contract the other two protocols build -- which is the same one, via
    _format_tools_prompt. Asserted so a protocol-specific contract cannot silently
    drop it (an Anthropic client asking for a hash is the same turn upstream)."""
    anthropic = translate_anthropic_request(
        AnthropicMessagesRequest(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "Read", "description": "Read a file.", "input_schema": _SCHEMA}],
        )
    )
    responses = translate_responses_request(
        OpenAIResponsesRequest(
            model="gpt-4o",
            input="hi",
            tools=[{"type": "function", "name": "Read", "parameters": _SCHEMA}],
        )
    )
    for label, result in (("anthropic", anthropic), ("responses", responses)):
        joined = result.prompt + "\n".join(result.additional_context)
        assert "exact computation" in joined, f"{label} contract lost the rule"


def test_the_consumer_contract_deliberately_omits_the_rule():
    """Consumer builds its own contract under a hard character budget that raises when
    exceeded, and no Consumer mode has been measured for exact computation at all.
    Pasting the rule in there would spend budget on an unmeasured guess -- if it ever
    belongs there, measure that provider first (see CONSUMER_MODE_TOOL_CALLING for how
    Consumer's own measurements are recorded)."""
    req = OpenAIChatRequest(model="gpt-4o", messages=[{"role": "user", "content": "hi"}], tools=_TOOLS)
    result = translate_openai_request(req, consumer_tool_max_chars=4000)
    joined = result.prompt + "\n".join(result.additional_context)
    assert "Consumer tool contract:" in joined
    assert "exact computation" not in joined


def test_an_admin_override_replaces_the_rule():
    """Documents the ceiling: the rule lives in the overridable base, so an admin who
    supplies their own system prompt owns this behaviour too (unlike NO_TOOL_NEEDED,
    which the proxy parses and therefore appends outside the override)."""
    injected = _injected("Only do what I say.")
    assert "exact computation" not in injected
    assert "NO_TOOL_NEEDED" in injected


# ------------------------------------------------------------------ /user hint
# The rule above can only fire on a turn that declares tools. A plain chat turn
# carries no contract at all, so tone=Claude_Sonnet asked for a hash there answered
# from memory -- measured, with no retraction (.probe/compute_no_exec_tool.py, C1).
# Nothing in the pipeline can verify a claimed digest (a wrong one is shaped exactly
# like a right one), so that turn gets one appended sentence instead (see the
# _combine_text tests below), plus the hint here, on the page where defaults are
# picked, because the sentence changes the answer into a refusal.


def test_user_page_warns_that_claude_modes_cannot_compute():
    assert 'data-i18n="user_no_interpreter_hint"' in _USER_HTML
    values = re.findall(r"user_no_interpreter_hint:'([^']*)'", _USER_HTML)
    assert len(values) == 2, f"the hint must exist in both languages, got {values}"
    assert all(v.strip() for v in values)


def test_the_hint_is_scoped_to_the_one_measured_mode():
    """It used to say "Claude-family", which the second measurement pass disproved:
    claude-sonnet-4-5 (Claude_Sonnet_Reasoning) computes with GeneratedCode frames.
    Warning about a mode that works is the same class of error as staying silent
    about one that does not."""
    values = re.findall(r"user_no_interpreter_hint:'([^']*)'", _USER_HTML)
    for value in values:
        assert "claude-sonnet-4-6" in value
        assert "family" not in value.lower() and "claude 系" not in value


def test_the_hint_names_the_way_out_not_just_the_problem():
    """A capability warning with no remedy just makes the mode look broken; the
    remedy is what the measurements found -- declare a tool that can run commands
    (the model then routes the hash to it) or switch to claude-sonnet-4-5, the one
    selector measured to have the interpreter AND to honour the tool contract."""
    values = re.findall(r"user_no_interpreter_hint:'([^']*)'", _USER_HTML)
    assert all("claude-sonnet-4-5" in v for v in values)
    assert any("声明" in v for v in values) and any("declare" in v.lower() for v in values)


def test_the_hint_sits_in_the_card_that_holds_the_mode_defaults():
    """#tone itself is deliberately hidden on /user (the mode travels in the model
    name), so the hint goes on the card that card-level hints already live on."""
    card = _USER_HTML[_USER_HTML.index('<div class="card mode-profile-card">') :]
    card = card[: card.index('id="my-sessions-details"')]
    assert 'data-i18n="user_no_interpreter_hint"' in card


# ------------------------------------------------- the no-tools half, automatic
# Measured at the shipped position (.probe/compute_no_tools_shipped.py): bare
# Claude_Sonnet fabricated a fresh nonce's digest, and with this sentence appended
# after the prompt it answered "I cannot compute this exactly here" instead, while
# "capital of France" stayed "Paris." Gated on TONE_SERVER_INTERPRETER because the
# sentence is a factual claim about the tone, not a style preference.


def test_the_sentence_is_appended_for_a_tone_measured_to_have_no_interpreter():
    assert _NO_INTERPRETER_NOTE in _combine_text("hash this", [], "Claude_Sonnet")


def test_it_does_not_fire_for_a_tone_that_can_actually_execute():
    """Every non-absent tone returned a fresh nonce's digest. Telling them they cannot
    execute would be false, and a model that believes it lost a capability it has is a
    worse outcome than the bug being fixed."""
    for tone, status in TONE_SERVER_INTERPRETER.items():
        if status != "absent":
            assert _NO_INTERPRETER_NOTE not in _combine_text("hash this", [], tone), tone


def test_only_the_one_measured_tone_is_marked_absent():
    """Tripwire for the bug this nearly shipped with: Claude_Sonnet_Reasoning was
    guessed "absent" by family and is measurably verified. The full sweep found no
    second fabricating tone, so a new "absent" entry means someone measured one --
    editing this list is the cheap part, having the probe output is the point."""
    assert [t for t, s in TONE_SERVER_INTERPRETER.items() if s == "absent"] == ["Claude_Sonnet"]


def test_an_unmeasured_tone_stays_silent():
    """Same rule the tool-calling map follows: absence of measurement is not evidence
    of absence, and Microsoft's rollout keeps moving. tone=None is the Consumer path,
    which builds its own contract and has never been measured for this at all."""
    for tone in (None, "", "Gpt_5_6_Reasoning", "Claude_Opus"):
        assert _NO_INTERPRETER_NOTE not in _combine_text("hash this", [], tone)


def test_a_tools_turn_gets_the_contract_rule_instead_of_the_sentence():
    """Two mitigations for one failure would double the instruction and contradict it:
    the contract's version is conditional on "no tool listed below can run code", so a
    turn carrying bash must not also be told flatly that nothing can execute."""
    combined = _combine_text("hash this", ["Tools:\n- Read\nEmit a tool_call block"], "Claude_Sonnet")
    assert _NO_INTERPRETER_NOTE not in combined
    assert "[FORMAT]" in combined


def test_the_sentence_survives_context_and_lands_last():
    """Position is part of the prompt: it was measured appended after the prompt, the
    same slot [FORMAT] uses, not buried in the context block above the --- divider."""
    combined = _combine_text("hash this", ["System instructions:\nBe brief."], "Claude_Sonnet")
    assert combined.endswith(_NO_INTERPRETER_NOTE)
    assert combined.index("---") < combined.index("hash this")
