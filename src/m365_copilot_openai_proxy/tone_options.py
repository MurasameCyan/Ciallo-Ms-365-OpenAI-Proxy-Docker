from __future__ import annotations

# Conversation tone (mode) options discovered from M365 Copilot's mode picker.
# The `tone` field in the Substrate chat payload controls which model/mode is used.
# Display labels become /v1/models ids (spaces → underscores via normalize_tone_options).
#
# Which of these an account may actually use is decided on the M365 side, not here:
# `Claude_Fable` and `Claude_Opus` are real modes that this tenant is currently
# refused on (measured 2026-08-02 with scan_tones.py) and are listed on purpose, so
# they come back by themselves once Microsoft rolls them out -- do not "clean them
# up". A refused mode now surfaces as an upstream error naming the mode rather than
# as a silent canned reply (see substrate_client._M365_REFUSAL_TEXTS).
TONE_OPTIONS = [
    {"value": "Magic", "label": "Copilot_自动", "label_zh": "Copilot_自动", "label_en": "Copilot_自动"},
    {"value": "Chat", "label": "Copilot_快速答复", "label_zh": "Copilot_快速答复", "label_en": "Copilot_快速答复"},
    {"value": "Reasoning", "label": "Copilot_深度思考", "label_zh": "Copilot_深度思考", "label_en": "Copilot_深度思考"},
    {"value": "Claude_Sonnet", "label": "claude-sonnet-4-6", "label_zh": "claude-sonnet-4-6", "label_en": "claude-sonnet-4-6"},
    {"value": "Claude_Sonnet_Reasoning", "label": "claude-sonnet-4-5", "label_zh": "claude-sonnet-4-5", "label_en": "claude-sonnet-4-5"},
    {"value": "Claude_Fable", "label": "claude-fable-5", "label_zh": "claude-fable-5", "label_en": "claude-fable-5"},
    {"value": "Claude_Opus", "label": "claude-opus", "label_zh": "claude-opus", "label_en": "claude-opus"},
    {"value": "Gpt_5_6_Reasoning", "label": "gpt-5.6", "label_zh": "gpt-5.6", "label_en": "gpt-5.6"},
    {"value": "Gpt_5_5_Chat", "label": "gpt-5.5_Chat", "label_zh": "gpt-5.5_Chat", "label_en": "gpt-5.5_Chat"},
    {"value": "Gpt_5_5_Reasoning", "label": "gpt-5.5", "label_zh": "gpt-5.5", "label_en": "gpt-5.5"},
    {"value": "Gpt_5_4_Chat", "label": "gpt-5.4_Chat", "label_zh": "gpt-5.4_Chat", "label_en": "gpt-5.4_Chat"},
    {"value": "Gpt_5_4_Reasoning", "label": "gpt-5.4", "label_zh": "gpt-5.4", "label_en": "gpt-5.4"},
    {"value": "Gpt_5_3_Chat", "label": "gpt-5.3_Chat", "label_zh": "gpt-5.3_Chat", "label_en": "gpt-5.3_Chat"},
    {"value": "Gpt_5_3_Reasoning", "label": "gpt-5.3", "label_zh": "gpt-5.3", "label_en": "gpt-5.3"},
    {"value": "Gpt_5_2_Chat", "label": "gpt-5.2_Chat", "label_zh": "gpt-5.2_Chat", "label_en": "gpt-5.2_Chat"},
    {"value": "Gpt_5_2_Reasoning", "label": "gpt-5.2", "label_zh": "gpt-5.2", "label_en": "gpt-5.2"},
]
TONE_VALUES = {option["value"] for option in TONE_OPTIONS}

