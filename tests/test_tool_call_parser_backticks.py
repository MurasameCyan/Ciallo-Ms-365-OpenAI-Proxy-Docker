from __future__ import annotations

import json

from m365_copilot_openai_proxy.tool_call_parser import (
    _extract_tool_calls,
    _strip_tool_call_blocks,
)


def _build_write_block(content: str) -> str:
    """A ```tool_call block whose Write content itself contains ``` fences."""
    payload = {
        "name": "Write",
        "arguments": {"file_path": "S:/tmp/readme.md", "content": content},
    }
    return (
        "Sure, here is the file:\n\n"
        "```tool_call\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\n```\n\n"
        "Let me know if you need changes."
    )


def test_extract_tool_call_with_backticks_in_content():
    # Markdown content containing a fenced python code block — this is exactly the
    # case the old non-greedy `\{.*?\}``` regex truncated (it stopped at the first
    # ``` inside the content), dropping the whole tool_call.
    content = "# Title\n\n```python\nprint('hi')\n```\n\nDone.\n"
    text = _build_write_block(content)

    calls = _extract_tool_calls(text)

    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "Write"
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["file_path"] == "S:/tmp/readme.md"
    assert args["content"] == content


def test_extract_tool_call_with_nested_json_object_content():
    # Nested braces inside the arguments must not confuse balanced-brace decoding.
    content = '{"a": {"b": [1, 2, 3]}, "c": "text with } brace"}'
    text = _build_write_block(content)

    calls = _extract_tool_calls(text)

    assert len(calls) == 1
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["content"] == content


def test_strip_tool_call_blocks_removes_block_with_inner_backticks():
    content = "# Title\n\n```python\nprint('hi')\n```\n"
    text = _build_write_block(content)

    remaining = _strip_tool_call_blocks(text)

    # The whole fenced tool_call (including the inner ``` fences) is removed,
    # surrounding prose is kept.
    assert "```tool_call" not in remaining
    assert "print('hi')" not in remaining
    assert remaining.startswith("Sure, here is the file:")
    assert remaining.endswith("Let me know if you need changes.")


def test_extract_plain_json_fence_still_detected():
    # A bare ```json fence with a tool-call-shaped object is still parsed via fallback.
    text = (
        "```json\n"
        '{"name": "Read", "arguments": {"file_path": "S:/tmp/a.txt"}}\n'
        "```"
    )

    calls = _extract_tool_calls(text)

    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "Read"
