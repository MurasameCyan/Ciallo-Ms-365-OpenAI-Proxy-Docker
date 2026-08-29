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


# ---------------------------------------------------------------------------
# Dead-vs-benign classification for pyflakes F401 ("imported but unused").
#
# A module-level import can be "unused" for two very different reasons:
#   1. Re-export bridge / facade: the module imports a symbol only so OTHER
#      modules can do `from .<thismod> import <name>` (e.g. cli.py re-exporting
#      cli_cdp helpers, templates.py re-exporting the *_HTML blobs). Deleting it
#      breaks the consumer at runtime -- exactly the cli->cli_cdp split bug in
#      AGENTS.md. These are auto-detected (no manual upkeep) by scanning every
#      source/test file for a matching `from .<thismod> import <name>`.
#   2. `__all__` export: the name is listed in the module's __all__, so it is a
#      deliberate public re-export even if unused locally.
#
# Anything else is either genuine dead code OR a symbol only reachable through a
# lazy `from .x import y` inside a function body (a monkeypatch blind spot per
# AGENTS.md). Those are tracked in _KNOWN_UNUSED_IMPORTS as an explicit,
# reviewed baseline: the guard fails on any NEW unused import, forcing a
# conscious decision (delete it, or justify + append to the baseline).
# ---------------------------------------------------------------------------

# Baseline of pre-existing, human-reviewed unused imports: (filename, name).
# NOT re-export bridges (those are auto-exempt) -- these are legacy imports that
# may be reachable only via lazy in-body imports (CDP capture path), so per the
# AGENTS.md split rules they are NOT blindly deleted. Trim this set only after a
# runtime/three-layer audit proves a given symbol is truly unreachable.
_KNOWN_UNUSED_IMPORTS: set[tuple[str, str]] = {
    ("cli.py", "json"),
    ("cli.py", "httpx"),
    ("cli.py", "websockets"),
    ("cli.py", "is_substrate_token_claims"),
    ("cli.py", "_cdp_nudge_and_wait_for_token"),
    ("cli.py", "_capture_token_to_env"),
    ("cli.py", "_classify_resource_token"),
    ("cli.py", "_ensure_first_page_navigates_to_m365"),
    ("cli.py", "_find_m365_page"),
    ("cli.py", "_is_m365_page_url"),
    ("cli.py", "_navigate_tab_to_m365"),
    ("cli.py", "_needs_substrate_token"),
    ("cli.py", "_select_substrate_token"),
    ("cli.py", "_startup_capture_loop"),
    ("cli.py", "_summarize_cdp_tabs"),
    ("cli.py", "_token_identity_email"),
    ("cli.py", "_wait_for_substrate_websocket_token"),
    ("refresh_scheduler.py", "json"),
    ("refresh_scheduler.py", "designer_file_token"),
    ("refresh_scheduler.py", "_is_login_url"),
    ("refresh_scheduler.py", "_is_logged_out_shell"),
    ("refresh_scheduler.py", "_resolve_chromium_path"),
    ("refresh_scheduler.py", "_cdp_cookie_params"),
    ("refresh_scheduler.py", "_critical_cookie_report"),
    ("refresh_scheduler.py", "_normalize_cookie_expires"),
    ("refresh_scheduler.py", "_normalize_cookie_same_site"),
    ("refresh_scheduler.py", "_auth_headers_for_token"),
    ("refresh_scheduler.py", "_is_teams_media_url"),
}


def _reexported_names() -> set[tuple[str, str]]:
    """(module_filename, symbol) pairs that some file imports FROM another local
    module, i.e. the exporting module legitimately re-exports that symbol."""
    pairs: set[tuple[str, str]] = set()
    search_dirs = [_SRC, Path(__file__).resolve().parent]
    seen: set[Path] = set()
    for base in search_dirs:
        for path in base.glob("*.py"):
            if path in seen:
                continue
            seen.add(path)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                    exporter = f"{node.module.split('.')[-1]}.py"
                    for alias in node.names:
                        pairs.add((exporter, alias.name))
    return pairs


def _all_exports() -> dict[str, set[str]]:
    """filename -> names listed in that module's module-level __all__."""
    exports: dict[str, set[str]] = {}
    for path in _SRC.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                    exports.setdefault(path.name, set()).update(
                        el.value for el in node.value.elts
                        if isinstance(el, ast.Constant) and isinstance(el.value, str)
                    )
    return exports


def _line_has_f401_noqa(filename: str, lineno: int) -> bool:
    """Whether that source line silences F401 with a ``# noqa`` comment.

    pyflakes does not implement ``# noqa`` itself -- measured: it reports the
    import regardless of the marker -- while this codebase uses the marker as its
    convention for an import kept deliberately for its side effect. The live case
    is consumer_camoufox's ``import camoufox.async_api  # noqa: F401`` inside
    ``camoufox_available()``, where the import IS the test: binding the name is
    beside the point and deleting it would delete the probe.

    Honouring the marker here keeps that idiom expressible without parking a
    permanent entry in _KNOWN_UNUSED_IMPORTS, which exists for unreviewed debt
    rather than for intent the author already stated in the source.
    """
    try:
        line = Path(filename).read_text(encoding="utf-8").splitlines()[lineno - 1]
    except (OSError, IndexError):
        return False
    comment = line.partition("#")[2].lower()
    if "noqa" not in comment:
        return False
    codes = comment.split("noqa", 1)[1].lstrip()
    if not codes.startswith(":"):
        return True  # bare `# noqa` silences every code, F401 included
    return "f401" in codes


