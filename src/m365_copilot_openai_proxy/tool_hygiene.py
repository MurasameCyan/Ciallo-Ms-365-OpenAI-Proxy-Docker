"""Guards on the tool_calls we hand a client, and the tool results it hands back.

Our tool_calls are PARSED OUT OF PROSE (see tool_call_parser), so every shape the
model can get wrong arrives here as routine input rather than as an exceptional
case. `_filter_schema_valid_tool_calls` already rejects calls the client cannot
execute; this module covers two defects it does not look at, each of which the
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

A per-round fan-out cap used to live here as a third guard
(`MAX_TOOL_CALLS_PER_ROUND` / `MAX_TOOL_CALLS_PER_TURN` / `refuse_over_cap` /
`tool_round_allowance` / `over_cap_reasons`). It was removed on 2026-09-14 for
three measured reasons, recorded here so it is not reintroduced on intuition:

* It had NO caller anywhere in `src/` -- only tests, which called it directly and
  were therefore green while nothing was wired.
* Its refusal payload assumed this proxy emits a `role:"tool"` / `tool_result`
  the client can pair with the refused call. This proxy never emits one and has
  no tool executor: it parses `tool_calls` out of prose and the CLIENT executes
  them, so those dicts had no delivery channel.
* A census of the deployed container's call log (100 entries, 42 carrying tool
  calls) found the largest real fan-out was ONE call per round against a cap of
  eight, so the guard would never have fired.

If a real fan-out storm ever shows up, the shape to build is a truncation whose
reasons join the EXISTING `rejected` channel (see `rejected_calls_note`), not a
second refusal vocabulary. Details:
docs/github-m365-proxy-candidates-temp-2026-08-20.md.

Every function here is pure: data in, data out, no I/O and no FastAPI. The whole
point is that each branch is unit-testable without a request, since the failures
being defended against are exactly the ones that are awkward to reproduce live.

Return shapes deliberately mirror `_filter_schema_valid_tool_calls`'s
``(kept, reasons)``, so a route can chain the filters and join one reason list.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any


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
