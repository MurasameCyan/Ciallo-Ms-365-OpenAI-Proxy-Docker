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
_SRC_PUA = "\ue000-\uf8ff"

# A turn-scoped citation id, e.g. turn1search6 / turn2file0.
_SRC_ID_WORDS = "search|file|news|image|video|base|knowledge|gpt|cid|doc"
_SRC_TURN_ID = rf"turn\d+(?:{_SRC_ID_WORDS})\d+"


def _prefix_alternation(words: list[str]) -> str:
    """Regex matching every NON-EMPTY prefix of any of ``words``.

    A streamed marker arrives one character at a time, so the tail in hand is
    usually a prefix of an id (``turn1se``) rather than the whole id. Built
    from the word list instead of spelled out, so adding an id word cannot
    silently leave the partial matcher behind.
    """
    alternatives = []
    for word in words:
        chain = word[-1]
        for char in reversed(word[:-1]):
            chain = f"{char}(?:{chain})?"
        alternatives.append(chain)
    return "(?:" + "|".join(alternatives) + ")"


_SRC_ID_WORD_PARTIAL = _prefix_alternation(_SRC_ID_WORDS.split("|"))
# A PREFIX of a turn id, digits included: turn1 / turn1s / turn1search7.
# The version WITHOUT digits (``turn``, ``tur``, ``t``) still has to be held --
# the stream can stop there and continue next delta -- but it is not yet
# evidence that the tag is a citation: ``<cite>Turn</cite>`` is a book title.
_SRC_TURN_ID_PARTIAL = (
    rf"turn\d+(?:{_SRC_ID_WORD_PARTIAL})?\d*"
)
# What the HOLD patterns accept, digits or not. Holding is free of consequence:
# `_release` gives the text back verbatim unless the evidence rule above is met.
_SRC_CITE_ID_PARTIAL = (
    rf"t(?:u(?:r(?:n(?:\d*(?:{_SRC_ID_WORD_PARTIAL})?\d*)?)?)?)?"
)

_SRC_MARKDOWN_CITE_RE = re.compile(
    rf"\[([^\]]*)\]\(\s*([{_SRC_PUA}]*cite[{_SRC_PUA}][^)]*)\)",
    re.IGNORECASE,
)
# The marker is STRUCTURED, not "PUA followed by a word": the opener, the word
# "cite", then one separator per id, then a closer. Treating any private-use
# byte as a separator let the CLOSER start a new id and swallowed the word
# after the marker ("\ue201Cloudflare" -> footnote 2 pointing at prose).
_SRC_OPEN = "\ue200"
_SRC_SEP = "\ue202"
_SRC_CLOSE = "\ue201"

# One marker may carry several ids: \ue200cite\ue202turn4search10\ue202turn4search12\ue201
_SRC_BARE_PUA_CITE_RE = re.compile(
    rf"{_SRC_OPEN}\s*cite\s*((?:{_SRC_SEP}\s*[A-Za-z0-9_]+)+)\s*{_SRC_CLOSE}?",
    re.IGNORECASE,
)
# The ids inside such a run, once the separators are what split them.
_SRC_PUA_ID_RE = re.compile(rf"{_SRC_SEP}\s*([A-Za-z0-9_]+)")
# The other rendering of the same marker, seen in the very same live turn.
_SRC_LITERAL_CITE_TAG_RE = re.compile(
    rf"<cite>\s*({_SRC_TURN_ID}(?:\s*,\s*{_SRC_TURN_ID})*)\s*</cite>",
    re.IGNORECASE,
)
# An id whose PUA half was already consumed. Only a PUA neighbour makes it a
# marker: prose that merely names an id (a bug report, these docs) keeps it.
_SRC_ORPHAN_TURN_CITE_RE = re.compile(
    rf"(?:[{_SRC_PUA}]+({_SRC_TURN_ID})(?:[{_SRC_PUA}]*)|({_SRC_TURN_ID})[{_SRC_PUA}]+)",
    re.IGNORECASE,
)
# Chinese-bracket web cites used by some M365 answers: 【1-1fd57a】 or 【3】.
_SRC_BRACKET_CITE_RE = re.compile(
    r"【\s*(\d{1,3})\s*(?:[-–—]\s*([0-9a-fA-F]{3,16}))?\s*】"
)
_SRC_SYDNEY_FOOTNOTE_RE = re.compile(r"\[\^(\d+)\^\]")
_SRC_CITE_KEY_NOISE_RE = re.compile(rf"[{_SRC_PUA}]+")

