from __future__ import annotations

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "get_token.user.js").read_text(encoding="utf-8")


def test_userscript_version_is_bumped_for_panel_fix():
    assert "// @version      1.0.74" in SCRIPT
    assert "const SCRIPT_VERSION = '1.0.74';" in SCRIPT


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
    assert "on('m365-push-media-auth', pushMediaAuth)" in SCRIPT


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


def test_userscript_captures_consumer_chat_token_from_copilot_socket():
    # Consumer Copilot carries its ChatAI token in the chat socket URL exactly
    # like Substrate, so the SAME WebSocket hook captures both -- no second
    # script, and copilot.microsoft.com is already inside the *.microsoft.com
    # @match. The token is URL-encoded, so it must be decoded before push.
    assert "CONSUMER_WS_RE" in SCRIPT
    assert "copilot\\.microsoft\\.com" in SCRIPT
    assert "accessToken=([^&]+)" in SCRIPT
    assert "CONSUMER_IDENTITY_RE" in SCRIPT
    assert "latestConsumerToken = decodeURIComponent" in SCRIPT


def test_userscript_collects_consumer_copilot_cookie_domains():
    # The consumer jar must match consumer_gate._pick_cookies: copilot/bing/live
    # alongside the shared microsoft.com. Without these the server replays a jar
    # that Cloudflare has never seen.
    assert "https://copilot.microsoft.com/" in SCRIPT
    assert "{ domain: '.copilot.microsoft.com' }" in SCRIPT
    assert "{ domain: '.bing.com' }" in SCRIPT
    assert "{ domain: '.live.com' }" in SCRIPT


def test_userscript_pushes_consumer_snapshot_to_dedicated_endpoint():
    # Distinct endpoint from /cookies: the server must not inject or refresh a
    # consumer snapshot, so it cannot ride the M365 cookie path.
    assert "pushUserConsumer" in SCRIPT
    assert "'/user/account/consumer'" in SCRIPT
    assert "access_token: latestConsumerToken" in SCRIPT
    assert "identity_type: latestConsumerIdentity" in SCRIPT
    assert "id=\"m365-push-consumer\"" in SCRIPT
    assert "pushConsumer" in SCRIPT


def test_userscript_splits_panel_into_m365_and_consumer_sections():
    # The two Copilots need different pushes, so the panel must render them as
    # two separate blocks instead of burying the consumer button inside the
    # M365 "manual config" drawer.
    assert "function m365Section()" in SCRIPT
    assert "function consumerSection()" in SCRIPT
    assert "section_m365:" in SCRIPT
    assert "section_consumer:" in SCRIPT


def test_userscript_shows_only_the_current_products_section():
    # Credentials can only be captured on their own host, so a known product site
    # shows just that product; the other one is collapsed into a drawer.
    assert "const IS_CONSUMER_SITE = location.hostname === 'copilot.microsoft.com';" in SCRIPT
    assert "const M365_SITE_HOSTS = [" in SCRIPT
    assert "const IS_M365_SITE = M365_SITE_HOSTS.some(" in SCRIPT
    assert "function panelBody()" in SCRIPT
    assert "return consumerSection() + otherProductDrawer(m365Section() + captureSection());" in SCRIPT
    assert "return m365Section() + captureSection() + otherProductDrawer(consumerSection());" in SCRIPT


def test_userscript_shows_both_sections_on_neither_product_host():
    # Login domains belong to no product: mid-login we cannot tell which Copilot
    # the user is heading for, so hiding either one would strand them.
    assert "return m365Section() + consumerSection() + captureSection();" in SCRIPT
    for host in ("login.microsoftonline.com", "login.live.com"):
        assert f"'{host}'" not in SCRIPT.split("const M365_SITE_HOSTS = [")[1].split("]")[0]


def test_userscript_keeps_the_off_site_product_reachable_instead_of_dropping_it():
    # M365's cookie push queries absolute domains (getAllCookies), so it works
    # from any tab. Dropping the block would make a working feature unreachable.
    assert "function otherProductDrawer(" in SCRIPT
    assert "other_product:" in SCRIPT
    assert "other_product_hint:" in SCRIPT


