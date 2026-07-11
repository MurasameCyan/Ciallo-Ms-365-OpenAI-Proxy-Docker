from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src" / "m365_copilot_openai_proxy"

# Stdlib modules that are commonly referenced as `name.attr` in this codebase.
# The guard only flags a missing import when one of these names is used as a
# module (attribute access) but never imported at any scope in the file.
_STDLIB_MODULES = {
    "re",
    "os",
    "sys",
    "json",
    "time",
    "asyncio",
    "base64",
    "shutil",
    "subprocess",
    "tempfile",
    "logging",
    "platform",
    "select",
    "threading",
    "argparse",
    "hashlib",
    "math",
    "random",
    "datetime",
    "functools",
    "itertools",
    "collections",
    "uuid",
    "io",
    "traceback",
    "warnings",
    "copy",
    "inspect",
    "signal",
    "socket",
}


def _imported_names(tree: ast.AST) -> set[str]:
    """All names bound by any import statement, at any scope."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _module_attr_usages(tree: ast.AST) -> set[str]:
    """Names used as `name.attr`, e.g. the `re` in `re.search(...)`."""
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            used.add(node.value.id)
    return used


def test_no_stdlib_module_used_without_import():
    """Regression guard for split-induced missing imports.

    When cli.py was split into cli_cdp.py the `import re` was left behind, so
    `re.search` in the CDP nudge path raised NameError at runtime. That path is
    monkeypatched in the unit tests, so the missing import slipped through all
    197 tests and only surfaced as "no fresh substrate token captured" in
    production. This static scan fails fast if any stdlib module is referenced
    as `module.attr` without a corresponding import anywhere in the file.
    """
    problems: list[str] = []
    for path in sorted(_SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = _imported_names(tree)
        used = _module_attr_usages(tree)
        for name in sorted(used & _STDLIB_MODULES):
            if name not in imported:
                problems.append(f"{path.name}: uses `{name}.` but never imports `{name}`")
    assert not problems, "missing stdlib imports:\n" + "\n".join(problems)


# Known-benign pyflakes F821 hits to ignore: (filename, undefined-name).
# translator.translate_responses_request uses a *string* forward-reference
# annotation "OpenAIResponsesRequest" plus a lazy `from .models import ...`
# inside the body. pyflakes cannot see through the string annotation, but the
# name is never evaluated at module scope, so this is safe by design.
_F821_ALLOWED = {
    ("translator.py", "OpenAIResponsesRequest"),
}


def test_no_undefined_module_level_names():
    """Regression guard for split-induced missing symbols (constants, helpers).

    The stdlib-import guard above only catches `module.attr` usages. It would
    NOT have caught the CDP JS constants (_CDP_JS / _CDP_NUDGE_JS /
    _CDP_DELETE_MSG_JS) or the cli helpers (_seconds_remaining /
    _try_auto_refresh / _write_token) that the cli -> cli_cdp split left behind:
    those raised NameError at runtime but were masked by monkeypatching in the
    unit tests. pyflakes' F821 (undefined name) sees all of them statically.
    """
    pyflakes_api = pytest.importorskip("pyflakes.api")
    from pyflakes import reporter as pyflakes_reporter  # noqa: WPS433

    problems: list[str] = []

    class _Collect(pyflakes_reporter.Reporter):
        def __init__(self) -> None:
            super().__init__(io.StringIO(), io.StringIO())

        def flake(self, message) -> None:  # noqa: ANN001
            from pyflakes import messages as pyflakes_messages  # noqa: WPS433

            if not isinstance(message, pyflakes_messages.UndefinedName):
                return
            fname = Path(message.filename).name
            name = message.message_args[0]
            if (fname, name) in _F821_ALLOWED:
                return
            problems.append(f"{fname}:{message.lineno}: undefined name {name!r}")

    reporter = _Collect()
    for path in sorted(_SRC.glob("*.py")):
        pyflakes_api.checkPath(str(path), reporter)

    assert not problems, "undefined names (split-induced missing symbols?):\n" + "\n".join(problems)
