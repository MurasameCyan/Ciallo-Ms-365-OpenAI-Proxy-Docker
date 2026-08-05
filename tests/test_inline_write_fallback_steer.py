"""The inline-fallback instruction must describe a shape the parser accepts.

M365 answers a file request by generating a hosted attachment: the reply carries
a download link and no code block, so ``_extract_prose_write`` -- which is sound,
and stays strict on purpose -- has nothing to match and the file never reaches
the user's path.

The prompt now steers a model that will not emit the ```tool_call``` fence toward
the prose shape the fallback CAN synthesize a Write from. That only helps if the
instruction and the parser agree on the shape, so these tests assert the round
trip rather than the wording alone: a reply written exactly as instructed must
parse into a correct Write.
"""

from __future__ import annotations

import json

import pytest

from m365_copilot_openai_proxy.substrate_parse import _combine_text
from m365_copilot_openai_proxy.tool_call_parser import _extract_prose_write
from m365_copilot_openai_proxy.translator import default_tool_system_prompt


def _tools_context():
    return ["System instructions:\nUse ```tool_call``` blocks.\n\nAvailable action types:\n- Write: ..."]


# ------------------------------------------------------- instruction wording
def test_system_prompt_forbids_hosting_a_file_itself():
    """The existing rule only forbade SUBSTITUTING a link for a Write. A generated
    attachment is not a substitution in the model's eyes -- it hosts a real file --
    so it slipped past and never reached the path the user named."""
    prompt = default_tool_system_prompt()
    assert "Do NOT generate, upload, or attach a file" in prompt
    assert "download link" in prompt


def test_system_prompt_describes_the_inline_fallback_shape():
    prompt = default_tool_system_prompt()
    assert "backticked absolute path" in prompt
    assert "fenced code block tagged with the file's language" in prompt


def test_format_block_repeats_the_inline_fallback_shape():
    """[FORMAT] is the last thing before the answer, so the steer belongs there too."""
    combined = _combine_text("Write a batch file", _tools_context())
    assert "backticked absolute path" in combined
    assert "Never attach a file in place of this" in combined


# ------------------------------------------------- instruction parses back
@pytest.mark.parametrize(
    ("path", "lang", "body"),
    [
        ("C:/temp/hello.bat", "bat", "@echo off\necho Hello"),
        ("S:/work/run.py", "python", 'print("Hello")'),
        ("/srv/www/index.html", "html", "<!doctype html>\n<title>Proxy</title>"),
        ("D:/site/app.js", "javascript", "console.log('hi')"),
    ],
)
def test_a_reply_written_as_instructed_parses_into_a_write(path, lang, body):
    """The round trip the whole change rests on: obey the instruction, get a Write."""
    reply = f"Saved to `{path}`\n\n```{lang}\n{body}\n```"
    calls = _extract_prose_write(reply, {"Write"})
    assert len(calls) == 1, f"instructed shape did not parse for .{path.rsplit('.', 1)[-1]}"
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["file_path"] == path
    assert args["content"] == body


def test_the_attachment_shape_still_parses_into_nothing():
    """What M365 actually returns today: a link, no code block. Nothing to salvage --
    asserted so the reason the steer exists stays visible."""
    reply = "Created the batch file: [hello.bat](http://host/v1/m365-media?u=aHR0cHM6&sig=abc)"
    assert _extract_prose_write(reply, {"Write"}) == []


def test_strictness_is_not_relaxed_by_the_new_wording():
    """Loosening the parser would let a usage example overwrite a real file. These
    shapes must keep failing, whatever the prompt now asks for."""
    assert _extract_prose_write("Saved to `hello.py`\n\n```python\nx=1\n```", {"Write"}) == []
    assert _extract_prose_write("Saved to C:/t/a.py\n\n```python\nx=1\n```", {"Write"}) == []
    assert _extract_prose_write("Run it:\n\n```bash\npython a.py\n```", {"Write"}) == []
