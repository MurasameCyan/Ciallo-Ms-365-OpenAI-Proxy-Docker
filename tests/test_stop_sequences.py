from __future__ import annotations

import asyncio
import json

from m365_copilot_openai_proxy.response_helpers import (
    _anthropic_stream,
    _openai_stream,
)
from m365_copilot_openai_proxy.stop_sequences import (
    StopSequenceTrimmer,
    apply_stop,
    normalize_stop,
)

# M365's ChatHub has no stop-sequence parameter, so `stop` (OpenAI) and
# `stop_sequences` (Anthropic) are ours to enforce at the delivery boundary.
# Before this existed both were accepted and silently ignored: a client asking to
# stop at "CHARLIE" received the whole answer, "DELTA" and all.
#
# The streaming half is where the real bug lives. Upstream splits deltas wherever
# it likes, so a sequence arrives as "CHAR" + "LIE" and a forwarder that inspects
# each delta alone never sees it. Every streaming case below therefore feeds the
# sequence SPLIT, which is what a per-delta check passes and a hold-back catches.


def _collect(gen_factory):
    async def run():
        return [chunk async for chunk in gen_factory()]

    return asyncio.run(run())


class _Deltas:
    """Streams exactly the deltas given, so a split can be placed deliberately."""

    def __init__(self, deltas):
        self._deltas = list(deltas)

    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        for d in self._deltas:
            yield d


def _openai_content(body: str) -> str:
    out = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        if payload.strip() == "[DONE]":
            continue
        for choice in json.loads(payload).get("choices", []):
            piece = choice.get("delta", {}).get("content")
            if piece:
                out.append(piece)
    return "".join(out)


def _anthropic_events(body: str) -> list[dict]:
    out = []
    for line in body.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: "):]))
    return out


def _anthropic_text(body: str) -> str:
    return "".join(
        e.get("delta", {}).get("text", "")
        for e in _anthropic_events(body)
        if e.get("type") == "content_block_delta"
    )


def test_normalize_accepts_both_spellings_and_drops_unusable_entries():
    # OpenAI allows a bare string; Anthropic only a list. An empty sequence would
    # match at index 0 and truncate every answer to nothing, so it is dropped.
    assert normalize_stop("STOP") == ["STOP"]
    assert normalize_stop(["A", "", None, "B", 7]) == ["A", "B"]
    assert normalize_stop(None) == []


def test_the_earliest_hit_wins_and_a_tie_takes_the_longest():
    # Two sequences can both match; the answer must end at the FIRST cut, and a
    # tie must not report a prefix of the sequence that actually matched.
    assert apply_stop("keep <A> tail <B> more", ["<B>", "<A>"]) == ("keep ", "<A>")
    assert apply_stop("keep STOP", ["STOP", "STOPPER"]) == ("keep ", "STOP")
    assert apply_stop("keep STOPPER", ["STOP", "STOPPER"]) == ("keep ", "STOPPER")


def test_a_sequence_split_across_deltas_is_still_caught():
    # The regression this module exists for: neither delta contains "STOP".
    trimmer = StopSequenceTrimmer(["STOP"])
    assert trimmer.feed("keep ST") == "keep "
    assert trimmer.feed("OP tail") == ""
    assert trimmer.stopped is True
    assert trimmer.matched_sequence == "STOP"


def test_a_held_partial_that_never_completes_is_delivered_not_swallowed():
    # An answer ending in "CHAR" must not be truncated just because it looks like
    # the start of "CHARLIE" -- holding it back forever would eat real text.
    trimmer = StopSequenceTrimmer(["CHARLIE"])
    assert trimmer.feed("done CHAR") == "done "
    assert trimmer.flush() == "CHAR"
    assert trimmer.stopped is False


def test_forwarded_text_is_never_revoked():
    # SSE is append-only: whatever feed() returned has already reached the client,
    # so released_text must equal the concatenation of every feed plus the flush.
    trimmer = StopSequenceTrimmer(["END"])
    pieces = [trimmer.feed(d) for d in ["a", "bE", "N", "x", "EN", "D", "after"]]
    pieces.append(trimmer.flush())
    assert "".join(pieces) == trimmer.released_text
    assert trimmer.released_text == "abENx"
    assert trimmer.matched_sequence == "END"


def test_no_stop_sequences_is_an_exact_passthrough():
    trimmer = StopSequenceTrimmer([])
    assert [trimmer.feed(d) for d in ["a", "b", "c"]] == ["a", "b", "c"]
    assert trimmer.flush() == ""
    assert trimmer.stopped is False


