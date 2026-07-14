from __future__ import annotations

from m365_copilot_openai_proxy.substrate_parse import (
    _combine_text,
    _dedupe_repeated_delta,
    _dedupe_signature,
    _extract_image_urls,
    _image_markdown,
    _is_image_loading_placeholder,
    _message_content,
    _final_fallback_remainder,
)


# --- _combine_text ---------------------------------------------------------

def test_combine_text_returns_prompt_when_no_context():
    assert _combine_text("just the prompt", []) == "just the prompt"


def test_combine_text_joins_context_before_prompt():
    result = _combine_text("PROMPT", ["ctx1", "ctx2"])
    assert result == "ctx1\n\nctx2\n\n---\n\nPROMPT"


def test_combine_text_appends_format_hint_when_context_mentions_tool_call():
    result = _combine_text("PROMPT", ["please emit a tool_call block"])
    assert "PROMPT" in result
    assert "[FORMAT]" in result
    assert "tool_call" in result


def test_combine_text_no_format_hint_without_tool_call_context():
    result = _combine_text("PROMPT", ["ordinary context"])
    assert "[FORMAT]" not in result


# --- _is_image_loading_placeholder / _image_markdown -----------------------

def test_is_image_loading_placeholder_case_insensitive():
    assert _is_image_loading_placeholder("Loading image") is True
    assert _is_image_loading_placeholder("  loading image  ") is True


def test_is_image_loading_placeholder_rejects_other_text():
    assert _is_image_loading_placeholder("here is your image") is False


def test_image_markdown_format():
    assert _image_markdown("https://x/a.png") == "![image](https://x/a.png)"


# --- _extract_image_urls ---------------------------------------------------

def test_extract_image_urls_requires_image_context():
    # A bare url with no image context must NOT be extracted.
    assert _extract_image_urls({"url": "https://x/a.png"}) == []


def test_extract_image_urls_from_typed_image_node():
    node = {"type": "image", "url": "https://x/a.png"}
    assert _extract_image_urls(node) == ["https://x/a.png"]


def test_extract_image_urls_from_image_keyed_container():
    # The "image" key itself establishes image context for its children.
    node = {"image": {"url": "https://x/a.png"}}
    assert _extract_image_urls(node) == ["https://x/a.png"]


def test_extract_image_urls_skips_non_http_and_dedupes():
    node = {
        "attachments": [
            {"type": "image", "url": "https://x/a.png"},
            {"type": "image", "url": "https://x/a.png"},
            {"type": "image", "url": "data:image/png;base64,zzz"},
        ]
    }
    assert _extract_image_urls(node) == ["https://x/a.png"]


def test_extract_image_urls_strips_backticks():
    node = {"type": "image", "url": "`https://x/a.png`"}
    assert _extract_image_urls(node) == ["https://x/a.png"]


# --- _final_fallback_remainder ---------------------------------------------

def test_final_fallback_empty_fallback_returns_empty():
    assert _final_fallback_remainder("streamed", "") == ""


def test_final_fallback_empty_streamed_returns_full_fallback():
    assert _final_fallback_remainder("", "full fallback") == "full fallback"


def test_final_fallback_returns_suffix_when_fallback_extends_streamed():
    assert _final_fallback_remainder("Hello", "Hello world") == " world"


def test_final_fallback_empty_when_fallback_already_streamed():
    assert _final_fallback_remainder("Hello world extra", "Hello world") == ""


def test_final_fallback_empty_when_signatures_match_despite_link_noise():
    # streamed carries a backtick URL that dedupe strips; fallback is the same
    # prose without it. Neither startswith/contains the other, so this exercises
    # the signature-match branch (not the prefix branch): nothing extra emitted.
    streamed = "See the docs `https://x/a` now"
    fallback = "See the docs now"
    assert _final_fallback_remainder(streamed, fallback) == ""


# --- _dedupe_repeated_delta ------------------------------------------------

def test_dedupe_repeated_delta_keeps_incremental_repeated_tokens():
    # Math/code stream repeated short tokens across deltas; none may be dropped
    # even though the later token already appeared in the accumulated stream.
    streamed = "2a_1 + 3d = 6\n"
    assert _dedupe_repeated_delta(streamed, "2a_1") == "2a_1"
    assert _dedupe_repeated_delta(streamed, " + 7d = 10\n") == " + 7d = 10\n"


def test_dedupe_repeated_delta_keeps_first_delta_when_nothing_streamed():
    assert _dedupe_repeated_delta("", "hello") == "hello"


def test_dedupe_repeated_delta_drops_full_reemission_with_link_variant():
    # The model restates the ENTIRE answer, swapping a raw backtick URL for a
    # citation link. Signatures match (URL/citation noise stripped), so the
    # whole re-emission is dropped rather than duplicated.
    streamed = "See the report `https://x/a` here"
    reemit = "See the report [link](\ue200cite\ue202turn1file1\ue201) here"
    assert _dedupe_repeated_delta(streamed, reemit) == ""


# --- _dedupe_signature -----------------------------------------------------

def test_dedupe_signature_strips_urls_links_and_whitespace():
    assert _dedupe_signature("a `https://x/a` b") == "ab"
    assert _dedupe_signature("a [t](https://x/a) b") == "ab"


# --- _message_content ------------------------------------------------------

def test_message_content_plain_text():
    assert _message_content({"text": "hello"}) == "hello"


def test_message_content_combines_text_and_image_markdown():
    entry = {"text": "caption", "image": {"url": "https://x/a.png"}}
    assert _message_content(entry) == "caption\n\n![image](https://x/a.png)"


def test_message_content_drops_loading_placeholder_when_image_present():
    entry = {"text": "Loading image", "image": {"url": "https://x/a.png"}}
    # The placeholder text is dropped, leaving only the real image.
    assert _message_content(entry) == "![image](https://x/a.png)"