def test_userscript_wires_every_panel_button_defensively():
    # Sections are host-dependent now, so an unguarded getElementById().onclick
    # would throw and abort the rest of the wiring -- including the close button,
    # leaving a panel the user cannot dismiss.
    assert "const on = (id, handler) => {" in SCRIPT
    assert "if (el) el.onclick = handler;" in SCRIPT
    for button in (
        "m365-copy-token",
        "m365-push-token",
        "m365-push-cookies",
        "m365-push-consumer",
        "m365-one-click",
        "m365-push-payload",
        "m365-close-panel",
    ):
        assert f"on('{button}'" in SCRIPT
        assert f"document.getElementById('{button}').onclick" not in SCRIPT


def test_userscript_badges_which_section_is_usable_here():
    # The off-site product stays in the DOM (collapsed), and on login hosts both
    # render, so each block still has to label whether this page can feed it.
    assert "function siteBadge(" in SCRIPT
    # Each badge asks "is this host the one that can capture my token", so both
    # test a positive predicate. Negating the sibling would be wrong: a login
    # page is neither product, and !IS_CONSUMER_SITE would badge it "here now"
    # for M365 even though no substrate token can ever appear there.
    assert "siteBadge(IS_M365_SITE, 'other_site_m365')" in SCRIPT
    assert "siteBadge(IS_CONSUMER_SITE, 'other_site_consumer')" in SCRIPT
    assert "siteBadge(!IS_CONSUMER_SITE" not in SCRIPT
    assert "here_now:" in SCRIPT


def test_userscript_wrong_site_push_names_the_page_to_open():
    # Pushing from the wrong host previously said "not captured yet", which
    # reads as a capture bug. Name the page to open instead.
    assert "m365_needs_site:" in SCRIPT
    assert "consumer_needs_site:" in SCRIPT
    # Keyed on "am I on the host that can capture this token", not on the other
    # product: login pages are neither, and they cannot produce either token.
    assert "alert(IS_M365_SITE ? tr('no_token_ws') : tr('m365_needs_site'))" in SCRIPT
    assert "alert(IS_CONSUMER_SITE ? tr('no_consumer_token') : tr('consumer_needs_site'))" in SCRIPT
    assert "alert(IS_CONSUMER_SITE ? tr('m365_needs_site')" not in SCRIPT


def test_userscript_consumer_button_label_writes_span_not_button_text():
    # The consumer button holds an icon plus a label span; writing
    # btn.textContent during the push would delete the icon.
    assert "id=\"m365-push-consumer-text\"" in SCRIPT
    assert "const btnText = document.getElementById('m365-push-consumer-text');" in SCRIPT


def test_userscript_treats_non_json_body_as_failure_even_on_http_200():
    # A reverse proxy fronting the container can answer 200 with an HTML login
    # page. Callers branch on .ok before reading .data, so parsing has to happen
    # before .ok is decided -- otherwise the success branch prints
    # "Token updated, remaining: undefineds" and hides the real cause.
    assert "bad_response:" in SCRIPT
    assert "let parseError = null;" in SCRIPT
    assert "ok: !parseError && resp.status >= 200 && resp.status < 300," in SCRIPT
    # the status has to reach the user, so the placeholder must be substituted
    assert ".replace('{status}', resp.status)" in SCRIPT
    # parsing must precede the resolve() that publishes .ok
    parse = SCRIPT.index("let parseError = null;")
    ok_decision = SCRIPT.index("ok: !parseError &&")
    assert parse < ok_decision


def test_userscript_labels_mode_capture_as_m365_only():
    # The WebSocket wrapper runs for both products, but the outgoing-frame tap
    # that feeds this section is installed inside the Substrate branch only --
    # the consumer socket is never tapped. Labelling it "shared" told the user
    # that capturing works on copilot.microsoft.com, which it does not.
    assert "section_capture_scope:" in SCRIPT
    assert "tr('section_capture_scope')" in SCRIPT
    assert "section_shared" not in SCRIPT
    # the tap must stay inside the Substrate branch for that label to hold
    tap = SCRIPT.index("ws.send = function(data)")
    substrate_branch = SCRIPT.index("if (match) {")
    consumer_branch = SCRIPT.index("if (consumerMatch) {")
    assert consumer_branch < substrate_branch < tap