def test_openai_stream_cuts_at_a_split_sequence_and_drops_the_remainder():
    body = "".join(
        _collect(
            lambda: _openai_stream(
                "m365-copilot",
                _Deltas(["ALPHA\nBRAVO\nCHAR", "LIE\nDELTA"]),
                "hi",
                [],
                stops=["CHARLIE"],
            )
        )
    )
    assert _openai_content(body) == "ALPHA\nBRAVO\n"
    assert "DELTA" not in body


def test_anthropic_stream_reports_the_matched_sequence_on_the_wire():
    # OpenAI has no field for which sequence hit; Anthropic does, and a client
    # that distinguishes "ran out" from "hit my sequence" reads stop_reason.
    body = "".join(
        _collect(
            lambda: _anthropic_stream(
                "m365-copilot",
                _Deltas(["ALPHA\nBRAVO\nCHAR", "LIE\nDELTA"]),
                "hi",
                [],
                stops=["CHARLIE"],
            )
        )
    )
    assert _anthropic_text(body) == "ALPHA\nBRAVO\n"
    assert "DELTA" not in body
    deltas = [e for e in _anthropic_events(body) if e.get("type") == "message_delta"]
    assert deltas[-1]["delta"] == {"stop_reason": "stop_sequence", "stop_sequence": "CHARLIE"}


def test_anthropic_stream_still_reports_end_turn_when_nothing_matched():
    body = "".join(
        _collect(
            lambda: _anthropic_stream(
                "m365-copilot",
                _Deltas(["ALPHA\nBRAVO\n"]),
                "hi",
                [],
                stops=["CHARLIE"],
            )
        )
    )
    assert _anthropic_text(body) == "ALPHA\nBRAVO\n"
    deltas = [e for e in _anthropic_events(body) if e.get("type") == "message_delta"]
    assert deltas[-1]["delta"] == {"stop_reason": "end_turn", "stop_sequence": None}


def test_the_turn_is_drained_past_the_cut_so_usage_stays_whole():
    # Truncation is a delivery boundary, not an early exit: usage totals and the
    # stored session message arrive with the last delta. Abandoning the iterator
    # at the hit would trade a correct usage row for latency no client observes.
    consumed: list[str] = []

    class _Counting:
        async def chat_stream(self, prompt, additional_context, session=None, images=None):
            for d in ["keep ", "STOP", "trailing", "more"]:
                consumed.append(d)
                yield d

    stored: list[str] = []
    body = "".join(
        _collect(
            lambda: _openai_stream(
                "m365-copilot",
                _Counting(),
                "hi",
                [],
                on_text_done=stored.append,
                stops=["STOP"],
            )
        )
    )
    assert consumed == ["keep ", "STOP", "trailing", "more"]
    assert _openai_content(body) == "keep "
    # What we recorded must match what the client actually saw, or the next turn
    # would reference text that was never delivered.
    assert stored == ["keep "]


# EVERY production request reaches these generators with `text_transform` set
# (routes_api_chat/messages always pass `media_rewriter`), and that argument
# selects a DIFFERENT code path: deltas are buffered instead of forwarded, so the
# hold-back trimmer above is bypassed and the cut is made once on the whole text.
# The tests above all omit it, so without these two the branch that actually runs
# in production had no coverage at all.
def _rewriter(text: str) -> str:
    """Stands in for media_rewriter: a real transform, not the identity."""
    return text.replace("PICTURE", "[image]")


def test_openai_stream_cuts_the_transformed_text_too():
    body = "".join(
        _collect(
            lambda: _openai_stream(
                "m365-copilot",
                _Deltas(["ALPHA PICTURE\nBRAVO\nCHAR", "LIE\nDELTA"]),
                "hi",
                [],
                text_transform=_rewriter,
                stops=["CHARLIE"],
            )
        )
    )
    # Transform applied, and the cut still lands before the sequence.
    assert _openai_content(body) == "ALPHA [image]\nBRAVO\n"
    assert "DELTA" not in body


def test_anthropic_stream_cuts_the_transformed_text_and_reports_the_sequence():
    body = "".join(
        _collect(
            lambda: _anthropic_stream(
                "m365-copilot",
                _Deltas(["ALPHA PICTURE\nBRAVO\nCHAR", "LIE\nDELTA"]),
                "hi",
                [],
                text_transform=_rewriter,
                stops=["CHARLIE"],
            )
        )
    )
    assert _anthropic_text(body) == "ALPHA [image]\nBRAVO\n"
    assert "DELTA" not in body
    deltas = [e for e in _anthropic_events(body) if e.get("type") == "message_delta"]
    assert deltas[-1]["delta"] == {"stop_reason": "stop_sequence", "stop_sequence": "CHARLIE"}
