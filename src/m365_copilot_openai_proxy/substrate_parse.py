from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from .media_proxy import normalize_m365_media_text

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


def clean_m365_citations(text: str) -> str:
    """Strip M365 private-use citation markers from model text.

    Safe on partial stream deltas: only complete cite patterns are removed.
    """
    if not text:
        return ""
    # Fast path: most chunks have neither the word "cite" nor private-use chars.
    if "cite" not in text.lower() and not any("\ue000" <= c <= "\uf8ff" for c in text):
        return text
    cleaned = _MARKDOWN_CITE_RE.sub("", text)
    cleaned = _BARE_PUA_CITE_RE.sub("", cleaned)
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
    nothing, and a partially-covered one is trimmed to the tail after the shared
    prefix so its already-streamed head is not repeated.
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
    # Partially covered: drop the head the stream already delivered verbatim and
    # emit only what follows, instead of re-sending the whole fallback.
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


def _combine_text(prompt: str, context: list[str]) -> str:
    if not context:
        return prompt
    has_tools = any("tool_call" in c for c in context)
    result = "\n\n".join(context) + "\n\n---\n\n" + prompt
    if has_tools:
        result += (
            "\n\n[FORMAT] Respond with a ```tool_call``` JSON block for any file action. "
            "Example: ```tool_call\n"
            '{"name": "Write", "arguments": {"file_path": "S:/path/file.ext", "content": "..."}}\n'
            "``` No other output format is valid for file operations.[/FORMAT]"
        )
    return result
