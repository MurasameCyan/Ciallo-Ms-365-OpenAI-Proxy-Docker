"""Review #2: the two views of one turn must agree on a source's number.

M365 sends a cumulative ``messages`` snapshot AND incremental
``writeAtCursor`` deltas for the same turn, and it does not always render a
citation the same way in both: one live capture had ``【4-6f710b】`` in the
snapshot against ``<cite>turn1search4</cite>`` in the deltas.

Both renderings name ONE source, but they normalise to unrelated keys, so the
tracker numbered them separately -- the snapshot said ``[4]`` where the deltas
said ``[1]``. ``_split_snapshot_lead`` then saw no common prefix, the delta's
replay of the opening looked like new text, and the reader was told the first
sentence twice.

Two things fix it, and both are pinned here: the source's renderings are
registered as ONE key as its reference metadata arrives, and the snapshot-lead
reconciliation tolerates a differing footnote NUMBER (never differing prose).
"""

from __future__ import annotations

import pytest

from m365_copilot_openai_proxy.substrate_parse import (
    CitationTracker,
    _message_content,
    _split_snapshot_lead,
    aligned_url_sources_for_stream,
    extract_source_attributions,
    openai_url_citations_from_sources,
)


def _stream(chunks: list[str], tracker: CitationTracker | None = None) -> str:
    """Clean ``chunks`` one at a time, then flush, as chat_stream does."""
    tracker = tracker or CitationTracker()
    out = [tracker.clean(chunk) for chunk in chunks]
    out.append(tracker.flush())
    return "".join(out)


# --- review #2: the two views of one turn must share ONE number per source ---

SNAPSHOT_MARK = "【4-6f710b】"
DELTA_MARK = "<cite>turn1search4</cite>"
SHARED_REFERENCE = {
    "ref_key": "4-6f710b",   # what 【4-6f710b】 normalises to
    "ref_id": "turn1search4",  # what <cite>turn1search4</cite> normalises to
    "label": "4",
    "url": "https://fastapi.tiangolo.com",
    "title": "FastAPI",
}


def test_both_renderings_of_one_source_take_the_same_number():
    """Same source, two renderings, ONE footnote.

    M365 restates a source as ``<cite>turn1search4</cite>`` in the streamed
    deltas and as ``【4-6f710b】`` in the cumulative snapshot. Numbering them
    separately made the snapshot say ``[4]`` where the delta said ``[1]``.
    """
    tracker = CitationTracker()
    tracker.note_source(SHARED_REFERENCE)

    delta_text = _stream([f"FastAPI 很快。{DELTA_MARK}"], tracker)
    snapshot_text = tracker.apply(f"FastAPI 很快。{SNAPSHOT_MARK}")

    assert delta_text == "FastAPI 很快。[4]"
    assert snapshot_text == delta_text
    assert tracker.count == 1
    assert len(tracker.keys_in_order) == 1


def test_shared_numbering_holds_without_reference_metadata():
    """No metadata to link the renderings: the numbers may differ, and the
    snapshot-lead reconciliation must still see them as the same run."""
    tracker = CitationTracker()
    lead = tracker.apply(f"FastAPI 很快。{SNAPSHOT_MARK}")
    delta = _stream([f"FastAPI 很快。{DELTA_MARK}"], tracker)

    assert lead != delta, "precondition: the numbers really do differ here"
    split = _split_snapshot_lead(lead, delta)
    assert split == ("", ""), f"replayed opening would be delivered twice: {split!r}"


def test_split_snapshot_lead_still_refuses_a_divergent_run():
    """The footnote tolerance must not become a licence to align anything."""
    assert _split_snapshot_lead("Alpha [1] 中间", "Alpha [2] 别处") is None
    assert _split_snapshot_lead("Alpha [1]", "Omega [1]") is None


def test_split_snapshot_lead_keeps_exact_prefix_behaviour():
    assert _split_snapshot_lead("Alpha Omega", "Alpha ") == ("Omega", "")
    assert _split_snapshot_lead("Alpha", "Alpha Omega") == ("", " Omega")
    assert _split_snapshot_lead("Alpha", "Omega") is None


