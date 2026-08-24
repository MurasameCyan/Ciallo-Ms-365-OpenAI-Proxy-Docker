from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from .media_proxy import normalize_m365_media_text
from .tone_options import tone_server_interpreter

# M365 injects private-use citation markers in streamed and final text, e.g.
#   [label](\ue200cite\ue202turn1file1\ue201)
# or bare  \ue200cite\ue202...\ue201  / PUA-wrapped "cite" runs.
# These are not useful in OpenAI-compatible clients and break dedupe signatures.
_MARKDOWN_CITE_RE = re.compile(
    r"\[[^\]]*\]\(\s*[\uE000-\uF8FF]*cite[\uE000-\uF8FF][^\)]*\)",
    re.IGNORECASE,
)
# Bare markers look like: \ue200cite\ue202turn1file1\ue201
# Only consume PUA + ascii id pieces — never trailing prose/CJK.
_BARE_PUA_CITE_RE = re.compile(
    r"[\uE000-\uF8FF]cite[\uE000-\uF8FF][A-Za-z0-9_]*[\uE000-\uF8FF]?",
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


def clean_m365_citations(text: str) -> str:
    """Strip M365 citation markers from model text.

    Safe on partial stream deltas: every pattern requires its closing delimiter,
    so a marker split across two deltas is left alone rather than half-stripped.
    """
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
    cleaned = _LITERAL_CITE_TAG_RE.sub("", cleaned)
    cleaned = _BRACKET_CITE_RE.sub("", cleaned)
    # Collapse whitespace left by removed markers (keep newlines).
    cleaned = re.sub(r"[^\S\n]{2,}", " ", cleaned)
    return cleaned


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
    elif tone_server_interpreter(tone) == "absent":
        result += "\n\n" + _NO_INTERPRETER_NOTE
    return result
