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

import asyncio
import pathlib
import re

from m365_copilot_openai_proxy import runtime_settings
from m365_copilot_openai_proxy.models import (
    AnthropicMessagesRequest,
    OpenAIChatRequest,
    OpenAIResponsesRequest,
)
from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotClient
from m365_copilot_openai_proxy.substrate_parse import _NO_INTERPRETER_NOTE, _combine_text
from m365_copilot_openai_proxy.templates import _USER_HTML
from m365_copilot_openai_proxy.tone_options import (
    TONE_OPTIONS,
    TONE_SERVER_INTERPRETER,
    consumer_mode_image_generation,
    router_applies,
    tone_server_interpreter,
    tone_tool_calling,
)
from m365_copilot_openai_proxy.tone_resolver import resolve_tone
from m365_copilot_openai_proxy.tool_router import build_router_prompt
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


# ------------------------------------------- the notice those hints fold into
# Three measured caveats, one per provider surface, are too long to sit as prose
# above the fields, and the first one is the least useful of the three read in
# isolation (it warns about one model out of sixteen). They now share a single
# "注意事项" row whose `!` tooltip carries all three, which also let the old
# "保存后仅影响当前用户" line go: it described the form, not a measurement.
# The tests below exist because the copy quotes MEASURED lists by name -- prose
# that outlives the map it summarises is how the earlier "Claude 系" wording got
# wrong, so each list is pinned to the map it came from.

_NOTICE_KEYS = (
    "user_notice_label",
    "user_notice_m365",
    "user_notice_m365_others",
    "user_notice_consumer",
    "user_no_interpreter_hint",
    "user_other_tones_hint",
    "user_consumer_image_hint",
)


def _i18n_values(key: str) -> list[str]:
    """Both language values for one key, zh first (the order of the two tables)."""
    return re.findall(rf"{key}:'([^']*)'", _USER_HTML)


def _inline_text(key: str) -> str:
    """The fallback text inside the element, shown before the i18n script runs."""
    match = re.search(rf'data-i18n="{key}">([^<]*)<', _USER_HTML)
    assert match, f"no inline fallback for {key}"
    return match.group(1)


def _notice_block() -> str:
    block = _USER_HTML[_USER_HTML.index('<div class="user-notice">') :]
    return block[: block.index("</div>") + len("</div>")]


def test_the_three_caveats_share_one_tooltip_on_the_notice_row():
    notice = _notice_block()
    assert 'class="field-tip"' in notice and 'class="field-tip-bubble"' in notice
    assert notice.count('class="tip-line"') == 3
    assert re.findall(r'<b data-i18n="([^"]+)"', notice) == [
        "user_notice_m365",
        "user_notice_m365_others",
        "user_notice_consumer",
    ]
    assert re.findall(r'<span data-i18n="(user_\w*hint)"', notice) == [
        "user_no_interpreter_hint",
        "user_other_tones_hint",
        "user_consumer_image_hint",
    ]


def test_the_notice_replaced_the_two_prose_hints_and_the_form_only_line():
    """user_tone_hint said nothing measured -- it described the save button. The
    two capability hints keep their keys but move inside the bubble, so a leftover
    `class="hint"` row would show the same text twice."""
    assert "user_tone_hint" not in _USER_HTML
    assert "不再跟随全局模板变化" not in _USER_HTML
    assert 'class="hint" data-i18n="user_no_interpreter_hint"' not in _USER_HTML
    assert 'class="hint" data-i18n="user_other_tones_hint"' not in _USER_HTML


def test_every_notice_string_is_bilingual_and_matches_its_inline_fallback():
    """The house rule on both templates: the inline text IS the zh value, so a zh
    edit that misses one of the two copies shows different words to the same
    reader depending on whether the i18n script has run."""
    for key in _NOTICE_KEYS:
        values = _i18n_values(key)
        assert len(values) == 2, f"{key} must exist in zh and en, got {values}"
        assert all(v.strip() for v in values), key
        assert _inline_text(key) == values[0], key


def _tone_labels(predicate) -> list[str]:
    """Public model names, in picker order, for the tones matching `predicate`."""
    return [option["label"] for option in TONE_OPTIONS if predicate(option["value"])]


def test_the_other_models_line_pins_the_lists_to_the_measured_maps():
    """Every list in that sentence is an enumeration of a map, so it is written
    here as a join of that map -- a tone added to TONE_OPTIONS, or a status that
    moves from unknown to verified, fails this with the exact text to paste."""
    interpreter_yes = _tone_labels(lambda t: tone_server_interpreter(t) == "verified")
    interpreter_unmeasured = _tone_labels(lambda t: tone_server_interpreter(t) == "unknown")
    contract_yes = _tone_labels(lambda t: tone_tool_calling(t) == "verified")
    extra_turn = _tone_labels(lambda t: router_applies("auto", t))
    assert extra_turn == _tone_labels(lambda t: tone_tool_calling(t) == "unsupported"), (
        "the sentence equates 'measured to ignore the contract' with 'pays for a "
        "routing turn under auto'; a flaky tone would make that false"
    )
    zh, en = _i18n_values("user_other_tones_hint")
    for group in (interpreter_yes, interpreter_unmeasured, contract_yes, extra_turn):
        assert "、".join(group) in zh, "、".join(group)
        assert ", ".join(group) in en, ", ".join(group)


def test_the_notice_accounts_for_every_model_in_the_picker():
    """A model the notice never names reads as "no caveat measured" when the truth
    may be that nobody looked -- the one interpreter-absent tone is named by the
    first line instead, so the two m365 lines together must cover the picker."""
    m365_lines = _i18n_values("user_other_tones_hint") + _i18n_values("user_no_interpreter_hint")
    covered = " ".join(m365_lines)
    for option in TONE_OPTIONS:
        assert option["label"] in covered, option["label"]