def test_snapshot_and_delta_sharing_a_map_stay_identical():
    """The whole point of applying the tracker to a snapshot: the two texts a
    reader may see must remain comparable."""
    tracker = CitationTracker()
    tracker.note_source(SHARED_REFERENCE)
    assert _stream([f"Alpha {DELTA_MARK}"], tracker) == "Alpha [4]"
    assert tracker.apply(f"Alpha {SNAPSHOT_MARK}") == "Alpha [4]"


def test_message_content_uses_the_delta_mapping_for_a_snapshot():
    """`_message_content` is what the snapshot path calls; cleaning it with a
    different rule than the deltas is what broke the prefix in the first place."""
    tracker = CitationTracker()
    tracker.note_source(SHARED_REFERENCE)
    _stream([f"Alpha {DELTA_MARK} Omega"], tracker)

    entry = {"author": "bot", "text": f"Alpha {SNAPSHOT_MARK} Omega"}
    assert _message_content(entry, tracker) == "Alpha [4] Omega"


@pytest.mark.parametrize("metadata_first", [False, True])
def test_reused_label_never_aliases_distinct_full_reference_ids(metadata_first):
    sources = [
        {"ref_key": "1-aaaaaa", "ref_id": "turn1search0", "label": "1", "url": "https://a.example"},
        {"ref_key": "1-bbbbbb", "ref_id": "turn1search1", "label": "1", "url": "https://b.example"},
    ]
    tracker = CitationTracker()
    if metadata_first:
        for source in sources:
            tracker.note_source(source)
    text = _stream(["A<cite>turn1search0</cite> B<cite>turn1search1</cite>"], tracker)
    if not metadata_first:
        for source in sources:
            tracker.note_source(source)

    assert text == "A[1] B[2]"
    assert tracker.apply("A【1-aaaaaa】 B【1-bbbbbb】") == text
    aligned = aligned_url_sources_for_stream(sources, tracker)
    annotations = openai_url_citations_from_sources(text, aligned)
    assert [(a["url"], text[a["start_index"]:a["end_index"]]) for a in annotations] == [
        ("https://a.example", "[1]"), ("https://b.example", "[2]"),
    ]


@pytest.mark.parametrize("metadata_first", [False, True])
def test_unique_numeric_label_still_links_bare_and_full_renderings(metadata_first):
    tracker = CitationTracker()
    if metadata_first:
        tracker.note_source(SHARED_REFERENCE)
    text = _stream(["A【4】"], tracker)
    if not metadata_first:
        tracker.note_source(SHARED_REFERENCE)

    assert text == "A[4]"
    assert tracker.apply("A<cite>turn1search4</cite>") == text
    assert tracker.apply("A【4-6f710b】") == text
    assert tracker.count == 1


def test_late_conflicting_label_revokes_only_the_numeric_alias():
    first = {"ref_key": "1-aaaaaa", "ref_id": "turn1search0", "label": "1", "url": "https://a.example"}
    second = {"ref_key": "1-bbbbbb", "ref_id": "turn1search1", "label": "1", "url": "https://b.example"}
    tracker = CitationTracker()
    tracker.note_source(first)
    assert _stream(["A【1-aaaaaa】"], tracker) == "A[1]"
    tracker.note_source(second)

    assert _stream([" B<cite>turn1search1</cite>"], tracker) == " B[2]"
    assert tracker.apply("A<cite>turn1search0</cite> B【1-bbbbbb】") == "A[1] B[2]"


def test_same_frame_url_metadata_enrichment_preserves_body_identity():
    payload = {"sourceAttributions": [
        {"providerDisplayName": "A", "seeMoreUrl": "https://a.example"},
        {"providerDisplayName": "B", "seeMoreUrl": "https://b.example"},
        {"providerDisplayName": "A", "seeMoreUrl": "https://a.example", "label": "1",
         "referenceMetadata": {"referenceId": "turn1search0"}},
        {"providerDisplayName": "B", "seeMoreUrl": "https://b.example", "label": "2",
         "referenceMetadata": {"referenceId": "turn1search1"}},
    ]}
    tracker = CitationTracker()
    text = _stream(["B<cite>turn1search1</cite> A<cite>turn1search0</cite>"], tracker)
    sources = extract_source_attributions(payload)
    for source in sources:
        tracker.note_source(source)
    aligned = aligned_url_sources_for_stream(sources, tracker)
    annotations = openai_url_citations_from_sources(text, aligned)

    assert len(sources) == 2
    assert [(a["url"], text[a["start_index"]:a["end_index"]]) for a in annotations] == [
        ("https://b.example", "[1]"), ("https://a.example", "[2]"),
    ]


