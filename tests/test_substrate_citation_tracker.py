"""Review #1: the streaming hold must only ever cover citation syntax.

`CitationTracker` holds a tail it cannot yet classify, so a marker split
across two deltas is never shipped in halves. The cost of holding is that the
tail is DELAYED, and the cost of mis-classifying it as a marker is that the
tail is DELETED. The second is what truncated a legal tool-call argument:

    {"name":"Write","arguments":{"content":"print('[')\n"}}   ->   ..."print('    

Every case here is fed one delta at a time, because that is the only shape in
which the bug appears: the same input given whole takes a different path
through `_split_incomplete`.
"""

from __future__ import annotations

import pytest

from m365_copilot_openai_proxy.substrate_parse import (
    CitationTracker,
    clean_m365_citations,
)


def _stream(chunks: list[str], tracker: CitationTracker | None = None) -> str:
    """Clean ``chunks`` one at a time, then flush, as chat_stream does."""
    tracker = tracker or CitationTracker()
    out = [tracker.clean(chunk) for chunk in chunks]
    out.append(tracker.flush())
    return "".join(out)


def _splits(text: str) -> list[list[str]]:
    """Every two- and three-way split of ``text``, plus one character at a time."""
    pieces = [[text[:cut], text[cut:]] for cut in range(1, len(text))]
    pieces += [
        [text[:first], text[first:second], text[second:]]
        for first in range(1, len(text) - 1)
        for second in range(first + 1, len(text))
    ]
    pieces.append(list(text))
    return pieces


# --- review #1: a legal bracket in a tool argument is not a citation ---------

TOOL_CALL_ARGUMENT = '{"name":"Write","arguments":{"content":"print(\'[\')\\n"}}'


@pytest.mark.parametrize("chunks", _splits(TOOL_CALL_ARGUMENT))
def test_bracket_in_a_tool_argument_survives_any_split(chunks):
    """The hold only ever covers text that is ALREADY citation syntax.

    An earlier version held every open ``[`` and deleted the tail on flush,
    which truncated this argument to ``print('`` -- a valid tool call the host
    then could not run.
    """
    assert _stream(chunks) == TOOL_CALL_ARGUMENT


def test_a_bracket_that_never_became_a_citation_is_given_back_verbatim():
    assert _stream(["print('[')"]) == "print('[')"
    assert _stream(["print('[", "')"]) == "print('[')"


def test_the_whole_text_cleaner_removes_the_same_markers():
    """The dedupe signature is built on the whole-text cleaner, so a marker the
    tracker converts must also be a marker that cleaner removes."""
    for text, marker in (
        ("参考 <cite>turn1search7</cite> 结束", "turn1search7"),
        ("见 【1-1e0595】 结束", "1-1e0595"),
        ("见 \ue200cite\ue202turn1search7\ue201 结束", "turn1search7"),
    ):
        assert marker not in clean_m365_citations(text)
        assert "[1]" in _stream([text])
