from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from .media_proxy import normalize_m365_media_text
from .reasoning import is_reasoning_entry
from .tone_options import tone_server_interpreter
from .tool_call_parser import _NO_TOOL_MARKER

# M365 injects private-use citation markers in streamed and final text, e.g.
#   [label](\ue200cite\ue202turn1file1\ue201)
# or bare  \ue200cite\ue202...\ue201  / PUA-wrapped "cite" runs.
# These are not useful in OpenAI-compatible clients and break dedupe signatures.
_MARKDOWN_CITE_RE = re.compile(
    r"\[[^\]]*\]\(\s*[\uE000-\uF8FF]*cite[\uE000-\uF8FF][^\)]*\)",
    re.IGNORECASE,
)
# Bare markers look like: \ue200cite\ue202turn1file1\ue201
# Only consume PUA + ascii id pieces, never trailing prose/CJK.
#
# One marker can carry SEVERAL ids, and the separator between them is another
# private-use character: \ue200cite\ue202turn4search10\ue202turn4search12\ue201
# The id run therefore repeats without bound, and consuming it once left every id
# after the first sitting in the delivered text ("...直接触发这个错误。
# turn4search10turn4search12"). The run is `*` rather than `+` so a delta that
# ends right after the word "cite" still loses the opener instead of shipping it.
_BARE_PUA_CITE_RE = re.compile(
    r"[\uE000-\uF8FF]cite(?:[\uE000-\uF8FF][A-Za-z0-9_]*)*",
    re.IGNORECASE,
)

# The closing half of a marker whose opening half went out in an earlier delta.
# Upstream splits its stream mid-marker and the streaming path cleans each delta
# alone (substrate_client feeds every writeAtCursor straight in), so the halves
# are never in hand together: the rule above strips "\ue200cite\ue202" on its
# own, and without this one the remainder ("turn3search5\ue201") matched nothing
# and reached the client butted against the prose. Anchored on the trailing
# private-use delimiter rather than on the id shape alone, so prose that merely
# names an id -- a bug report, this project's own docs -- keeps the word it is
# about. One id per match is all this needs: the substitution is global, so a
# tail that orphaned a whole run of ids is taken one id at a time. A split
# *inside* an id still leaks that fragment; closing that needs cross-delta
# buffering, not a wider pattern.
_ORPHAN_CITE_TAIL_RE = re.compile(
    r"turn\d+[a-z]+\d*[\uE000-\uF8FF]",
    re.IGNORECASE,
)

# Two further renderings, both seen within a SINGLE live turn: the streamed
# deltas carried literal <cite> tags while the cumulative snapshot of the very
# same sentences carried bracket marks.
#
#   deltas:   FastAPI 性能媲美 Node.js。<cite>turn1search7</cite>
#   snapshot: FastAPI 性能媲美 Node.js。【4-6f710b】
#
# Both are bounded to citation-ID shapes rather than matching the delimiters
# outright, because both delimiters have legitimate uses that must survive:
# HTML's <cite> marks the title of a work, and 【】 is ordinary CJK punctuation
# for emphasis. A citation id never contains spaces, and a bracket marker always
# leads with "<digits>-", so real prose matches neither pattern.
_LITERAL_CITE_TAG_RE = re.compile(r"<cite>[A-Za-z0-9_,\-]*</cite>", re.IGNORECASE)
_BRACKET_CITE_RE = re.compile(r"【\d+-[0-9a-z]{3,}】", re.IGNORECASE)

# --- fork: citation tracker + source attributions ---
_SRC_PUA = "-"
_SRC_MARKDOWN_CITE_RE = re.compile(
    rf"\[([^\]]*)\]\(\s*([{_SRC_PUA}]*cite[{_SRC_PUA}][^)]*)\)",
    re.IGNORECASE,
)
# Require a non-empty ascii id so "cite" alone is NOT consumed (held instead).
_SRC_BARE_PUA_CITE_RE = re.compile(
    rf"[{_SRC_PUA}]cite[{_SRC_PUA}]([A-Za-z0-9_]+)[{_SRC_PUA}]?",
    re.IGNORECASE,
)
# Leftover after a split ate the cite opener: "turn1search6" or plain "turn1search6".
_SRC_LOOSE_TURN_CITE_RE = re.compile(
    rf"(?:[{_SRC_PUA}])?(turn\d+(?:search|file|news|image|video|base|knowledge|gpt|cid|doc)\d+)(?:[{_SRC_PUA}])?",
    re.IGNORECASE,
)
# Chinese-bracket web cites used by some M365 answers: 【1-1fd57a】 or 【3】.
_SRC_BRACKET_CITE_RE = re.compile(
    r"【\s*(\d{1,3})\s*(?:[-–—]\s*([0-9a-fA-F]{3,16}))?\s*】"
)
_SRC_SYDNEY_FOOTNOTE_RE = re.compile(r"\[\^(\d+)\^\]")
_SRC_CITE_KEY_NOISE_RE = re.compile(rf"[{_SRC_PUA}]+")

# Incomplete tails we must HOLD across stream deltas (not emit raw).
_SRC_INCOMPLETE_CITE_TAIL_RE = re.compile(
    rf"(?:"
    rf"\[[^\]]*\]\(\s*[{_SRC_PUA}]*cite[{_SRC_PUA}][^)]*$"  # open markdown cite
    rf"|[{_SRC_PUA}]cite[{_SRC_PUA}][A-Za-z0-9_]*$"          # open bare PUA cite
    rf"|[{_SRC_PUA}]cite$"
    rf"|[{_SRC_PUA}]$"                                    # lone PUA starter
    rf"|\[$"                                          # lone "["
    rf"|\[[^\]]*$"                                    # open "[" label
    rf")",
    re.IGNORECASE,
)



