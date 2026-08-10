// ==UserScript==
// @name         Ciallo Ms-365 Proxy
// @namespace    https://m365.cloud.microsoft
// @version      1.0.73
// @description  提取 M365 Copilot 完整 Cookie（含 httpOnly）推送到代理服务实现登录
// @match        https://m365.cloud.microsoft/*
// @match        https://microsoft365.com/*
// @match        https://*.microsoft365.com/*
// @match        https://login.microsoftonline.com/*
// @match        https://login.live.com/*
// @match        https://microsoftonline.com/*
// @match        https://www.office.com/*
// @match        https://*.office.com/*
// @match        https://office.com/*
// @match        https://teams.microsoft.com/*
// @match        https://*.teams.microsoft.com/*
// @match        https://microsoft.com/*
// @match        https://*.microsoft.com/*
// @grant        GM_cookie
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        unsafeWindow
// @updateURL    https://gh-proxy.com/https://raw.githubusercontent.com/MurasameCyan/Ciallo-Ms-365-OpenAI-Proxy-Docker/multi/get_token.user.js
// @downloadURL  https://gh-proxy.com/https://raw.githubusercontent.com/MurasameCyan/Ciallo-Ms-365-OpenAI-Proxy-Docker/multi/get_token.user.js
// @connect      *
// ==/UserScript==