# Tails a delta may END inside a citation marker. Only these are held; anything
# else goes straight through. A marker that split mid-way used to leak its
# halves, but holding more than the marker costs text: an earlier version held
# every open "[" and DELETED the tail at flush, which truncated a legal
# tool-call argument that merely contained a bracket.
#
# Every pattern is anchored at the end and describes the marker's OWN grammar,
# so a tail that has already failed to be a marker ("[']") stops matching and
# is released verbatim on the next delta.
_SRC_HOLD_TAIL_RES = (
    # [label](<pua>cite... -- a markdown citation whose target is arriving
    re.compile(rf"\[[^\]\n]*\]\(\s*[{_SRC_PUA}]*(?:cite[{_SRC_PUA}]|c(?:i(?:t(?:e)?)?)?)?[^)\n]*$", re.IGNORECASE),
    # \ue200cite\ue202turn1s -- an open marker run, ids still arriving
    re.compile(rf"{_SRC_OPEN}\s*c(?:i(?:t(?:e)?)?)?(?:{_SRC_SEP}\s*[A-Za-z0-9_]*)*\s*{_SRC_CLOSE}?$", re.IGNORECASE),
    # \ue202turn1se -- a separator plus the id that follows it, the opener
    # having gone out in an earlier delta.
    re.compile(rf"{_SRC_SEP}\s*[A-Za-z0-9_]*$"),
    # A lone private-use byte: the marker's first half.
    re.compile(rf"[{_SRC_PUA}]$"),
    # <cite>turn1s / <cite>turn1search7< / <cite>turn1search7</ -- an open
    # literal cite tag, including its own closing half. Bounded to a PREFIX of a
    # turn id, never to "anything alphanumeric": the same element name is real
    # HTML (<cite>Moby Dick</cite>), and holding a title delayed it one delta and
    # then let _release() cut it at the tag ("quote: <cite>Some Book").
    re.compile(
        rf"<cite>\s*{_SRC_CITE_ID_PARTIAL}"
        rf"(?:\s*,\s*(?:{_SRC_CITE_ID_PARTIAL})?)*"
        rf"\s*(?:<\s*/?\s*(?:c(?:i(?:t(?:e)?)?)?)?\s*>?)?$",
        re.IGNORECASE,
    ),
    # A bare <cite> closing a delta: the id it will carry is not in hand yet,
    # so it is held for one delta. _release() gives it back VERBATIM when no
    # citation id follows -- an HTML title must never lose its closing half.
    re.compile(r"<cite>\s*$", re.IGNORECASE),
    # < / <c / <cite / <cite> -- the opening halves of such a tag.
    # A lone "<" is held for one delta so a tag split right after it is still
    # recognized; a real "a < b" costs one delta of delay, never content.
    #
    # Closing halves (</, </c, </cite) are deliberately NOT held: they can only
    # complete a tag whose <cite> half is still buffered, and buffering them on
    # their own only parked the tail of a real HTML </cite> for one delta.
    re.compile(r"<(?:c(?:i(?:t(?:e)?)?)?)?>?$", re.IGNORECASE),
    # 【1- -- an open chinese-bracket cite. Bounded to a citation's own digits
    # so ordinary 【emphasis】 punctuation is never held.
    re.compile(r"【\s*(?:\d{0,3}(?:[-–—]\s*[0-9a-fA-F]{0,16})?)?$"),
    # [label] or [label -- an open or closed markdown citation label. Held so
    # the label and the marker that may follow it are rewritten together; a
    # tail that never became a citation is given back VERBATIM by flush(), so a
    # bracket in ordinary text (a tool argument writing "print('[')") is
    # delayed by one delta at worst, never lost.
    re.compile(r"\[[^\]\n]*\]?$"),
    re.compile(r"\[\^\d{0,4}\^?$"),
)
# A hold above this size is released as-is: real markers are short, and an
# unbounded hold would delay the rest of the answer to the end of the stream.
_SRC_MAX_HOLD = 160

# A markdown citation cut off before its target closed. flush() keeps the
# label, which is real text, and drops the marker.
_SRC_MARKDOWN_CITE_OPEN_RE = re.compile(
    rf"\[([^\]\n]*)\]\(\s*[{_SRC_PUA}]*(?:c(?:i(?:t(?:e)?)?)?)?\s*$", re.IGNORECASE
)
# The link form of the literal tag: [label](<cite>turn1search7</cite>)
_SRC_MARKDOWN_CITE_TAG_RE = re.compile(
    rf"\[([^\]\n]*)\]\(\s*<cite>([^<]*)</cite>\s*\)", re.IGNORECASE
)
# Where a citation tag actually STARTS: <cite> followed by (a prefix of) a turn
# id. The element name on its own is not enough -- HTML uses it for the title of
# a work, and a delta that happens to end right after "<cite>" would otherwise
# be remembered as marker syntax and have its title deleted on release.
_SRC_CITE_TAG_START_RE = re.compile(
    f"<cite>\\s*{_SRC_TURN_ID_PARTIAL}", re.IGNORECASE
)
# Only a private-use byte or a cite/turnN id proves a held tail really was a
# marker. Without that evidence the tail is replayed VERBATIM: it is real
# text that happened to end where a marker could have started.
_SRC_MARKER_EVIDENCE_RE = re.compile(
    rf"[{_SRC_PUA}]|<cite>\s*{_SRC_TURN_ID_PARTIAL}|\b{_SRC_TURN_ID}\b", re.IGNORECASE
)

