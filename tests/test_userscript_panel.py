from __future__ import annotations

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "get_token.user.js").read_text(encoding="utf-8")


def test_userscript_version_is_bumped_for_panel_fix():
    assert "// @version      1.0.65" in SCRIPT
    assert "const SCRIPT_VERSION = '1.0.65';" in SCRIPT


def test_userscript_exports_media_seed_url_with_cookies():
    # media/designer auth tokens are NOT in the MSAL cache; they only appear as
    # Authorization headers when a conversation with media is opened. The
    # userscript sends the current conversation URL so the refresh flow can
    # revisit it and capture those live headers. A bare /chat must yield "".
    assert "function getCurrentChatUrl()" in SCRIPT
    assert "media_seed_url: getCurrentChatUrl()" in SCRIPT


def test_userscript_exports_msal_local_storage_with_cookies():
    # m365 is an MSAL SPA that keeps the signed-in account in localStorage, not
    # just cookies. A cookie-only injected profile boots NoAccountOnStart and
    # silent SSO degrades to an interactive popup, so the userscript must export
    # the MSAL localStorage alongside cookies for the server to seed back.
    assert "function getMsalLocalStorage()" in SCRIPT
    assert "local_storage: getMsalLocalStorage()" in SCRIPT


def test_userscript_panel_title_displays_script_version_on_the_right():
    assert "id=\"m365-script-version\"" in SCRIPT
    assert "v${SCRIPT_VERSION}" in SCRIPT



def test_userscript_matches_m365_account_variant_hosts():
    assert "// @match        https://*.microsoft365.com/*" in SCRIPT
    assert "// @match        https://microsoft365.com/*" in SCRIPT
    assert "// @match        https://*.office.com/*" in SCRIPT


def test_userscript_collects_officeapps_live_cookies_for_generated_images():
    assert "https://designerapp.officeapps.live.com/" in SCRIPT
    assert "{ domain: '.officeapps.live.com' }" in SCRIPT


def test_userscript_collects_teams_cookies_for_asyncgw_media():
    assert "https://teams.microsoft.com/" in SCRIPT
    assert "https://jp-prod.asyncgw.teams.microsoft.com/" in SCRIPT
    assert "{ domain: '.teams.microsoft.com' }" in SCRIPT
    assert "{ domain: '.asyncgw.teams.microsoft.com' }" in SCRIPT


def test_userscript_probes_media_auth_headers_without_storing_secret_values():
    assert "MEDIA_AUTH_HOST_RE" in SCRIPT
    assert "captureMediaAuthProbe" in SCRIPT
    assert "source: 'media_auth_probe'" in SCRIPT
    assert "valueSummary" in SCRIPT
    assert "x-skypetoken" in SCRIPT.lower()
    assert "authorization" in SCRIPT.lower()
    assert "rawValue" not in SCRIPT


def test_userscript_wraps_fetch_and_xhr_for_media_auth_probe():
    assert "const OrigFetch = pageWindow.fetch" in SCRIPT
    assert "const OrigXMLHttpRequest = pageWindow.XMLHttpRequest" in SCRIPT
    assert "captureMediaAuthProbe(input" in SCRIPT
    assert "captureMediaAuthProbe(probeUrl" in SCRIPT


def test_userscript_captures_media_response_details_for_asyncgw():
    # Response-level probe: records the browser's REAL asyncgw request outcome
    # (status code, method, full URL with query params, key response headers)
    # so we can reproduce the request that actually succeeds in the native page.
    assert "captureMediaResponse" in SCRIPT
    assert "source: 'media_response_probe'" in SCRIPT
    # captures the final resolved URL (may differ from the requested URL)
    assert "resp.url" in SCRIPT
    assert "xhr.responseURL" in SCRIPT
    # records HTTP status code from both fetch and xhr
    assert "resp.status" in SCRIPT
    # reads response headers without consuming the body
    assert "getAllResponseHeaders" in SCRIPT
    assert "content-range" in SCRIPT
    # must not consume/clone the response body
    assert "resp.clone" not in SCRIPT
    assert "resp.text()" not in SCRIPT


def test_userscript_captures_full_request_headers_for_media_hosts():
    # Diagnostic probe: the browser's designerapp GET returns 200 but our proxy
    # replay (same URL, same designer token) returns 400. To find the missing
    # field we record ALL request header names (with sanitized summaries) plus
    # the exact request URL, so we can diff the browser's REAL request against
    # ours. Read-only: sensitive headers are recorded as "present" only.
    assert "captureMediaRequestHeaders" in SCRIPT
    assert "source: 'media_request_probe'" in SCRIPT
    # sensitive headers must never leak their value
    assert "MEDIA_REQUEST_SENSITIVE_HEADERS" in SCRIPT
    # records the exact request URL (to confirm whether fileToken is present)
    assert "summarizeMediaRequestHeaders" in SCRIPT


def test_userscript_media_probe_covers_designerapp_officeapps_host():
    # Generated images are served by designerapp.officeapps.live.com. The
    # read-only auth/response probe must cover that host too, so we can see the
    # browser's REAL request headers (esp. Authorization) and status code for
    # designer images, the same way we did for asyncgw audio.
    assert "officeapps\\.live\\.com" in SCRIPT


def test_userscript_captures_designer_auth_raw_and_pushes_to_account():
    # designerapp sends the Authorization value WITHOUT a "Bearer " prefix (raw
    # JWE). It must be captured separately from the teams media bearer (different
    # audience) and stored verbatim, then pushed to /user/account/designer-auth.
    assert "latestDesignerAuth" in SCRIPT
    assert "'/user/account/designer-auth'" in SCRIPT
    # designer host branch keeps the raw header value as-is (no Bearer requirement).
    assert "officeapps.live.com" in SCRIPT


def test_userscript_pushes_media_auth_token_to_user_account():
    assert "latestMediaAuth" in SCRIPT
    assert "pushUserMediaAuth" in SCRIPT
    assert "'/user/account/media-auth'" in SCRIPT
    assert "authorization: latestMediaAuth.authorization" in SCRIPT
    assert "host: latestMediaAuth.host" in SCRIPT


def test_userscript_panel_exposes_media_auth_status_and_manual_push():
    assert "media_auth: '媒体鉴权'" in SCRIPT
    assert "media_auth_captured: '✓ Media Bearer 可用'" in SCRIPT
    assert "media_auth_not_captured: '⚠ 尚未捕获 Media Bearer'" in SCRIPT
    assert "push_media_auth: '推送媒体鉴权'" in SCRIPT
    assert "id=\"m365-push-media-auth\"" in SCRIPT
    assert "pushMediaAuth" in SCRIPT
    assert "document.getElementById('m365-push-media-auth').onclick = pushMediaAuth" in SCRIPT


def test_userscript_refreshes_latest_media_auth_even_for_duplicate_probe_entries():
    duplicate_check = SCRIPT.index("seenMediaAuthProbes.has(key)")
    latest_assignment = SCRIPT.index("latestMediaAuth = { host, authorization: raw }")
    assert latest_assignment < duplicate_check


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