def test_same_url_does_not_overwrite_conflicting_reference_identities():
    sources = extract_source_attributions({"sourceAttributions": [
        {"providerDisplayName": "A", "seeMoreUrl": "https://shared.example", "label": "1",
         "referenceMetadata": {"referenceId": "turn1search0"}},
        {"providerDisplayName": "B", "seeMoreUrl": "https://shared.example", "label": "1",
         "referenceMetadata": {"referenceId": "turn1search1"}},
    ]})
    tracker = CitationTracker()
    for source in sources:
        tracker.note_source(source)
    text = _stream(["A<cite>turn1search0</cite> B<cite>turn1search1</cite>"], tracker)

    assert text == "A[1] B[2]"
    assert [s["ref_id"] for s in sources] == ["turn1search0", "turn1search1"]
    annotations = openai_url_citations_from_sources(text, aligned_url_sources_for_stream(sources, tracker))
    assert [text[a["start_index"]:a["end_index"]] for a in annotations] == ["[1]", "[2]"]


def test_late_label_conflict_leaves_an_earlier_bare_marker_unbound():
    first = {"ref_key": "1-aaaaaa", "ref_id": "turn1search0", "label": "1", "url": "https://a.example"}
    second = {"ref_key": "1-bbbbbb", "ref_id": "turn1search1", "label": "1", "url": "https://b.example"}
    tracker = CitationTracker()
    tracker.note_source(first)
    text = _stream(["Ambiguous【1】"], tracker)
    tracker.note_source(second)
    aligned = aligned_url_sources_for_stream([first, second], tracker, text=text)

    assert text == "Ambiguous[1]"
    annotations = openai_url_citations_from_sources(text, aligned)
    assert all(a["start_index"] == a["end_index"] == len(text) for a in annotations)
    assert [s["footnote"] for s in aligned] == [2, 3]


def test_url_only_sources_with_one_numeric_label_remain_ambiguous():
    sources = [
        {"label": "1", "url": "https://a.example"},
        {"label": "1", "url": "https://b.example"},
    ]
    tracker = CitationTracker()
    for source in sources:
        tracker.note_source(source)
    text = _stream(["Ambiguous【1】"], tracker)
    annotations = openai_url_citations_from_sources(text, aligned_url_sources_for_stream(sources, tracker))

    assert text == "Ambiguous[1]"
    assert all(a["start_index"] == a["end_index"] == len(text) for a in annotations)


@pytest.mark.parametrize("source", [
    {"label": "2", "url": "https://public.example"},
    {"ref_key": "2-bbbbbb", "url": "https://public.example"},
])
def test_empty_tracker_uses_explicit_number_without_body_argument(source):
    aligned = aligned_url_sources_for_stream([source], CitationTracker())
    annotation, = openai_url_citations_from_sources("Internal [1], public [2].", aligned)

    assert aligned[0]["footnote"] == 2
    assert annotation["start_index"] == len("Internal [1], public ")


@pytest.mark.parametrize("chunks", [
    ["value = data[1]; Claim <cite>turn1search9</cite>"],
    ["value = data[1]; ", "Claim <cite>turn1search9</cite>"],
])
def test_plain_brackets_reserve_numbers_without_claiming_an_identity(chunks):
    tracker = CitationTracker()
    text = _stream(chunks, tracker)

    assert text == "value = data[1]; Claim [2]"
    assert tracker.keys_in_order == ["turn1search9"]
    assert aligned_url_sources_for_stream([], tracker, text=text) == []


def test_large_literal_bracket_does_not_expand_the_tracker_number_map():
    tracker = CitationTracker()
    text = _stream(["data[1000000000]; Claim <cite>turn1search9</cite>"], tracker)

    assert text == "data[1000000000]; Claim [1]"
    assert tracker.number_of("turn1search9") == 1
    assert tracker.count == 1


def test_reapplying_normalized_numbers_does_not_renumber_full_identities():
    tracker = CitationTracker()
    raw = "A<cite>turn1search0</cite> B<cite>turn1search1</cite>"
    text = tracker.apply(raw)

    assert text == "A[1] B[2]"
    assert tracker.apply(text) == text
    assert tracker.apply(raw) == text


