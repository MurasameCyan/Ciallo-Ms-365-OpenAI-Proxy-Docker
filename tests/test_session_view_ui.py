from __future__ import annotations

import re

from m365_copilot_openai_proxy.templates import _ADMIN_HTML, _USER_HTML

# Guards the two session-view invariants that a browser found and no unit test
# could have: a row list may not grow the card it lives in, and the dropdown
# that opens over that card has to be opaque.
#
# BOUNDARY (honest scope): this reads the rendered CSS text, it does not lay
# anything out. It catches the cap/alpha being dropped or loosened, which is how
# both defects existed in the first place. Re-measure with
# probe-style Playwright runs after reworking either view.

_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _rules_for(html: str, selector: str) -> list[str]:
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))
    return [
        body
        for sel, body in _RULE_RE.findall(css)
        if any(" ".join(part.split()).endswith(selector) for part in sel.split(","))
    ]


def _background_alpha(body: str) -> float:
    """Lowest alpha in the rule's `background` declaration (1.0 when opaque).

    The background only, and its most transparent stop: a menu whose top stop is
    opaque and whose bottom stop is not still shows the card through its bottom
    half, and the shadow/border colours in the same rule are supposed to be
    translucent.
    """
    declaration = re.search(r"(?:^|;)\s*background(?:-image)?\s*:([^;]*)", body)
    if not declaration:
        return 1.0
    alphas = [float(m) for m in re.findall(r"rgba\([^)]*?,\s*([0-9.]+)\)", declaration.group(1))]
    return min(alphas, default=1.0)


def test_user_session_list_scrolls_instead_of_growing_the_card():
    """The /user session list must be height-capped, not free to stretch.

    Measured in Chrome with the store filled to its 1000-session cap: the
    sessions `.card` grew to 43670px (26320px at 600 rows). A card carrying
    `backdrop-filter` stops painting its backdrop past the compositor's max
    texture size (16384px), so from roughly 600 rows on the whole viewport
    rendered as a flat grey-white sheet -- borders, corners and page gradient
    gone. That is the "画面变灰白" report. With the cap the same 1000 rows
    measure 789px and every row is still reachable by scrolling the list.
    """
    rules = _rules_for(_USER_HTML, "#my-sessions-content")
    assert rules, (
        "/user session list lost its height cap; it renders one row per session "
        "(up to 1000) into a backdrop-filtered .card, which stops painting past 16384px"
    )
    body = " ".join(rules)
    assert "max-height" in body, f"#my-sessions-content has no max-height: {body}"
    assert re.search(r"overflow\s*:\s*(auto|scroll)", body), (
        f"#my-sessions-content is capped but cannot scroll, so rows past the cap are unreachable: {body}"
    )


def test_admin_session_table_keeps_its_height_cap():
    """Same failure mode, already prevented on /admin -- keep it that way.

    Measured at 600 and 1000 rows: the `.view-sessions` card stayed at 800px
    purely because of this rule, which is why /admin never greyed out.
    """
    rules = _rules_for(_ADMIN_HTML, ".view-sessions .tbl-scroll")
    assert any("max-height" in body for body in rules), (
        "/admin sessions table lost its .tbl-scroll cap; the card would then grow "
        "with the upstream conversation count and hit the same 16384px paint limit"
    )


def test_glass_select_menu_stays_opaque_over_a_card():
    """A dropdown menu cannot rely on its own blur to hide what is behind it.

    The menu opens inside a `.card`, and a card carrying `backdrop-filter` is
    its own backdrop root -- the menu's `backdrop-filter:blur(22px)` never
    samples the card content underneath, so at the original .82/.78 alpha the
    card's text read straight through the option list (screenshotted on the
    /admin session filter).
    """
    for label, html in (("admin", _ADMIN_HTML), ("user", _USER_HTML)):
        rules = _rules_for(html, ".glass-select-menu")
        backgrounds = [body for body in rules if "background:" in body]
        assert backgrounds, f"{label} page has no .glass-select-menu background rule"
        for body in backgrounds:
            assert _background_alpha(body) >= 0.95, (
                f"{label} page .glass-select-menu is translucent ({body[:120]}); its own "
                f"backdrop-filter cannot blur the card behind it, so option labels end up "
                f"overlapping the card text"
            )


def test_admin_session_filter_escapes_card_overflow_when_open():
    """The session filter menu must paint beyond the rounded sessions card."""
    rules = _rules_for(_ADMIN_HTML, ".view-sessions:has(.glass-select.open)")
    assert rules, "the sessions card has no open-dropdown overflow escape rule"
    assert any(re.search(r"overflow\s*:\s*visible", body) for body in rules), (
        "opening the session filter still leaves the card's overflow:hidden clip"
    )


def test_admin_session_filter_releases_shell_clip_and_raises_menu_layer():
    """The menu must also escape the page shell and sit above the card chrome."""
    shell_rules = _rules_for(_ADMIN_HTML, 'body[data-view="sessions"] .main')
    assert any(re.search(r"overflow\s*:\s*visible", body) for body in shell_rules), (
        "the sessions view's .main shell still clips the open filter menu"
    )
    card_rules = _rules_for(_ADMIN_HTML, ".view-sessions:has(.glass-select.open) .flow-box")
    assert any("overflow:visible" in body.replace(" ", "") for body in card_rules), (
        "the filter wrapper still clips the menu"
    )
    menu_rules = _rules_for(_ADMIN_HTML, ".view-sessions:has(.glass-select.open) .glass-select-menu")
    assert any(re.search(r"z-index\s*:\s*4000", body) for body in menu_rules), (
        "the session filter menu has no elevated stacking layer"
    )
