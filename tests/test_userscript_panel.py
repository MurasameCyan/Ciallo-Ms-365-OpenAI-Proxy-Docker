from __future__ import annotations

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "get_token.user.js").read_text(encoding="utf-8")


def test_userscript_version_is_bumped_for_panel_fix():
    assert "// @version      5.7" in SCRIPT



def test_userscript_matches_m365_account_variant_hosts():
    assert "// @match        https://*.microsoft365.com/*" in SCRIPT
    assert "// @match        https://microsoft365.com/*" in SCRIPT
    assert "// @match        https://*.office.com/*" in SCRIPT


def test_userscript_collects_officeapps_live_cookies_for_generated_images():
    assert "https://designerapp.officeapps.live.com/" in SCRIPT
    assert "{ domain: '.officeapps.live.com' }" in SCRIPT


def test_userscript_registers_menu_command_as_panel_fallback():
    assert "// @grant        GM_registerMenuCommand" in SCRIPT
    assert "GM_registerMenuCommand" in SCRIPT
    assert "togglePanel" in SCRIPT


def test_userscript_uses_capture_phase_keyboard_shortcut():
    assert "addEventListener('keydown', handlePanelShortcut, true)" in SCRIPT
    assert "e.stopPropagation()" in SCRIPT
    assert "e.preventDefault()" in SCRIPT



def test_userscript_panel_avoids_inline_event_handlers_blocked_by_csp():
    assert "onmouseover=" not in SCRIPT
    assert "onmouseout=" not in SCRIPT
    assert "onfocus=" not in SCRIPT
    assert "onblur=" not in SCRIPT



def test_userscript_panel_inline_handlers_keep_color_literals_quoted():
    assert "this.style.borderColor=#" not in SCRIPT
    assert "this.style.color=#" not in SCRIPT


def test_userscript_displays_cookie_push_warning_response():
    assert "cr.data.warning ? '\\n' + cr.data.warning : ''" in SCRIPT


def test_userscript_one_click_reports_token_and_cookie_status_separately():
    assert "const tokenLine = tr('token_push_status')" in SCRIPT
    assert "const cookieLine = tr('cookie_push_status')" in SCRIPT
    assert "alert(tokenLine + '\\n' + cookieLine" in SCRIPT