# One lexical pass: a later literal bracket must not reserve a number before
# an earlier citation merely because both arrived in the same delta.
_SRC_CITATION_TOKEN_PATTERNS = {
    "markdown": _SRC_MARKDOWN_CITE_RE,
    "pua": _SRC_BARE_PUA_CITE_RE,
    "tag": _SRC_LITERAL_CITE_TAG_RE,
    "orphan": _SRC_ORPHAN_TURN_CITE_RE,
    "bracket": _SRC_BRACKET_CITE_RE,
    "sydney": _SRC_SYDNEY_FOOTNOTE_RE,
}
_SRC_CITATION_TOKEN_RE = re.compile(
    "|".join(f"(?P<{name}>{pattern.pattern})" for name, pattern in _SRC_CITATION_TOKEN_PATTERNS.items()),
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
    """Whether ``text`` holds anything a citation rule could act on."""
    if not text:
        return False
    return bool(
        _SRC_MARKER_EVIDENCE_RE.search(text)
        or _SRC_BRACKET_CITE_RE.search(text)
        or _SRC_SYDNEY_FOOTNOTE_RE.search(text)
    )


def _marker_start(text: str) -> int | None:
    """Offset where citation-marker syntax begins, or ``None`` when absent.

    Everything before it is real text that must survive verbatim; only from
    here on is it safe to drop characters.
    """
    candidates = [position for position in (text.find(marker) for marker in ("\ue200", "\ue201", "\ue202")) if position >= 0]
    # <cite> only counts as a marker when a citation id follows it. The element
    # is real HTML elsewhere (<cite>Moby Dick</cite>), and treating that as a
    # marker start deleted the title together with the rest of the held tail.
    for pattern in (
        _SRC_CITE_TAG_START_RE,
        re.compile(r"【\s*\d"),
        re.compile(r"\[\^\d"),
    ):
        match = pattern.search(text)
        if match:
            candidates.append(match.start())
    return min(candidates) if candidates else None


def _source_footnote_number(source: dict) -> int | None:
    """The footnote number a source states for itself, or ``None``.

    ``label`` is what upstream prints ("4" for ``【4-6f710b】``); ``ref_key``
    repeats it as its leading digits. Reading both means a payload that drops
    one of them still numbers the source where the body puts it.
    """
    for value in (source.get("label"), source.get("ref_key")):
        match = re.match(r"\s*(\d{1,3})", str(value or ""))
        if match:
            number = int(match.group(1))
            if number > 0:
                return number
    return None


class CitationTracker:
    """Track streamed cite markers and renumber them as ``[n]``.

    Holds incomplete openers across ``clean()`` calls so split deltas cannot
    leak raw ``turn1search6`` / lone PUA bytes / bare ``cite`` to the client.

    Only text that is ALREADY citation syntax is held, and ``flush()`` gives
    back everything it held that turned out not to be a citation. Holding any
    ``[`` and deleting the tail at flush is what truncated a legal tool-call
    argument that merely contained a bracket, and what turned a plain
    ``turn3search5`` in prose into a footnote.
    """

    def __init__(self) -> None:
        self._key_to_num: dict[str, int] = {}
        self._order: list[str] = []
        self._hold = ""
        # Alternate keys for a source already numbered under its first
        # rendering, e.g. turn1search4 -> bracket4-6f710b. See note_source().
        self._aliases: dict[str, str] = {}
        # The footnote number upstream states for a key, when it states one.
        # 【4-6f710b】 carries its own 4; the same source's turn1search4
        # rendering does not, and has to inherit it through the alias.
        self._preferred: dict[str, int] = {}
        # Display numbers are weak aliases, revocable when another identity
        # reuses the label. Full ref keys/ids never merge through such a label.
        self._source_index = _SourceAttributionIndex()
        self._source_markers: dict[int, str] = {}
        self._source_labels: dict[int, set[str]] = {}
        self._label_sources: dict[str, dict[int, str]] = {}
        self._numeric_only: dict[str, str] = {}
        self._reserved_numbers: set[int] = set()

    def _canonical(self, key: str) -> str:
        """Follow an alias chain to the key that owns the number."""
        seen: set[str] = set()
        while key in self._aliases and key not in seen:
            seen.add(key)
            key = self._aliases[key]
        return key

    def alias(self, left: str, right: str) -> None:
        """Declare that two marker keys name the SAME source.

        M365 renders one source more than one way inside a single turn:
        ``【4-6f710b】`` in the cumulative snapshot and
        ``<cite>turn1search4</cite>`` in the streamed deltas. The two
        renderings produce unrelated keys, so without this the same source
        was numbered twice -- the snapshot said ``[4]``, the deltas said
        ``[1]``, ``_split_snapshot_lead`` no longer saw a prefix, and the
        opening of the answer was delivered to the reader twice.

        Only ever merges when at most ONE of the keys has a number: once
        both are numbered their text is already out, and renumbering cannot
        retract it.
        """
        first = self._canonical((left or "").lower())
        second = self._canonical((right or "").lower())
        if not first or not second or first == second:
            return
        num_first = self._key_to_num.get(first)
        num_second = self._key_to_num.get(second)
        if num_first is not None and num_second is not None:
            return
        if num_second is not None:
            self._aliases[first] = second
        else:
            self._aliases[second] = first

    def note_source(self, source: dict) -> None:
        """Link full marker identities; bind a numeric label only while unique."""
        if not isinstance(source, dict):
            return
        record, merged = self._source_index.add(source)
        source = record
        ref_key = str(source.get("ref_key") or "").strip().lower()
        ref_id = _normalize_cite_key(str(source.get("ref_id") or ""))
        keys: list[str] = []
        if ref_key and not ref_key.isdigit():
            keys.append(f"bracket{ref_key}")
        if ref_id:
            keys.append(ref_id)
        if not keys and source.get("url"):
            keys.append(f"url:{str(source['url']).strip().lower()}")
        preferred = _source_footnote_number(source)
        if not keys:
            return
        if preferred:
            for key in keys:
                self._preferred.setdefault(key, preferred)
        for other in keys[1:]:
            self.alias(keys[0], other)
        if not preferred:
            return

        owner = self._source_markers.get(id(record))
        if owner is not None:
            self.alias(owner, keys[0])
        labels = self._source_labels.setdefault(id(record), set())
        label_key = f"bracket{preferred}"
        affected = {label_key}
        for previous in merged:
            previous_key = self._source_markers.pop(id(previous), None)
            if previous_key is not None:
                self.alias(previous_key, keys[0])
            previous_labels = self._source_labels.pop(id(previous), set())
            for previous_label in previous_labels:
                self._label_sources[previous_label].pop(id(previous), None)
            labels.update(previous_labels)
            affected.update(previous_labels)
        labels.add(label_key)
        owner = self._canonical(keys[0])
        self._source_markers[id(record)] = owner
        for affected_label in affected:
            candidates = self._label_sources.setdefault(affected_label, {})
            candidates[id(record)] = owner
            self._bind_numeric_label(affected_label, candidates)

    def _bind_numeric_label(self, label_key: str, candidates: dict[int, str]) -> None:
        if len(candidates) != 1:
            previous = self._aliases.pop(label_key, None)
            if previous is not None:
                previous = self._canonical(previous)
                if self._numeric_only.pop(previous, None) == label_key:
                    # Only the bare label was delivered before its ambiguity
                    # became known. Keep its number, but remove URL ownership.
                    self._key_to_num[label_key] = self._key_to_num.pop(previous)
                    self._order[self._order.index(previous)] = label_key
            return

        owner = self._canonical(next(iter(candidates.values())))
        if label_key in self._key_to_num:
            if owner in self._key_to_num:
                return  # Both renderings were delivered; neither can be retracted.
            self._key_to_num[owner] = self._key_to_num.pop(label_key)
            self._order[self._order.index(label_key)] = owner
            self._numeric_only[owner] = label_key
        self._aliases[label_key] = owner

    def _num_for(self, key: str, preferred: int | None = None) -> int:
        if key:
            normalized = self._canonical(key)
            if preferred is None:
                preferred = self._preferred.get(normalized)
        else:
            normalized = f"anon{len(self._order)}"
        numeric_key = key if re.fullmatch(r"bracket\d+", key or "") else None
        if numeric_key is None:
            self._numeric_only.pop(normalized, None)
        elif normalized != key and normalized not in self._key_to_num:
            self._numeric_only[normalized] = key
        if normalized in self._key_to_num:
            return self._key_to_num[normalized]
        if (
            preferred is not None and preferred > 0
            and preferred not in self._key_to_num.values()
            and (
                preferred not in self._reserved_numbers
                or self._canonical(f"bracket{preferred}") == normalized
            )
        ):
            while len(self._order) < preferred - 1:
                placeholder = f"pad{len(self._order)}"
                self._order.append(placeholder)
                self._key_to_num[placeholder] = len(self._order)
            if len(self._order) == preferred - 1:
                self._order.append(normalized)
                self._key_to_num[normalized] = preferred
                return preferred
        while len(self._order) + 1 in self._reserved_numbers:
            placeholder = f"pad{len(self._order)}"
            self._order.append(placeholder)
            self._key_to_num[placeholder] = len(self._order)
        self._key_to_num[normalized] = len(self._order) + 1
        self._order.append(normalized)
        return self._key_to_num[normalized]

    @property
    def count(self) -> int:
        return len(self.keys_in_order)

    @property
    def keys_in_order(self) -> list[str]:
        """Numbered keys, one per source, in the order they were first cited.

        Aliases are folded in: a source cited as 【4-6f710b】 and as
        ``turn1search4`` is ONE entry, or a consumer that walks this list
        would emit the same URL twice.
        """
        ordered: list[str] = []
        for key in self._order:
            if key.startswith("pad"):
                continue
            canonical = self._canonical(key)
            if canonical != key:
                continue
            ordered.append(key)
        return ordered

    def number_of(self, key: str) -> int | None:
        """The in-body footnote number of ``key``, or ``None`` when uncited."""
        return self._key_to_num.get(self._canonical((key or "").lower()))

    def _split_incomplete(self, text: str) -> tuple[str, str]:
        """Return (safe_prefix, hold_suffix) for cite openers still in progress."""
        if not text:
            return "", ""
        for pattern in _SRC_HOLD_TAIL_RES:
            match = pattern.search(text)
            if match and match.end() == len(text) and match.start() < len(text):
                # An over-long "marker" is prose that merely looks like one:
                # release it rather than delay the rest of the answer.
                if len(text) - match.start() > _SRC_MAX_HOLD:
                    return text, ""
                return text[: match.start()], text[match.start():]
        return text, ""

    def _substitute(self, text: str) -> str:
        """Rewrite every COMPLETE marker in ``text`` as ``label + [n]``."""

        def md_repl(match: re.Match[str]) -> str:
            label = (match.group(1) or "").strip()
            key = _normalize_cite_key(match.group(2) or "")
            num = self._num_for(key)
            return f"{label}[{num}]" if label else f"[{num}]"

        def pua_repl(match: re.Match[str]) -> str:
            """One marker run may carry several ids; each gets its own number."""
            run = match.group(0) or ""
            keys = [_normalize_cite_key(part) for part in _SRC_PUA_ID_RE.findall(run)]
            keys = [key for key in keys if key and key != "cite"]
            if not keys:
                return ""
            return "".join(f"[{self._num_for(key)}]" for key in keys)

        def tag_repl(match: re.Match[str]) -> str:
            ids = [part.strip() for part in (match.group(1) or "").split(",")]
            ids = [_normalize_cite_key(part) for part in ids if part.strip()]
            if not ids:
                return ""
            return "".join(f"[{self._num_for(key)}]" for key in ids)

        def orphan_repl(match: re.Match[str]) -> str:
            key = _normalize_cite_key(match.group(1) or match.group(2) or "")
            return f"[{self._num_for(key)}]" if key else ""

        def bracket_repl(match: re.Match[str]) -> str:
            idx = int(match.group(1))
            suffix = (match.group(2) or "").lower()
            key = f"bracket{idx}-{suffix}" if suffix else f"bracket{idx}"
            return f"[{self._num_for(key, preferred=idx)}]"

        replacements = {
            "markdown": md_repl,
            "pua": pua_repl,
            "tag": tag_repl,
            "orphan": orphan_repl,
            "bracket": bracket_repl,
        }
        pieces: list[str] = []
        cursor = 0
        for token in _SRC_CITATION_TOKEN_RE.finditer(text):
            prefix = text[cursor:token.start()]
            self._reserve_plain_numbers(prefix)
            pieces.append(prefix)
            kind = token.lastgroup
            raw = token.group(0)
            if kind == "sydney":
                self._reserve_plain_numbers(raw)
                pieces.append(_SRC_SYDNEY_FOOTNOTE_RE.sub(r"[\1]", raw))
            else:
                pieces.append(_SRC_CITATION_TOKEN_PATTERNS[kind].sub(replacements[kind], raw))
            cursor = token.end()
        suffix = text[cursor:]
        self._reserve_plain_numbers(suffix)
        pieces.append(suffix)
        cleaned = _SRC_MARKDOWN_CITE_TAG_RE.sub(tag_repl, "".join(pieces))
        cleaned = _SRC_CITE_KEY_NOISE_RE.sub("", cleaned)
        # A footnote restated by the marker right after it was already counted.
        cleaned = re.sub(
            r"\[(\d+)\]\[(\d+)\]",
            lambda m: f"[{m.group(1)}]" if m.group(1) == m.group(2) else m.group(0),
            cleaned,
        )
        # Collapse whitespace left by removed markers (keep newlines).
        return re.sub(r"[^\S\n]{2,}", " ", cleaned)

    def _reserve_plain_numbers(self, text: str) -> None:
        # Reservation alone grants no source identity. This keeps a later
        # verified marker away from both plain citations and code indexing.
        self._reserved_numbers.update(
            int(match.group(1))
            for match in re.finditer(r"\[\^?(\d+)\^?\](?!\()", text)
        )

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
            self._reserve_plain_numbers(text)
            return text

        cleaned = self._substitute(text)
        # Re-hold if the replacements left a NEW incomplete tail behind.
        cleaned, more_hold = self._split_incomplete(cleaned)
        self._hold = more_hold + self._hold
        return cleaned
    def apply(self, text: str) -> str:
        """Render a COMPLETE text (a cumulative snapshot) with the SAME map.

        A snapshot restates the whole answer, so it must not interact with the
        streaming hold: nothing can arrive later to complete a tail of it. Its
        markers are rewritten with the same key->number table as the deltas,
        which is what keeps a snapshot and the deltas replaying the same run
        comparable -- otherwise ``_split_snapshot_lead`` stops matching and the
        reader is shown the opening twice.
        """
        if not text:
            return ""
        if not _has_cite_noise(text):
            self._reserve_plain_numbers(text)
            return text
        return self._substitute(text)


    def _release(self, held: str) -> str:
        """Rewrite a held tail that will never complete into delivered text."""
        # No marker evidence at all means this was never a citation: a plain
        # "[" whose text has not arrived, part of a tool-call argument, an
        # unfinished markdown label. Give it back exactly as it came in --
        # deleting it is what truncated legal content.
        probe = _SRC_MARKDOWN_CITE_TAG_RE.sub("", held)
        probe = _SRC_MARKDOWN_CITE_RE.sub("", probe)
        if not (
            _SRC_MARKER_EVIDENCE_RE.search(probe)
            or _SRC_BRACKET_CITE_RE.search(probe)
            or _SRC_SYDNEY_FOOTNOTE_RE.search(probe)
        ):
            return held
        cleaned = self._substitute(held)
        # A citation cut off before its target closed: the label is real text.
        cleaned = _SRC_MARKDOWN_CITE_OPEN_RE.sub(
            lambda match: (match.group(1) or "").strip(), cleaned
        )
        # From the first marker byte on, this is syntax, not text: drop it.
        start = _marker_start(cleaned)
        if start is not None:
            cleaned = cleaned[:start]
        cleaned = _SRC_CITE_KEY_NOISE_RE.sub("", cleaned)
        cleaned = re.sub(
            rf"\s*(?:{_SRC_TURN_ID}|\bturn\d+[A-Za-z0-9_]*)$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s*\bcite$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*<\/?c(?:i(?:t(?:e)?)?)?>?$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*【[^】]*$", "", cleaned)
        cleaned = re.sub(r"\s*\[\^[^\]]*$", "", cleaned)
        cleaned = re.sub(r"\s*\[[^\]\n]*$", "", cleaned)
        return cleaned

    def flush(self) -> str:
        """Release whatever is still held at end of stream.

        A hold that turned out NOT to be a citation is returned VERBATIM.
        Deleting it is what truncated a legal tool-call argument that merely
        contained a bracket, and what swallowed the tail of a plain "[".
        """
        if not self._hold:
            return ""
        held, self._hold = self._hold, ""
        return self._release(held)



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


# The footnote shapes the two views of a turn can disagree about.
_SRC_FOOTNOTE_TOKEN_RE = re.compile(r"\[(\d+)\]|\[\^(\d+)\^\]")


def _footnote_flex_prefix(left: str, right: str) -> tuple[int, int] | None:
    """Align two views of one answer, allowing their footnote NUMBERS to differ.

    The snapshot and the deltas of a single turn render the same citation in
    different ways -- ``【4-6f710b】`` against ``<cite>turn1search4</cite>`` --
    and when the upstream reference metadata cannot link the two renderings
    of a source, the tracker numbers them separately. The prose is identical
    character for character; only the digits inside ``[n]`` are not.

    Returns the offsets just past the longest aligned prefix, but ONLY when
    that prefix reaches the end of at least one side and at least one
    footnote number actually differed. Exact agreement is not this
    function's business -- the callers already test ``startswith`` -- and a
    mid-text divergence is never aligned, because guessing there emits a run
    the reader already has.
    """
    if not left or not right:
        return None
    left_index = right_index = 0
    number_differs = False
    while True:
        left_token = _SRC_FOOTNOTE_TOKEN_RE.match(left, left_index)
        right_token = _SRC_FOOTNOTE_TOKEN_RE.match(right, right_index)
        if left_token and right_token:
            left_number = left_token.group(1) or left_token.group(2)
            right_number = right_token.group(1) or right_token.group(2)
            if left_number != right_number:
                number_differs = True
            left_index = left_token.end()
            right_index = right_token.end()
            continue
        if left_index < len(left) and right_index < len(right) and left[left_index] == right[right_index]:
            left_index += 1
            right_index += 1
            continue
        break
    if not number_differs:
        return None
    if left_index >= len(left) or right_index >= len(right):
        return left_index, right_index
    return None


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

    Only exact matches count -- except for the footnote NUMBER, which the two
    renderings of one turn do not always agree on (see
    ``_footnote_flex_prefix``). Everything else has to match character for
    character, and the lead is non-empty only in the brief window after a
    snapshot ran ahead of the deltas, so every character it covers has
    provably been sent already.
    """
    if not lead or not delta:
        return None
    if lead.startswith(delta):
        return lead[len(delta):], ""
    if delta.startswith(lead):
        return "", delta[len(lead):]
    flex = _footnote_flex_prefix(lead, delta)
    if flex is None:
        return None
    lead_index, delta_index = flex
    if lead_index >= len(lead):
        return "", delta[delta_index:]
    return lead[lead_index:], ""


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


def _message_content(entry: dict, tracker: "CitationTracker | None" = None) -> str:
    """One message entry as deliverable text.

    When a ``tracker`` is passed, citation markers become the same ``[n]``
    footnotes the delta stream produced for this turn. Cleaning the snapshot
    with a different rule than the deltas is what broke the dedupe between
    them: the snapshot dropped its markers, the deltas kept ``[n]``, the two
    stopped sharing a prefix, and the reader got the opening twice.
    """
    text = normalize_m365_media_text(str(entry.get("text") or ""))
    text = tracker.apply(text) if tracker is not None else clean_m365_citations(text)
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


def _merge_source_attribution(existing: dict, incoming: dict) -> bool:
    """Enrich one identity without replacing conflicting full reference IDs.

    The caller must first establish a shared URL or reference identity.
    """
    for field in ("ref_key", "ref_id"):
        left = str(existing.get(field) or "").strip().lower()
        right = str(incoming.get(field) or "").strip().lower()
        if left and right and left != right:
            return False
    for field, value in incoming.items():
        if value and not existing.get(field):
            existing[field] = value
    return True


class _SourceAttributionIndex:
    """Coalesce compatible partial records with bounded identity lookups."""

    def __init__(self) -> None:
        self._by_key: dict[str, dict | None] = {}
        self._records: dict[int, dict] = {}
        self._positions: dict[int, int] = {}
        self._parents: dict[int, dict] = {}

    @staticmethod
    def _keys(source: dict) -> list[str]:
        keys = [
            f"{field}:{str(source[field]).strip().lower()}"
            for field in ("ref_key", "ref_id") if source.get(field)
        ]
        if source.get("url"):
            keys.append(f"url:{str(source['url']).strip()}")
        if not keys and source.get("title"):
            keys.append(f"title:{source['title']}")
        return keys

    def _canonical(self, source: dict) -> dict:
        parent = self._parents.get(id(source))
        if parent is not None:
            parent = self._canonical(parent)
            self._parents[id(source)] = parent
            return parent
        return source

    def add(self, source: dict) -> tuple[dict, list[dict]]:
        keys = self._keys(source)
        record: dict | None = None
        merged: list[dict] = []
        visited: set[int] = set()
        for key in keys:
            candidate = self._by_key.get(key)
            if candidate is None:
                continue
            candidate = self._canonical(candidate)
            if id(candidate) in visited:
                continue
            visited.add(id(candidate))
            if record is None:
                if _merge_source_attribution(candidate, source):
                    record = candidate
            elif _merge_source_attribution(record, candidate):
                if self._positions[id(candidate)] < self._positions[id(record)]:
                    _merge_source_attribution(candidate, record)
                    record, candidate = candidate, record
                self._parents[id(candidate)] = record
                merged.append(candidate)
        if record is None:
            record = dict(source)
            self._positions[id(record)] = len(self._records)
            self._records[id(record)] = record
        for key in keys:
            if key not in self._by_key:
                self._by_key[key] = record
            else:
                previous = self._by_key[key]
                if previous is not None and self._canonical(previous) is not record:
                    self._by_key[key] = None
        return record, merged

    def values(self) -> list[dict]:
        return [record for identity, record in self._records.items() if identity not in self._parents]


def extract_source_attributions(value: object) -> list[dict]:
    """Collect normalized citations from a SignalR message / entry tree.

    Walks:
      * legacy ``sourceAttributions`` / ``citations`` lists
      * current ``references`` dicts keyed by ``1-1e0595``-style ids
      * already-resolved ``[label](https://...)`` links in final bot text

    Repeated URLs enrich missing metadata; conflicting full reference IDs
    remain separate. URL-less entries use ref_key / ref_id / title instead.
    """
    index = _SourceAttributionIndex()
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
        index.add(normalized)

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
    return index.values()


def match_sources_for_tracker(
    sources: list[dict],
    tracker: "CitationTracker | None",
    *,
    text: str | None = None,
) -> list[dict]:
    """Order/filter sources to match in-body ``[n]`` numbering.

    Body markers are rewritten to ``[n]`` from, in priority order:
      * ``【1-1e0595】`` -> tracker key ``bracket1-1e0595`` / raw ``1-1e0595``
      * ``\ue200cite\ue202turn1search10\ue201`` -> tracker key ``turn1search10``
    Upstream ``references`` carry both ``ref_key`` (1-1e0595) and ``ref_id``
    (turn1search10). Match them so footnote 1 points at the right URL.

    Every returned source carries the ``footnote`` number the BODY used for it,
    which is the only thing that survives filtering: a later consumer that
    drops or reorders sources (an internal reference has no URL) must not
    renumber by list position, or the URL lands on the wrong ``[n]``.

    Plain/Sydney numbers need explicit, unique source metadata. With delivered
    ``text``, every numeric bracket also reserves its number, including ordinary
    code: an unrelated supplemental URL must never highlight that bracket.
    """
    index = _SourceAttributionIndex()
    for source in sources:
        if isinstance(source, dict) and (source.get("title") or source.get("url") or source.get("ref_key")):
            index.add(source)
    usable = index.values()
    if not usable:
        return []
    tracked_keys = tracker.keys_in_order if tracker is not None else []
    allocated = {
        tracker.number_of(key) for key in tracked_keys
        if tracker is not None and tracker.number_of(key) is not None
    }
    body_numbers = {
        int(match.group(1)) for match in re.finditer(r"\[\^?(\d+)\^?\]", text or "")
    }
    by_key: dict[str, dict | None] = {}
    by_number: dict[int, dict | None] = {}

    for source in usable:
        keys: list[str] = []
        ref_key = str(source.get("ref_key") or "").strip().lower()
        ref_id = str(source.get("ref_id") or "").strip().lower()
        if ref_key and not ref_key.isdigit():
            keys.append(ref_key if ref_key.startswith("bracket") else f"bracket{ref_key}")
        if ref_id:
            keys.append(ref_id)
        if source.get("url"):
            keys.append(f"url:{str(source['url']).strip().lower()}")
        for key in keys:
            if key not in by_key:
                by_key[key] = source
            elif by_key[key] is not source:
                by_key[key] = None
        number = _source_footnote_number(source)
        if number is not None:
            if number not in by_number:
                by_number[number] = source
            elif by_number[number] is not source:
                by_number[number] = None

    ordered: list[dict] = []
    used: set[int] = set()
    deferred: list[tuple[dict, int]] = []
    for key in tracked_keys:
        hit = by_key.get(key)
        if hit is None and re.fullmatch(r"bracket\d+", key):
            hit = by_number.get(int(key[len("bracket"):]))
        if hit is not None and id(hit) not in used:
            number = tracker.number_of(key)
            if text is None or number in body_numbers:
                ordered.append({**hit, "footnote": number})
                used.add(id(hit))
            else:
                # A replay may have allocated a different number while the
                # adopted snapshot supplied the actual delivered marker.
                deferred.append((hit, number))

    # Raw [n]/[^n^] text is not a tracked identity. Only an unambiguous
    # source-stated number can link it, never the source's list position.
    for number, source in by_number.items():
        if source is None or id(source) in used or number in allocated:
            continue
        if number in body_numbers or (text is None and not tracked_keys):
            ordered.append({**source, "footnote": number})
            used.add(id(source))
            allocated.add(number)

    for source, number in deferred:
        if id(source) not in used:
            ordered.append({**source, "footnote": number})
            used.add(id(source))

    # Include unmatched tracked IDs and all raw brackets, not just matched
    # sources, so supplemental URLs have zero-width EOF annotations.
    reserved = allocated | body_numbers
    if text is None and not tracked_keys:
        reserved.update(by_number)
    next_number = max(reserved, default=0)
    for s in usable:
        if id(s) not in used and s.get("url"):
            next_number += 1
            ordered.append({**s, "footnote": next_number})
            used.add(id(s))
    return ordered

def aligned_url_sources_for_stream(
    sources: list[dict],
    tracker: CitationTracker | None = None,
    *,
    text: str | None = None,
) -> list[dict]:
    """Return URL-bearing sources ordered to match in-body ``[n]`` markers.

    URL-less placeholders are dropped: protocol-native citation fields and the
    Markdown bibliography both need a real link to be useful.
    """
    aligned = match_sources_for_tracker(sources, tracker, text=text)
    return [s for s in aligned if isinstance(s, dict) and str(s.get("url") or "").strip()]


def _footnote_span(text: str, index: int) -> tuple[int, int] | None:
    """Return ``[start, end)`` for the first ``[index]`` (or legacy ``[^index]``) marker.

    ``None`` means the body never emitted that number. The callers turn that
    into a ZERO-WIDTH span at end-of-text, and that is deliberate rather than
    a gap left for later:

    * the numbers are upstream's. ``【3-aa11bb】`` followed by ``【1-cc22dd】``
      legitimately delivers ``A[3] B[4]`` -- the body never says ``[2]`` -- and
      a source may carry a footnote the prose does not show at all;
    * there is nothing better to point at. Guessing (nearest marker, or the
      position in the filtered list) is exactly what put a URL on somebody
      else's ``[n]`` in review #4;
    * an EOF span still carries the url and the title, so the protocol-native
      citation stays usable instead of being dropped.

    A consumer that highlights ranges therefore sees an empty range at the end
    of the text -- no highlight, rather than a wrong one.
    """
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

    The span is located from the source's OWN ``footnote`` number, never from
    its position in ``sources``: dropping a URL-less source would otherwise
    shift every later URL onto the previous marker. See
    :func:`match_sources_for_tracker`.
    """
    body = text or ""
    annotations: list[dict] = []
    for position, source in enumerate(sources, 1):
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if not url:
            continue
        title = str(source.get("title") or url).strip() or url
        number = int(source.get("footnote") or 0) or position
        span = _footnote_span(body, number)
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

    Like the OpenAI mapper, the cited span comes from the source's own
    ``footnote`` number, so filtering a URL-less source cannot move a URL onto
    somebody else's ``[n]``.
    """
    body = text or ""
    citations: list[dict] = []
    for position, source in enumerate(sources, 1):
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if not url:
            continue
        title = str(source.get("title") or url).strip() or url
        snippet = str(source.get("snippet") or "").strip()
        number = int(source.get("footnote") or 0) or position
        span = _footnote_span(body, number)
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
                "encrypted_index": f"m365_{number}",
            }
        )
    return citations
