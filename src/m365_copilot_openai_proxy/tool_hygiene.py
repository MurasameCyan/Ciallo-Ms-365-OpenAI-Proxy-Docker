"""Guards on the tool_calls we hand a client, and the tool results it hands back.

Our tool_calls are PARSED OUT OF PROSE (see tool_call_parser), so every shape the
model can get wrong arrives here as routine input rather than as an exceptional
case. `_filter_schema_valid_tool_calls` already rejects calls the client cannot
execute; this module covers three defects it does not look at, each of which the
client turns into a hard error rather than a degraded answer:

1. **A duplicate `id` in one response.** The id is how a client maps a result
   back to the call that asked for it, so two calls sharing one id make that
   mapping ambiguous -- and Anthropic rejects a repeated `tool_use.id` outright,
   turning the whole turn into a 400. Our own emitter mints a fresh uuid per
   call, so a duplicate means the same fenced block was matched twice and the
   second copy is not a second request.

2. **A `tool_result` naming a call that was never made.** Sent to Anthropic, an
   unmatched `tool_use_id` is a 400; sent to OpenAI, a `role="tool"` message with
   no preceding `tool_calls` id is also rejected. This one is worth catching on
   the way IN because it usually means the CLIENT's transcript and ours disagree
   about what happened, and the resulting 400 names a field rather than the
   disagreement.

3. **A fan-out storm in one response.** Nothing in this proxy caps how many
   calls one response may carry, and a round's calls are dispatched in PARALLEL
   by the client -- so charging them afterwards only ever stops the NEXT round.
   The cap has to bind BEFORE the calls are delivered, which is why this is a
   filter over the parsed list rather than a counter somewhere downstream.

Every function here is pure: data in, data out, no I/O and no FastAPI. The whole
point is that each branch is unit-testable without a request, since the failures
being defended against are exactly the ones that are awkward to reproduce live.

Return shapes deliberately mirror `_filter_schema_valid_tool_calls`'s
``(kept, reasons)``, so a route can chain the filters and join one reason list.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# How many tool calls one response may deliver, and how many one conversation may
# accumulate. Both are ceilings on OUR fan-out, not on the model's ambition.
#
# 8 per round: the largest tool count we have ever observed a real client declare
# is in the low twenties (Claude Code), but a single ROUND that legitimately needs
# more than a handful of parallel calls has not been seen -- and the failure mode
# of guessing too low is mild and self-correcting (the model is told to call again
# next round), while guessing too high is a parallel storm the client executes
# before anyone can intervene. Deliberately not derived from the declared tool
# count: a client offering 20 tools is not asking for 20 simultaneous calls.
#
# 32 per turn: eight rounds at the round cap. A conversation that has issued 32
# tool calls and still has not answered is looping, and one more call will not
# fix it.
MAX_TOOL_CALLS_PER_ROUND = 8
MAX_TOOL_CALLS_PER_TURN = 32

# Stable codes, not prose: these travel back to the model as a tool result and are
# matched in tests, so the wording can change without breaking either.
REASON_BUDGET_SPENT = "budget_spent"
REASON_TOO_MANY_THIS_ROUND = "too_many_calls_this_round"

# The two refusals say DIFFERENT things on purpose, and conflating them is the
# mistake worth naming. A call refused because the whole turn's budget is gone
# must be told the work is over ("answer with what you have"), because more calls
# genuinely will not run. A call refused only because it exceeded THIS round's
# fan-out still has turn budget behind it, so telling it the budget is spent is a
# lie that makes the model give up while it could still finish the job -- it has
# to be told to read the results it did get and call again. Same refusal
# mechanism, opposite instruction.
_REFUSAL_MESSAGE = {
    REASON_BUDGET_SPENT: (
        "Not run: this turn's tool budget is spent and no further calls will "
        "execute. Answer now using what you have already gathered."
    ),
    REASON_TOO_MANY_THIS_ROUND: (
        "Not run: too many tool calls were requested at once. The ones that fit "
        "did run -- read their results, then make any further calls next round."
    ),
}


def _field(obj: Any, name: str) -> Any:
    """Read ``name`` off a pydantic model or a plain dict.

    Routes pass validated models; session history passes the dicts it persisted.
    Both reach these guards, so both have to be readable -- the same
    getattr-then-get access `translator.py` uses for exactly this reason.
    """
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _tool_call_id(call: Any) -> str:
    value = _field(call, "id")
    return value.strip() if isinstance(value, str) else ""


def _tool_call_label(call: Any) -> str:
    """A name for messages, without assuming the call is well-formed."""
    function = _field(call, "function")
    name = _field(function, "name") if function is not None else None
    return name if isinstance(name, str) and name else "(未命名)"


def dedupe_tool_call_ids(
    tool_calls: Sequence[Any],
) -> tuple[list[Any], list[str]]:
    """``(kept, reasons)`` with each id appearing at most once.

    First occurrence wins: it is the one the model actually asked for first, and
    the duplicate is an artifact of the same block being matched twice rather
    than a second request. A missing or blank id is rejected rather than
    back-filled -- our emitter always mints one, so its absence means the parse
    produced something malformed, and inventing an id here would hand the client
    a call we cannot correlate a result with.
    """
    kept: list[Any] = []
    reasons: list[str] = []
    seen: set[str] = set()
    for call in tool_calls:
        call_id = _tool_call_id(call)
        label = _tool_call_label(call)
        if not call_id:
            reasons.append(f"{label} 没有 tool_call id，无法与返回结果配对，已丢弃")
            continue
        if call_id in seen:
            reasons.append(
                f"{label} 的 tool_call id 与前一个调用重复（{call_id}），已丢弃重复的那个"
            )
            continue
        seen.add(call_id)
        kept.append(call)
    return kept, reasons


def _tool_call_payload(call: Any) -> tuple[str, str]:
    """The (name, arguments) a client would actually execute.

    The id is deliberately excluded: it is minted by us, per parse, and is
    therefore the one part of a call that is guaranteed NOT to repeat even when
    the request does.
    """
    function = _field(call, "function")
    name = _field(function, "name") if function is not None else None
    arguments = _field(function, "arguments") if function is not None else None
    return (
        name if isinstance(name, str) else "",
        arguments if isinstance(arguments, str) else "",
    )


def dedupe_tool_call_payloads(
    tool_calls: Sequence[Any],
) -> tuple[list[Any], list[str]]:
    """``(kept, reasons)`` with each (name, arguments) delivered at most once.

    THIS is the duplicate that actually reaches clients, and `dedupe_tool_call_ids`
    structurally cannot catch it. Measured 2026-09-12 against our own parser:
    `_extract_tool_calls` runs three passes -- fenced ```tool_call blocks, then
    ```json blocks, then unfenced tool-shaped JSON -- and each pass mints a FRESH
    `call_<uuid4>` id. So one model intent that appears twice in the prose (the
    same fence repeated, or a fenced block the model also echoed unfenced)
    becomes two calls with different ids and byte-identical payloads. Verified
    shapes: `Write {"file_path": "/a.txt", "content": "x"}` twice, and
    `Bash {"command": "rm -rf /tmp/x"}` fenced plus echoed. A client executing
    that list performs the write -- or the `rm` -- twice.

    Id-based dedupe is blind to it by construction (two uuids never collide), and
    the span-overlap filter in `_extract_tool_calls` does not help either: the
    two occurrences are at different offsets, so neither span contains the other.

    First occurrence wins, matching `dedupe_tool_call_ids`. Arguments are
    compared as the exact strings we would send rather than as parsed JSON: two
    spellings of the same object are a different, unmeasured case, and treating
    them as identical here would be a guess about client behaviour we have not
    observed.
    """
    kept: list[Any] = []
    reasons: list[str] = []
    seen: set[tuple[str, str]] = set()
    for call in tool_calls:
        payload = _tool_call_payload(call)
        if payload in seen:
            reasons.append(
                f"{_tool_call_label(call)} 与前一个调用的名称和参数完全相同，"
                "已丢弃重复的那个（同一个意图被解析了两次，执行两次会重复副作用）"
            )
            continue
        seen.add(payload)
        kept.append(call)
    return kept, reasons


def _content_blocks(message: Any) -> list[Any]:
    content = _field(message, "content")
    return [block for block in content if block is not None] if isinstance(content, list) else []


def _declared_call_ids(message: Any) -> set[str]:
    """Every tool-call id this ONE message declares, in either dialect."""
    ids: set[str] = set()
    for call in _field(message, "tool_calls") or []:
        call_id = _tool_call_id(call)
        if call_id:
            ids.add(call_id)
    for block in _content_blocks(message):
        if _field(block, "type") != "tool_use":
            continue
        block_id = _field(block, "id")
        if isinstance(block_id, str) and block_id.strip():
            ids.add(block_id.strip())
    return ids


def _answered_ids(message: Any) -> list[tuple[str, str]]:
    """``(id, dialect)`` for every tool result this ONE message carries.

    An empty id counts as a result naming nothing, which is the same defect as
    naming something absent -- so it is reported rather than skipped.
    """
    out: list[tuple[str, str]] = []
    if _field(message, "role") == "tool":
        value = _field(message, "tool_call_id")
        out.append((value.strip() if isinstance(value, str) else "", "tool_call_id"))
    for block in _content_blocks(message):
        if _field(block, "type") != "tool_result":
            continue
        value = _field(block, "tool_use_id")
        out.append((value.strip() if isinstance(value, str) else "", "tool_use_id"))
    return out


def orphan_tool_results(messages: Iterable[Any]) -> list[str]:
    """Reason strings for tool results that answer no call made earlier.

    Walks the transcript FORWARD and accumulates declared ids, so a result is
    judged only against calls that precede it -- a result appearing before its
    own call is as broken as one with no call at all, and upstream rejects both.

    Reported rather than removed: which repair is right depends on the route (a
    400 telling the client its transcript is wrong, versus dropping the stray
    message and continuing), and that decision does not belong in a pure guard.
    """
    reasons: list[str] = []
    known: set[str] = set()
    for message in messages:
        for answered_id, field_name in _answered_ids(message):
            if not answered_id:
                reasons.append(f"有一条工具结果没有 {field_name}，找不到它回应的调用")
            elif answered_id not in known:
                reasons.append(
                    f"工具结果的 {field_name}={answered_id} 在之前的消息里找不到对应的工具调用"
                )
        known |= _declared_call_ids(message)
    return reasons


def tool_round_allowance(
    *,
    remaining_turn_budget: int | None = None,
    per_round_cap: int = MAX_TOOL_CALLS_PER_ROUND,
) -> int:
    """How many calls this round may deliver: the SMALLER of the two caps.

    Neither cap may be widened by the other. Taking the round cap alone would let
    a turn that has already spent its budget keep issuing calls a round at a
    time; taking the turn remainder alone would let one response fan out to the
    whole remaining budget at once, which is the parallel storm the round cap
    exists to stop. ``None`` means "no turn budget tracked", not "unlimited
    round".
    """
    round_cap = max(0, int(per_round_cap))
    if remaining_turn_budget is None:
        return round_cap
    return min(round_cap, max(0, int(remaining_turn_budget)))


def refuse_over_cap(
    tool_calls: Sequence[Any],
    *,
    remaining_turn_budget: int | None = None,
    per_round_cap: int = MAX_TOOL_CALLS_PER_ROUND,
) -> tuple[list[Any], list[dict[str, str]]]:
    """``(kept, refusals)`` -- the first N calls run, the excess is REFUSED.

    Refused, not dropped: a `tool_calls` entry the client never sees a result for
    leaves its transcript unpaired, and the next request is then rejected for the
    orphan this would have created (see `orphan_tool_results`). So the excess
    comes back as a synthetic failure result the client can pair, carrying the
    reason it did not run.

    Order is the round's own call order -- the first N are the ones the model
    thought of first, and reordering would make which calls survive depend on
    something the model cannot see.

    Which refusal each call gets is the load-bearing part: past the TURN budget
    it is ``budget_spent`` (the work really is over), past only the ROUND cap it
    is ``too_many_calls_this_round`` (come back next round). See the block
    comment on `_REFUSAL_MESSAGE`.
    """
    turn_allowance = (
        None if remaining_turn_budget is None else max(0, int(remaining_turn_budget))
    )
    allowance = tool_round_allowance(
        remaining_turn_budget=remaining_turn_budget, per_round_cap=per_round_cap
    )
    kept: list[Any] = []
    refusals: list[dict[str, str]] = []
    for index, call in enumerate(tool_calls):
        if index < allowance:
            kept.append(call)
            continue
        past_turn_budget = turn_allowance is not None and index >= turn_allowance
        reason = REASON_BUDGET_SPENT if past_turn_budget else REASON_TOO_MANY_THIS_ROUND
        refusals.append(
            {
                "tool_call_id": _tool_call_id(call),
                "name": _tool_call_label(call),
                "reason": reason,
                "message": _REFUSAL_MESSAGE[reason],
            }
        )
    return kept, refusals


def over_cap_reasons(refusals: Sequence[Mapping[str, str]]) -> list[str]:
    """User-facing reason strings for `refuse_over_cap`'s refusals.

    Separate from the refusals themselves because the two audiences differ: the
    dicts go back to the MODEL as tool results, these go in the call log and the
    delivered note for a HUMAN. Naming which cap bound matters here too -- a turn
    that exhausted its budget over many rounds is a different animal from one
    shotgun response, and a log that only says "refused N" cannot tell them
    apart.
    """
    round_bound = sum(
        1 for item in refusals if item.get("reason") == REASON_TOO_MANY_THIS_ROUND
    )
    turn_bound = len(refusals) - round_bound
    reasons: list[str] = []
    if round_bound:
        reasons.append(f"本轮工具调用数超过单轮上限，有 {round_bound} 个没有执行")
    if turn_bound:
        reasons.append(f"本次对话的工具调用预算已用尽，有 {turn_bound} 个没有执行")
    return reasons
