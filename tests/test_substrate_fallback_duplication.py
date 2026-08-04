from __future__ import annotations

from m365_copilot_openai_proxy.substrate_parse import (
    _dedupe_repeated_delta,
    _dedupe_signature,
    _final_fallback_remainder,
)


# The t==3 fallback is the server's authoritative full message for the turn, so
# it regularly restates what was already streamed with cosmetic differences.
# Emitting it verbatim appended the WHOLE answer a second time -- the "reply
# shows up twice" bug. These guards pin the cases that caused it.


def test_fallback_normalized_image_link_is_not_re_emitted():
    """`_message_content` runs normalize_m365_media_text over the fallback, so a
    bare image URL comes back as ![image](url) while the streamed delta kept the
    raw URL. Same sentence, so nothing may be emitted again."""
    streamed = "这是结果 https://x/a.png 完成"
    fallback = "这是结果 ![image](https://x/a.png) 完成"
    assert _final_fallback_remainder(streamed, fallback) == ""


def test_fallback_reworded_restatement_is_not_re_emitted():
    """M365 sometimes re-words the final frame (here one swapped punctuation
    mark). Neither startswith nor a signature-subset test catches that, so the
    coverage ratio has to."""
    streamed = "第一步做A。第二步做B。第三步做C。"
    fallback = "第一步做A。第二步做B！第三步做C。"
    assert _final_fallback_remainder(streamed, fallback) == ""


def test_fallback_still_emits_genuinely_new_answer():
    """A fallback that shares almost nothing with the stream is real content and
    must survive -- the fix must not silently swallow answers."""
    streamed = "短"
    fallback = "完全不同的一段很长的新内容需要被发出来才对"
    assert _final_fallback_remainder(streamed, fallback) == fallback


def test_fallback_trims_already_streamed_head():
    """Partially covered fallback: the shared head is dropped, only the tail that
    was never streamed is emitted."""
    streamed = "共同开头。"
    fallback = "共同开头。后面这一大段是全新的内容需要补发出来给客户端看到。"
    assert _final_fallback_remainder(streamed, fallback) == (
        "后面这一大段是全新的内容需要补发出来给客户端看到。"
    )


def test_fallback_continuation_suffix_unchanged():
    assert _final_fallback_remainder("Hello", "Hello world") == " world"


def test_signature_collapses_every_url_form():
    """The two sides of a dedupe comparison reach us through different pipelines,
    so a bare URL, a backticked URL and an image link must all normalize away --
    otherwise the same sentence yields two signatures and dedupe misses."""
    assert _dedupe_signature("看 https://x/a.png 完") == "看完"
    assert _dedupe_signature("看 `https://x/a.png` 完") == "看完"
    assert _dedupe_signature("看 ![image](https://x/a.png) 完") == "看完"
    assert _dedupe_signature("看 [t](https://x/a.png) 完") == "看完"


def test_per_delta_guard_still_keeps_repeated_tokens():
    """Regression guard: the signature change must not make the per-delta guard
    eat repeated math/code fragments."""
    streamed = "2a_1 + 3d = 6\n"
    assert _dedupe_repeated_delta(streamed, "2a_1") == "2a_1"
    assert _dedupe_repeated_delta(streamed, " + 7d = 10\n") == " + 7d = 10\n"
    assert _dedupe_repeated_delta(streamed, "}") == "}"