(function() {
    'use strict';

    const SCRIPT_VERSION = '1.0.73';
    const SUBSTRATE_WS_RE = /wss:\/\/substrate\.office\.com\/.*[?&]access_token=([^&]+)/;
    const M365_RT_CLIENT_ID = '4765445b-32c6-49b0-83e6-1d93765276ca';
    const M365_RT_SCOPE = 'https://substrate.office.com/sydney/.default';
    // Consumer (personal-account) Copilot puts its ChatAI token in the chat
    // socket URL exactly like Substrate does, so the same WebSocket hook below
    // captures both tokens (the outgoing-frame tap stays Substrate-only).
    // copilot.microsoft.com is already covered by the
    // https://*.microsoft.com/* @match, so no new @match is needed.
    const CONSUMER_WS_RE = /wss:\/\/copilot\.microsoft\.com\/.*[?&]accessToken=([^&]+)/;
    const CONSUMER_IDENTITY_RE = /[?&]X-UserIdentityType=([^&]+)/;
    // Which product the current tab belongs to. The two Copilots live on
    // different hosts and need different pushes, so the panel leads with the
    // section that can actually work here and tucks the other one away.
    const IS_CONSUMER_SITE = location.hostname === 'copilot.microsoft.com';
    // Hosts that belong to the M365 (work/school) Copilot. The login domains are
    // deliberately on NEITHER list: mid-login we cannot tell which product the
    // user is heading for, so the panel falls back to showing both sections.
    const M365_SITE_HOSTS = ['m365.cloud.microsoft', 'microsoft365.com', 'office.com', 'teams.microsoft.com'];
    const IS_M365_SITE = M365_SITE_HOSTS.some(
        (h) => location.hostname === h || location.hostname.endsWith('.' + h)
    );
    const PROXY_BASE = ''; // 留空则从面板输入框读取，或填入你的代理地址如 http://192.168.1.100:8000
    const USER_API_KEY = ''; // 留空则从面板输入框读取，或填入常驻的 /user API Key 如 sk-xxxx（写死后无需每次输入）

    // Domains whose cookies are needed for M365 login
    const COOKIE_DOMAINS = [
        'https://m365.cloud.microsoft',
        'https://login.microsoftonline.com',
        'https://login.live.com',
        'https://microsoftonline.com',
        'https://microsoft.com',
        'https://office.com',
        'https://www.office.com',
        'https://designerapp.officeapps.live.com/',
        'https://teams.microsoft.com/',
        'https://jp-prod.asyncgw.teams.microsoft.com/',
        // Consumer Copilot session domains. Mirrors the keep-list in
        // consumer_gate._pick_cookies so a userscript push and a browser-gate
        // export carry the same jar.
        'https://copilot.microsoft.com/',
        'https://www.bing.com/',
    ];

    // Store the latest token
    let latestToken = '';
    let latestMediaAuth = null;
    let mediaAuthPushInFlight = false;
    let latestDesignerAuth = null;
    let designerAuthPushInFlight = false;
    // OAuth2 refresh_token captured from the AAD token response. Lets the proxy
    // refresh the substrate token over plain HTTP (no headless browser).
    let latestRefreshToken = '';
    let latestRefreshTokenBinding = null;
    let refreshTokenGeneration = 0;
    let refreshTokenPushPromise = null;
    // Consumer (personal-account) Copilot ChatAI token + identity type, captured
    // from the copilot.microsoft.com chat socket URL.
    let latestConsumerToken = '';
    let latestConsumerIdentity = '';

    // Store the latest captured chat payloads (for mode-field comparison)
    // Each entry: { time, mode, raw } where raw is the parsed arguments[0] object
    let capturedPayloads = [];

    // ---- i18n (Chinese default, toggle to English, persisted in localStorage) ----
    let lang = 'zh';
    try { lang = localStorage.getItem('m365-panel-lang') || 'zh'; } catch (e) {}
    const I18N = {
        zh: {
            title: 'Ciallo Ms-365 代理',
            proxy_url: '代理地址',
            reset_proxy_url: '重置已保存代理地址',
            reset_proxy_url_done: '已清除保存的代理地址',
            user_api_key: '用户 API Key',
            reset_user_key: '重置已保存 Key',
            reset_user_key_done: '已清除保存的 Key',
            token: 'Token',
            token_captured: '✓ Token 可用',
            token_not_captured: '⚠ 尚未捕获',
            copy_token: '复制 Token',
            push_token: '推送 Token',
            cookie_login: 'Cookie 状态',
            gm_available: '✓ Cookie 可用',
            gm_unavailable: '⚠ GM_cookie 不可用，请使用 Tampermonkey Beta。',
            push_cookies: '推送 Cookie',
            media_auth: '媒体鉴权',
            media_auth_captured: '✓ Media Bearer 可用',
            media_auth_not_captured: '⚠ 尚未捕获 Media Bearer',
            push_media_auth: '推送媒体鉴权',
            media_auth_pushed: '媒体鉴权已推送',
            no_media_auth: '尚未捕获 Media Bearer。请先在 M365 页面生成/播放一次媒体。',
            consumer_captured: '✓ ChatAI Token 可用',
            consumer_not_captured: '⚠ 尚未捕获（先在 copilot.microsoft.com 发一条消息）',
            no_consumer_token: '尚未捕获个人版 ChatAI Token。请在 copilot.microsoft.com 登录并发送一条消息后重试。',
            no_consumer_identity: '无法把 ChatAI Token 对应到唯一的微软账户。请在当前个人版账户中重新发送一条消息后再推送。',
            consumer_pushed: '个人版 Copilot 已推送，Cookie 数：',
            // ---- 两个产品分区 ----
            section_m365: ' M365 商业版',
            section_consumer: ' 个人版 Copilot',
            // 抓帧钩子只装在 Substrate 分支（见 WebSocket 包装里的 if (match)），
            // 个人版 socket 不抓帧，所以这一节只对 M365 有效。
            section_capture_scope: '仅 M365',
            here_now: '当前页面',
            // 折叠抽屉的标题：当前站点用不到的那个产品收进这里，不直接展示。
            // M365 的 Cookie 推送查的是绝对域名，跨站也能用，所以只折叠、不移除。
            other_product: '其他产品',
            other_product_hint: '（当前页面用不到，展开可用跨站功能）',
            other_site_m365: '需在 m365.cloud.microsoft 操作',
            other_site_consumer: '需在 copilot.microsoft.com 操作',
            consumer_desc: '推送 Cookie + ChatAI Token 到当前账户',
            consumer_one_click: '一键推送个人版',
            m365_needs_site: '请先打开 m365.cloud.microsoft 并登录，本页无法采集 M365 凭据。',
            consumer_needs_site: '请先打开 copilot.microsoft.com 并发送一条消息，本页无法采集个人版凭据。',
            quick_setup_desc: '全量推送 Token 和 Cookie 到当前账户',
            one_click: '一键推送',
            manual_config: ' 手动配置',
            mode_capture: ' 模式抓包',
            click_expand: '（点击展开）',
            mode_capture_desc: '在 Copilot 切换模式（快速/深度、GPT 5.5/5.2）并发送一条消息。下方会显示 payload 字段，推送到代理可对比哪个字段控制模式。',
            no_capture: '暂无抓包数据。选择模式并发送一条消息。',
            push_payloads: '推送抓包数据',
            toggle_hint: 'Ctrl+Shift+M 切换面板',
            close: '关闭',
            lang_btn: 'EN',
            // alerts
            enter_proxy_first: '请先填写代理地址',
            no_token_ws: '尚未捕获 Token。在 Copilot 输入内容以触发 WebSocket。',
            no_user_key: '请先填写用户 API Key。',
            token_pushed: 'Token 已更新，剩余：',
            failed: '失败：',
            network_error: '网络错误：',
            bad_response: '代理返回了非 JSON 响应（HTTP {status}）。请检查代理地址，可能打开的是登录页或错误页。',
            gm_unavailable_alert: 'GM_cookie API 不可用。\n\n请使用 Tampermonkey Beta，或在 Tampermonkey 设置中启用「允许脚本访问 HttpOnly cookie」：\n设置 > 安全 > 「允许脚本访问 cookie」',
            fetching: '获取中...',
            pushing: '推送中...',
            no_cookies: '未找到 Cookie。',
            cookies_pushed: 'Cookie 已推送：',
            httponly_included: '（含 httpOnly：',
            error: '错误：',
            no_token_copy: '尚未捕获 Token',
            token_copied: 'Token 已复制！',
            copy_failed: '复制失败',
            working: '处理中...',
            pushing_cookies: '正在检查 Cookie...',
            pushing_token: '更新 Token...',
            setup_complete: '更新完成，Token 剩余：',
            proxy_ready: '秒',
            token_push_failed: 'Token 推送失败：',
            token_push_status: 'Token 推送：',
            cookie_push_status: 'Cookie 推送：',
            status_success: '成功',
            status_warning: '成功（警告）',
            status_failed: '失败',
            status_skipped: '未执行',
            no_payload: '暂无抓包数据。先在 Copilot 选择模式并发送一条消息。',
            pushed_n_payloads: '已推送 {n} 条 payload 到代理。',
            capture_disabled: '代理已关闭「接收抓包」。请先在 /admin 调试页面打开开关，调试完成后再关闭。',
        },
        en: {
            title: 'Ciallo Ms-365 Proxy',
            proxy_url: 'Proxy URL',
            reset_proxy_url: 'Reset Saved Proxy URL',
            reset_proxy_url_done: 'Saved proxy URL cleared',
            user_api_key: 'User API Key',
            reset_user_key: 'Reset Saved Key',
            reset_user_key_done: 'Saved key cleared',
            token: 'Token',
            token_captured: '✓ captured',
            token_not_captured: '⚠ not captured yet',
            copy_token: 'Copy Token',
            push_token: 'Push Token',
            cookie_login: 'Cookie Status',
            gm_available: '✓ GM_cookie available',
            gm_unavailable: '⚠ GM_cookie unavailable. Use Tampermonkey Beta.',
            push_cookies: 'Push Cookies',
            media_auth: 'Media Auth',
            media_auth_captured: '✓ Media Bearer captured',
            media_auth_not_captured: '⚠ Media Bearer not captured',
            push_media_auth: 'Push Media Auth',
            media_auth_pushed: 'Media auth pushed',
            no_media_auth: 'No Media Bearer captured yet. Generate or play media in M365 first.',
            consumer_captured: '✓ ChatAI token captured',
            consumer_not_captured: '⚠ not captured (send a message on copilot.microsoft.com first)',
            no_consumer_token: 'No personal ChatAI token captured yet. Sign in at copilot.microsoft.com, send one message, then retry.',
            no_consumer_identity: 'The ChatAI token could not be matched to one Microsoft account. Send a new message from the current personal account, then push again.',
            consumer_pushed: 'Personal Copilot pushed, cookies: ',
            // ---- the two product sections ----
            section_m365: 'M365 Business',
            section_consumer: 'Personal Copilot',
            // The frame hook lives in the Substrate branch only (see if (match)
            // in the WebSocket wrapper); the consumer socket is not tapped.
            section_capture_scope: 'M365 only',
            here_now: 'this page',
            // Drawer title for the product this host cannot feed. M365 cookie
            // push queries absolute domains and works cross-site, so the block is
            // collapsed rather than removed.
            other_product: 'Other product',
            other_product_hint: '(not usable on this page; expand for cross-site actions)',
            other_site_m365: 'open m365.cloud.microsoft to use',
            other_site_consumer: 'open copilot.microsoft.com to use',
            consumer_desc: 'Push cookies + ChatAI token to the current account.',
            consumer_one_click: 'Push Personal',
            m365_needs_site: 'Open m365.cloud.microsoft and sign in first; M365 credentials cannot be collected from this page.',
            consumer_needs_site: 'Open copilot.microsoft.com and send one message first; personal credentials cannot be collected from this page.',
            quick_setup_desc: 'Push Token and Cookies to the current account.',
            one_click: 'Push',
            manual_config: 'Manual Config',
            mode_capture: 'Mode Capture',
            click_expand: '(click to expand)',
            mode_capture_desc: 'Pick a mode (Fast/Think, GPT 5.5/5.2) in Copilot and send a message. The payload fields appear below; push them to the proxy to compare which field controls the mode.',
            no_capture: 'No chat payload captured yet. Pick a mode and send a message.',
            push_payloads: 'Push Captured Payloads',
            toggle_hint: 'Ctrl+Shift+M to toggle',
            close: 'Close',
            lang_btn: '中文',
            // alerts
            enter_proxy_first: 'Please enter proxy URL first',
            no_token_ws: 'No token captured yet. Type something in Copilot to trigger WebSocket.',
            no_user_key: 'Please enter User API Key first.',
            token_pushed: 'Token updated. Remaining: ',
            failed: 'Failed: ',
            network_error: 'Network error: ',
            bad_response: 'Proxy returned a non-JSON response (HTTP {status}). Check the proxy URL, it may be a login/error page.',
            gm_unavailable_alert: 'GM_cookie API not available.\n\nPlease use Tampermonkey Beta or enable "Allow scripts to access HttpOnly cookies" in Tampermonkey settings:\nSettings > Security > "Allow scripts to access cookies"',
            fetching: 'Fetching...',
            pushing: 'Pushing...',
            no_cookies: 'No cookies found.',
            cookies_pushed: 'Cookies pushed: ',
            httponly_included: '(httpOnly included: ',
            error: 'Error: ',
            no_token_copy: 'No token captured yet',
            token_copied: 'Token copied!',
            copy_failed: 'Copy failed',
            working: 'Working...',
            pushing_cookies: 'Checking cookies...',
            pushing_token: 'Updating token...',
            setup_complete: 'Updated successfully. Token remaining: ',
            proxy_ready: 's',
            token_push_failed: 'Token push failed: ',
            token_push_status: 'Token push: ',
            cookie_push_status: 'Cookie push: ',
            status_success: 'success',
            status_warning: 'success with warning',
            status_failed: 'failed',
            status_skipped: 'skipped',
            no_payload: 'No chat payload captured yet. Pick a mode in Copilot and send a message first.',
            pushed_n_payloads: 'Pushed {n} payload(s) to proxy.',
            capture_disabled: 'The proxy has "Receive captures" turned off. Enable the switch on the /admin debug page first, and turn it off after debugging.',
        },
    };
    function tr(key) { return (I18N[lang] && I18N[lang][key]) || (I18N.en[key]) || key; }

    // Colored inline-SVG icons (fixed 18px box so titles align regardless of glyph width)
    function ic(name) {
        const svgs = {
            // lightning bolt — Quick Setup (amber)
            bolt: '<svg viewBox="0 0 24 24" width="15" height="15" fill="#f59e0b"><path d="M13 2L3 14h7l-1 8 10-12h-7l1-8z"/></svg>',
            // gear — Manual Config (slate blue)
            gear: '<svg viewBox="0 0 24 24" width="15" height="15" fill="#60f2ff"><path d="M12 8a4 4 0 100 8 4 4 0 000-8zm9 4a7 7 0 00-.1-1.2l2-1.6-2-3.5-2.4 1a7 7 0 00-2-1.2l-.4-2.5H9.9l-.4 2.5a7 7 0 00-2 1.2l-2.4-1-2 3.5 2 1.6A7 7 0 003 12c0 .4 0 .8.1 1.2l-2 1.6 2 3.5 2.4-1a7 7 0 002 1.2l.4 2.5h4.2l.4-2.5a7 7 0 002-1.2l2.4 1 2-3.5-2-1.6c.1-.4.1-.8.1-1.2z"/></svg>',
            // crosshair/aperture — Mode Capture (green)
            scope: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="#22c55e" stroke-width="2"><circle cx="12" cy="12" r="8"/><line x1="12" y1="1" x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="1" y1="12" x2="5" y2="12"/><line x1="19" y1="12" x2="23" y2="12"/><circle cx="12" cy="12" r="2" fill="#22c55e" stroke="none"/></svg>',
            // sparkle/rocket — panel title (sky)
            spark: '<svg viewBox="0 0 24 24" width="17" height="17" fill="#60f2ff"><path d="M12 2l1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8L12 2z"/></svg>',
            // rocket — One-Click Push (colorful: cyan body, purple fins, orange flame)
            rocket: '<svg viewBox="0 0 24 24" width="15" height="15"><path d="M14.5 2c2 0 4 0 5.5 1.5S21.5 8 21.5 10c-1.2 2.6-3 4.7-5 6.3l.2 3.2-3.5-1.8-3.1 1.6-1.6-3.1L4.7 12.5C6.3 10.5 8.4 8.7 11 7.5c1.4-2 3-3.5 3.5-3.5z" fill="#60f2ff"/><path d="M11 7.5C8.4 8.7 6.3 10.5 4.7 12.5l3.8 1.6 3.1-1.6c1-2.2 2.3-4.2 3.9-6.1-2.6.4-4.5 1.1-4.5 1.1z" fill="#8c6bff"/><circle cx="15" cy="6" r="2" fill="#050815"/><path d="M9 16l1.6 3.1 3.1-1.6-.3 4.1s-2.4-.2-4.1-1.9c-1.2-1.2-.6-3.6-.6-3.6z" fill="#ff8c42"/><path d="M9 16l1.6 3.1 3.1-1.6-.5 2.4-3.7-1.8z" fill="#ffd76f"/></svg>',
            // fox head — Personal Copilot (the consumer path runs on Firefox/Camoufox)
            fox: '<svg viewBox="0 0 24 24" width="15" height="15"><path d="M3 3l3.5 2.5L12 4l5.5 1.5L21 3l-1 6c0 5-3.5 9-8 9s-8-4-8-9L3 3z" fill="#f97316"/><path d="M12 4L6.5 5.5 3 3l1 6c0 2.2.7 4.2 1.9 5.8C5.3 12.6 5 10.4 5 8l6-2.5 1-1.5z" fill="#fb923c"/><circle cx="9" cy="10" r="1.2" fill="#050815"/><circle cx="15" cy="10" r="1.2" fill="#050815"/><path d="M12 13l-1.8 1.4c.5.5 1.1.8 1.8.8s1.3-.3 1.8-.8L12 13z" fill="#050815"/></svg>',
        };
        return '<span style="display:inline-flex; width:18px; height:18px; align-items:center; justify-content:center; vertical-align:middle;">' + (svgs[name] || '') + '</span>';
    }

    function toggleLang() {
        lang = (lang === 'zh') ? 'en' : 'zh';
        try { localStorage.setItem('m365-panel-lang', lang); } catch (e) {}
        showPanel();
    }

    // Extract current username from page
    function getUsername() {
        try {
            // M365 Copilot stores user info in sessionStorage (most reliable)
            const s = sessionStorage.getItem('ms-m365-shell-session-data');
            if (s) {
                const d = JSON.parse(s);
                if (d && d.userDisplayName) return d.userDisplayName;
                if (d && d.upn) return d.upn.split('@')[0];
            }
        } catch {}
        try {
            // Try aria-label on avatar/persona buttons (e.g. aria-label="Account Manager for John Doe")
            const avatarEls = document.querySelectorAll('[data-testid="header-person-menu"], [data-testid="persona"], button[aria-label*="Account"], button[aria-label*="Manager"], [role="button"][aria-label*="for "], [role="button"][title*="for "], [role="button"][aria-label*="概要"]');
            for (const el of avatarEls) {
                const a = el.getAttribute('aria-label') || el.getAttribute('title') || '';
                // Pattern: "Account Manager for John Doe" or "John Doe 的帐户"
                const m = a.match(/(?:for\s+|的[帐账]户(?:管理器)?[：:]?\s*)(.+)/i) || a.match(/^(.+?)(?:\s*\(|\s*-|\s*的)/);
                if (m && m[1] && m[1].trim().length > 1 && m[1].trim().length < 80) return m[1].trim();
                // If aria-label is just the name itself (not a common UI keyword)
                if (a && a.length > 1 && a.length < 80 && !/^(home|copilot|apps|chat|create|menu|back|close)$/i.test(a)) return a.trim();
            }
        } catch {}
        try {
            // Try persona button or header elements
            const els = document.querySelectorAll('[data-testid="header-person-menu"], [data-testid="persona"], [aria-label*="Account"], [aria-label*="Profiles"]');
            for (const el of els) {
                const t = el.textContent.trim();
                if (t && t.length > 1 && t.length < 80) return t;
            }
        } catch {}
        try {
            // Fluent UI text span — but only accept multi-char text (skip single-letter avatar initials)
            const fus = document.querySelectorAll('span.fui-Text, span[class*="fai-bebop"]');
            for (const el of fus) {
                const t = el.textContent.trim();
                // Skip single characters (avatar initials like "G") and common UI labels
                if (t && t.length > 1 && t.length < 80 && !/^(home|copilot|apps|chat|create)$/i.test(t)) return t;
            }
        } catch {}
        return '';
    }

    // ---- Consumer account email resolution --------------------------------
    // Personal Copilot can render arbitrary email addresses inside chat, so the
    // account identity must come from structured MSAL state, never page text.
    const CONSUMER_EMAIL_RE = /^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/i;
    const CONSUMER_EMAIL_SCAN_RE = /[a-z0-9.!#$%&'*+/?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+/gi;
    let cachedConsumerEmail = { accountId: '', email: '', name: '' };

    function normalizeConsumerEmail(value) {
        if (typeof value !== 'string') return '';
        const email = value.trim().toLowerCase();
        return email.length <= 320 && CONSUMER_EMAIL_RE.test(email) ? email : '';
    }

    function normalizeConsumerName(value) {
        if (typeof value !== 'string') return '';
        const name = value.replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim();
        return name.length > 0 && name.length <= 120 ? name : '';
    }

    function parseConsumerStorageJson(raw) {
        let value = raw;
        for (let i = 0; i < 2 && typeof value === 'string'; i++) {
            try { value = JSON.parse(value); }
            catch (e) { return null; }
        }
        return value;
    }

    function getConsumerStorageEntries() {
        const entries = [];
        try {
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (typeof key === 'string') entries.push([key, localStorage.getItem(key)]);
            }
        } catch (e) {}
        return entries;
    }

    function consumerRecordValue(record, names) {
        for (const name of names) {
            const value = record && record[name];
            if (typeof value === 'string' && value.trim()) return value.trim();
        }
        return '';
    }

    function consumerAccountId(record, storageKey) {
        const homeId = consumerRecordValue(record, ['homeAccountId', 'home_account_id']);
        if (homeId) return 'home:' + homeId.toLowerCase();
        const localId = consumerRecordValue(record, ['localAccountId', 'local_account_id']);
        if (localId) return 'local:' + localId.toLowerCase();
        return storageKey ? 'key:' + storageKey.toLowerCase() : '';
    }

    function getStructuredConsumerAccounts(entries) {
        const values = new Map(entries);
        const accountKeys = new Set();
        for (const [key, raw] of entries) {
            if (!key.toLowerCase().includes('account.keys')) continue;
            const parsed = parseConsumerStorageJson(raw);
            if (!Array.isArray(parsed)) continue;
            for (const accountKey of parsed) {
                if (typeof accountKey === 'string' && accountKey) accountKeys.add(accountKey);
            }
        }
        const byId = new Map();
        for (const accountKey of accountKeys) {
            const record = parseConsumerStorageJson(values.get(accountKey));
            if (!record || typeof record !== 'object' || Array.isArray(record)) continue;
            const id = consumerAccountId(record, accountKey);
            if (!id) continue;
            const email = normalizeConsumerEmail(consumerRecordValue(record, [
                'username', 'email', 'mail', 'upn', 'preferred_username', 'loginHint', 'login_hint',
            ]));
            const name = normalizeConsumerName(consumerRecordValue(record, [
                'name', 'displayName', 'display_name',
            ]));
            const previous = byId.get(id);
            if (!previous) {
                byId.set(id, { id, email, name, record });
            } else if ((!previous.email && email) || (!previous.name && name)) {
                byId.set(id, {
                    id,
                    email: previous.email || email,
                    name: previous.name || name,
                    record: previous.record,
                });
            }
        }
        return Array.from(byId.values());
    }

    function getConsumerTokenAccountId(entries, accessToken) {
        if (!accessToken) return '';
        const matches = new Set();
        for (const [, raw] of entries) {
            const record = parseConsumerStorageJson(raw);
            if (!record || typeof record !== 'object' || Array.isArray(record)) continue;
            const credentialType = consumerRecordValue(record, ['credentialType', 'credential_type']);
            const target = consumerRecordValue(record, ['target', 'scope', 'scopes']);
            const secret = consumerRecordValue(record, ['secret', 'accessToken', 'access_token']);
            if (credentialType.toLowerCase() !== 'accesstoken') continue;
            if (!/chatai/i.test(target) || secret !== accessToken) continue;
            const id = consumerAccountId(record, '');
            if (/^(home|local):/.test(id)) matches.add(id);
        }
        return matches.size === 1 ? Array.from(matches)[0] : '';
    }

    function getActiveConsumerFilters(entries) {
        const filters = [];
        const addFilter = (value) => {
            if (!value || typeof value !== 'object' || Array.isArray(value)) return;
            const homeId = consumerRecordValue(value, ['homeAccountId', 'home_account_id']);
            const localId = consumerRecordValue(value, ['localAccountId', 'local_account_id']);
            if (homeId || localId) filters.push(value);
        };
        for (const [key, raw] of entries) {
            if (!key.toLowerCase().includes('active-account-filters')) continue;
            const parsed = parseConsumerStorageJson(raw);
            if (Array.isArray(parsed)) {
                for (const item of parsed) addFilter(item);
            } else {
                addFilter(parsed);
                if (parsed && typeof parsed === 'object') {
                    for (const item of Object.values(parsed)) addFilter(item);
                }
            }
        }
        return filters;
    }

    function consumerFilterId(filter) {
        const homeId = consumerRecordValue(filter, ['homeAccountId', 'home_account_id']);
        if (homeId) return 'home:' + homeId.toLowerCase();
        const localId = consumerRecordValue(filter, ['localAccountId', 'local_account_id']);
        return localId ? 'local:' + localId.toLowerCase() : '';
    }

    function consumerFilterMatchesAccount(filter, account) {
        const fields = [
            ['homeAccountId', 'home_account_id'],
            ['localAccountId', 'local_account_id'],
            ['tenantId', 'tenant_id'],
            ['environment'],
        ];
        let compared = false;
        for (const names of fields) {
            const expected = consumerRecordValue(filter, names);
            if (!expected) continue;
            compared = true;
            const actual = consumerRecordValue(account.record, names);
            if (!actual || actual.toLowerCase() !== expected.toLowerCase()) return false;
        }
        return compared;
    }

    function getIdentityCookieEmail(cookies) {
        const emails = new Set();
        for (const cookie of (Array.isArray(cookies) ? cookies : [])) {
            const name = String(cookie && cookie.name || '').toLowerCase();
            if (name !== 'msppre' && name !== 'jshp') continue;
            let text = String(cookie && cookie.value || '');
            for (let attempt = 0; attempt < 3; attempt++) {
                const matches = text.match(CONSUMER_EMAIL_SCAN_RE) || [];
                for (const match of matches) {
                    const email = normalizeConsumerEmail(match);
                    if (email) emails.add(email);
                }
                try {
                    const decoded = decodeURIComponent(text.replace(/\+/g, '%20'));
                    if (decoded === text) break;
                    text = decoded;
                } catch (e) { break; }
            }
        }
        return emails.size === 1 ? Array.from(emails)[0] : '';
    }

    function getConsumerAccountEmail(cookies, accessToken = '') {
        const entries = getConsumerStorageEntries();
        const accounts = getStructuredConsumerAccounts(entries);
        const tokenAccountId = getConsumerTokenAccountId(entries, accessToken);
        if (accessToken && !tokenAccountId) {
            cachedConsumerEmail = { accountId: '', email: '', name: '' };
            return '';
        }
        const filters = getActiveConsumerFilters(entries);
        const activeFilterIds = new Set(filters.map(consumerFilterId).filter(Boolean));
        if (accessToken && activeFilterIds.size && (
            activeFilterIds.size !== 1 || !activeFilterIds.has(tokenAccountId)
        )) {
            cachedConsumerEmail = { accountId: '', email: '', name: '' };
            return '';
        }
        const matched = new Map();
        for (const filter of filters) {
            for (const account of accounts) {
                if (consumerFilterMatchesAccount(filter, account)) matched.set(account.id, account);
            }
        }

        let selected = tokenAccountId
            ? (accounts.find((account) => account.id === tokenAccountId) || null)
            : (matched.size === 1 ? Array.from(matched.values())[0] : null);
        if (!accessToken && !selected && matched.size === 0 && accounts.length === 1) selected = accounts[0];

        let activeAccountId = tokenAccountId || (selected ? selected.id : '');
        if (!accessToken && !activeAccountId) {
            const filterIds = new Set(filters.map(consumerFilterId).filter(Boolean));
            if (filterIds.size === 1) activeAccountId = Array.from(filterIds)[0];
        }
        if (cachedConsumerEmail.accountId !== activeAccountId) {
            cachedConsumerEmail = { accountId: activeAccountId, email: '', name: '' };
        }
        if (selected && selected.name) cachedConsumerEmail.name = selected.name;
        if (selected && selected.email) {
            cachedConsumerEmail.email = selected.email;
            return selected.email;
        }
        if (activeAccountId && cachedConsumerEmail.email) return cachedConsumerEmail.email;

        const cookieEmail = getIdentityCookieEmail(cookies);
        if (cookieEmail && activeAccountId) {
            cachedConsumerEmail.email = cookieEmail;
        }
        return cookieEmail;
    }

    function getConsumerAccountId() {
        const accountId = String(cachedConsumerEmail.accountId || '').toLowerCase();
        return /^(home|local):[a-z0-9._-]+$/.test(accountId) ? accountId : '';
    }

    function getConsumerAccountName() {
        return normalizeConsumerName(cachedConsumerEmail.name);
    }
    // ---- End consumer account email resolution -----------------------------

    // ---- M365 refresh-token capture helpers -------------------------------
    function m365RefreshAuthority(requestUrl) {
        try {
            const url = new URL(String(requestUrl || ''), location.href);
            if (url.hostname !== 'login.microsoftonline.com') return '';
            const match = url.pathname.match(/^\/([^/]+)\/oauth2\/v2\.0\/token\/?$/i);
            if (!match) return '';
            const authority = match[1].toLowerCase();
            if (authority === 'consumers' || !/^[a-z0-9](?:[a-z0-9.-]{0,126}[a-z0-9])?$/i.test(authority)) return '';
            return authority;
        } catch (e) {
            return '';
        }
    }

    function m365RequestBodyText(body) {
        try {
            if (typeof body === 'string') return body;
            if (!body) return '';
            if (Object.prototype.toString.call(body) === '[object URLSearchParams]') return body.toString();
            if (typeof ArrayBuffer !== 'undefined' && (body instanceof ArrayBuffer || ArrayBuffer.isView(body))) {
                return new TextDecoder().decode(body);
            }
        } catch (e) {}
        return '';
    }

    async function m365FetchRequestBodyText(input, init) {
        const direct = m365RequestBodyText(init && init.body);
        if (direct) return direct;
        try {
            if (input && typeof input.clone === 'function') return await input.clone().text();
        } catch (e) {}
        return '';
    }

    function decodeM365JwtClaims(token) {
        try {
            const parts = String(token || '').split('.');
            if (parts.length < 2 || !parts[1]) return null;
            const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/');
            return JSON.parse(atob(payload + '='.repeat((4 - payload.length % 4) % 4)));
        } catch (e) {
            return null;
        }
    }

    function captureM365RefreshToken(requestUrl, requestBody, responseData) {
        const authority = m365RefreshAuthority(requestUrl);
        if (!authority || !responseData || typeof responseData !== 'object') return false;
        let params;
        try { params = new URLSearchParams(String(requestBody || '')); }
        catch (e) { return false; }
        const clientId = String(params.get('client_id') || '').toLowerCase();
        const scopes = String(params.get('scope') || '').split(/\s+/).filter(Boolean);
        if (clientId !== M365_RT_CLIENT_ID || !scopes.includes(M365_RT_SCOPE)) return false;
        const refreshToken = typeof responseData.refresh_token === 'string' ? responseData.refresh_token.trim() : '';
        const claims = decodeM365JwtClaims(responseData.access_token);
        if (!refreshToken || !claims) return false;
        if (!String(claims.aud || '').startsWith('https://substrate.office.com/')) return false;
        const issuedClient = String(claims.azp || claims.appid || '').toLowerCase();
        if (issuedClient && issuedClient !== M365_RT_CLIENT_ID) return false;
        const tenantId = String(claims.tid || '').toLowerCase();
        const objectId = String(claims.oid || '').toLowerCase();
        const guid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
        if (!guid.test(tenantId) || !guid.test(objectId)) return false;
        latestToken = String(responseData.access_token || '').trim();
        latestRefreshToken = refreshToken;
        latestRefreshTokenBinding = {
            client_id: M365_RT_CLIENT_ID,
            authority,
            tenant_id: tenantId,
            object_id: objectId,
        };
        refreshTokenGeneration++;
        pushLatestRefreshTokenSilently();
        return true;
    }
    // ---- End M365 refresh-token capture helpers ---------------------------

    // Intercept browser APIs on the real page (not in sandbox)
    const pageWindow = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;
    const MEDIA_AUTH_HOST_RE = /(^|\.)(asyncgw\.teams\.microsoft\.com|teams\.microsoft\.com|officeapps\.live\.com)$/i;
    const MEDIA_AUTH_HEADER_NAMES = ['authorization', 'x-skypetoken', 'skypetoken'];
    const seenMediaAuthProbes = new Set();

    function mediaAuthHostFromUrl(urlLike) {
        try {
            let url = urlLike;
            if (urlLike && typeof urlLike === 'object' && typeof urlLike.url === 'string') url = urlLike.url;
            const parsed = new URL(String(url), location.href);
            return MEDIA_AUTH_HOST_RE.test(parsed.hostname) ? parsed.hostname : '';
        } catch (e) {
            return '';
        }
    }

    function mediaAuthValueSummary(name, value) {
        const text = String(value || '').trim();
        if (!text) return '';
        if (name === 'authorization') {
            const scheme = (text.split(/\s+/, 1)[0] || 'present').toLowerCase();
            return scheme + ' token present';
        }
        return 'present';
    }

    function addMediaAuthProbe(host, headerName, valueSummary, source, headerValue) {
        const key = host + '|' + headerName + '|' + valueSummary + '|' + source;
        if (!host || !headerName || !valueSummary) return;
        if (headerName === 'authorization') {
            const raw = String(headerValue || '').trim();
            if (/officeapps\.live\.com$/i.test(host)) {
                // designerapp sends a raw JWE token WITHOUT a "Bearer " prefix; keep it
                // verbatim so it can be replayed exactly as the browser sends it.
                if (raw) {
                    latestDesignerAuth = { host, authorization: raw };
                    pushLatestDesignerAuthSilently();
                }
            } else if (/^Bearer\s+\S+/i.test(raw)) {
                latestMediaAuth = { host, authorization: raw };
                pushLatestMediaAuthSilently();
            }
        }
        if (seenMediaAuthProbes.has(key)) return;
        seenMediaAuthProbes.add(key);
        capturedPayloads.unshift({
            time: new Date().toLocaleTimeString(),
            source: 'media_auth_probe',
            frameType: 'media-auth',
            target: host,
            tone: source,
            modelId: headerName,
            rawText: JSON.stringify({ source: 'media_auth_probe', host, headerName, valueSummary, via: source }),
        });
        if (capturedPayloads.length > 20) capturedPayloads.pop();
        renderCaptured();
    }

    function captureMediaAuthProbe(urlLike, headersLike, source) {
        const host = mediaAuthHostFromUrl(urlLike);
        if (!host || !headersLike) return;
        const add = (name, value) => {
            const headerName = String(name || '').toLowerCase();
            if (!MEDIA_AUTH_HEADER_NAMES.includes(headerName)) return;
            const valueSummary = mediaAuthValueSummary(headerName, value);
            addMediaAuthProbe(host, headerName, valueSummary, source, value);
        };
        try {
            if (typeof headersLike.forEach === 'function') {
                headersLike.forEach((value, name) => add(name, value));
                return;
            }
        } catch (e) {}
        if (Array.isArray(headersLike)) {
            headersLike.forEach((entry) => {
                if (Array.isArray(entry) && entry.length >= 2) add(entry[0], entry[1]);
            });
            return;
        }
        if (typeof headersLike === 'object') {
            Object.keys(headersLike).forEach((name) => add(name, headersLike[name]));
        }
    }

    // Request-header diagnostic probe: the browser's designerapp GET returns 200
    // but our proxy replay (same URL + same designer token) returns 400. To find
    // the missing field we record ALL request header NAMES (with sanitized value
    // summaries) plus the exact request URL, so we can diff the browser's REAL
    // request against ours. Read-only: sensitive headers are recorded as
    // "present" only (never their value); other headers keep a short truncated
    // value that helps compare (e.g. sec-fetch-mode, accept, origin, referer).
    const MEDIA_REQUEST_SENSITIVE_HEADERS = ['authorization', 'cookie', 'x-skypetoken', 'skypetoken', 'x-anchormailbox', 'x-routing-id'];
    const seenMediaRequestProbes = new Set();

    function summarizeMediaRequestHeaders(headersLike) {
        const out = {};
        if (!headersLike) return out;
        const take = (name, value) => {
            const n = String(name || '').toLowerCase();
            if (!n) return;
            if (MEDIA_REQUEST_SENSITIVE_HEADERS.includes(n)) {
                out[n] = value ? 'present' : '';
                return;
            }
            const v = String(value || '');
            out[n] = v.length > 80 ? v.slice(0, 80) + '…' : v;
        };
        try {
            if (typeof headersLike.forEach === 'function') {
                headersLike.forEach((value, name) => take(name, value));
                return out;
            }
            if (Array.isArray(headersLike)) {
                headersLike.forEach((entry) => {
                    if (Array.isArray(entry) && entry.length >= 2) take(entry[0], entry[1]);
                });
                return out;
            }
            if (typeof headersLike === 'object') {
                Object.keys(headersLike).forEach((name) => take(name, headersLike[name]));
            }
        } catch (e) {}
        return out;
    }

    function captureMediaRequestHeaders(method, url, headersLike, via) {
        const host = mediaAuthHostFromUrl(url);
        if (!host) return;
        const headerSummary = summarizeMediaRequestHeaders(headersLike);
        const headerNames = Object.keys(headerSummary).sort();
        if (!headerNames.length) return;
        const fullUrl = String(url || '');
        const key = via + '|' + (method || '') + '|' + fullUrl + '|' + headerNames.join(',');
        if (seenMediaRequestProbes.has(key)) return;
        seenMediaRequestProbes.add(key);
        capturedPayloads.unshift({
            time: new Date().toLocaleTimeString(),
            source: 'media_request_probe',
            frameType: 'media-request',
            target: host,
            tone: via,
            modelId: (method || 'GET') + ' ' + headerNames.length + ' headers',
            rawText: JSON.stringify({ source: 'media_request_probe', via, method: method || 'GET', url: fullUrl, headerNames, headers: headerSummary }),
        });
        if (capturedPayloads.length > 20) capturedPayloads.pop();
        renderCaptured();
    }

    // Response-level probe: records the browser's REAL asyncgw request outcome
    // (status code, method, full URL with query params, key response headers).
    // Read-only: never consumes/clones the body and never logs token values.
    const MEDIA_RESPONSE_HEADER_NAMES = ['content-type', 'content-length', 'content-range', 'accept-ranges', 'location', 'etag', 'www-authenticate'];
    const seenMediaResponseProbes = new Set();

    function summarizeMediaResponseHeaders(headersLike) {
        const out = {};
        if (!headersLike) return out;
        const take = (name, value) => {
            const n = String(name || '').toLowerCase();
            if (MEDIA_RESPONSE_HEADER_NAMES.includes(n)) out[n] = String(value || '');
        };
        try {
            if (typeof headersLike === 'string') {
                headersLike.split(/\r?\n/).forEach((line) => {
                    const idx = line.indexOf(':');
                    if (idx > 0) take(line.slice(0, idx), line.slice(idx + 1).trim());
                });
                return out;
            }
            if (typeof headersLike.forEach === 'function') {
                headersLike.forEach((value, name) => take(name, value));
                return out;
            }
            if (typeof headersLike === 'object') {
                Object.keys(headersLike).forEach((name) => take(name, headersLike[name]));
            }
        } catch (e) {}
        return out;
    }

    function captureMediaResponse(method, url, status, headersLike, via) {
        const host = mediaAuthHostFromUrl(url);
        if (!host) return;
        const fullUrl = String(url || '');
        const key = via + '|' + (method || '') + '|' + fullUrl + '|' + status;
        if (seenMediaResponseProbes.has(key)) return;
        seenMediaResponseProbes.add(key);
        const headerSummary = summarizeMediaResponseHeaders(headersLike);
        capturedPayloads.unshift({
            time: new Date().toLocaleTimeString(),
            source: 'media_response_probe',
            frameType: 'media-response',
            target: host,
            tone: via,
            modelId: (method || 'GET') + ' ' + status,
            rawText: JSON.stringify({ source: 'media_response_probe', via, method: method || 'GET', status, url: fullUrl, headers: headerSummary }),
        });
        if (capturedPayloads.length > 20) capturedPayloads.pop();
        renderCaptured();
    }

    const OrigFetch = pageWindow.fetch;
    if (typeof OrigFetch === 'function') {
        pageWindow.fetch = function(input, init) {
            let reqUrl = '';
            let reqMethod = 'GET';
            let rtRequestBodyPromise = null;
            try {
                captureMediaAuthProbe(input, init && init.headers, 'fetch-init');
                if (input && typeof input === 'object' && input.headers) captureMediaAuthProbe(input, input.headers, 'fetch-request');
                reqUrl = (input && typeof input === 'object' && typeof input.url === 'string') ? input.url : String(input || '');
                reqMethod = (init && init.method) || (input && typeof input === 'object' && input.method) || 'GET';
                if (m365RefreshAuthority(reqUrl)) rtRequestBodyPromise = m365FetchRequestBodyText(input, init);
                if (mediaAuthHostFromUrl(reqUrl)) {
                    const reqHeaders = (init && init.headers) || (input && typeof input === 'object' && input.headers) || null;
                    captureMediaRequestHeaders(reqMethod, reqUrl, reqHeaders, 'fetch-request');
                }
            } catch (e) {}
            const p = OrigFetch.apply(this, arguments);
            try {
                if (p && typeof p.then === 'function' && mediaAuthHostFromUrl(reqUrl)) {
                    p.then((resp) => {
                        try {
                            if (resp) captureMediaResponse(reqMethod, resp.url || reqUrl, resp.status, resp.headers, 'fetch-response');
                        } catch (e) {}
                    }, () => {});
                }
                if (p && typeof p.then === 'function' && rtRequestBodyPromise) {
                    p.then((tokenResp) => {
                        try {
                            if (!tokenResp || !tokenResp.clone) return;
                            Promise.all([rtRequestBodyPromise, tokenResp.clone().json()]).then(
                                ([body, data]) => { captureM365RefreshToken(reqUrl, body, data); },
                                () => {}
                            );
                        } catch (e) {}
                    }, () => {});
                }
            } catch (e) {}
            return p;
        };
    }

    const OrigXMLHttpRequest = pageWindow.XMLHttpRequest;
    if (typeof OrigXMLHttpRequest === 'function') {
        pageWindow.XMLHttpRequest = function() {
            const xhr = new OrigXMLHttpRequest();
            let probeUrl = '';
            const probeHeaders = {};
            let probeMethod = 'GET';
            let rtRequestBody = '';
            const origOpen = xhr.open;
            const origSetRequestHeader = xhr.setRequestHeader;
            const origSend = xhr.send;
            xhr.open = function(method, url) {
                probeUrl = url;
                probeMethod = method || 'GET';
                return origOpen.apply(xhr, arguments);
            };
            xhr.setRequestHeader = function(name, value) {
                probeHeaders[name] = value;
                captureMediaAuthProbe(probeUrl, probeHeaders, 'xhr');
                return origSetRequestHeader.apply(xhr, arguments);
            };
            xhr.send = function(body) {
                rtRequestBody = m365RequestBodyText(body);
                return origSend.apply(xhr, arguments);
            };
            xhr.addEventListener('load', function() {
                try {
                    const finalUrl = xhr.responseURL || probeUrl;
                    if (mediaAuthHostFromUrl(finalUrl)) {
                        captureMediaRequestHeaders(probeMethod, probeUrl, probeHeaders, 'xhr-request');
                        captureMediaResponse(probeMethod, finalUrl, xhr.status, xhr.getAllResponseHeaders(), 'xhr-response');
                    }
                    if (m365RefreshAuthority(finalUrl)) {
                        let data = xhr.responseType === 'json' ? xhr.response : null;
                        if (!data) data = JSON.parse(xhr.responseText || xhr.response || '{}');
                        captureM365RefreshToken(finalUrl, rtRequestBody, data);
                    }
                } catch (e) {}
            });
            return xhr;
        };
        pageWindow.XMLHttpRequest.prototype = OrigXMLHttpRequest.prototype;
    }

    const OrigWebSocket = pageWindow.WebSocket;
    pageWindow.WebSocket = function(url, protocols) {
        const match = url.match(SUBSTRATE_WS_RE);
        const consumerMatch = url.match(CONSUMER_WS_RE);
        const ws = new OrigWebSocket(url, protocols);
        if (consumerMatch) {
            // The token is URL-encoded in the query string; decodeURIComponent
            // reverses the quote() the client applied when building the URL.
            try { latestConsumerToken = decodeURIComponent(consumerMatch[1]); }
            catch (e) { latestConsumerToken = consumerMatch[1]; }
            const idMatch = url.match(CONSUMER_IDENTITY_RE);
            if (idMatch) {
                try { latestConsumerIdentity = decodeURIComponent(idMatch[1]); }
                catch (e) { latestConsumerIdentity = idMatch[1]; }
            }
            showPanel();
        }
        if (match) {
            latestToken = match[1];
            showPanel();
            // Intercept .send() to capture outgoing SignalR frames. We capture ALL
            // non-heartbeat frames (not just chat) because the mode/model selection
            // may live in a different frame than the chat invoke. SignalR frames are
            // JSON objects separated by the \x1e record separator.
            try {
                const origSend = ws.send.bind(ws);
                ws.send = function(data) {
                    try {
                        if (typeof data === 'string' && data.length > 2) {
                            const clean = data.replace(/\x1e/g, '');
                            // A single send may contain multiple concatenated frames
                            for (const frame of data.split('\x1e')) {
                                const f = frame.trim();
                                if (!f) continue;
                                let obj;
                                try { obj = JSON.parse(f); } catch (e) { continue; }
                                // Skip pure heartbeat/ack frames (type 6 = ping)
                                if (obj.type === 6) continue;
                                const args = (obj.arguments && obj.arguments[0]) || null;
                                let slim = null;
                                if (args) {
                                    slim = JSON.parse(JSON.stringify(args));
                                    if (slim.message && typeof slim.message === 'object') {
                                        slim.message = {
                                            author: slim.message.author,
                                            messageType: slim.message.messageType,
                                            experienceType: slim.message.experienceType,
                                            text: (slim.message.text || '').slice(0, 80),
                                        };
                                    }
                                }
                                capturedPayloads.unshift({
                                    time: new Date().toLocaleTimeString(),
                                    frameType: obj.type,
                                    target: obj.target || '(none)',
                                    optionsSets: (args && args.optionsSets) || [],
                                    tone: args && args.tone,
                                    gptId: args && (args.threadLevelGptId || args.gptId),
                                    modelId: args && (args.modelId || args.model),
                                    raw: slim || obj,
                                    rawText: f.slice(0, 1500),
                                });
                                if (capturedPayloads.length > 20) capturedPayloads.pop();
                                renderCaptured();
                            }
                        }
                    } catch (e) { /* ignore parse errors */ }
                    return origSend(data);
                };
            } catch (e) { /* ignore */ }
        }
        return ws;
    };
    pageWindow.WebSocket.prototype = OrigWebSocket.prototype;
    pageWindow.WebSocket.CONNECTING = OrigWebSocket.CONNECTING;
    pageWindow.WebSocket.OPEN = OrigWebSocket.OPEN;
    pageWindow.WebSocket.CLOSING = OrigWebSocket.CLOSING;
    pageWindow.WebSocket.CLOSED = OrigWebSocket.CLOSED;

    function getProxyBase() {
        const input = document.getElementById('m365-proxy-url');
        let val = input ? input.value.trim().replace(/\/+$/, '') : '';
        if (!val) {
            try { val = GM_getValue('m365_proxy_base', '') || ''; } catch (e) {}
            if (!val) val = PROXY_BASE;
        }
        try { if (val) GM_setValue('m365_proxy_base', val); } catch (e) {}
        return val;
    }
    function resetSavedProxyBase() {
        try { GM_setValue('m365_proxy_base', ''); } catch (e) {}
        const input = document.getElementById('m365-proxy-url');
        if (input) input.value = '';
        const btn = document.getElementById('m365-reset-proxy-url');
        if (btn) {
            const orig = btn.textContent;
            btn.textContent = tr('reset_proxy_url_done');
            btn.style.color = '#22c55e';
            setTimeout(() => { btn.textContent = orig; btn.style.color = ''; }, 1500);
        }
    }
    function getUserApiKey() {
        const input = document.getElementById('m365-user-api-key');
        let val = input ? input.value.trim() : '';
        if (!val) {
            // Fall back to persisted value, then the hard-coded resident constant.
            try { val = GM_getValue('m365_user_api_key', '') || ''; } catch (e) {}
            if (!val) val = USER_API_KEY;
        }
        try { if (val) GM_setValue('m365_user_api_key', val); } catch (e) {}
        return val;
    }
    function resetSavedUserKey() {
        try { GM_setValue('m365_user_api_key', ''); } catch (e) {}
        const input = document.getElementById('m365-user-api-key');
        if (input) input.value = '';
        const btn = document.getElementById('m365-reset-user-key');
        if (btn) {
            const orig = btn.textContent;
            btn.textContent = tr('reset_user_key_done');
            btn.style.color = '#22c55e';
            setTimeout(() => { btn.textContent = orig; btn.style.color = ''; }, 1500);
        }
    }

    // Cross-origin fetch via GM_xmlhttpRequest
    function gmFetch(url, options) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: options.method || 'GET',
                url: url,
                headers: options.headers || {},
                data: options.body || null,
                onload: (resp) => {
                    // Parse eagerly: a reverse proxy can answer HTTP 200 with an HTML
                    // login page, and callers branch on .ok before reading .data. If the
                    // body is not JSON the request did not reach the proxy API, so .ok
                    // must be false or the success branch prints "undefined".
                    let body = null;
                    let parseError = null;
                    if (typeof resp.response === 'object' && resp.response !== null) {
                        // responseType 'json' — already parsed for us
                        body = resp.response;
                    } else {
                        const raw = resp.responseText || '';
                        try {
                            body = JSON.parse(raw || '{}');
                        } catch (e) {
                            // Surface status + snippet instead of a raw
                            // "Unexpected token '<'" JSON error.
                            const snippet = raw.replace(/\s+/g, ' ').trim().slice(0, 120);
                            parseError = {
                                error: {
                                    message: tr('bad_response')
                                        .replace('{status}', resp.status)
                                        + (snippet ? ' — ' + snippet : ''),
                                },
                            };
                        }
                    }
                    resolve({
                        ok: !parseError && resp.status >= 200 && resp.status < 300,
                        status: resp.status,
                        json: () => Promise.resolve(parseError || body),
                    });
                },
                onerror: (err) => reject(new Error('GM_xmlhttpRequest error: ' + err)),
                ontimeout: () => reject(new Error('GM_xmlhttpRequest timeout')),
            });
        });
    }

    // Get ALL cookies (including httpOnly) via GM_cookie
    async function getAllCookies() {
        const allCookies = [];
        const seen = new Set();

        function addCookie(c) {
            const key = c.name + '@' + c.domain;
            if (seen.has(key)) return;
            seen.add(key);
            allCookies.push({
                name: c.name || '',
                value: c.value || '',
                domain: c.domain || '',
                path: c.path || '/',
                secure: c.secure !== false,
                httpOnly: !!c.httpOnly,
                sameSite: (c.sameSite || '').charAt(0).toUpperCase() + (c.sameSite || '').slice(1).toLowerCase() || 'None',
                expires: c.expirationDate || c.expires || undefined,
            });
        }

        function gmCookieList(details) {
            return new Promise((resolve) => {
                const timer = setTimeout(() => resolve([]), 1500);
                try {
                    GM_cookie.list(details, (c, err) => {
                        clearTimeout(timer);
                        if (err) { resolve([]); }
                        else { resolve(c || []); }
                    });
                } catch(e) { clearTimeout(timer); resolve([]); }
            });
        }

        // All queries to run in parallel
        const queries = [
            {},  // current document URL
            { url: 'https://m365.cloud.microsoft/' },
            { url: 'https://login.microsoftonline.com/' },
            { url: 'https://login.live.com/' },
            { url: 'https://microsoftonline.com/' },
            { url: 'https://microsoft.com/' },
            { url: 'https://office.com/' },
            { url: 'https://www.office.com/' },
            { url: 'https://designerapp.officeapps.live.com/' },
            { url: 'https://teams.microsoft.com/' },
            { url: 'https://jp-prod.asyncgw.teams.microsoft.com/' },
            { domain: '.login.microsoftonline.com' },
            { domain: '.login.live.com' },
            { domain: '.microsoft.com' },
            { domain: '.microsoftonline.com' },
            { domain: '.officeapps.live.com' },
            { domain: '.teams.microsoft.com' },
            { domain: '.asyncgw.teams.microsoft.com' },
            { url: 'https://copilot.microsoft.com/' },
            { url: 'https://www.bing.com/' },
            { domain: '.copilot.microsoft.com' },
            { domain: '.bing.com' },
            { domain: '.live.com' },
        ];

        // Run all queries in parallel
        const results = await Promise.all(queries.map(q => gmCookieList(q)));

        for (const cookies of results) {
            for (const c of (cookies || [])) {
                addCookie(c);
            }
        }

        console.log(`[M365 Proxy] Total cookies:`, allCookies.length, '(httpOnly:', allCookies.filter(c=>c.httpOnly).length, ')');
        return allCookies;
    }

    // Export MSAL localStorage (signed-in account + token cache). m365 is an
    // MSAL SPA that keeps the account in localStorage, NOT just cookies. A
    // cookie-only injected profile has an empty MSAL cache (NoAccountOnStart),
    // so silent SSO can't run and refresh dead-ends on an interactive popup.
    // Exporting these lets the server seed them back so refresh works headless.
    function getMsalLocalStorage() {
        const out = {};
        try {
            for (const k of Object.keys(localStorage)) {
                const lk = k.toLowerCase();
                if (lk.includes('login.windows') || lk.includes('login.microsoftonline.com') ||
                    lk.includes('msal') || lk.includes('authority') || lk.includes('account') ||
                    lk.includes('clientinfo') || lk.includes('appmetadata') ||
                    lk.includes('accesstoken') || lk.includes('refreshtoken') || lk.includes('idtoken')) {
                    const v = localStorage.getItem(k);
                    if (v != null) out[k] = v;
                }
            }
        } catch (e) {}
        return out;
    }

    // Capture the CURRENT chat conversation URL so the server can navigate back
    // into it during a headless token refresh and re-trigger media (image/audio)
    // fetches. Media/designer auth tokens are NOT in the MSAL cache; they only
    // appear as Authorization headers on the asyncgw/teams/designerapp fetches
    // the page issues when a conversation with media is opened. Returns "" for a
    // bare /chat (no specific conversation) so we never store a useless seed.
    function getCurrentChatUrl() {
        try {
            const u = new URL(location.href);
            if (u.hostname !== 'm365.cloud.microsoft') return '';
            if (!/\/chat\/conversation\/[0-9a-fA-F-]{16,}/.test(u.pathname)) return '';
            return u.origin + u.pathname + u.search;
        } catch (e) { return ''; }
    }

    // Check if GM_cookie is available
    function hasGMCookie() {
        return (typeof GM_cookie !== 'undefined' && typeof GM_cookie.list === 'function') ||
            (typeof GM !== 'undefined' && GM.cookie && typeof GM.cookie.list === 'function');
    }

    async function pushUserToken(base, token) {
        const key = getUserApiKey();
        if (!key) throw new Error(tr('no_user_key'));
        const r = await gmFetch(base + '/user/account/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key },
            body: JSON.stringify({ token })
        });
        return { response: r, data: await r.json() };
    }
    async function pushUserCookies(base, cookies) {
        const key = getUserApiKey();
        if (!key) throw new Error(tr('no_user_key'));
        const username = getUsername();
        const r = await gmFetch(base + '/user/account/cookies', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key },
            body: JSON.stringify({ cookies, username, local_storage: getMsalLocalStorage(), media_seed_url: getCurrentChatUrl() })
        });
        return { response: r, data: await r.json() };
    }

    // Push a consumer (personal-account) Copilot snapshot: cookies + the ChatAI
    // token captured off the copilot.microsoft.com chat socket. Distinct endpoint
    // from /cookies because the server must NOT try to inject or refresh it.
    async function pushUserConsumer(base, cookies) {
        const key = getUserApiKey();
        if (!key) throw new Error(tr('no_user_key'));
        const email = getConsumerAccountEmail(cookies, latestConsumerToken);
        const username = getConsumerAccountName() || email;
        const consumerAccountId = getConsumerAccountId();
        if (!consumerAccountId) throw new Error(tr('no_consumer_identity'));
        const r = await gmFetch(base + '/user/account/consumer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key },
            body: JSON.stringify({
                cookies,
                username,
                email,
                consumer_account_id: consumerAccountId,
                access_token: latestConsumerToken,
                identity_type: latestConsumerIdentity,
            })
        });
        return { response: r, data: await r.json() };
    }

    async function pushUserMediaAuth(base) {
        const key = getUserApiKey();
        if (!key || !latestMediaAuth) return null;
        const r = await gmFetch(base + '/user/account/media-auth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key },
            body: JSON.stringify({ authorization: latestMediaAuth.authorization, host: latestMediaAuth.host })
        });
        return { response: r, data: await r.json() };
    }

    async function pushMediaAuth() {
        const base = getProxyBase();
        if (!base) { alert(tr('enter_proxy_first')); return; }
        if (!getUserApiKey()) { alert(tr('no_user_key')); return; }
        if (!latestMediaAuth) { alert(tr('no_media_auth')); return; }
        try {
            const mr = await pushUserMediaAuth(base);
            alert(mr && mr.response.ok ? tr('media_auth_pushed') : tr('failed') + (mr?.data?.error?.message || mr?.data?.error || 'unknown'));
        } catch (e) { alert(tr('network_error') + e); }
    }

    async function pushLatestMediaAuthSilently() {
        if (mediaAuthPushInFlight || !latestMediaAuth) return;
        const base = getProxyBase();
        if (!base || !getUserApiKey()) return;
        mediaAuthPushInFlight = true;
        try { await pushUserMediaAuth(base); } catch (e) {}
        finally { mediaAuthPushInFlight = false; }
    }

    async function pushUserDesignerAuth(base) {
        const key = getUserApiKey();
        if (!key || !latestDesignerAuth) return null;
        const r = await gmFetch(base + '/user/account/designer-auth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key },
            body: JSON.stringify({ authorization: latestDesignerAuth.authorization, host: latestDesignerAuth.host })
        });
        return { response: r, data: await r.json() };
    }

    async function pushLatestDesignerAuthSilently() {
        if (designerAuthPushInFlight || !latestDesignerAuth) return;
        const base = getProxyBase();
        if (!base || !getUserApiKey()) return;
        designerAuthPushInFlight = true;
        try { await pushUserDesignerAuth(base); } catch (e) {}
        finally { designerAuthPushInFlight = false; }
    }

    async function pushUserRefreshToken(base) {
        const key = getUserApiKey();
        if (!key || !latestRefreshToken || !latestRefreshTokenBinding) return null;
        const r = await gmFetch(base + '/user/account/refresh-token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key },
            body: JSON.stringify({ refresh_token: latestRefreshToken, ...latestRefreshTokenBinding })
        });
        return { response: r, data: await r.json() };
    }

    async function pushLatestRefreshTokenSilently(forceReplay = false) {
        if (!latestRefreshToken || !latestRefreshTokenBinding) return null;
        const base = getProxyBase();
        if (!base || !getUserApiKey()) return null;
        if (forceReplay) refreshTokenGeneration++;
        if (refreshTokenPushPromise) return refreshTokenPushPromise;
        refreshTokenPushPromise = (async () => {
            let result = null;
            let pushedGeneration = -1;
            try {
                while (pushedGeneration !== refreshTokenGeneration && latestRefreshToken && latestRefreshTokenBinding) {
                    pushedGeneration = refreshTokenGeneration;
                    try { result = await pushUserRefreshToken(base); } catch (e) { result = null; }
                }
                return result;
            } finally {
                refreshTokenPushPromise = null;
            }
        })();
        return refreshTokenPushPromise;
    }

    // Push Token to proxy
    async function pushToken() {
        const base = getProxyBase();
        if (!base) { alert(tr('enter_proxy_first')); return; }
        // The substrate token only ever appears on an M365 host, so anywhere else
        // -- the consumer site AND the login pages -- say which page to open
        // instead of "not captured yet", which would tell the user to keep
        // waiting on a page that can never produce one.
        if (!latestToken) { alert(IS_M365_SITE ? tr('no_token_ws') : tr('m365_needs_site')); return; }
        try {
            const ur = await pushUserToken(base, latestToken);
            if (ur.response.ok && latestMediaAuth) await pushUserMediaAuth(base);
            if (ur.response.ok && latestDesignerAuth) { try { await pushUserDesignerAuth(base); } catch (e) {} }
            if (ur.response.ok && latestRefreshToken) await pushLatestRefreshTokenSilently(true);
            alert(ur.response.ok ? tr('token_pushed') + (ur.data.token_status?.seconds_remaining) + 's' : tr('token_push_failed') + (ur.data.error?.message || ur.data.error));
        } catch (e) { alert(tr('network_error') + e); }
    }

    // Push cookies to the current /user account profile only; no global cookie is touched.
    async function pushCookies() {
        const base = getProxyBase();
        if (!base) { alert(tr('enter_proxy_first')); return; }
        if (!hasGMCookie()) {
            alert(tr('gm_unavailable_alert'));
            return;
        }
        const btn = document.getElementById('m365-push-cookies');
        if (btn) { btn.disabled = true; btn.textContent = tr('fetching'); }
        try {
            if (latestToken) {
                try { await pushUserToken(base, latestToken); } catch (e) {}
            }
            const cookies = await getAllCookies();
            if (!cookies.length) { alert(tr('no_cookies')); return; }
            const cr = await pushUserCookies(base, cookies);
            if (cr.response.ok && latestMediaAuth) {
                try { await pushUserMediaAuth(base); } catch (e) {}
            }
            if (cr.response.ok && latestDesignerAuth) {
                try { await pushUserDesignerAuth(base); } catch (e) {}
            }
            if (cr.response.ok && latestRefreshToken) {
                await pushLatestRefreshTokenSilently(true);
            }
            const warning = cr.data.warning ? '\n' + cr.data.warning : '';
            alert(cr.response.ok ? tr('cookies_pushed') + cr.data.injected + '/' + cr.data.total + '\n' + tr('httponly_included') + cookies.filter(c => c.httpOnly).length + ')' + warning : tr('failed') + (cr.data.error?.message || cr.data.error));
        } catch (e) {
            alert(tr('error') + e);
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = tr('push_cookies'); }
        }
    }

    // Push a consumer (personal-account) Copilot session. Requires the ChatAI
    // token, which only appears after the copilot.microsoft.com chat socket has
    // opened -- i.e. after at least one turn on the page.
    async function pushConsumer() {
        const base = getProxyBase();
        if (!base) { alert(tr('enter_proxy_first')); return; }
        if (!hasGMCookie()) { alert(tr('gm_unavailable_alert')); return; }
        // The ChatAI token only appears on the consumer host, so from an M365 tab
        // name the page to open rather than repeating "not captured yet".
        if (!latestConsumerToken) { alert(IS_CONSUMER_SITE ? tr('no_consumer_token') : tr('consumer_needs_site')); return; }
        const btn = document.getElementById('m365-push-consumer');
        // The label lives in a child span (icon + text), so write the span and
        // never btn.textContent -- that would wipe the icon out of the button.
        const btnText = document.getElementById('m365-push-consumer-text');
        const setBtnText = (t) => { if (btnText) { btnText.textContent = t; } else if (btn) { btn.textContent = t; } };
        if (btn) { btn.disabled = true; setBtnText(tr('fetching')); }
        try {
            const cookies = await getAllCookies();
            if (!cookies.length) { alert(tr('no_cookies')); return; }
            const cr = await pushUserConsumer(base, cookies);
            alert(cr.response.ok
                ? tr('consumer_pushed') + (cr.data.cookies || cookies.length)
                : tr('failed') + (cr.data.error?.message || cr.data.error));
        } catch (e) {
            alert(tr('error') + e);
        } finally {
            if (btn) { btn.disabled = false; setBtnText(tr('consumer_one_click')); }
        }
    }

    // Copy token to clipboard
    function copyToken() {        if (!latestToken) { alert(tr('no_token_copy')); return; }
        navigator.clipboard.writeText(latestToken).then(() => alert(tr('token_copied'))).catch(() => alert(tr('copy_failed')));
    }

    // One-click pushes both token and cookies to the current /user account.
    async function oneClickSetup() {
        const base = getProxyBase();
        if (!base) { alert(tr('enter_proxy_first')); return; }
        if (!latestToken) { alert(IS_M365_SITE ? tr('no_token_ws') : tr('m365_needs_site')); return; }
        if (!hasGMCookie()) { alert(tr('gm_unavailable_alert')); return; }
        const btn = document.getElementById('m365-one-click');
        const btnText = document.getElementById('m365-one-click-text');
        const setBtnText = (t) => { if (btnText) { btnText.textContent = t; } else { btn.textContent = t; } };
        setBtnText(tr('working'));
        btn.disabled = true;
        try {
            const ur = await pushUserToken(base, latestToken);
            const tokenLine = tr('token_push_status') + (ur.response.ok ? tr('status_success') + ' (' + (ur.data.token_status?.seconds_remaining) + tr('proxy_ready') + ')' : tr('status_failed') + ' - ' + (ur.data.error?.message || ur.data.error));
            if (!ur.response.ok) {
                const cookieLine = tr('cookie_push_status') + tr('status_skipped');
                alert(tokenLine + '\n' + cookieLine);
                return;
            }
            if (latestRefreshToken) {
                await pushLatestRefreshTokenSilently(true);
            }
            setBtnText(tr('pushing_cookies'));
            const cookies = await getAllCookies();
            if (!cookies.length) { alert(tokenLine + '\n' + tr('cookie_push_status') + tr('status_failed') + ' - ' + tr('no_cookies')); return; }
            const cr = await pushUserCookies(base, cookies);
            if (cr.response.ok && latestMediaAuth) {
                try { await pushUserMediaAuth(base); } catch (e) {}
            }
            if (cr.response.ok && latestDesignerAuth) {
                try { await pushUserDesignerAuth(base); } catch (e) {}
            }
            const warning = cr.data.warning ? '\n' + cr.data.warning : '';
            const cookieState = cr.response.ok ? (cr.data.warning ? tr('status_warning') : tr('status_success')) : tr('status_failed');
            const cookieDetail = cr.response.ok ? ' (' + cr.data.injected + '/' + cr.data.total + ')' + warning : ' - ' + (cr.data.error?.message || cr.data.error);
            const cookieLine = tr('cookie_push_status') + cookieState + cookieDetail;
            alert(tokenLine + '\n' + cookieLine);
        } catch (e) {
            alert(tr('error') + e);
        } finally {
            setBtnText(tr('one_click'));
            btn.disabled = false;
        }
    }

    // Push the most recent captured chat payload to the proxy for inspection/comparison
    async function pushPayload() {
        const base = getProxyBase();
        if (!base) { alert(tr('enter_proxy_first')); return; }
        if (!capturedPayloads.length) { alert(tr('no_payload')); return; }
        try {
            const r = await gmFetch(base + '/admin/capture-payload', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ payloads: capturedPayloads })
            });
            const d = await r.json();
            if (r.ok) { alert(tr('pushed_n_payloads').replace('{n}', capturedPayloads.length)); }
            else if (r.status === 403) { alert(tr('capture_disabled')); }
            else { alert(tr('failed') + (d.error?.message || d.error)); }
        } catch (e) { alert(tr('network_error') + e); }
    }

    // Render captured payloads into the panel area (if present)
    function renderCaptured() {
        const box = document.getElementById('m365-captured');
        if (!box) return;
        if (!capturedPayloads.length) {
            box.innerHTML = '<span style="color:#475569">' + tr('no_capture') + '</span>';
            return;
        }
        const escHtml = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        box.innerHTML = capturedPayloads.map((p) => {
            const opts = (p.optionsSets || []).join(', ');
            const gpt = p.gptId && Object.keys(p.gptId).length ? JSON.stringify(p.gptId) : '-';
            return `<div style="border-bottom:1px solid #1e293b; padding:6px 0; font-size:10px; line-height:1.5;">
                <div style="color:#60f2ff;">${p.time} &nbsp; type: <b>${p.frameType}</b> &nbsp; target: <b>${escHtml(p.target)}</b></div>
                <div style="color:#60f2ff;">tone: <b>${p.tone || '-'}</b> &nbsp; model: <b>${escHtml(p.modelId) || '-'}</b></div>
                <div style="color:#94a3b8;">gptId: ${escHtml(gpt)}</div>
                <div style="color:#64748b; word-break:break-all;">optionsSets: ${escHtml(opts)}</div>
                <details style="margin-top:3px"><summary style="cursor:pointer; color:#64748b;">raw frame</summary>
                <pre style="white-space:pre-wrap; word-break:break-all; background:#020617; padding:5px; border-radius:5px; color:#94a3b8; margin-top:2px; max-height:160px; overflow:auto;">${escHtml(p.rawText)}</pre></details>
            </div>`;
        }).join('');
    }

    function togglePanel() {
        const existing = document.getElementById('m365-token-panel');
        if (existing) {
            existing.remove();
            return;
        }
        showPanel();
    }

    // ---- Panel sections, one per product ----------------------------------
    // The two Copilots are separate products with separate credentials, so each
    // gets its own block with its own one-click push and its own manual drawer.
    // The host decides which block leads: on a known product site the other
    // product is collapsed into a drawer so the panel shows only what this page
    // can feed. It is collapsed rather than dropped because M365's cookie push
    // queries absolute domains (see getAllCookies) and therefore works from any
    // tab -- dropping the block would make a working feature unreachable. Every
    // id stays in the DOM either way, which keeps the wiring below safe.
    function siteBadge(isHere, otherKey) {
        const color = isHere ? '#22c55e' : '#475569';
        const text = isHere ? tr('here_now') : tr(otherKey);
        return `<span style="margin-left:auto; font-weight:500; font-size:10px; color:${color};">${text}</span>`;
    }

    function m365Section() {
        return `
                <div style="border-top:1px solid #1e293b; margin:0 0 12px; padding-top:12px;">
                    <div style="font-size:12px; color:#60f2ff; font-weight:700; margin-bottom:4px; display:flex; align-items:center;">
                        <span style="display:flex; align-items:center;">${ic('bolt')}${tr('section_m365')}</span>
                        ${siteBadge(IS_M365_SITE, 'other_site_m365')}
                    </div>
                    <div style="font-size:10px; color:#475569; margin-bottom:8px; display:flex; align-items:center;">
                        <span>${tr('quick_setup_desc')}</span>
                        <span style="margin-left:auto; display:flex; gap:8px;">
                            <span style="color:${latestToken ? '#22c55e' : '#f59e0b'};">${tr('token')} ${latestToken ? '&#10003;' : '&#9888;'}</span>
                            <span style="color:${hasGMCookie() ? '#22c55e' : '#f59e0b'};">Cookie ${hasGMCookie() ? '&#10003;' : '&#9888;'}</span>
                        </span>
                    </div>
                    <button id="m365-one-click" style="width:100%; padding:10px 0; border:none;
                            border-radius:10px; background:linear-gradient(135deg,#60f2ff,#8c6bff 55%,#ffd76f); color:#fff;
                            cursor:pointer; font-weight:700; font-size:13px; letter-spacing:0.3px;
                            transition:opacity 0.2s; display:flex; align-items:center; justify-content:center; gap:6px;">
                        ${ic('rocket')}<span id="m365-one-click-text">${tr('one_click')}</span>
                    </button>

                    <details style="margin-top:10px;">
                        <summary style="font-size:11px; color:#60f2ff; font-weight:600; cursor:pointer; list-style:none; outline:none;">${ic('gear')}${tr('manual_config')} <span style="color:#475569; font-weight:400;">${tr('click_expand')}</span></summary>

                        <div style="font-size:11px; color:#94a3b8; margin:10px 0 5px; font-weight:500; display:flex; align-items:center;"><span>${tr('token')}</span><span style="margin-left:auto; color:${latestToken ? '#22c55e' : '#f59e0b'};">${latestToken ? tr('token_captured') : tr('token_not_captured')}</span></div>
                        <div style="display:flex; gap:8px;">
                            <button id="m365-copy-token" style="flex:1; padding:8px 0; border:none;
                                    border-radius:8px; background:#0ea5e9; color:#fff;
                                    cursor:pointer; font-weight:600; font-size:12px;
                                    transition:opacity 0.2s;">
                                &#128203; ${tr('copy_token')}
                            </button>
                            <button id="m365-push-token" style="flex:1; padding:8px 0; border:none;
                                    border-radius:8px; background:#22c55e; color:#fff;
                                    cursor:pointer; font-weight:600; font-size:12px;
                                    transition:opacity 0.2s;">
                                &#128228; ${tr('push_token')}
                            </button>
                        </div>

                        <div style="font-size:11px; color:#94a3b8; margin:12px 0 8px; font-weight:500; display:flex; align-items:center;"><span>${tr('cookie_login')}</span><span style="margin-left:auto; color:${hasGMCookie() ? '#22c55e' : '#f59e0b'};">${hasGMCookie() ? tr('gm_available') : tr('gm_unavailable')}</span></div>
                        <button id="m365-push-cookies" style="width:100%; padding:8px 0; border:none;
                                border-radius:8px; background:linear-gradient(135deg,#8c6bff,#7c3aed); color:#fff;
                                cursor:pointer; font-weight:600; font-size:12px;
                                transition:opacity 0.2s;">
                            &#127850; ${tr('push_cookies')}
                        </button>

                        <div style="font-size:11px; color:#94a3b8; margin:12px 0 8px; font-weight:500; display:flex; align-items:center;"><span>${tr('media_auth')}</span><span style="margin-left:auto; color:${latestMediaAuth ? '#22c55e' : '#f59e0b'};">${latestMediaAuth ? tr('media_auth_captured') : tr('media_auth_not_captured')}</span></div>
                        <button id="m365-push-media-auth" style="width:100%; padding:8px 0; border:none;
                                border-radius:8px; background:linear-gradient(135deg,#0ea5e9,#2563eb); color:#fff;
                                cursor:pointer; font-weight:600; font-size:12px;
                                transition:opacity 0.2s;">
                            &#128228; ${tr('push_media_auth')}
                        </button>
                    </details>
                </div>`;
    }

    function consumerSection() {
        return `
                <div style="border-top:1px solid #1e293b; margin:0 0 12px; padding-top:12px;">
                    <div style="font-size:12px; color:#10b981; font-weight:700; margin-bottom:4px; display:flex; align-items:center;">
                        <span style="display:flex; align-items:center;">${ic('fox')}${tr('section_consumer')}</span>
                        ${siteBadge(IS_CONSUMER_SITE, 'other_site_consumer')}
                    </div>
                    <div style="font-size:10px; color:#475569; margin-bottom:8px; display:flex; align-items:center;">
                        <span>${tr('consumer_desc')}</span>
                        <span style="margin-left:auto; color:${latestConsumerToken ? '#22c55e' : '#f59e0b'};">${latestConsumerToken ? tr('consumer_captured') : '&#9888;'}</span>
                    </div>
                    <button id="m365-push-consumer" style="width:100%; padding:10px 0; border:none;
                            border-radius:10px; background:linear-gradient(135deg,#10b981,#0d9488); color:#fff;
                            cursor:pointer; font-weight:700; font-size:13px; letter-spacing:0.3px;
                            transition:opacity 0.2s; display:flex; align-items:center; justify-content:center; gap:6px;">
                        &#129302; <span id="m365-push-consumer-text">${tr('consumer_one_click')}</span>
                    </button>
                    <div style="font-size:10px; color:#475569; margin-top:6px;">${latestConsumerToken ? '' : tr('consumer_not_captured')}</div>
                </div>`;
    }

    // Mode capture belongs to M365: the outgoing-frame tap is installed inside
    // the Substrate branch only, so this section can never fill up on the
    // consumer site. It travels with the M365 block instead of standing alone.
    function captureSection() {
        return `
                <details style="border-top:1px solid #1e293b; margin:0 0 12px; padding-top:12px;">
                    <summary style="font-size:12px; color:#60f2ff; font-weight:700; cursor:pointer; list-style:none; outline:none;">${ic('scope')}${tr('mode_capture')} <span style="color:#475569; font-weight:400;">${tr('click_expand')} — ${tr('section_capture_scope')}</span></summary>
                    <div style="font-size:10px; color:#64748b; margin:8px 0;">${tr('mode_capture_desc')}</div>
                    <div id="m365-captured" style="background:#0f172a; padding:8px 12px; border-radius:8px; border:1px solid #334155; max-height:160px; overflow-y:auto; margin-bottom:8px;">
                        <span style="color:#475569">${tr('no_capture')}</span>
                    </div>
                    <button id="m365-push-payload" style="width:100%; padding:8px 0; border:none;
                            border-radius:8px; background:linear-gradient(135deg,#f59e0b,#ef4444); color:#fff;
                            cursor:pointer; font-weight:600; font-size:12px;
                            transition:opacity 0.2s;">
                        &#128228; ${tr('push_payloads')}
                    </button>
                </details>`;
    }

    // Collapsed wrapper for the product the current tab cannot feed.
    function otherProductDrawer(inner) {
        return `
                <details style="border-top:1px solid #1e293b; margin:0 0 12px; padding-top:12px;">
                    <summary style="font-size:11px; color:#64748b; font-weight:600; cursor:pointer; list-style:none; outline:none;">${ic('gear')}${tr('other_product')} <span style="color:#475569; font-weight:400;">${tr('other_product_hint')}</span></summary>
                    ${inner}
                </details>`;
    }

    function panelBody() {
        if (IS_CONSUMER_SITE) {
            return consumerSection() + otherProductDrawer(m365Section() + captureSection());
        }
        if (IS_M365_SITE) {
            return m365Section() + captureSection() + otherProductDrawer(consumerSection());
        }
        // Neither product host (login pages, other Microsoft domains): we cannot
        // tell where the user is headed, so show both and let them choose.
        return m365Section() + consumerSection() + captureSection();
    }

    function showPanel() {
        if (document.getElementById('m365-token-panel')) {
            document.getElementById('m365-token-panel').remove();
        }

        const panel = document.createElement('div');
        panel.id = 'm365-token-panel';
        panel.innerHTML = `
            <div style="position:fixed; top:10px; right:10px; z-index:99999;
                        background:linear-gradient(180deg,rgba(13,19,45,0.92) 0%,rgba(7,10,24,0.9) 100%);
                        color:#f3f6ff; padding:20px 24px;
                        border-radius:18px; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',monospace; font-size:13px;
                        box-shadow:0 18px 48px rgba(0,0,0,0.55),0 0 0 1px rgba(108,137,255,0.24);
                        max-width:480px; width:calc(100vw - 20px); max-height:90vh; overflow-y:auto;
                        backdrop-filter:blur(16px);">
                <div style="font-weight:700; font-size:16px; margin-bottom:12px; color:#60f2ff;
                            letter-spacing:0.5px; display:flex; align-items:center; gap:8px;">
                    ${ic('spark')} ${tr('title')}
                    <span id="m365-script-version" style="font-size:10px; color:#94a3b8; font-weight:600;">v${SCRIPT_VERSION}</span>
                    <button id="m365-lang-toggle" style="margin-left:auto; padding:3px 12px; border:1px solid #334155;
                            border-radius:8px; background:transparent; color:#60f2ff; cursor:pointer;
                            font-weight:600; font-size:11px; transition:all 0.2s;">
                        ${tr('lang_btn')}
                    </button>
                </div>

                <div style="margin-bottom:12px;">
                    <div style="font-size:11px; color:#94a3b8; margin-bottom:5px; font-weight:500;">${tr('proxy_url')}</div>
                    <div style="display:flex; gap:6px; align-items:center;">
                        <input id="m365-proxy-url" type="text" placeholder="http://your-server:8000"
                            value="${(() => { try { return GM_getValue('m365_proxy_base', PROXY_BASE); } catch (e) { return PROXY_BASE; } })()}"
                            style="flex:1; box-sizing:border-box; padding:8px 12px; background:#0f172a; border:1px solid #334155;
                                   border-radius:8px; color:#e2e8f0; font-size:12px; font-family:monospace;
                                   outline:none; transition:border-color 0.2s;">
                        <button id="m365-reset-proxy-url" title="${tr('reset_proxy_url')}"
                            style="padding:8px 10px; border:1px solid #334155; border-radius:8px; background:#0f172a; color:#94a3b8;
                                   font-size:11px; cursor:pointer; white-space:nowrap; transition:all 0.2s;">&#9851;</button>
                    </div>
                    <div style="font-size:11px; color:#94a3b8; margin:8px 0 5px; font-weight:500;">${tr('user_api_key')}</div>
                    <div style="display:flex; gap:6px; align-items:center;">
                        <input id="m365-user-api-key" type="password" placeholder="sk-..."
                            value="${(() => { try { return GM_getValue('m365_user_api_key', ''); } catch (e) { return ''; } })()}"
                            style="flex:1; box-sizing:border-box; padding:8px 12px; background:#0f172a; border:1px solid #334155;
                                   border-radius:8px; color:#e2e8f0; font-size:12px; font-family:monospace;
                                   outline:none; transition:border-color 0.2s;">
                        <button id="m365-reset-user-key" title="${tr('reset_user_key')}"
                            style="padding:8px 10px; border:1px solid #334155; border-radius:8px; background:#0f172a; color:#94a3b8;
                                   font-size:11px; cursor:pointer; white-space:nowrap; transition:all 0.2s;">&#9851;</button>
                    </div>
                </div>

                ${panelBody()}

                <div style="border-top:1px solid #1e293b; margin:0; padding-top:12px; display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:10px; color:#475569">${tr('toggle_hint')}</span>
                    <button id="m365-close-panel" style="padding:6px 16px; border:1px solid #334155;
                            border-radius:8px; background:transparent; color:#94a3b8;
                            cursor:pointer; font-weight:500; font-size:12px;
                            transition:all 0.2s;">
                        ${tr('close')}
                    </button>
                </div>
            </div>
        `;
        (document.body || document.documentElement).appendChild(panel);

        const langBtn = document.getElementById('m365-lang-toggle');
        if (langBtn) langBtn.onclick = () => toggleLang();
        // Every button is wired defensively: the sections are host-dependent, and
        // one throw here would abort the rest of the wiring -- including the close
        // button, leaving a panel that cannot be dismissed.
        const on = (id, handler) => {
            const el = document.getElementById(id);
            if (el) el.onclick = handler;
        };
        on('m365-copy-token', () => copyToken());
        on('m365-push-token', () => pushToken());
        on('m365-push-cookies', () => pushCookies());
        on('m365-push-media-auth', pushMediaAuth);
        on('m365-push-consumer', () => pushConsumer());
        on('m365-one-click', () => oneClickSetup());
        on('m365-reset-proxy-url', () => resetSavedProxyBase());
        on('m365-reset-user-key', () => resetSavedUserKey());
        on('m365-push-payload', () => pushPayload());
        on('m365-close-panel', () => panel.remove());
        renderCaptured();
    }

    function handlePanelShortcut(e) {
        const key = String(e.key || '').toLowerCase();
        if (key !== 'm' || !e.shiftKey || (!e.ctrlKey && !e.altKey)) return;
        e.preventDefault();
        e.stopPropagation();
        togglePanel();
    }

    try {
        if (typeof GM_registerMenuCommand === 'function') {
            GM_registerMenuCommand('打开/关闭 M365 Proxy 面板', togglePanel);
        }
    } catch (e) {}

    // Show panel on demand via keyboard shortcut (Ctrl+Shift+M / Alt+Shift+M)
    pageWindow.addEventListener('keydown', handlePanelShortcut, true);
    document.addEventListener('keydown', handlePanelShortcut, true);
})();