def clean_m365_citations(text: str, tracker: "CitationTracker | None" = None) -> str:
    """Strip M365 citation markers from model text.

    When ``tracker`` is provided, markers become stable ``[n]`` citations.

    Safe on partial stream deltas, but by handling each half rather than by
    waiting for both: the streaming path cleans every delta on its own, so a
    marker split mid-way is never in hand whole. The PUA rule takes an opening
    half alone and _ORPHAN_CITE_TAIL_RE takes the closing half alone. Leaving
    either for a closing delimiter that arrives in a different call is what put
    bare ids in front of readers.
    """
    if tracker is not None:
        return tracker.clean(text)
    if not text:
        return ""
    # Fast path: most chunks carry none of the marker shapes. "【" has to be part
    # of this test -- a bracket marker contains neither the word "cite" nor a
    # private-use character, so keying the fast path on those alone let every
    # bracket marker through untouched.
    if "cite" not in text.lower() and "【" not in text and not any("\ue000" <= c <= "\uf8ff" for c in text):
        return text
    cleaned = _MARKDOWN_CITE_RE.sub("", text)
    cleaned = _BARE_PUA_CITE_RE.sub("", cleaned)
    cleaned = _ORPHAN_CITE_TAIL_RE.sub("", cleaned)
    cleaned = _LITERAL_CITE_TAG_RE.sub("", cleaned)
    cleaned = _BRACKET_CITE_RE.sub("", cleaned)
    # Collapse whitespace left by removed markers (keep newlines).
    cleaned = re.sub(r"[^\S\n]{2,}", " ", cleaned)
    return cleaned



def _normalize_cite_key(raw: str) -> str:
    """Collapse a PUA cite target to a stable ascii key (e.g. ``turn1search0``)."""
    key = _SRC_CITE_KEY_NOISE_RE.sub("", raw or "")
    key = re.sub(r"^cite", "", key, flags=re.IGNORECASE)
    key = re.sub(r"[^A-Za-z0-9_]+", "", key).lower()
    return key



