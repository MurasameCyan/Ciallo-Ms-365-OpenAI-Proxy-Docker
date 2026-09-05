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
    ".nav-item.active::after",
    ".nav-item.active:after",
)

# A rule only runs unconditionally when its selector carries no interaction
# state. `.nav-item:hover::after` animating is fine; `.orb` animating is not.
#
# `.active` is deliberately NOT in here. It reads like an interaction state but
# on a nav item it marks the current page, so it is set from page load and never
# clears -- the selected tab animated forever and the first version of this test
# waved it through.
_STATE_GATED = (":hover", ":focus", ":active", "[open]", ".open", ".on", ".loading", "@keyframes")

_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _selectors_of(rule_selector: str) -> list[str]:
    return [" ".join(part.split()) for part in rule_selector.split(",")]


def _always_on_animated_rules(css: str) -> list[tuple[str, str]]:
    """Rules that start an animation with no interaction state in the selector.

    Judged per comma-separated selector, not per rule: `.nav-item:hover::after,
    .nav-item.active::after` shares one body, and treating the rule as gated
    because *one* of its selectors is `:hover` is how the always-on `.active`
    variant slipped through.
    """
    found = []
    for selector, body in _RULE_RE.findall(css):
        sel = " ".join(selector.split())
        if not re.search(r"(^|[;\s])animation\s*:", body):
            continue
        # `animation:none` and `animation-*` longhands that stop motion are fine.
        if re.search(r"animation\s*:\s*none", body):
            continue
        ungated = [p for p in _selectors_of(sel) if not any(gate in p for gate in _STATE_GATED)]
        if not ungated:
            continue
        found.append((", ".join(ungated), body))
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
def test_light_theme_does_not_restart_ambient_motion(page: str) -> None:
    """The light theme must not switch ambient motion back on.

    `_STILL_DECOR_CSS` is appended last, so it beats an equally-important rule
    above it -- but a `body[data-theme="light"]` rule carries a higher-specificity
    selector, so an `animation:<name>!important` there WOULD win and restart the
    motion. Every light-theme `animation` today is `none` (light already dropped
    some focus sweeps of its own), which is why light measured 1-2% of a core on
    all three views against dark's 0-1%. This keeps it that way.

    Light is not the cheaper theme by accident and is not exempt from the rest:
    it raises every blur to 28px (dark runs 14-22px), and SMIL animation is
    theme-independent, so the dashboard fix mattered equally in both.
    """
    css = _css_of(PAGES[page])
    restarted = [
        (" ".join(sel.split()), m.group(1).strip())
        for sel, body in _RULE_RE.findall(css)
        if 'data-theme="light"' in sel
        for m in [re.search(r"(?:^|[;\s])animation\s*:\s*([^;]+)", body)]
        if m and not m.group(1).lstrip().startswith("none")
    ]
    assert not restarted, (
        f"{page} page light theme starts an animation; a light-theme selector outranks "
        f"the shared freeze block, so this runs even though the decor is frozen:\n"
        + "\n".join(f"  {sel} -> animation:{val}" for sel, val in restarted)
    )


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


def test_donut_ring_holds_still_and_only_its_halo_breathes() -> None:
    """The rings may keep one ambient animation, and only in discrete notches.

    The colour band carries nothing: it was asked to hold still, and the shares
    are what a reader measures off it. What is left is the blurred halo group
    breathing its opacity, which is affordable only because it is stepped.
    Measured on the live dashboard, idle, whole Chrome process tree:

        linear (continuous)          115-137% of one core
        steps(60), ~92ms per notch        9%
        steps(36), ~153ms per notch       6%
        steps(24), ~229ms per notch       3%
        not animating                     0%

    The donut sits in a stack of 37 backdrop-filter surfaces that cannot be
    composited, so every frame is a real repaint -- stripping all SVG filters
    still cost 104%, and `will-change`/`contain` made it worse. Drawing fewer
    frames is the only lever, so a `steps()` timing function is load-bearing
    here, not a style choice. A future edit swapping it for `linear` would look
    identical and cost 13x more, which is exactly the regression to catch.
    """
    css = _css_of(_ADMIN_HTML)
    spun = [f"{sel} -> {body.strip()[:110]}" for sel, body in _RULE_RE.findall(css) if ".donut-spin" in sel]
    assert not spun and 'class="donut-spin"' not in _ADMIN_HTML, (
        "the dashboard rings rotate again; the ring was asked to be a static colour "
        "band:\n" + "\n".join(spun)
    )
    rules = [body for sel, body in _RULE_RE.findall(css) if ".donut-breathe" in sel and "animation" in body]
    assert rules, "admin dashboard donut lost its halo breath; .donut-breathe has no animation"
    for body in rules:
        assert re.search(r"animation\s*:[^;]*steps\(", body), (
            f"admin .donut-breathe animates continuously; on this page that is 115-137% of a "
            f"CPU core versus 3-6% stepped:\n  {body.strip()[:140]}"
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
def test_no_indefinite_smil_animation(page: str) -> None:
    """SVG SMIL animation must not repeat forever.

    Separate from the CSS rules above because `animation:none` cannot reach it
    and `document.getAnimations()` does not report it -- which is why freezing
    the CSS decor left the signed-in admin console untouched. Measured there:
    43 `<animate>` elements, 39 of them `repeatCount="indefinite"`, driving
    ~1460 style recalcs/s and 105% of a core in RecalcStyleDuration alone.
    `svg.pauseAnimations()` dropped that to 2%, and unpausing restored it.

    Worse than a CSS animation of the same size: the donut animates
    `stroke-width`, so every frame invalidates layout as well as style, and two
    of its three rings carry an feGaussianBlur filter that is re-run per frame.
    """
    for tag in ("animate", "animateTransform", "animateMotion"):
        # `[^<>\n]*` so a `<animate` wrapped across lines in a comment cannot
        # match forward into a later attribute; real markup is emitted on one line.
        offenders = re.findall(rf"<{tag}\b[^<>\n]*repeatCount\s*=\s*[\"']indefinite", PAGES[page])
        assert not offenders, (
            f"{page} page has {len(offenders)} <{tag} repeatCount=\"indefinite\">; SMIL runs "
            f"off the CSS animation machinery, so it keeps recalculating style forever and no "
            f"animation:none rule can stop it"
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
