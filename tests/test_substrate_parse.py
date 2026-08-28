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
    clean_m365_citations,
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


# --- clean_m365_citations --------------------------------------------------

def test_clean_m365_citations_strips_markdown_cite_links():
    raw = "已生成音频：\n\n🎧 [流水声](\ue200cite\ue202turn1file1\ue201)\n\n可下载。"
    cleaned = clean_m365_citations(raw)
    assert "\ue200" not in cleaned
    assert "cite" not in cleaned.lower()
    assert "流水声" not in cleaned  # whole markdown link removed
    assert "已生成音频" in cleaned
    assert "可下载" in cleaned


def test_clean_m365_citations_strips_bare_pua_cite_runs():
    raw = "见参考 \ue200cite\ue202turn2file0\ue201 结束"
    cleaned = clean_m365_citations(raw)
    assert "\ue200" not in cleaned
    assert "见参考" in cleaned
    assert "结束" in cleaned


def test_clean_m365_citations_leaves_normal_text_and_urls():
    raw = "See [docs](https://example.com) and `https://x/a`"
    assert clean_m365_citations(raw) == raw


# One marker can carry SEVERAL ids, separated by the same private-use character
# that opens the id run. Every case above has exactly one id, which is how the
# pattern below shipped for weeks only ever consuming the first: production
# delivered "已有更高版本的 Node.js 也可能直接触发这个错误。turn4search10turn4search12"
# to a client, the ids butted straight against the prose.

def test_clean_m365_citations_strips_every_id_in_a_multi_id_marker():
    raw = (
        "已有更高版本也可能触发这个错误。"
        "citeturn4search10turn4search12"
        "\n\n先检查是否已安装。"
    )
    cleaned = clean_m365_citations(raw)
    assert "turn4search10" not in cleaned
    assert "turn4search12" not in cleaned
    assert not any("" <= c <= "" for c in cleaned)
    assert "已有更高版本也可能触发这个错误。" in cleaned
    assert "先检查是否已安装。" in cleaned


def test_clean_m365_citations_strips_a_three_id_marker():
    """The id run repeats without bound, so two ids cannot be the whole rule."""
    raw = (
        "没有可靠来源确认这项联动。"
        "citeturn2search15turn2search20turn2search21"
        " 初步判断如下。"
    )
    cleaned = clean_m365_citations(raw)
    for marker in ("turn2search15", "turn2search20", "turn2search21"):
        assert marker not in cleaned
    assert not any("" <= c <= "" for c in cleaned)
    assert "没有可靠来源确认这项联动。" in cleaned
    assert "初步判断如下。" in cleaned


# Upstream splits its stream wherever it likes, including inside a marker, and
# the streaming path cleans each delta on its own (substrate_client feeds every
# writeAtCursor straight in), so the two halves are never seen together and each
# has to be handled alone. Production leaked "优先选择 LTS。turn3search5" exactly
# this way: the opening half was stripped by itself, then nothing matched the rest.

def test_clean_m365_citations_strips_both_halves_of_a_marker_split_across_deltas():
    deltas = ["官方建议优先选择 LTS。cite", "turn3search5\n\n### 方法一"]
    joined = "".join(clean_m365_citations(d) for d in deltas)
    assert "turn3search5" not in joined
    assert "cite" not in joined.lower()
    assert not any("" <= c <= "" for c in joined)
    assert "官方建议优先选择 LTS。" in joined
    assert "### 方法一" in joined


# The two shapes where the id run's own repetition is what saves the text: a
# delta that stops mid-run, and one that stops on the word "cite" itself. Neither
# leaves a trailing private-use delimiter behind, so the orphan rule below cannot
# reach them -- taking the whole run in one match is the only thing that does. A
# mutation run is what turned these up: with the id run narrowed back to a single
# id, every other case in this file still passed, because the orphan rule covered
# each of them. These two are the reason that pattern reads the way it does.

def test_clean_m365_citations_strips_an_id_run_cut_off_without_its_delimiter():
    raw = "已有更高版本也可能触发这个错误。citeturn4search10turn4search12"
    cleaned = clean_m365_citations(raw)
    assert "turn4search10" not in cleaned
    assert "turn4search12" not in cleaned
    assert "cite" not in cleaned.lower()
    assert "已有更高版本也可能触发这个错误。" in cleaned