def test_no_dead_unused_imports():
    """Fail on any NEW unused import that is not a re-export bridge.

    Re-export bridges (consumed via `from .<mod> import <name>` elsewhere) and
    __all__ exports are auto-exempt. Everything else must be either removed or
    explicitly listed in _KNOWN_UNUSED_IMPORTS with justification. This turns the
    ad-hoc pyflakes scan into a CI gate that catches dead imports before they
    accrete, while never forcing the deletion of a lazily-referenced symbol.
    """
    pyflakes_api = pytest.importorskip("pyflakes.api")
    from pyflakes import messages as pyflakes_messages  # noqa: WPS433
    from pyflakes import reporter as pyflakes_reporter  # noqa: WPS433

    reexported = _reexported_names()
    all_exports = _all_exports()
    found: set[tuple[str, str]] = set()

    class _Collect(pyflakes_reporter.Reporter):
        def __init__(self) -> None:
            super().__init__(io.StringIO(), io.StringIO())

        def flake(self, message) -> None:  # noqa: ANN001
            if not isinstance(message, pyflakes_messages.UnusedImport):
                return
            if _line_has_f401_noqa(message.filename, message.lineno):
                return
            fname = Path(message.filename).name
            # message_args[0] is the full import string, e.g. ".cli_cdp._foo" or
            # "httpx"; the bound name is its last dotted segment.
            bound = str(message.message_args[0]).split(".")[-1]
            found.add((fname, bound))

    reporter = _Collect()
    for path in sorted(_SRC.glob("*.py")):
        pyflakes_api.checkPath(str(path), reporter)

    offenders: list[str] = []
    for fname, name in sorted(found):
        if (fname, name) in reexported:
            continue  # re-export bridge: consumed elsewhere
        if name in all_exports.get(fname, set()):
            continue  # deliberate __all__ export
        if (fname, name) in _KNOWN_UNUSED_IMPORTS:
            continue  # reviewed baseline debt
        offenders.append(f"{fname}: unused import {name!r}")

    assert not offenders, (
        "new dead imports (delete them, or justify + add to "
        "_KNOWN_UNUSED_IMPORTS):\n" + "\n".join(offenders)
    )

    # Keep the baseline honest: flag entries that no longer apply so the set is
    # trimmed as debt is paid down instead of silently rotting.
    stale = sorted(
        f"{fname}: {name}"
        for (fname, name) in _KNOWN_UNUSED_IMPORTS
        if (fname, name) not in found
        or (fname, name) in reexported
        or name in all_exports.get(fname, set())
    )
    assert not stale, (
        "stale _KNOWN_UNUSED_IMPORTS entries (no longer unused or now "
        "auto-exempt -- remove them):\n" + "\n".join(stale)
    )


def _names_bound_in_own_scope(func: ast.AST) -> set[str]:
    """Names the function body rebinds, ignoring nested function/class scopes.

    A nested scope gets its own ``nonlocal``/``global`` declaration, so its
    assignments say nothing about whether the outer declaration carries weight.
    Comprehension targets are likewise skipped: they live in the comprehension's
    own scope and never touch the enclosing function's binding.
    """
    bound: set[str] = set()
    _NESTED_SCOPES = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.Lambda,
        ast.ClassDef,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
    )

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _NESTED_SCOPES):
                # The def/class statement itself binds its own name here; what it
                # does inside is governed by its own scope declarations.
                name = getattr(child, "name", None)
                if name:
                    bound.add(name)
                continue
            visit(child)

    for stmt in getattr(func, "body", []):
        if isinstance(stmt, _NESTED_SCOPES):
            name = getattr(stmt, "name", None)
            if name:
                bound.add(name)
            continue
        visit(stmt)
    return bound


def _own_scope_nonlocal_names(func: ast.AST) -> set[str]:
    """Names declared ``nonlocal`` by this function itself, not by a nested def."""
    names: set[str] = set()

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue  # nested scope owns its own declarations
            if isinstance(child, ast.Nonlocal):
                names.update(child.names)
            visit(child)

    visit(func)
    return names


def test_no_redundant_nonlocal_declarations():
    """Fail on ``nonlocal x`` in a function that never rebinds ``x``.

    Reading a closed-over name needs no declaration -- the free-variable lookup
    already finds it -- so a ``nonlocal`` naming a read-only name is noise that
    reads as "this function writes here". pyflakes has no check for it, which is
    how routes_api_messages accumulated four such names across three closures
    (`shortfall_note`/`declined_note` in router_answer and studio_answer,
    `actual_planning` in inline_answer) while every gate stayed green.

    The declaration is kept whenever the function's own body binds the name by
    any means -- assignment, augmented assignment, walrus, for/with/except
    target, del, import, nested def/class -- so this only ever flags a name the
    function provably cannot write.
    """
    offenders: list[str] = []
    for path in sorted(_SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            declared = _own_scope_nonlocal_names(node)
            if not declared:
                continue
            writable = _names_bound_in_own_scope(node)
            for name in sorted(declared - writable):
                offenders.append(
                    f"{path.name}:{node.lineno} {node.name}(): "
                    f"nonlocal {name!r} but never assigns it"
                )

    assert not offenders, (
        "redundant nonlocal declarations (the name is only read -- drop it from "
        "the nonlocal statement):\n" + "\n".join(offenders)
    )
