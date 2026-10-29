"""``<cite>`` is an HTML element before it is ever a citation.

M365 renders a citation as ``<cite>turn1search7</cite>``; HTML uses the very
same element for the title of a work (``<cite>Moby Dick</cite>``). The
streaming cleaner has to tell them apart, and it has to do so while the tag is
arriving in pieces.

An earlier version held ``<cite>`` plus anything alphanumeric after it, on the
assumption that a citation id would follow. When it did not, ``_release`` cut
the text at the tag start and the title's closing half was lost:

    'quote: <cite>Some Book</cite>'  ->  'quote: <cite>Some Book'

The tracker is fed one chunk at a time here, because that is the only shape in
which this shows up: a whole answer takes a different path.
"""

from __future__ import annotations

import pytest

from m365_copilot_openai_proxy.substrate_parse import CitationTracker


def _stream(chunks: list[str]) -> str:
    tracker = CitationTracker()
    out = [tracker.clean(chunk) for chunk in chunks]
    out.append(tracker.flush())
    return "".join(out)


def _splits(text: str) -> list[list[str]]:
    pieces = [[text[:cut], text[cut:]] for cut in range(1, len(text))]
    pieces += [
        [text[:first], text[first:second], text[second:]]
        for first in range(1, len(text) - 1)
        for second in range(first + 1, len(text))
    ]
    pieces.append(list(text))
    return pieces


HTML_CITE_CASES = (
    "quote: <cite>Some Book</cite>",
    "见 <cite>规范</cite>",
    "The novel <cite>Moby Dick</cite> is referenced.",
    "参见 <cite>Some Book</cite> 与 <cite>规范</cite>",
    # A title that OPENS with the letters of a citation id. Holding it is
    # harmless; treating it as marker EVIDENCE is what deleted it.
    "<cite>Turn</cite>",
    "Read <cite>Turn of the Screw</cite> next.",
    "<cite>Turning 30</cite>",
)


@pytest.mark.parametrize("text", HTML_CITE_CASES)
def test_html_cite_element_survives_every_split(text):
    """``<cite>`` is real HTML. Holding it as a marker held the title one delta
    and then deleted it in `_release`, leaving ``<cite>Some Book``."""
    for chunks in _splits(text):
        assert _stream(chunks) == text, f"damaged by split {chunks!r}"


def test_a_citation_tag_is_still_converted():
    assert _stream(["参考 <cite>turn1search7</cite> 结束"]) == "参考 [1] 结束"
    assert _stream(list("参考 <cite>turn1search7</cite> 结束")) == "参考 [1] 结束"
    assert (
        _stream(["参考 <cite>turn1search7, turn2file0</cite> 结束"])
        == "参考 [1][2] 结束"
    )


def test_html_and_citation_tags_in_one_answer_are_told_apart():
    text = "A <cite>Moby Dick</cite> B <cite>turn1search7</cite> C"
    assert _stream(list(text)) == "A <cite>Moby Dick</cite> B [1] C"