def test_clean_m365_citations_strips_an_opener_that_ends_on_the_word_cite():
    """A delta can stop between "cite" and the delimiter that follows it."""
    cleaned = clean_m365_citations("官方建议优先选择 LTS。cite")
    assert "cite" not in cleaned.lower()
    assert not any("" <= c <= "" for c in cleaned)
    assert "官方建议优先选择 LTS。" in cleaned


def test_clean_m365_citations_strips_an_orphaned_multi_id_tail():
    """A split can land mid-id-run, orphaning several ids at once."""
    tail = clean_m365_citations("turn4search10turn4search12 后续段落")
    assert "turn4search10" not in tail
    assert "turn4search12" not in tail
    assert not any("" <= c <= "" for c in tail)
    assert "后续段落" in tail


def test_clean_m365_citations_keeps_an_id_shaped_word_that_is_real_prose():
    """The orphan rule keys on the trailing delimiter, not the id shape alone.

    Without the delimiter requirement, prose that merely mentions a marker id --
    a bug report, this project's own docs -- would lose the word it is about.

    The bare sentence proves less than it looks: carrying no marker character at
    all, it comes back off the fast path before any pattern runs, so it passed
    even with the delimiter made optional. The second case is the one that
    reaches the rule, and it is also the realistic one -- a turn that cites a
    source while its prose discusses an id.
    """
    plain = "日志里残留了 turn3search5 这个锚点，是清理漏了。"
    assert clean_m365_citations(plain) == plain

    mixed = plain + "citeturn1search4"
    cleaned = clean_m365_citations(mixed)
    assert "turn3search5" in cleaned
    assert "turn1search4" not in cleaned
    assert not any("" <= c <= "" for c in cleaned)


# The two NON-PUA citation renderings, both seen in a single live turn against a
# real deployment: the streamed deltas carried literal <cite> tags while the
# cumulative snapshot of the same sentences carried bracket marks. Leaving either
# form in place cost twice over -- the markers reached the client as visible
# noise, and because _dedupe_signature is built on clean_m365_citations the same
# sentence produced two different signatures, which drove coverage down and made
# the final reconciliation append text the reader already had.

def test_clean_m365_citations_strips_literal_cite_tags():
    raw = "FastAPI 性能媲美 Node.js。<cite>turn1search7</cite> 它底层依赖 Starlette。"
    cleaned = clean_m365_citations(raw)
    assert "cite" not in cleaned.lower()
    assert "FastAPI 性能媲美 Node.js。" in cleaned
    assert "它底层依赖 Starlette。" in cleaned


def test_clean_m365_citations_strips_bracket_cite_marks():
    raw = "已被 Microsoft、Netflix 采用。【4-6f710b】 FastAPI 已被广泛使用。"
    cleaned = clean_m365_citations(raw)
    assert "【4-6f710b】" not in cleaned
    assert "已被 Microsoft、Netflix 采用。" in cleaned
    assert "FastAPI 已被广泛使用。" in cleaned


def test_clean_m365_citations_keeps_bracket_emphasis_that_is_not_a_citation():
    """【】 is ordinary CJK punctuation; only citation-shaped marks may go.

    Stripping every 【...】 would delete real content from Chinese and Japanese
    answers, where the brackets are used for emphasis and for titles.
    """
    raw = "【重要】请先阅读文档，【注意事项】见下。"
    assert clean_m365_citations(raw) == raw


def test_clean_m365_citations_keeps_html_cite_element_with_prose():
    """HTML's <cite> marks the title of a work; that is real content.

    Only citation-id payloads (``turn1search7``) are markers, so the pattern is
    bounded to id characters and a real title with spaces survives.
    """
    raw = "The novel <cite>Moby Dick</cite> is referenced."
    assert clean_m365_citations(raw) == raw


def test_dedupe_signature_collapses_both_citation_renderings():
    """The same sentence in either rendering must yield ONE signature.

    This is the comparison that decides whether the final frame's restatement is
    appended, so a mismatch here is what surfaced as a duplicated answer.
    """
    delta_form = "FastAPI 性能媲美 Node.js。<cite>turn1search7</cite>"
    snapshot_form = "FastAPI 性能媲美 Node.js。【4-6f710b】"
    assert _dedupe_signature(delta_form) == _dedupe_signature(snapshot_form)


def test_message_content_strips_citations_from_text():
    entry = {"text": "音频 [x](\ue200cite\ue202turn1file1\ue201) 完成"}
    assert "\ue200" not in _message_content(entry)
    assert "完成" in _message_content(entry)


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
