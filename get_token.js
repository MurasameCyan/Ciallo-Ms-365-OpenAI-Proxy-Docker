// ==UserScript==
// @name         M365 Copilot Token & Cookie Extractor
// @namespace    https://m365.cloud.microsoft
// @version      4.0
// @description  拦截 M365 Copilot Substrate WebSocket 连接，提取 access_token；通过 GM_cookie 获取完整 Cookie（含 httpOnly）推送到代理服务实现 Chromium 登录
// @match        https://m365.cloud.microsoft/*
// @match        https://login.microsoftonline.com/*
// @match        https://microsoftonline.com/*
// @match        https://www.office.com/*
// @match        https://office.com/*
// @match        https://microsoft.com/*
// @grant        GM_cookie
// @grant        GM_xmlhttpRequest
// @grant        unsafeWindow
// @connect      *
// ==/UserScript==

(function() {
    'use strict';

    const SUBSTRATE_WS_RE = /wss:\/\/substrate\.office\.com\/.*[?&]access_token=([^&]+)/;
    const PROXY_BASE = ''; // 留空则从面板输入框读取，或填入你的代理地址如 http://192.168.1.100:8000

    // Domains whose cookies are needed for M365 login
    const COOKIE_DOMAINS = [
        'https://m365.cloud.microsoft',
        'https://login.microsoftonline.com',
        'https://microsoftonline.com',
        'https://microsoft.com',
        'https://office.com',
        'https://www.office.com',
    ];

    // Store the latest token
    let latestToken = '';

    // Intercept WebSocket construction on the real page (not in sandbox)
    const pageWindow = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;

    const OrigWebSocket = pageWindow.WebSocket;
    pageWindow.WebSocket = function(url, protocols) {
        const match = url.match(SUBSTRATE_WS_RE);
        if (match) {
            latestToken = match[1];
            showPanel();
        }
        return new OrigWebSocket(url, protocols);
    };
    pageWindow.WebSocket.prototype = OrigWebSocket.prototype;
    pageWindow.WebSocket.CONNECTING = OrigWebSocket.CONNECTING;
    pageWindow.WebSocket.OPEN = OrigWebSocket.OPEN;
    pageWindow.WebSocket.CLOSING = OrigWebSocket.CLOSING;
    pageWindow.WebSocket.CLOSED = OrigWebSocket.CLOSED;

    function getProxyBase() {
        const input = document.getElementById('m365-proxy-url');
        return input ? input.value.trim().replace(/\/+$/, '') : PROXY_BASE;
    }

    // Cross-origin fetch via GM_xmlhttpRequest
    function gmFetch(url, options) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: options.method || 'GET',
                url: url,
                headers: options.headers || {},
                data: options.body || null,
                responseType: 'json',
                onload: (resp) => {
                    resolve({
                        ok: resp.status >= 200 && resp.status < 300,
                        status: resp.status,
                        json: () => Promise.resolve(resp.response || {}),
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
            { url: 'https://microsoftonline.com/' },
            { url: 'https://microsoft.com/' },
            { url: 'https://office.com/' },
            { url: 'https://www.office.com/' },
            { domain: '.login.microsoftonline.com' },
            { domain: '.microsoft.com' },
            { domain: '.microsoftonline.com' },
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

    // Check if GM_cookie is available
    function hasGMCookie() {
        return (typeof GM_cookie !== 'undefined' && typeof GM_cookie.list === 'function') ||
               (typeof GM !== 'undefined' && GM.cookie && typeof GM.cookie.list === 'function');
    }

    // Push Token to proxy
    async function pushToken() {
        const base = getProxyBase();
        if (!base) { alert('Please enter proxy URL first'); return; }
        if (!latestToken) { alert('No token captured yet. Type something in Copilot to trigger WebSocket.'); return; }
        try {
            const r = await gmFetch(base + '/v1/token/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: latestToken })
            });
            const d = await r.json();
            alert(r.ok ? `Token pushed! Remaining: ${d.token_status?.seconds_remaining}s` : `Failed: ${d.error?.message || d.error}`);
        } catch (e) { alert('Network error: ' + e); }
    }

    // Push ALL cookies (including httpOnly) to proxy for Chromium login
    async function pushCookies() {
        const base = getProxyBase();
        if (!base) { alert('Please enter proxy URL first'); return; }

        if (!hasGMCookie()) {
            alert('GM_cookie API not available.\n\nPlease use Tampermonkey Beta or enable "Allow scripts to access HttpOnly cookies" in Tampermonkey settings:\nSettings > Security > "Allow scripts to access cookies"');
            return;
        }

        const btn = document.getElementById('m365-push-cookies');
        if (btn) { btn.disabled = true; btn.textContent = 'Fetching...'; }

        try {
            const cookies = await getAllCookies();
            if (!cookies.length) { alert('No cookies found.'); return; }

            if (btn) btn.textContent = 'Pushing...';
            const r = await gmFetch(base + '/v1/cookie/inject', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cookies })
            });
            const d = await r.json();
            alert(r.ok ? `Cookies pushed! ${d.message}\n(httpOnly included: ${cookies.filter(c => c.httpOnly).length})` : `Failed: ${d.error?.message || d.error}`);
        } catch (e) {
            alert('Error: ' + e);
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = 'Push Cookies'; }
        }
    }

    // Copy token to clipboard
    function copyToken() {
        if (!latestToken) { alert('No token captured yet'); return; }
        navigator.clipboard.writeText(latestToken).then(() => alert('Token copied!')).catch(() => alert('Copy failed'));
    }

    // One-click: push cookies first (to login Chromium), then push token
    async function oneClickSetup() {
        const base = getProxyBase();
        if (!base) { alert('Please enter proxy URL first'); return; }
        if (!latestToken) { alert('No token captured yet. Type something in Copilot to trigger WebSocket first.'); return; }

        const btn = document.getElementById('m365-one-click');
        btn.textContent = 'Working...';
        btn.disabled = true;

        try {
            // Step 1: Push cookies (if GM_cookie available) to login Chromium
            if (hasGMCookie()) {
                btn.textContent = '1/2 Pushing cookies...';
                const cookies = await getAllCookies();
                if (cookies.length) {
                    await gmFetch(base + '/v1/cookie/inject', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ cookies })
                    });
                    // Wait for Chromium to process cookies and reload
                    await new Promise(r => setTimeout(r, 3000));
                }
            }

            // Step 2: Push token
            btn.textContent = '2/2 Pushing token...';
            const r = await gmFetch(base + '/v1/token/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: latestToken })
            });
            const d = await r.json();
            if (r.ok) {
                alert(`Setup complete! Token remaining: ${d.token_status?.seconds_remaining}s\nProxy is ready to use.`);
            } else {
                alert('Token push failed: ' + (d.error?.message || d.error));
            }
        } catch (e) {
            alert('Error: ' + e);
        } finally {
            btn.textContent = 'One-Click Setup';
            btn.disabled = false;
        }
    }

    function showPanel() {
        if (document.getElementById('m365-token-panel')) {
            document.getElementById('m365-token-panel').remove();
        }

        const gmCookieNote = hasGMCookie()
            ? '<span style="color:#22c55e">GM_cookie available - httpOnly cookies accessible</span>'
            : '<span style="color:#f59e0b">GM_cookie not available. Install Tampermonkey Beta or enable httpOnly access in settings.</span>';

        const panel = document.createElement('div');
        panel.id = 'm365-token-panel';
        panel.innerHTML = `
            <div style="position:fixed; top:10px; right:10px; z-index:99999;
                        background:#1a1a2e; color:#e0e0e0; padding:16px 20px;
                        border-radius:10px; font-family:monospace; font-size:13px;
                        box-shadow:0 4px 20px rgba(0,0,0,0.5); max-width:520px;
                        border:1px solid #16213e; max-height:90vh; overflow-y:auto;">
                <div style="font-weight:bold; font-size:15px; margin-bottom:8px; color:#00d2ff;">
                    M365 Copilot Proxy Tool
                </div>

                <div style="margin-bottom:10px;">
                    <div style="font-size:11px; color:#8892b0; margin-bottom:4px;">Proxy URL</div>
                    <input id="m365-proxy-url" type="text" placeholder="http://your-server:8000"
                        value="${PROXY_BASE}"
                        style="width:100%; padding:6px 10px; background:#0f0f23; border:1px solid #475569;
                               border-radius:6px; color:#e0e0e0; font-size:12px; font-family:monospace;">
                </div>

                <div style="font-size:11px; color:#8892b0; margin-bottom:4px;">Token<span style="color:#64748b"> (truncated)</span></div>
                <div style="word-break:break-all; max-height:60px; overflow-y:auto;
                            background:#0f0f23; padding:8px; border-radius:6px;
                            font-size:10px; color:#a8b2d1; line-height:1.4;">
                    ${latestToken ? latestToken.slice(0, 80) + '...' : 'No token captured yet'}
                </div>

                <div style="margin-top:10px; display:flex; flex-wrap:wrap; gap:6px;">
                    <button id="m365-copy-token" style="padding:5px 12px; border:none;
                            border-radius:6px; background:#00d2ff; color:#1a1a2e;
                            cursor:pointer; font-weight:bold; font-size:12px;">
                        Copy Token
                    </button>
                    <button id="m365-push-token" style="padding:5px 12px; border:none;
                            border-radius:6px; background:#22c55e; color:#fff;
                            cursor:pointer; font-weight:bold; font-size:12px;">
                        Push Token
                    </button>
                </div>

                <div style="border-top:1px solid #334155; margin:12px 0 10px; padding-top:10px;">
                    <div style="font-size:11px; color:#8892b0; margin-bottom:6px;">Cookie Login <span style="font-size:10px">${gmCookieNote}</span></div>
                    <button id="m365-push-cookies" style="padding:5px 12px; border:none;
                            border-radius:6px; background:#8b5cf6; color:#fff;
                            cursor:pointer; font-weight:bold; font-size:12px; width:100%;">
                        Push All Cookies (incl. httpOnly)
                    </button>
                </div>

                <div style="border-top:1px solid #334155; margin:12px 0 10px; padding-top:10px;">
                    <div style="font-size:11px; color:#22c55e; margin-bottom:6px; font-weight:bold;">Quick Setup</div>
                    <div style="font-size:10px; color:#8892b0; margin-bottom:6px;">Push cookies + token to proxy for Chromium login and auto-refresh</div>
                    <button id="m365-one-click" style="padding:5px 12px; border:none;
                            border-radius:6px; background:linear-gradient(135deg,#8b5cf6,#06b6d4,#22c55e); color:#fff;
                            cursor:pointer; font-weight:bold; font-size:12px; width:100%;">
                        One-Click Setup
                    </button>
                </div>

                <div style="border-top:1px solid #334155; margin:12px 0 0; padding-top:10px;">
                    <button id="m365-close-panel" style="padding:5px 12px; border:none;
                            border-radius:6px; background:#e94560; color:#fff;
                            cursor:pointer; font-weight:bold; font-size:12px;">
                        Close
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(panel);

        document.getElementById('m365-copy-token').onclick = () => copyToken();
        document.getElementById('m365-push-token').onclick = () => pushToken();
        document.getElementById('m365-push-cookies').onclick = () => pushCookies();
        document.getElementById('m365-one-click').onclick = () => oneClickSetup();
        document.getElementById('m365-close-panel').onclick = () => panel.remove();
    }

    // Show panel on demand via keyboard shortcut (Ctrl+Shift+M)
    pageWindow.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.shiftKey && e.key === 'M') {
            showPanel();
        }
    });
})();
