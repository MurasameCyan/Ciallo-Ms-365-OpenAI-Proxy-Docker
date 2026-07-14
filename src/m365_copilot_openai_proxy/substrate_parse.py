from __future__ import annotations

import json
import re

from .media_proxy import normalize_m365_media_text


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
    normalized = re.sub(r"`https?://[^`\s]+`", "", text)
    normalized = re.sub(r"\[[^\]]+\]\(https?://[^\)]+\)", "", normalized)
    normalized = re.sub(r"\[[^\]]+\]\(\ue200cite\ue202[^\)]+\ue201\)", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _remaining_fallback_text(streamed_text: str, fallback_text: str) -> str:
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
    return fallback_text


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
    text = normalize_m365_media_text(str(entry.get("text") or ""))
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