def _has_cite_noise(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    if "cite" in lower or "turn" in lower and "search" in lower:
        return True
    if "[^" in text or "【" in text:
        return True
    return any("" <= c <= "" for c in text)



class CitationTracker:
    """Track streamed cite markers and renumber them as ``[n]``.

    Holds incomplete openers across ``clean()`` calls so split deltas cannot
    leak raw ``turn1search6`` / lone PUA bytes / bare ``cite`` to the client.
    """

    def __init__(self) -> None:
        self._key_to_num: dict[str, int] = {}
        self._order: list[str] = []
        self._hold = ""

    def _num_for(self, key: str, preferred: int | None = None) -> int:
        normalized = key or f"anon{len(self._order)}"
        if normalized in self._key_to_num:
            return self._key_to_num[normalized]
        if preferred is not None and preferred > 0 and preferred not in self._key_to_num.values():
            while len(self._order) < preferred - 1:
                placeholder = f"pad{len(self._order)}"
                self._order.append(placeholder)
                self._key_to_num[placeholder] = len(self._order)
            if len(self._order) == preferred - 1:
                self._order.append(normalized)
                self._key_to_num[normalized] = preferred
                return preferred
        self._key_to_num[normalized] = len(self._order) + 1
        self._order.append(normalized)
        return self._key_to_num[normalized]

    @property
    def count(self) -> int:
        return len([k for k in self._order if not k.startswith("pad")])

    @property
    def keys_in_order(self) -> list[str]:
        return [k for k in self._order if not k.startswith("pad")]

    def _split_incomplete(self, text: str) -> tuple[str, str]:
        """Return (safe_prefix, hold_suffix) for cite openers still in progress."""
        if not text:
            return "", ""
        # Longest incomplete tails first. MUST hold partial turn/search tokens
        # like "turn1s" / "turn1search" mid-id, otherwise chunked streams leak them.
        patterns = [
            r"\[[^\]]*\]\(\s*[-]*cite[-][^)]*$",
            r"\[[^\]]*\]\(\s*$",
            r"[-]cite[-][A-Za-z0-9_]*$",
            r"[-]+cite$",
            r"(?:^|[^A-Za-z])cite$",
            # full or partial sydney turn ids, optionally after a footnote
            r"(?:\[\^?\d+\^?\])?turn\d*(?:search|file|news|image|video|base|knowledge|gpt|cid|doc)?[A-Za-z0-9_]*$",
            r"turn\d*[A-Za-z0-9_]*$",
            r"【[^】]*$",
            r"\[\^[^\]]*$",
            r"\[[^\]]*$",
            r"[-]+$",
        ]
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match and match.end() == len(text):
                start = match.start()
                if pat.startswith("(?:^|[^A-Za-z])"):
                    if start < len(text) and text[start].lower() != "c":
                        start += 1
                # Keep a completed footnote in the safe prefix when the hold is
                # only the trailing turn residual: "[1]turn1s" → ("[1]", "turn1s").
                held = text[start:]
                if held.startswith("[") and "turn" in held.lower():
                    foot = re.match(r"\[\^?\d+\^?\]", held)
                    if foot:
                        start += foot.end()
                return text[:start], text[start:]
        return text, ""

    def clean(self, text: str) -> str:
        """Replace complete cite patterns with label + ``[n]`` markers."""
        if text is None:
            text = ""
        text = f"{self._hold}{text}"
        self._hold = ""
        if not text:
            return ""

        text, self._hold = self._split_incomplete(text)
        if not text:
            return ""
        if not _has_cite_noise(text):
            return text

        def md_repl(match: re.Match[str]) -> str:
            label = (match.group(1) or "").strip()
            key = _normalize_cite_key(match.group(2) or "")
            num = self._num_for(key)
            return f"{label}[{num}]" if label else f"[{num}]"

        def bare_repl(match: re.Match[str]) -> str:
            key = _normalize_cite_key(match.group(1) or match.group(0) or "")
            num = self._num_for(key)
            return f"[{num}]"

        def loose_repl(match: re.Match[str]) -> str:
            key = _normalize_cite_key(match.group(1) or match.group(0) or "")
            num = self._num_for(key)
            return f"[{num}]"

        def bracket_repl(match: re.Match[str]) -> str:
            idx = int(match.group(1))
            suffix = (match.group(2) or "").lower()
            key = f"bracket{idx}-{suffix}" if suffix else f"bracket{idx}"
            num = self._num_for(key, preferred=idx)
            return f"[{num}]"

        cleaned = _SRC_MARKDOWN_CITE_RE.sub(md_repl, text)
        cleaned = _SRC_BARE_PUA_CITE_RE.sub(bare_repl, cleaned)
        # If a footnote is immediately followed by the same turn token residual
        # (common when a prior delta already emitted [n] and a later delta
        # carries turnNsearchM), drop the residual instead of doubling.
        cleaned = re.sub(
            rf"(\[\^?\d+\^?\])\s*[{_SRC_PUA}]?turn\d+(?:search|file|news|image|video|base|knowledge|gpt|cid|doc)\d+[{_SRC_PUA}]?",
            r"\1",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = _SRC_LOOSE_TURN_CITE_RE.sub(loose_repl, cleaned)
        cleaned = _SRC_BRACKET_CITE_RE.sub(bracket_repl, cleaned)
        cleaned = _SRC_SYDNEY_FOOTNOTE_RE.sub(r"[\1]", cleaned)
        cleaned = re.sub(r"[-]+", "", cleaned)
        cleaned = re.sub(r"[^\S\n]{2,}", " ", cleaned)
        # Re-hold if replacements left a new incomplete tail.
        cleaned, more_hold = self._split_incomplete(cleaned)
        self._hold = more_hold + self._hold
        return cleaned

    def flush(self) -> str:
        """Force-emit any held incomplete tail (best-effort, never leaks tokens)."""
        if not self._hold:
            return ""
        held, self._hold = self._hold, ""
        held = _SRC_MARKDOWN_CITE_RE.sub(lambda m: (m.group(1) or "").strip(), held)
        held = _SRC_BARE_PUA_CITE_RE.sub("", held)
        held = _SRC_LOOSE_TURN_CITE_RE.sub("", held)
        held = _SRC_BRACKET_CITE_RE.sub("", held)
        held = re.sub(r"[-]+", "", held)
        held = re.sub(r"turn\d+\w*", "", held, flags=re.I)
        held = re.sub(r"\bcite\b", "", held, flags=re.I)
        held = re.sub(r"\[[^\]]*$", "", held)
        held = re.sub(r"【[^】]*$", "", held)
        return held



def _capture_suspicious_response_event(sink, msg: dict) -> None:
    if sink is None:
        return
    try:
        probe = json.dumps(msg, ensure_ascii=False).lower()
    except (TypeError, ValueError):
        return
    if any(
        key in probe
        for key in (
            "image",
            "card",
            "render",
            "attachment",
            "contenturl",
            "downloadurl",
            "filetoken",
            "thumbnail",
            "generatedgraphic",
            "generatedaudio",
            "asyncgw",
            "citation",
        )
    ):
        sink(msg)


def _dedupe_signature(text: str) -> str:
    """Normalize text down to the part that identifies WHAT was said.

    Every form a URL can take must collapse to the same thing, because the two
    sides of a dedupe comparison reach us through different pipelines: streamed
    deltas are only citation-cleaned, while the upstream fallback also goes
    through ``normalize_m365_media_text``, which rewrites a bare image URL into
    ``![image](url)``. Leaving bare URLs (or the ``!`` of an image link) in the
    signature made the same sentence produce two different signatures, so dedupe
    missed the restatement and the answer was emitted twice.
    """
    normalized = clean_m365_citations(text)
    normalized = re.sub(r"!?\[[^\]]*\]\(\s*https?://[^\)]*\)", "", normalized)
    normalized = re.sub(r"`\s*https?://[^`]*`", "", normalized)
    # Bounded to URL-legal characters, not \S+: a URL butted straight against
    # CJK prose ("https://x/a.png完成") would otherwise swallow the prose too and
    # make dedupe drop real content.
    normalized = re.sub(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


# Share of the fallback signature that must already appear in the streamed text
# for the fallback to count as a restatement rather than new content.
_RESTATEMENT_COVERAGE = 0.9


def _signature_coverage(streamed_sig: str, fallback_sig: str) -> float:
    """Fraction of ``fallback_sig`` that also appears in ``streamed_sig``.

    Uses matching blocks rather than a plain substring test so a fallback that
    only differs from the streamed answer in scattered spots (one swapped
    character, a changed punctuation mark, a re-worded clause) still scores as
    almost fully covered.
    """
    if not fallback_sig:
        return 1.0
    if not streamed_sig:
        return 0.0
    matcher = SequenceMatcher(None, streamed_sig, fallback_sig, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / len(fallback_sig)


# Anchor sizes for locating the end of the delivered text inside the fallback.
# Long enough that a match is not coincidence, short enough that a turn which
# streamed only a few words can still be anchored.
_TAIL_ANCHOR_MAX = 200
_TAIL_ANCHOR_MIN = 24

# Minimum size for a matching run to count as a trustworthy alignment point. Same
# order as the exact anchor, for the same reason: shorter runs recur by chance (a
# shared full stop, a markdown ``---``), and aligning on one either swallows real
# content or appends text the reader already has.
_ALIGN_BLOCK_MIN = 24

# Share of the fallback the delivered text must account for before "the stream
# already reached the end" is a plausible reading of an end-to-end alignment. A
# stream missing most of the answer is a truncated one, whatever its last
# character happens to match.
_REACHED_END_MIN_SHARE = 0.5


def _aligned_tail(streamed_text: str, fallback_text: str) -> str | None:
    """Locate the delivered position by approximate alignment, or ``None`` when no
    run is solid enough to align on.

    Handles the one case the exact end anchor cannot: a stream that lost a run
    NEAR ITS END. The delivered tail is then a splice of the text either side of
    the gap -- a string that occurs nowhere in the authoritative answer -- so
    ``rfind`` misses at every anchor length. Falling through to the common-prefix
    trim then appended everything from the FIRST gap onward; measured on the shape
    of the live capture, 288 characters appended against 125 lost, which is the
    reader being shown the middle of the answer a second time.
    """
    blocks = [
        block
        for block in SequenceMatcher(
            None, streamed_text, fallback_text, autojunk=False
        ).get_matching_blocks()
        if block.size
    ]
    if not blocks:
        return None
    # A final run that terminates BOTH texts means the stream reached the end of
    # the answer. Whatever sits before that run is a hole, and the reader already
    # has the text after it, so appending would duplicate -- and land out of order
    # on top of it. Nothing to add.
    final = blocks[-1]
    if (
        final.a + final.size == len(streamed_text)
        and final.b + final.size == len(fallback_text)
        and len(streamed_text) >= _REACHED_END_MIN_SHARE * len(fallback_text)
    ):
        return ""
    solid = [block for block in blocks if block.size >= _ALIGN_BLOCK_MIN]
    if not solid:
        return None
    last = solid[-1]
    return fallback_text[last.b + last.size :]


def _fallback_tail_after_delivered(streamed_text: str, fallback_text: str) -> str | None:
    """Return the part of ``fallback_text`` that follows the END of what was
    already delivered, or ``None`` when the end cannot be located.

    Anchoring on the end is what keeps a stream that lost text in the MIDDLE from
    having everything after the gap repeated. ``_common_prefix_len`` stops dead at
    the first gap, so trimming by common prefix appended the whole rest of the
    answer a second time -- observed live as an answer with holes punched through
    its middle followed by a verbatim slab of everything from the first hole
    onward. The already-delivered gap cannot be repaired (that text is long gone
    to the client), but it must not cost the reader the answer twice.

    ``rfind`` so a phrase that recurs earlier in the answer resolves to the most
    recent occurrence, which is where the stream actually stands. When the gap
    falls inside the anchor window itself no exact match exists at all, and
    ``_aligned_tail`` takes over.
    """
    limit = min(len(streamed_text), _TAIL_ANCHOR_MAX)
    for size in range(limit, _TAIL_ANCHOR_MIN - 1, -1):
        anchor = streamed_text[-size:]
        position = fallback_text.rfind(anchor)
        if position >= 0:
            return fallback_text[position + size:]
    return _aligned_tail(streamed_text, fallback_text)


def _cumulative_catchup(streamed_text: str, cumulative_text: str) -> str:
    """Text to append so the stream catches up to a cumulative snapshot.

    M365 sends two views of the same turn: ``writeAtCursor`` deltas, which are
    incremental, and ``messages`` snapshots, which restate the whole answer so
    far. When the deltas skip ahead the snapshot is the only place the skipped run
    exists, and appending it AS SOON AS the snapshot lands keeps the answer in
    order -- waiting for the final frame would append it after everything else.

    Deliberately conservative: only an exact prefix relationship counts. The two
    views do not always render citations the same way (one live capture had
    ``【4-6f710b】`` in the snapshot against ``<cite>turn1search4</cite>`` in the
    deltas), and guessing at an alignment across that difference risks emitting a
    run the reader already has. Anything less certain is left to the final
    reconciliation, which has the authoritative full text to work from.
    """
    if not cumulative_text or not streamed_text:
        return ""
    if cumulative_text.startswith(streamed_text):
        return cumulative_text[len(streamed_text):]
    return ""


def _split_snapshot_lead(lead: str, delta: str) -> tuple[str, str] | None:
    """Reconcile an incoming delta against text already delivered from a snapshot.

    ``lead`` is the run a cumulative snapshot let us deliver BEFORE the deltas got
    there. Deltas may then replay that same run from the top -- one live turn sent
    a snapshot of the opening and then streamed that opening again as deltas -- and
    forwarding them would tell the reader the same sentences twice.

    Returns ``(remaining_lead, text_to_emit)``, or ``None`` when the delta is
    unrelated to the lead and must be forwarded as-is:

    * delta inside the lead   -> consumed, emit nothing, shrink the lead
    * delta reaches past it   -> lead consumed, emit only the new remainder

    Only exact matches count. This is safe against the "repeated fragment" trap
    that ``_dedupe_repeated_delta`` warns about (a formula's ``2a_1``, a closing
    ``}``) because the lead is non-empty only in the brief window after a snapshot
    ran ahead of the deltas, and every character it covers has provably been sent.
    """
    if not lead or not delta:
        return None
    if lead.startswith(delta):
        return lead[len(delta):], ""
    if delta.startswith(lead):
        return "", delta[len(lead):]
    return None


def _final_fallback_remainder(streamed_text: str, fallback_text: str) -> str:
    """Final (t==3) reconciliation ONLY: return the tail of the whole fallback
    answer that has not been streamed yet.

    This compares the ENTIRE streamed-so-far text against the ENTIRE fallback
    answer and is meant to run exactly once, after the stream ends. Do NOT use
    it as a per-delta guard: its ``fallback in streamed`` / signature-subset
    branches would drop small repeated fragments (``2a_1``, a closing ``}``)
    and corrupt formulas or code. Per-delta dedupe belongs in
    ``_dedupe_repeated_delta``.

    The upstream fallback is the server's authoritative full message for the
    turn, so it regularly restates text we already streamed with cosmetic
    differences: ``_message_content`` runs ``normalize_m365_media_text`` over it
    (a bare image URL becomes ``![image](url)``) while streamed deltas are only
    citation-cleaned, and M365 sometimes re-words a clause in the final frame.
    Neither startswith/contains nor a strict signature-subset test catches those,
    so emitting the fallback verbatim appended the WHOLE answer a second time --
    the "reply shows up twice" bug. Fall back to a coverage ratio instead: a
    fallback that is already ``_RESTATEMENT_COVERAGE`` covered by the stream adds
    nothing, and a partially-covered one is trimmed to whatever follows the END of
    the delivered text (see ``_fallback_tail_after_delivered``) so neither its
    already-streamed head nor a run the stream skipped is sent twice.
    """
    if not fallback_text:
        return ""
    if not streamed_text:
        return fallback_text
    if fallback_text.startswith(streamed_text):
        return fallback_text[len(streamed_text):]
    if fallback_text in streamed_text:
        return ""
    streamed_sig = _dedupe_signature(streamed_text)
    fallback_sig = _dedupe_signature(fallback_text)
    if streamed_sig and fallback_sig and (streamed_sig in fallback_sig or fallback_sig in streamed_sig):
        return ""
    if _signature_coverage(streamed_sig, fallback_sig) >= _RESTATEMENT_COVERAGE:
        return ""
    # Partially covered: append only what follows the END of the delivered text.
    # Trimming by common PREFIX was wrong whenever the stream lost a run from its
    # middle -- the prefix stops at the gap, so everything after the gap came back
    # as a duplicate.
    tail = _fallback_tail_after_delivered(streamed_text, fallback_text)
    if tail is not None:
        return tail
    prefix = _common_prefix_len(streamed_text, fallback_text)
    return fallback_text[prefix:] if prefix else fallback_text


def _common_prefix_len(left: str, right: str) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


def _dedupe_repeated_delta(streamed_text: str, delta: str) -> str:
    r"""Per-delta guard for the SSE response layer (response_helpers).

    ``chat_stream`` already yields a deduplicated incremental stream (the t==3
    fallback reconciliation happens inside substrate_client). As defense in
    depth the response layer must still drop a delta that RE-EMITS the entire
    answer so far -- observed with media answers, where the model restates the
    whole message swapping a raw backtick-wrapped URL for a
    ``[text](cite...)`` link.

    It must NOT drop a delta merely because its short text already appeared
    earlier: math and code answers legitimately repeat tokens such as ``2a_1``,
    ``+ 3d = 6`` or a closing ``}`` across separate deltas. Dropping those
    corrupts formulas (``\\frac{8}{2}(2a_1+7d)`` losing ``2a_1``) and silently
    deletes code.

    Rule: drop the delta only when its dedupe-signature is a SUPERSET of the
    whole streamed-so-far signature (the delta reproduces everything already
    emitted, modulo URL/citation noise). Incremental fragments never satisfy
    this because their signature is a small subset, not a superset.
    """
    if not delta or not streamed_text:
        return delta
    streamed_sig = _dedupe_signature(streamed_text)
    delta_sig = _dedupe_signature(delta)
    if streamed_sig and delta_sig and streamed_sig in delta_sig:
        return ""
    return delta


# messageTypes that narrate what the turn is DOING rather than carrying the answer.
# The reverse scan that fills `fallback_text` used to take the last non-user entry
# whatever it was, so any of these could become the turn's answer-of-record.
#
# Measured on live ChatHub (2026-09-01, .probe/fallback_shapes.py, three
# search-triggering turns): the answer always arrives with NO messageType and
# `contentOrigin: "DeepLeo"` (24 wins), while every non-answer that won the scan was
# a Progress frame -- `ChainOfThoughtSummary` reasoning transcript (6),
# `Searching...` (6), `EarlyProgress`/"Gathering details..." (3) -- plus an empty
# `ReferencesListComplete` (3). One of those transcripts shipped to a client:
# .probe/cot_leak.py turn P2 delivered `**Considering SSE vs WebSocket...**` appended
# to the answer, because it was the last entry in the completion frame.
#
# Deny-list rather than an allow-list of answer types on purpose: the answer's own
# shape is "no messageType at all", so an allow-list would have to guess at every
# type an answer might one day arrive under, and guessing wrong DROPS THE ANSWER --
# a far worse failure than letting one narration line through. Refusal detection is
# unaffected for the same reason: the canned refusal carries `BotConnection` with no
# messageType, so it still wins the scan and still raises.
_NON_ANSWER_MESSAGE_TYPES = frozenset({
    "Progress",
    "ReferencesListComplete",
    "InternalSearchQuery",
    "InternalLoaderMessage",
    "SearchQuery",
    "SemanticSerp",
    "AdsQuery",
    "GenerateContentQuery",
    "DeveloperLogs",
    "Suggestion",
})


def _is_answer_entry(entry: dict) -> bool:
    """Whether a bot message may be taken as (part of) the turn's answer.

    Two independent signals, because they fail differently. `messageType` is the
    one measured to separate answers from narration across every observed shape.
    `addToChainOfThought` is checked as well so a build that moves the reasoning
    transcript to a different messageType still cannot land in the answer -- that
    flag means "this is reasoning about the answer" no matter what carries it.

    ponytail: an answer arriving under a denied messageType would be skipped. Nothing
    in the live capture does that, and the t==3 refusal path plus the delta stream are
    both independent of this, so the visible cost would be a missing fallback on a
    turn that streamed nothing, not a wrong answer.
    """
    if bool(entry.get("addToChainOfThought")):
        return False
    if str(entry.get("contentOrigin") or "") == "ChainOfThoughtSummary":
        return False
    return str(entry.get("messageType") or "") not in _NON_ANSWER_MESSAGE_TYPES


def _message_content(entry: dict) -> str:
    text = clean_m365_citations(normalize_m365_media_text(str(entry.get("text") or "")))
    image_urls = _extract_image_urls(entry)
    if image_urls and _is_image_loading_placeholder(text):
        text = ""
    image_markdown = [_image_markdown(url) for url in image_urls]
    parts = [part for part in [text, *image_markdown] if part]
    return "\n\n".join(parts)


def _is_image_loading_placeholder(text: str) -> bool:
    return text.strip().lower() == "loading image"


def _image_markdown(url: str) -> str:
    return f"![image]({url})"


def _extract_image_urls(value: object) -> list[str]:
    urls: list[str] = []

    def add(url: object) -> None:
        if not isinstance(url, str):
            return
        cleaned = url.strip().strip("`").strip()
        if not cleaned.startswith(("http://", "https://")):
            return
        if cleaned not in urls:
            urls.append(cleaned)

    def walk(node: object, image_context: bool = False) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item, image_context)
            return
        if isinstance(node, str):
            if image_context:
                add(node)
            return
        if not isinstance(node, dict):
            return
        if is_reasoning_entry(node):
            return

        type_value = str(node.get("type") or node.get("contentType") or node.get("mediaType") or "").lower()
        kind_value = str(node.get("kind") or node.get("role") or "").lower()
        local_image_context = image_context or type_value == "image" or type_value.startswith("image/") or "image" in kind_value

        for key in ("url", "contentUrl", "source", "src", "imageUrl", "thumbnailUrl"):
            if key in node and local_image_context:
                add(node.get(key))

        for key, child in node.items():
            key_image_context = local_image_context or key in {"adaptiveCards", "attachments", "images", "image", "thumbnail", "previewImage"}
            walk(child, key_image_context)

    walk(value)
    return urls


# Appended to a turn that carries NO tool contract, for tones measured to have no
# server-side interpreter (tone_options.TONE_SERVER_INTERPRETER). Those tones answer
# "what is the SHA-256 of <nonce>" with a fabricated 64-hex digest -- measured, and
# with no retraction when there is no tool list to notice the gap. A tools-bearing
# turn is covered by the exact-computation rule in the injected contract instead, so
# this only fires where that rule cannot reach.
#
# ponytail: prompt-level again, and it only claims what was measured -- the model
# stops inventing when told it cannot execute. Nothing here can verify an arbitrary
# claimed value, so a tone that ignores the sentence is not detectable downstream.
# Three call sites send an empty context, so a no-tools turn reaches this note from all
# three. Only the router turn is excluded (see _combine_text). The other two were measured
# with the shipped sentence on Claude_Sonnet, one turn per arm, and neither changed
# outcome:
#   /v1/images/generations (routes_api_images, "Generate exactly one image...") -- the
#       image is still produced, a designerapp document.ashx url in both arms.
#   /admin/model-test (routes_admin_modeltest, "Reply with one word: pong") -- still
#       answered non-empty, so classify_probe still reports "ok" to the operator.
# Both survive because the sentence is conditional on an exact computation being asked
# for; a non-computation turn is unaffected ("capital of France" -> "Paris."). The router
# turn is different in kind -- its contract is in the prompt, so it contradicts.
_NO_INTERPRETER_NOTE = (
    "You have no code execution in this environment. If an exact result requires "
    "computation (a hash, checksum, large-number arithmetic, an encoding conversion), "
    "say you cannot compute it exactly here instead of producing a value from memory: "
    "a wrong value is indistinguishable from a right one."
)


def _combine_text(prompt: str, context: list[str], tone: str | None = None) -> str:
    has_tools = any("tool_call" in c for c in context)
    result = "\n\n".join(context) + "\n\n---\n\n" + prompt if context else prompt
    if has_tools:
        # Scoped to "any listed tool", not just file actions: the earlier wording
        # named only file operations, so a caller's get_weather or calculate tool
        # got no instruction at all and was answered from the model's own
        # abilities every time.
        #
        # The two prohibitions are the failure modes seen live. M365 carries its
        # own tool set (web.run, image_gen, python, record_memory) and treats the
        # injected list as fictional -- verbatim: "that tool isn't available in
        # this conversation" -- or quietly substitutes a native equivalent,
        # answering a Write by generating a real hosted attachment and returning
        # its download link. Neither reaches the client as a tool call, so the
        # host never runs the tool it asked for.
        #
        # ponytail: prompt-level mitigation only, and compliance stays partial --
        # the upstream model's willingness is not ours to control. A durable fix
        # needs a real tool-calling channel from M365, which the substrate
        # protocol does not currently expose.
        result += (
            "\n\n[FORMAT] To use any tool listed above, respond with a ```tool_call``` JSON block. "
            "Example: ```tool_call\n"
            '{"name": "Write", "arguments": {"file_path": "S:/path/file.ext", "content": "..."}}\n'
            "```\n"
            "The tools listed above are real and available to you; a program executes them and "
            "returns their results. Ignore any other tools you may normally have -- do not search "
            "the web, run code, or generate, upload or attach a file to answer a request that a "
            "listed tool covers. Never claim a listed tool is unavailable. Emitting the "
            "```tool_call``` block is the only valid way to invoke one.\n"
            # Second-best outcome, deliberately shaped to what _extract_prose_write
            # keys on: a backticked ABSOLUTE path plus a fenced block whose language
            # tag matches the extension. When the model will not emit the fence --
            # the common case, since M365 prefers to answer a file request with a
            # hosted attachment -- this at least lands in the shape the prose
            # fallback can still synthesize a Write from. Anything looser is not
            # worth having: the fallback's strictness is what stops a usage-example
            # block from overwriting a real file.
            "If you will not emit the block, write the answer inline instead: a backticked "
            "absolute path (`S:/dir/name.ext`) on its own line, then the complete file body in a "
            "fenced code block tagged with its language. Never attach a file in place of this."
            "[/FORMAT]"
        )
    elif tone_server_interpreter(tone) == "absent" and _NO_TOOL_MARKER not in prompt:
        # The router's classification turn (tool_router.build_router_prompt, sent as
        # client.chat(prompt, [])) carries its contract in the PROMPT, not the context,
        # so has_tools is False for it. It lists tools that do run -- possibly a shell
        # -- and demands exactly one line of output, so appending "you have no code
        # execution" there would both contradict it and turn a hash request the router
        # should route into a refusal. The marker is that contract's fingerprint.
        # A user prompt that happens to contain the marker loses the sentence: an
        # acceptable false negative, since it drops a mitigation, never breaks a turn.
        result += "\n\n" + _NO_INTERPRETER_NOTE
    return result



def _parse_reference_metadata(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def _normalize_source_attribution(item: object, *, ref_key: str = "") -> dict | None:
    """Normalize one M365 citation entry into a plain dict.

    Supports both legacy list entries::

        {"providerDisplayName": "...", "seeMoreUrl": "https://...", "referenceMetadata": "{...}"}

    and the current ``messages[].references`` map values (observed 2026-08)::

        {
          "targetLink": "https://news.weather.com.cn/...",
          "displayData": {
            "type": "text/json",
            "renderType": "CITATION",
            "content": "{\"metadata\":{\"referenceId\":\"turn1search10\",\"type\":\"Web\"},
                         \"label\":\"1\",\"providerDisplayName\":\"...\",\"Title\":\"...\",\"snippet\":\"...\"}"
          },
          "isCitedInResponse": true
        }

    ``ref_key`` is the map key (e.g. ``1-1e0595``) used by body markers ``【1-1e0595】``.
    """
    if not isinstance(item, dict):
        return None

    # Newer references-map shape: lift displayData.content JSON up.
    display = item.get("displayData")
    content: dict = {}
    if isinstance(display, dict):
        raw_content = display.get("content")
        if isinstance(raw_content, dict):
            content = raw_content
        elif isinstance(raw_content, str) and raw_content.strip():
            try:
                parsed = json.loads(raw_content)
                if isinstance(parsed, dict):
                    content = parsed
            except (TypeError, ValueError, json.JSONDecodeError):
                content = {}

    meta = _parse_reference_metadata(
        item.get("referenceMetadata")
        or content.get("metadata")
        or item.get("metadata")
        or {}
    )
    # Merge content-level fields as a shallow overlay for title/url lookup.
    merged = {**content, **item}

    title = str(
        merged.get("providerDisplayName")
        or merged.get("Title")
        or merged.get("title")
        or merged.get("sourceName")
        or merged.get("name")
        or meta.get("title")
        or ""
    ).strip()
    url = str(
        merged.get("targetLink")
        or merged.get("seeMoreUrl")
        or merged.get("url")
        or merged.get("sourceUrl")
        or merged.get("displayUrl")
        or merged.get("path")
        or meta.get("url")
        or ""
    ).strip()
    if url.lower() in {"null", "none"}:
        url = ""
    ref_type = str(
        meta.get("type")
        or meta.get("refType")
        or meta.get("typeDescription")
        or meta.get("sourceType")
        or merged.get("refType")
        or ""
    ).strip()
    snippet = str(
        merged.get("snippet")
        or meta.get("snippet")
        or item.get("snippet")
        or ""
    ).strip()
    search_query = str(
        merged.get("searchQuery")
        or meta.get("searchQuery")
        or ""
    ).strip()
    # Ids that body markers may use.
    ref_id = str(
        meta.get("referenceId")
        or meta.get("citationRefId")
        or merged.get("referenceId")
        or ""
    ).strip()
    label = str(merged.get("label") or meta.get("label") or "").strip()
    key = (ref_key or "").strip()
    if not title and not url and not key and not ref_id:
        return None
    if not title:
        title = url or key or ref_id or "来源"
    return {
        "title": title,
        "url": url,
        "type": ref_type,
        "snippet": snippet,
        "search_query": search_query,
        "ref_key": key,          # e.g. 1-1e0595  (matches 【1-1e0595】)
        "ref_id": ref_id,        # e.g. turn1search10 (matches citeturn1search10)
        "label": label,          # e.g. "1"
    }


def extract_source_attributions(value: object) -> list[dict]:
    """Collect normalized citations from a SignalR message / entry tree.

    Walks:
      * legacy ``sourceAttributions`` / ``citations`` lists
      * current ``references`` dicts keyed by ``1-1e0595``-style ids
      * already-resolved ``[label](https://...)`` links in final bot text

    De-duplicates by URL, then by ref_key / ref_id / title.
    """
    found: list[dict] = []
    seen: set[str] = set()
    list_keys = {
        "sourceAttributions",
        "source_attributions",
        "SourceAttributions",
        "citations",
        "Citations",
        "grounding",
    }
    # `references` is a dict in modern payloads; also accept list just in case.
    map_keys = {"references", "References"}

    def add(item: object, *, ref_key: str = "") -> None:
        normalized = _normalize_source_attribution(item, ref_key=ref_key)
        if normalized is None:
            return
        # Prefer stable identity: url > ref_key > ref_id > title
        key = (
            (normalized.get("url") or "").lower()
            or (normalized.get("ref_key") or "").lower()
            or (normalized.get("ref_id") or "").lower()
            or (normalized.get("title") or "")
        )
        if not key or key in seen:
            # If we already have this key but the new entry has a URL and the
            # old one doesn't, upgrade in place.
            if key and key in seen and normalized.get("url"):
                for existing in found:
                    ek = (
                        (existing.get("url") or "").lower()
                        or (existing.get("ref_key") or "").lower()
                        or (existing.get("ref_id") or "").lower()
                        or (existing.get("title") or "")
                    )
                    if ek == key and not existing.get("url"):
                        existing.update({k: v for k, v in normalized.items() if v})
                        break
            return
        seen.add(key)
        found.append(normalized)

    def add_inline_markdown_links(text: str) -> None:
        if not text or "http" not in text:
            return
        for match in re.finditer(r"\[([^\]]{0,200})\]\((https?://[^)\s]+)\)", text):
            label = (match.group(1) or "").strip() or match.group(2)
            if label.startswith("!") or "m365-media?" in match.group(2):
                continue
            add({"providerDisplayName": label, "seeMoreUrl": match.group(2), "refType": "Web"})

    def walk(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        for key in list_keys:
            attrs = node.get(key)
            if isinstance(attrs, list):
                for item in attrs:
                    add(item)
            elif isinstance(attrs, dict):
                # Sometimes a single attribution object.
                if any(k in attrs for k in ("seeMoreUrl", "providerDisplayName", "url", "targetLink")):
                    add(attrs)
                else:
                    for rk, rv in attrs.items():
                        add(rv, ref_key=str(rk))
        for key in map_keys:
            refs = node.get(key)
            if isinstance(refs, dict):
                for rk, rv in refs.items():
                    add(rv, ref_key=str(rk))
            elif isinstance(refs, list):
                for item in refs:
                    add(item)
        if node.get("author") not in (None, "user") and isinstance(node.get("text"), str):
            add_inline_markdown_links(node["text"])
        if isinstance(node.get("hiddenText"), str):
            add_inline_markdown_links(node["hiddenText"])
        for child in node.values():
            if isinstance(child, (dict, list)):
                walk(child)

    walk(value)
    return found


def match_sources_for_tracker(
    sources: list[dict],
    tracker: "CitationTracker | None",
) -> list[dict]:
    """Order/filter sources to match in-body ``[n]`` numbering.

    Body markers are rewritten to ``[n]`` from, in priority order:
      * ``【1-1e0595】`` -> tracker key ``bracket1-1e0595`` / raw ``1-1e0595``
      * ``citeturn1search10`` -> tracker key ``turn1search10``
    Upstream ``references`` carry both ``ref_key`` (1-1e0595) and ``ref_id``
    (turn1search10). Match them so footnote 1 points at the right URL.
    """
    usable = [s for s in sources if isinstance(s, dict) and (s.get("title") or s.get("url") or s.get("ref_key"))]
    if not usable:
        return []
    if tracker is None or not tracker.keys_in_order:
        # No body footnotes recorded — keep upstream order, drop URL-less noise.
        return [s for s in usable if s.get("url") or s.get("title")]

    by_ref_key: dict[str, dict] = {}
    by_ref_id: dict[str, dict] = {}
    by_label: dict[str, dict] = {}
    for s in usable:
        rk = str(s.get("ref_key") or "").lower()
        rid = str(s.get("ref_id") or "").lower()
        lab = str(s.get("label") or "").strip()
        if rk:
            by_ref_key[rk] = s
            # Also index without the "bracket" prefix the tracker uses.
            if rk.startswith("bracket"):
                by_ref_key[rk[len("bracket"):]] = s
            else:
                by_ref_key[f"bracket{rk}"] = s
        if rid:
            by_ref_id[rid] = s
        if lab:
            by_label[lab] = s

    ordered: list[dict] = []
    used: set[int] = set()
    for key in tracker.keys_in_order:
        k = (key or "").lower()
        hit = by_ref_key.get(k) or by_ref_id.get(k)
        if hit is None and k.startswith("bracket"):
            # bracket1-1e0595 or bracket1
            rest = k[len("bracket"):]
            hit = by_ref_key.get(rest) or by_ref_key.get(k)
            if hit is None and re.fullmatch(r"\d+", rest or ""):
                hit = by_label.get(rest)
        if hit is None and re.fullmatch(r"bracket\d+-[0-9a-f]+", k):
            # direct ref_key form
            hit = by_ref_key.get(k) or by_ref_key.get(k.split("bracket", 1)[-1])
        if hit is not None and id(hit) not in used:
            ordered.append(hit)
            used.add(id(hit))

    # Append any remaining sources with real URLs that were not cited inline.
    for s in usable:
        if id(s) not in used and s.get("url"):
            ordered.append(s)
            used.add(id(s))
    return ordered


def aligned_url_sources_for_stream(
    sources: list[dict],
    tracker: CitationTracker | None = None,
) -> list[dict]:
    """Return URL-bearing sources ordered to match in-body ``[n]`` markers.

    URL-less placeholders are dropped: protocol-native citation fields and the
    Markdown bibliography both need a real link to be useful.
    """
    aligned = match_sources_for_tracker(sources, tracker)
    return [s for s in aligned if isinstance(s, dict) and str(s.get("url") or "").strip()]


def _footnote_span(text: str, index: int) -> tuple[int, int] | None:
    """Return ``[start, end)`` for the first ``[index]`` (or legacy ``[^index]``) marker."""
    if index <= 0 or not text:
        return None
    for marker in (f"[{index}]", f"[^{index}]"):
        start = text.find(marker)
        if start >= 0:
            return start, start + len(marker)
    return None


def openai_url_citations_from_sources(text: str, sources: list[dict]) -> list[dict]:
    """Map normalized sources to OpenAI Responses ``url_citation`` annotations.

    ``start_index`` / ``end_index`` prefer the in-body ``[n]`` marker span so
    clients can highlight the cite marker. When a marker is missing the span is
    placed at EOF (zero-width) so the annotation still carries url/title.
    """
    body = text or ""
    annotations: list[dict] = []
    for index, source in enumerate(sources, 1):
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if not url:
            continue
        title = str(source.get("title") or url).strip() or url
        span = _footnote_span(body, index)
        if span is None:
            start = end = len(body)
        else:
            start, end = span
        annotations.append(
            {
                "type": "url_citation",
                "start_index": start,
                "end_index": end,
                "url": url,
                "title": title,
            }
        )
    return annotations


def anthropic_web_citations_from_sources(text: str, sources: list[dict]) -> list[dict]:
    """Map normalized sources to Anthropic ``web_search_result_location`` citations.

    These hang on a text content block's ``citations`` array (and as streaming
    ``citations_delta`` events). ``encrypted_index`` is an opaque required field
    in the official SDK; we emit a stable synthetic token per source.
    """
    body = text or ""
    citations: list[dict] = []
    for index, source in enumerate(sources, 1):
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if not url:
            continue
        title = str(source.get("title") or url).strip() or url
        snippet = str(source.get("snippet") or "").strip()
        span = _footnote_span(body, index)
        if span is not None:
            cited_text = body[span[0]:span[1]]
        elif snippet:
            cited_text = snippet[:200]
        else:
            cited_text = title
        citations.append(
            {
                "type": "web_search_result_location",
                "url": url,
                "title": title,
                "cited_text": cited_text,
                # Opaque per Anthropic SDK; not a real encrypted payload.
                "encrypted_index": f"m365_{index}",
            }
        )
    return citations
