"""The capture panel must survive an optionsSets that is not a list.

POST /admin/capture-payload stores whatever the userscript pushed (it is the one
admin endpoint with no auth by design -- a cross-origin Tampermonkey push cannot
carry the cookie), and renderCapture then did ``(p.optionsSets||[]).join(', ')``.
A string or object there threw, the throw landed in loadCapture's empty catch, and
the panel went blank with nothing in the console -- permanently, because
__capVersion had already advanced so every later poll answered "unchanged".

Executes the real renderCapture out of the rendered template under node with a
stub DOM, rather than asserting on the source text: the point is what it does with
each shape, and a string assertion would pass on a rewrite that still throws.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from m365_copilot_openai_proxy.templates import _ADMIN_HTML

_NODE = shutil.which("node")

_HARNESS = """
globalThis.window=globalThis;
const panel={innerHTML:'',querySelectorAll:()=>[]};
const count={textContent:''};
globalThis.document={getElementById:id=>id==='capture-content'?panel:count};
globalThis.t=k=>k;
%(funcs)s
const out=[];
for(const shape of %(shapes)s){
  panel.innerHTML='';
  renderCapture([{time:'12:00:00',tone:'Magic',modelId:'m',optionsSets:shape,raw:'{}'}]);
  out.push(panel.innerHTML);
}
console.log(JSON.stringify(out));
"""

# Every shape the endpoint will actually hand the panel. The list is the normal
# case and must keep rendering as "a, b" -- formatRawText alone would JSON it.
SHAPES = [
    ["fluxcopilot", "nojcheck"],
    "fluxcopilot,nojcheck",
    {"sets": ["fluxcopilot"]},
    None,
    17,
]
EXPECTED = [
    "fluxcopilot, nojcheck",
    "fluxcopilot,nojcheck",
    '"sets"',
    "optionsSets: </div>",
    "17",
]


def _js_function(js: str, name: str) -> str:
    """Slice one top-level `function name(...){...}` out of a script body."""
    start = js.index(f"function {name}(")
    depth = 0
    for i in range(js.index("{", start), len(js)):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                return js[start : i + 1]
    raise AssertionError(f"unbalanced braces in {name}")


@pytest.mark.skipif(_NODE is None, reason="node not available for JS execution")
def test_every_options_sets_shape_still_renders_the_record():
    script = _HARNESS % {
        "funcs": "\n".join(
            _js_function(_ADMIN_HTML, name) for name in ("formatRawText", "renderCapture")
        ),
        "shapes": json.dumps(SHAPES),
    }
    fd = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    with fd:
        fd.write(script)
    try:
        proc = subprocess.run([_NODE, fd.name], capture_output=True, text=True)
    finally:
        Path(fd.name).unlink(missing_ok=True)

    assert proc.returncode == 0, f"renderCapture threw:\n{proc.stderr.strip()}"
    rendered = json.loads(proc.stdout.strip().splitlines()[-1])
    for shape, expected, html in zip(SHAPES, EXPECTED, rendered):
        # The record itself has to be there: a blank panel is the bug, and an empty
        # optionsSets line inside a rendered record is not.
        assert "tone: <b>Magic</b>" in html, f"{shape!r} rendered nothing: {html!r}"
        assert expected in html, f"{shape!r} lost its optionsSets: {html!r}"
