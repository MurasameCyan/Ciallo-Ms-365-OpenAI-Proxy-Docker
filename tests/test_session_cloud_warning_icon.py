from __future__ import annotations

import re

from m365_copilot_openai_proxy.templates import _ADMIN_HTML, _USER_HTML

# The per-account "cloud sessions unavailable" notes used to render as a text
# banner above the cleanup row: one line per consumer account, so a pool with
# several of them pushed the session table off the screen. They are now a single
# amber (!) icon at the right end of the cleanup row, details on hover.

_CASES = (
    ("admin", _ADMIN_HTML, "sessions-warn", "sessions-content"),
    ("user", _USER_HTML, "my-sessions-warn", "my-sessions-content"),
)


def _element(html: str, element_id: str) -> str:
    match = re.search(rf'<span id="{element_id}".*?</span>', html, re.S)
    assert match, f"#{element_id} is not a <span> icon in the rendered page"
    return match.group(0)


def test_cloud_warning_renders_as_a_hoverable_icon():
    for label, html, warn_id, content_id in _CASES:
        icon = _element(html, warn_id)
        assert "<circle" in icon and "<svg" in icon, f"{label}: #{warn_id} carries no circular icon"
        assert "#fbbf24" in icon, f"{label}: #{warn_id} icon is not amber"
        assert "cursor:help" in icon, f"{label}: #{warn_id} does not advertise its hover tooltip"
        assert 'title=""' in icon, f"{label}: #{warn_id} has no title attribute to fill on render"


def test_icon_sits_at_the_right_end_of_the_cleanup_row():
    for label, html, warn_id, content_id in _CASES:
        icon_at = html.index(f'<span id="{warn_id}"')
        button_at = html.index('data-i18n="sess_cleanup_btn"')
        content_at = html.index(f'id="{content_id}"')
        assert button_at < icon_at < content_at, (
            f"{label}: #{warn_id} left the cleanup row (expected after the cleanup "
            f"button, before the session list)"
        )
        assert "margin-left:auto" in _element(html, warn_id), (
            f"{label}: #{warn_id} is no longer pinned to the right end of the row"
        )


def test_warning_details_go_to_the_tooltip_not_the_page():
    for label, html, warn_id, _content_id in _CASES:
        render = re.search(
            rf"getElementById\('{warn_id}'\).*?\n\s*\}}", html, re.S
        )
        assert render, f"{label}: no render block found for #{warn_id}"
        block = render.group(0)
        assert "warn.title=" in block, f"{label}: warning details are not put in the tooltip"
        assert "warn.innerHTML" not in block, (
            f"{label}: warning details are still written into the page as text"
        )