# Whether a tone honours the injected tool-calling contract is a property of the
# tone, not of this proxy: prompt injection (translator._format_tools_prompt) ->
# fenced-block parse (tool_call_parser) -> tool_calls is the same pipeline for
# every tone. Measured 2026-08-18 against this tenant, one real upstream turn per
# cell, with the Read / bash / Write tools:
#   Claude_Sonnet, Claude_Sonnet_Reasoning -> 3/3 correct tool_calls each
#   Magic, Reasoning, Gpt_5_6_Reasoning,
#   Gpt_5_5_Reasoning, Gpt_5_5_Chat        -> 0 tool_calls. The turn either refuses
#       ("I cannot reach your local files, attach them instead") or runs the
#       command in Microsoft's own server-side interpreter and returns its output
#       as prose. Forcing tool_choice does not change this.
#   Claude_Fable, Claude_Opus              -> tone refused outright, untestable
# Only directly measured tones are listed. Everything else is "unknown" and is
# never flagged: tone behaviour drifts with Microsoft's rollout (see the same
# caveat above for mode availability), so an untested tone must not be advertised
# as broken. This map is advisory only -- the hard failure in
# routes_api_common.required_tool_call_error keys on the actual outcome, not this.
TONE_TOOL_CALLING = {
    "Claude_Sonnet": "verified",
    "Claude_Sonnet_Reasoning": "verified",
    "Magic": "unsupported",
    "Reasoning": "unsupported",
    "Gpt_5_6_Reasoning": "unsupported",
    "Gpt_5_5_Reasoning": "unsupported",
    "Gpt_5_5_Chat": "unsupported",
}

# Same question for the Consumer provider, whose selector is a mode rather than a
# tone (see _BUILTIN_CONSUMER_MODE_OPTIONS). Measured 2026-08-19 against the live
# account, three rounds over all nine Consumer model names, streaming, with a Read
# tool; the counts below pool the names that share a mode:
#   search 3/3, research 3/3, coco 3/3    -> honoured every time
#   reasoning 5/6 (copilot-reasoning + copilot-thinking) -> one miss in six
#   chat 1/3, smart 1/6 (copilot + copilot-smart)        -> complied once
#   study 0/3                                            -> never
# Unlike the tones, Consumer is NOT binary: the same mode both refused ("I can't
# access files on your machine, paste the contents") and emitted a correct call
# across rounds, so "flaky" is its own status -- calling smart/chat unsupported
# would be false (they provably can) and calling them verified would be worse.
# Keys are modes, not model names: two model names can share one mode, and the
# routes carry the resolved mode.
CONSUMER_MODE_TOOL_CALLING: dict[str, str] = {
    "search": "verified",
    "research": "verified",
    "coco": "verified",
    "reasoning": "verified",
    "chat": "flaky",
    "smart": "flaky",
    "study": "unsupported",
}


def tone_tool_calling(tone: str | None) -> str:
    """Measured tool-calling status: verified / flaky / unsupported / unknown.

    Also answers for a Consumer mode, because the routes carry whichever selector
    the provider uses in the same variable (see apply_request_model). Tone values
    are CamelCase and Consumer modes are lower_snake, so the two namespaces cannot
    collide.
    """
    key = str(tone or "")
    return TONE_TOOL_CALLING.get(key) or CONSUMER_MODE_TOOL_CALLING.get(key, "unknown")


# How a tools-bearing turn is planned; see tool_router.py for what each mode does.
# Kept in this leaf module rather than next to the router because runtime_settings
# needs to normalize the persisted value, and importing the router there would
# close a cycle (runtime_settings <- media_proxy <- substrate_client <- router).
TOOL_PLANNING_MODES = {"auto", "native", "router", "studio"}


def tool_planning_mode(raw: str | None) -> str:
    """Normalize a stored/requested planning mode, defaulting to ``auto``."""
    value = str(raw or "").strip().lower()
    return value if value in TOOL_PLANNING_MODES else "auto"


def router_applies(mode: str | None, tone: str) -> bool:
    """Whether this turn should be planned by a dedicated classification turn.

    ``auto`` keys on the measured status rather than a hardcoded tone list, so a
    tone that starts honouring the native contract stops paying for the extra
    turn without a code change -- and an unmeasured tone keeps today's behaviour
    instead of silently doubling its upstream cost. ``flaky`` routes too: a
    selector that complied 1-in-6 natively is one an agent client cannot build on,
    and the router turn is a deterministic replacement for that coin flip.
    """
    normalized = tool_planning_mode(mode)
    if normalized == "native":
        return False
    if normalized in {"router", "studio"}:
        return True
    return tone_tool_calling(tone) in {"unsupported", "flaky"}


def effective_tool_calling(tone: str | None, planning_mode: str | None) -> str:
    """Measured status, plus "router" when this turn's tools go through the router.

    What a client needs to know is whether sending ``tools`` will produce calls,
    and with router mode on it does even for a tone that ignores the inline
    contract. Reporting the bare measured status there is a pessimistic lie that
    makes a gating client withhold tools it would have got calls for.
    """
    status = tone_tool_calling(tone)
    if status != "verified" and router_applies(planning_mode, str(tone or "")):
        return "router"
    return status