def test_url_acquisition_coalesces_a_previously_url_less_full_identity():
    early = {"ref_key": "1-aaaaaa", "ref_id": "turn1search0", "label": "1", "title": "A"}
    enriched = {**early, "url": "https://a.example"}
    tracker = CitationTracker()
    tracker.note_source(early)
    text = _stream(["Claim <cite>turn1search0</cite>."], tracker)
    aligned = aligned_url_sources_for_stream([early, enriched], tracker, text=text)

    assert text == "Claim [1]."
    assert [(s["footnote"], s["url"]) for s in aligned] == [(1, "https://a.example")]
    annotation, = openai_url_citations_from_sources(text, aligned)
    assert text[annotation["start_index"]:annotation["end_index"]] == "[1]"


def test_bridge_metadata_coalesces_compatible_url_and_id_only_records():
    sources = [
        {"title": "A", "url": "https://a.example", "label": "1"},
        {"title": "A", "ref_id": "turn1search0", "label": "1"},
        {"title": "A", "url": "https://a.example", "ref_id": "turn1search0", "label": "1"},
    ]
    tracker = CitationTracker()
    for source in sources:
        tracker.note_source(source)
    text = _stream(["Claim【1】"], tracker)
    assert tracker.apply("Claim<cite>turn1search0</cite>") == text
    aligned = aligned_url_sources_for_stream(sources, tracker, text=text)

    assert len(aligned) == 1
    assert aligned[0]["footnote"] == 1
    annotation, = openai_url_citations_from_sources(text, aligned)
    assert text[annotation["start_index"]:annotation["end_index"]] == "[1]"


def test_same_frame_url_acquisition_enriches_the_existing_reference():
    sources = extract_source_attributions({"sourceAttributions": [
        {"providerDisplayName": "A", "label": "1", "referenceMetadata": {"referenceId": "turn1search0"}},
        {"providerDisplayName": "A", "label": "1", "seeMoreUrl": "https://a.example",
         "referenceMetadata": {"referenceId": "turn1search0"}},
    ]})
    tracker = CitationTracker()
    for source in sources:
        tracker.note_source(source)
    text = _stream(["Claim<cite>turn1search0</cite>"], tracker)
    aligned = aligned_url_sources_for_stream(sources, tracker, text=text)

    assert len(sources) == 1
    assert [(s["footnote"], s["url"]) for s in aligned] == [(1, "https://a.example")]


@pytest.mark.parametrize("raw,expected", [
    ("Claim <cite>turn1search0</cite>. data[1];", "Claim [1]. data[1];"),
    ("data[1]; Claim <cite>turn1search0</cite>.", "data[1]; Claim [2]."),
    ("A【1-aaaaaa】 B<cite>turn1search1</cite>.", "A[1] B[2]."),
])
def test_literal_reservations_and_mixed_markers_follow_text_order(raw, expected):
    assert _stream([raw]) == expected
    for split in range(1, len(raw)):
        assert _stream([raw[:split], raw[split:]]) == expected, split


def test_repeated_label_metadata_uses_bounded_identity_lookups(monkeypatch):
    import m365_copilot_openai_proxy.substrate_parse as parser

    calls = 0
    merge = parser._merge_source_attribution

    def counted_merge(existing, incoming):
        nonlocal calls
        calls += 1
        return merge(existing, incoming)

    monkeypatch.setattr(parser, "_merge_source_attribution", counted_merge)
    sources = [
        {"ref_key": f"1-{i:06x}", "ref_id": f"turn1search{i}", "label": "1", "url": f"https://example/{i}"}
        for i in range(128)
    ]
    tracker = CitationTracker()
    for _ in range(2):
        for source in sources:
            tracker.note_source(source)
    assert calls <= 12 * len(sources)
    text = _stream(["A<cite>turn1search0</cite> B<cite>turn1search127</cite>"], tracker)
    aligned = aligned_url_sources_for_stream(sources, tracker, text=text)
    annotations = openai_url_citations_from_sources(text, aligned)
    assert [(a["url"], text[a["start_index"]:a["end_index"]]) for a in annotations[:2]] == [
        ("https://example/0", "[1]"), ("https://example/127", "[2]"),
    ]
