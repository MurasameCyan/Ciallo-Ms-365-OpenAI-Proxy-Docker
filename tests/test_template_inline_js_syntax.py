from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from m365_copilot_openai_proxy.templates import _ADMIN_HTML, _LOGIN_HTML, _USER_HTML

# JS smoke test for the inline <script> blocks in the rendered templates.
#
# WHY: template_admin/user/login embed large JS blobs that are assembled by
# string concatenation across several modules (template_admin_*.py, etc.). A
# split that reorders or drops a fragment can produce a syntactically broken
# <script> that no Python test would catch -- the pytest suite only does string
# assertions on the templates, it never parses the JS. This runs `node --check`
# on each rendered <script> so a broken concatenation fails fast.
#
# BOUNDARY (honest scope): `node --check` only PARSES the script, it does not
# execute it. It catches syntax errors (unbalanced braces, broken string
# literals, bad concatenation order that yields invalid JS) but NOT runtime
# problems like referencing an undefined variable. Runtime correctness of the
# admin/user JS still relies on manual browser verification.

_NODE = shutil.which("node")

_SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.S)


def _script_bodies(html: str) -> list[str]:
    return [body for body in _SCRIPT_RE.findall(html) if body.strip()]


def _node_check(js: str) -> tuple[int, str]:
    # Write to a temp .js file and let Node parse it. --check reports syntax
    # errors without executing, which is exactly the smoke level we want.
    fd, path = tempfile.mkstemp(suffix=".js")
    Path(path).write_text(js, encoding="utf-8")
    import os

    os.close(fd)
    try:
        proc = subprocess.run(
            [_NODE, "--check", path],
            capture_output=True,
            text=True,
        )
        return proc.returncode, proc.stderr.strip()
    finally:
        Path(path).unlink(missing_ok=True)


_TEMPLATES = [
    ("admin", _ADMIN_HTML),
    ("user", _USER_HTML),
    ("login", _LOGIN_HTML),
]


@pytest.mark.skipif(_NODE is None, reason="node not available for JS syntax check")
@pytest.mark.parametrize("name,html", _TEMPLATES, ids=[t[0] for t in _TEMPLATES])
def test_template_inline_js_parses(name: str, html: str):
    bodies = _script_bodies(html)
    assert bodies, f"{name} template has no non-empty <script> block"
    for i, js in enumerate(bodies):
        rc, err = _node_check(js)
        assert rc == 0, f"{name} template <script> #{i} failed node --check:\n{err}"