def test_the_consumer_line_sorts_every_shipped_model_by_whether_it_draws():
    """Same enumeration risk on the Consumer side, plus a claim about structure:
    the first sentence is the answer (the models that draw), everything after it is
    the explanation (the ones that do not), so a model on the wrong side of that
    boundary sends someone to a mode that answers "已为你生成" with no image.
    Verdicts come from CONSUMER_MODE_IMAGE_GENERATION, and modes are shared
    (copilot/copilot-smart, copilot-reasoning/copilot-thinking), so the page has to
    name models while the map keys modes."""
    catalogue = runtime_settings._RUNTIME_SETTINGS_DEFAULTS["consumer_mode_options"]
    verdict = {
        option["model"]: consumer_mode_image_generation(option["mode"]) for option in catalogue
    }
    assert set(verdict.values()) == {"verified", "absent"}, verdict
    draws = {name for name, status in verdict.items() if status == "verified"}
    for value in _i18n_values("user_consumer_image_hint"):
        answer, rest = re.split(r"。|\. ", value, maxsplit=1)
        assert _consumer_names(answer) == draws, answer
        assert _consumer_names(rest) == set(verdict) - draws, rest


def _consumer_names(text: str) -> set[str]:
    return {match.group(0) for match in re.finditer(r"copilot(?:-[a-z]+)*", text)}


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


# ------------------------------------- the gate is reachable from a real request
# _combine_text gating is only worth anything if a production turn arrives with the
# tone spelled the way the map keys it. Two links carry that: the public model name
# resolves to a tone value (tone_resolver), and the route assigns it to the client
# (routes_api_common.apply_request_model does `client._tone = tone`) which chat_stream
# then passes down. Renaming a label or resolving to a default would silently stop the
# note from ever firing, and no unit test on _combine_text alone would notice.


def test_the_public_model_name_resolves_to_the_tone_the_map_keys():
    assert resolve_tone("claude-sonnet-4-6", TONE_OPTIONS, "Magic")[0] == "Claude_Sonnet"
    assert TONE_SERVER_INTERPRETER["Claude_Sonnet"] == "absent"
    # The remedy the /user hint names has to resolve too, or the advice is dead copy.
    assert resolve_tone("claude-sonnet-4-5", TONE_OPTIONS, "Magic")[0] == "Claude_Sonnet_Reasoning"


def _wire_text(tone: str, context: list[str], prompt: str = "What is the SHA-256 of abc?") -> str:
    """The text chat_stream actually hands the turn streamer."""
    client = SubstrateCopilotClient.__new__(SubstrateCopilotClient)
    client._token = "token"
    client._time_zone = "Asia/Shanghai"
    client._extra_tool_prompt = ""
    client._oid = "oid"
    client._tid = "tid"
    client._tone = tone  # exactly what apply_request_model assigns
    sent: list[str] = []

    async def capture(*, text, conv_id, session_id, is_start_of_session, annotations=None):
        sent.append(text)
        yield "ok"

    client._stream_turn_with_retry = capture

    async def run() -> None:
        async for _ in client.chat_stream(prompt, context):
            pass

    asyncio.run(run())
    return sent[0]


def test_a_no_tools_turn_carries_the_note_all_the_way_to_the_turn_streamer():
    assert _wire_text("Claude_Sonnet", []).endswith(_NO_INTERPRETER_NOTE)


def test_the_sibling_tone_and_a_tools_turn_send_nothing_extra():
    assert _NO_INTERPRETER_NOTE not in _wire_text("Claude_Sonnet_Reasoning", [])
    assert _NO_INTERPRETER_NOTE not in _wire_text("Claude_Sonnet", ["Emit a tool_call block"])


def test_the_router_classification_turn_is_left_alone():
    """The router sends its contract as the PROMPT with empty context, so the has_tools
    check cannot see it. Appending "you have no code execution" there would contradict a
    prompt that lists a shell and demands exactly one line -- a hash request the router
    should answer with CALL_TOOL: bash(...) would come back as a refusal instead.
    Built with the real prompt builder so a rewording that drops the marker fails here.
    """
    router_prompt = build_router_prompt(
        "user: what is the sha256 of abc?", ["- bash: run a shell command"]
    )
    assert _NO_INTERPRETER_NOTE not in _wire_text("Claude_Sonnet", [], router_prompt)


# ------------------------------------------ the enumeration itself, machine-checked
# The router exclusion is only complete if the empty-context callers are known, and that
# set was audited by hand once. This pins it: a fourth caller sends a no-tools turn into
# the note's reach, and whoever adds it has to decide the same question the router raised
# (does this prompt carry its own conflicting contract?) instead of finding out in prod.

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "m365_copilot_openai_proxy"
# `client.chat(prompt, [], ...)` / `client.chat_stream(prompt, [], ...)`, across newlines.
_EMPTY_CONTEXT_CALL = re.compile(r"\.chat(?:_stream)?\(\s*[A-Za-z_][\w.]*\s*,\s*\[\s*\]")


def _empty_context_callers() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted(_SRC.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in _EMPTY_CONTEXT_CALL.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            if text[line_start:].lstrip().startswith("#"):
                continue  # a comment quoting the shape, not a call site
            found[path.name] = found.get(path.name, 0) + 1
    return found


def test_the_empty_context_callers_are_the_three_that_were_audited():
    assert _empty_context_callers() == {
        # The contract is in the prompt -> excluded by the _NO_TOOL_MARKER check above.
        "tool_router.py": 1,
        # Measured with the shipped sentence, one turn per arm, outcome unchanged:
        # the image is still produced, and the probe still classifies as "ok".
        "routes_api_images.py": 1,
        "routes_admin_modeltest.py": 1,
    }

