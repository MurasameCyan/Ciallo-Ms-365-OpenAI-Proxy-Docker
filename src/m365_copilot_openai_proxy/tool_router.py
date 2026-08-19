"""Router-mode tool planning: ask the model to classify, not to inline a block.

The native contract asks the model to answer normally *and* drop a fenced
``tool_call`` block into that answer. Measured 2026-08-18, only the Claude Sonnet
tones do it; every Copilot/GPT tone answers in prose and the tools are silently
lost. Measured again 2026-08-19 with a single-purpose classification prompt
instead -- "does this turn need a tool: answer one line" -- and all 7 tones
complied, 16/16 across both directions. So the failure was never the tone's
capability, it was the shape we asked for. This module is that second shape.

The decision is rewritten into the very fenced block the native parser already
consumes, so everything downstream -- schema validation, the read-only guard,
tool_calls/finish_reason emission, the admin call log -- is reached unchanged.
Cost is one extra upstream turn, and only when the router finds no call: a
decided call needs no answer turn at all, because the answer *is* the call.

Borrowed from HEXUXIU/M365-Copilot2API (``internal/web/model_tool_router.go``,
``tool_planning.go``); its ``CALL_TOOL:`` line format is what the live probe
measured, so it is kept verbatim. Its parser is not: it locates the argument
list with ``LastIndex(rest, ")")``, which overshoots on the reasoning tones,
because those append their thinking *after* the decision line.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator

from .substrate_client import SubstrateCopilotError
from .tone_options import TOOL_PLANNING_MODES, router_applies, tool_planning_mode
from .tool_call_parser import _NO_TOOL_MARKER, _coerce_tool_call

_log = logging.getLogger("copilot_proxy")

# Re-exported from tone_options (a leaf, so runtime_settings can normalize the
# persisted value, and /v1/models can report the effective status, without either
# importing this module):
#   "auto" is the default -- the router costs an extra turn, so it is spent only
#   on the tones measured to need it. "native"/"router" force one shape
#   everywhere, which is what a bug report or a rollout change needs to be
#   diagnosable.
__all__ = [
    "TOOL_PLANNING_MODES",
    "build_router_prompt",
    "parse_router_decision",
    "routed_or_answered",
    "routed_or_streamed",
    "router_applies",
    "router_text",
    "tool_planning_mode",
]

_CALL_TOOL_RE = re.compile(r"CALL_TOOL\s*:\s*([A-Za-z0-9_.\-]+)\s*\(", re.IGNORECASE)
_DECODER = json.JSONDecoder()


def build_router_prompt(
    conversation: str,
    tool_lines: list[str],
    choice: tuple[str, str | None, bool] | None = None,
) -> str:
    """The classification turn: one job, one line of output.

    Deliberately not a system prompt bolted onto the real request -- the whole
    finding is that these tones follow a single-purpose instruction and ignore a
    secondary one. Nothing here asks for an answer to the user's question.
    """
    demand = ""
    if choice is not None:
        mode, name, _allow_parallel = choice
        if mode == "tool" and name:
            demand = (
                f"\nThe host requires the tool named {name} this turn. Emit "
                f"CALL_TOOL: {name}(...) and nothing else."
            )
        elif mode == "required":
            demand = (
                "\nThe host requires a tool call this turn. Never answer "
                f"{_NO_TOOL_MARKER}."
            )
    return (
        "You are a tool-use router for a host program. Read the conversation "
        "below and decide whether the LAST user request needs one of the host's "
        "local tools to be executed.\n\n"
        "Available tools:\n" + "\n".join(tool_lines) + "\n\n"
        "Reply with EXACTLY ONE line, and nothing else:\n"
        '  CALL_TOOL: <tool_name>({"argument": "value"})\n'
        f"  {_NO_TOOL_MARKER}\n\n"
        "Rules:\n"
        "- The arguments must be ONE JSON object matching that tool's parameters.\n"
        "- Take paths, names and values verbatim from the conversation; never "
        "invent them, never use placeholders.\n"
        "- The tools run on the user's own machine, not here. Never say you "
        "cannot access local files, and never ask for an upload.\n"
        "- If the conversation already contains the result of the call you were "
        f"about to make, that work is done: answer {_NO_TOOL_MARKER}.\n"
        f"- If no tool is needed at all, answer {_NO_TOOL_MARKER}."
        f"{demand}\n\n"
        "Conversation:\n" + conversation
    )


def _decoded_arguments(text: str, open_paren: int) -> dict | None:
    """Decode the JSON object inside ``name( ... )``, or None if there is none."""
    brace = text.find("{", open_paren)
    closing = text.find(")", open_paren)
    if brace == -1 or (closing != -1 and closing < brace):
        # `ListDir()` -- a call with genuinely no arguments is still a decision.
        # Anything else between the parens is a reply we cannot read as arguments,
        # and guessing `{}` there would forge a call the model never specified.
        return {} if closing != -1 and not text[open_paren + 1:closing].strip() else None
    try:
        obj, _end = _DECODER.raw_decode(text, brace)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def parse_router_decision(text: str) -> list[dict]:
    """Parse ``CALL_TOOL: name({...})`` decisions into OpenAI-shaped tool_calls.

    Balanced-brace decoding from the first ``{`` after the paren, like the fenced
    parser: the reasoning tones continue talking after the decision line, so
    anything that scans for the last ``)`` swallows the commentary too.
    """
    calls: list[dict] = []
    for match in _CALL_TOOL_RE.finditer(text or ""):
        arguments = _decoded_arguments(text, match.end() - 1)
        if arguments is None:
            continue
        call = _coerce_tool_call({"name": match.group(1), "arguments": arguments})
        if call:
            calls.append(call)
    return calls


def router_text(decision: str) -> str:
    """Rewrite a router decision as the fenced block the native parser consumes.

    Reusing the existing text -> tool_calls path is what keeps router mode a
    prompt change instead of a second pipeline: the schema check, the read-only
    guard and the call log all sit downstream of it and need no router awareness.
    Returns "" when the router decided no tool was needed (or answered so far off
    format that no decision can be read), which is the caller's signal to spend a
    real answer turn.
    """
    blocks = [
        "```tool_call\n"
        + json.dumps(
            {
                "name": call["function"]["name"],
                "arguments": json.loads(call["function"]["arguments"]),
            },
            ensure_ascii=False,
        )
        + "\n```"
        for call in parse_router_decision(decision)
    ]
    return "\n\n".join(blocks)


async def routed_or_answered(
    client,
    router_prompt: str,
    prompt: str,
    additional_context: list[str],
    session=None,
    images: list | None = None,
) -> str:
    """One turn's text: the router's decision if it produced a call, else an answer.

    The router turn runs with ``session=None`` on purpose -- it is a throwaway
    classification, and letting it into the persistent conversation would leave
    the user's session carrying protocol chatter that the next turn's history
    (and the rot heuristics) would have to live with.
    """
    declined = False
    if router_prompt:
        decided, declined = await _router_decision(client, router_prompt)
        if decided:
            return decided
    text = await client.chat(prompt, additional_context, session, images)
    return text + _marker_suffix(text, declined)


async def routed_or_streamed(
    client,
    router_prompt: str,
    prompt: str,
    additional_context: list[str],
    session=None,
    images: list | None = None,
) -> AsyncIterator[str]:
    """chat_stream, with the same router pre-step, yielding the decision as one chunk.

    Shaped like ``chat_stream`` so a caller that already buffers a tools-bearing
    stream needs no restructuring: a router hit is simply a one-chunk turn.
    """
    declined = False
    if router_prompt:
        decided, declined = await _router_decision(client, router_prompt)
        if decided:
            yield decided
            return
    text = ""
    async for delta in client.chat_stream(prompt, additional_context, session, images):
        text += delta
        yield delta
    suffix = _marker_suffix(text, declined)
    if suffix:
        yield suffix


def _marker_suffix(text: str, declined: bool) -> str:
    """Carry a "no tool needed" verdict to the caller inside the turn's text.

    Same trick as ``router_text`` in the other direction: rather than a second
    return channel every route would have to thread, the verdict is re-emitted as
    the marker the native path already looks for, so ``split_no_tool_marker``
    strips it and the whole declined-vs-ignored distinction downstream (no
    shortfall note, no prose-Write fallback, no corrective retry, the right
    tool_choice=required diagnosis) applies with no router awareness at all.

    Empty when the answer turn came back empty, because the marker alone reads as
    a malformed turn -- which is exactly what an empty answer is.
    """
    return f"\n\n{_NO_TOOL_MARKER}" if declined and text.strip() else ""


async def _router_decision(client, router_prompt: str) -> tuple[str, bool]:
    """``(fenced call text, declined)``. Never fatal: falling back to an ordinary
    answer turn is strictly better than failing a request over a planning
    optimisation -- and a fallback answer is NOT a declined one, so a failed
    classification keeps today's reporting instead of claiming a verdict."""
    try:
        decision = await client.chat(router_prompt, [], None)
    except SubstrateCopilotError as exc:
        _log.warning("[router] classification turn failed, answering natively: %s", exc)
        return "", False
    _log.info("[router] decision: %s", (decision or "").strip()[:300])
    return router_text(decision), _NO_TOOL_MARKER.lower() in (decision or "").lower()
