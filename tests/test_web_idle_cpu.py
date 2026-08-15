from __future__ import annotations

import re

import pytest

from m365_copilot_openai_proxy.templates import _ADMIN_HTML, _LOGIN_HTML, _USER_HTML

# Guards the idle CPU cost of the rendered pages.
#
# WHY: every page stacks blurred surfaces -- a fixed `filter:blur()` `.orb`
# behind cards that carry `backdrop-filter`. A blur is only cheap while its
# source is still: as soon as anything in that stack animates, the blurred
# surfaces are re-derived every frame, off the renderer main thread, in the GPU
# process. Measured on a live deployment with Chrome (idle page, no input):
#
#     view                as shipped   animations frozen
#     login                   49%              2%
#     signed-in user          69%              2%
#     admin                   85%              1%
#
# ...of one CPU core, for decoration nobody interacts with. Freezing a single
# animation while another still runs barely helped (-1 to -11 points); only
# stopping all continuous motion collapsed the cost. Confirming the mechanism:
# an opacity-only animation on the blurred orb still cost 52%, while a transform
# animation on an unblurred element cost 2%. So the rule is about what the
# animation touches, not which property it animates.
#
# The fix these tests lock in: ambient decor -- decor that runs forever without
# any user interaction -- must not animate. Animations gated on :hover, :focus,
# [open], .loading and friends are untouched; they run only while the user is
# actually interacting, which is brief and expected.
#
# BOUNDARY (honest scope): this parses CSS text, it does not render or measure.
# It catches an always-on `animation:` on the known ambient selectors, which is
# how the regression happened. It cannot catch a newly added ambient element
# under a different selector, nor prove a rendered frame rate. Re-measure with
# tests/manual/measure_web_cpu.py after touching page CSS.

PAGES = {"admin": _ADMIN_HTML, "login": _LOGIN_HTML, "user": _USER_HTML}

# Decorative elements that exist purely to look alive, are not gated on any
# interaction state, and sit inside the blurred stack.
AMBIENT_SELECTORS = (
    ".orb",
    ".brand-mark:before",
    ".brand-mark::before",
    ".brand-mark:after",
    ".brand-mark::after",
    ".account-side:before",
    ".debug-gate:before",
    ".data-globe:before",
    ".data-globe:after",
    ".flow-box::after",
    ".tenant-pill:before",
    ".tone-share-fill",
    ".glass-select-menu:before",
)

# A rule only runs unconditionally when its selector carries no interaction
# state. `.nav-item:hover::after` animating is fine; `.orb` animating is not.
_STATE_GATED = (":hover", ":focus", ":active", "[open]", ".open", ".on", ".loading", ".active", "@keyframes")

_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _selectors_of(rule_selector: str) -> list[str]:
    return [" ".join(part.split()) for part in rule_selector.split(",")]


def _always_on_animated_rules(css: str) -> list[tuple[str, str]]:
    """Rules that start an animation with no interaction state in the selector."""
    found = []
    for selector, body in _RULE_RE.findall(css):
        sel = " ".join(selector.split())
        if not re.search(r"(^|[;\s])animation\s*:", body):
            continue
        # `animation:none` and `animation-*` longhands that stop motion are fine.
        if re.search(r"animation\s*:\s*none", body):
            continue
        if any(gate in sel for gate in _STATE_GATED):
            continue
        found.append((sel, body))
    return found


def _muted_selectors(css: str) -> set[str]:
    """Selectors an `animation:none!important` rule switches off.

    Checked instead of the raw declarations because the fix keeps the decorative
    CSS intact and overrides it in one shared block, so re-enabling the motion
    stays a one-line change. `!important` wins over the earlier declaration
    regardless of order or specificity, which is what the browser does -- and
    what `document.getAnimations()` confirmed on the live page.
    """
    muted: set[str] = set()
    for selector, body in _RULE_RE.findall(css):
        if re.search(r"animation\s*:\s*none\s*!important", body):
            muted.update(_selectors_of(selector))
    return muted


def _css_of(html: str) -> str:
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))


@pytest.mark.parametrize("page", sorted(PAGES))
def test_ambient_decor_does_not_animate_forever(page: str) -> None:
    css = _css_of(PAGES[page])
    muted = _muted_selectors(css)
    offenders = [
        (sel, body)
        for sel, body in _always_on_animated_rules(css)
        if any(amb in sel for amb in AMBIENT_SELECTORS)
        # Every selector the rule targets has to be switched off, otherwise one
        # of them is still animating and still driving the per-frame re-blur.
        and not all(
            any(part.endswith(m) or m.endswith(part) for m in muted)
            for part in _selectors_of(sel)
            if any(amb in part for amb in AMBIENT_SELECTORS)
        )
    ]
    assert not offenders, (
        f"{page} page animates ambient decor with no interaction gate and no "
        f"animation:none override; each of these re-rasterises the blurred stack "
        f"every frame:\n"
        + "\n".join(f"  {sel} -> {body.strip()[:110]}" for sel, body in offenders)
    )


@pytest.mark.parametrize("page", sorted(PAGES))
def test_pages_honour_prefers_reduced_motion(page: str) -> None:
    """A reduced-motion request must stop the remaining interaction animations too."""
    css = _css_of(PAGES[page])
    assert "prefers-reduced-motion" in css, (
        f"{page} page has no prefers-reduced-motion block, so a user who asked the OS "
        f"to reduce motion still gets every hover/focus sweep"
    )


@pytest.mark.parametrize("page", sorted(PAGES))
def test_autofocused_field_does_not_sweep(page: str) -> None:
    """An `autofocus` field starts its focus animation with nobody interacting.

    Measured 43% of a core on /admin from this alone: the sweep animates
    `background-position`, which never leaves the main thread, and the field sits
    on a blurred card. Only the sweep is dropped -- border and glow still apply.
    """
    css = _css_of(PAGES[page])
    if "autofocus" not in PAGES[page]:
        pytest.skip(f"{page} page has no autofocus field")
    assert re.search(r"\[autofocus\]:focus\{[^{}]*animation\s*:\s*none\s*!important", css), (
        f"{page} page autofocuses a field whose :focus rule animates, so the sweep "
        f"runs from page load with no interaction"
    )


@pytest.mark.parametrize("page", sorted(PAGES))
def test_interaction_animations_are_kept(page: str) -> None:
    """The fix must not strip motion that only runs while the user interacts."""
    css = _css_of(PAGES[page])
    gated = [
        sel
        for sel, body in _RULE_RE.findall(css)
        if re.search(r"(^|[;\s])animation\s*:(?!\s*none)", body)
        and any(gate in sel for gate in (":hover", ":focus", "[open]", ".open", ".on", ".loading"))
    ]
    assert gated, f"{page} page lost all interaction-driven animation; only ambient decor should be frozen"
