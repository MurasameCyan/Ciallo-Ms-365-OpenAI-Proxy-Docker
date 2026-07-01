// ==UserScript==
// @name         Ciallo Ms-365 Proxy
// @namespace    https://m365.cloud.microsoft
// @version      5.0
// @description  提取 M365 Copilot 完整 Cookie（含 httpOnly）推送到代理服务实现登录
// @match        https://m365.cloud.microsoft/*
// @match        https://login.microsoftonline.com/*
// @match        https://microsoftonline.com/*
// @match        https://www.office.com/*
// @match        https://office.com/*
// @match        https://microsoft.com/*
// @grant        GM_cookie
// @grant        GM_xmlhttpRequest
// @grant        unsafeWindow
// @updateURL    https://gh-proxy.com/https://raw.githubusercontent.com/MurasameCyan/Ciallo-Ms-365-OpenAI-Proxy-Docker/main/get_token.user.js
// @downloadURL  https://gh-proxy.com/https://raw.githubusercontent.com/MurasameCyan/Ciallo-Ms-365-OpenAI-Proxy-Docker/main/get_token.user.js
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
            token: 'Token',
            token_captured: '✓ Token 可用',
            token_not_captured: '⚠ 尚未捕获',
            copy_token: '复制 Token',
            push_token: '推送 Token',
            cookie_login: 'Cookie 登录',
            gm_available: '✓ Cookie 可用',
            gm_unavailable: '⚠ GM_cookie 不可用，请使用 Tampermonkey Beta。',
            push_cookies: '推送全部 Cookie',
            quick_setup: ' 一键配置',
            quick_setup_desc: '推送 Cookie + Token 到代理，用于 Chromium 登录和自动刷新',
            one_click: '推送配置',
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
            token_pushed: 'Token 已推送！剩余：',
            failed: '失败：',
            network_error: '网络错误：',
            gm_unavailable_alert: 'GM_cookie API 不可用。\n\n请使用 Tampermonkey Beta，或在 Tampermonkey 设置中启用「允许脚本访问 HttpOnly cookie」：\n设置 > 安全 > 「允许脚本访问 cookie」',
            fetching: '获取中...',
            pushing: '推送中...',
            no_cookies: '未找到 Cookie。',
            cookies_pushed: 'Cookie 已推送！',
            httponly_included: '（含 httpOnly：',
            error: '错误：',
            no_token_copy: '尚未捕获 Token',
            token_copied: 'Token 已复制！',
            copy_failed: '复制失败',
            working: '处理中...',
            pushing_cookies: '1/2 推送 Cookie...',
            pushing_token: '2/2 推送 Token...',
            setup_complete: '配置完成！Token 剩余：',
            proxy_ready: '秒\n代理已就绪。',
            token_push_failed: 'Token 推送失败：',
            no_payload: '暂无抓包数据。先在 Copilot 选择模式并发送一条消息。',
            pushed_n_payloads: '已推送 {n} 条 payload 到代理。',
        },
        en: {
            title: 'Ciallo Ms-365 Proxy',
            proxy_url: 'Proxy URL',
            token: 'Token',
            token_captured: '✓ captured',
            token_not_captured: '⚠ not captured yet',
            copy_token: 'Copy Token',
            push_token: 'Push Token',
            cookie_login: 'Cookie Login',
            gm_available: '✓ GM_cookie available',
            gm_unavailable: '⚠ GM_cookie unavailable. Use Tampermonkey Beta.',
            push_cookies: 'Push All Cookies',
            quick_setup: 'Quick Setup',
            quick_setup_desc: 'Push cookies + token to proxy for Chromium login and auto-refresh',
            one_click: 'One-Click Setup',
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
            token_pushed: 'Token pushed! Remaining: ',
            failed: 'Failed: ',
            network_error: 'Network error: ',
            gm_unavailable_alert: 'GM_cookie API not available.\n\nPlease use Tampermonkey Beta or enable "Allow scripts to access HttpOnly cookies" in Tampermonkey settings:\nSettings > Security > "Allow scripts to access cookies"',
            fetching: 'Fetching...',
            pushing: 'Pushing...',
            no_cookies: 'No cookies found.',
            cookies_pushed: 'Cookies pushed! ',
            httponly_included: '(httpOnly included: ',
            error: 'Error: ',
            no_token_copy: 'No token captured yet',
            token_copied: 'Token copied!',
            copy_failed: 'Copy failed',
            working: 'Working...',
            pushing_cookies: '1/2 Pushing cookies...',
            pushing_token: '2/2 Pushing token...',
            setup_complete: 'Setup complete! Token remaining: ',
            proxy_ready: 's\nProxy is ready to use.',
            token_push_failed: 'Token push failed: ',
            no_payload: 'No chat payload captured yet. Pick a mode in Copilot and send a message first.',
            pushed_n_payloads: 'Pushed {n} payload(s) to proxy.',
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

    // Intercept WebSocket construction on the real page (not in sandbox)
    const pageWindow = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;

    const OrigWebSocket = pageWindow.WebSocket;
    pageWindow.WebSocket = function(url, protocols) {
        const match = url.match(SUBSTRATE_WS_RE);
        const ws = new OrigWebSocket(url, protocols);
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
                onload: (resp) => {
                    resolve({
                        ok: resp.status >= 200 && resp.status < 300,
                        status: resp.status,
                        json: () => {
                            // If responseType is 'json', resp.response is already parsed
                            if (typeof resp.response === 'object' && resp.response !== null) {
                                return Promise.resolve(resp.response);
                            }
                            return Promise.resolve(JSON.parse(resp.responseText || '{}'));
                        },
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
        if (!base) { alert(tr('enter_proxy_first')); return; }
        if (!latestToken) { alert(tr('no_token_ws')); return; }
        const username = getUsername();
        try {
            const r = await gmFetch(base + '/admin/token/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: latestToken, username: username || undefined })
            });
            const d = await r.json();
            alert(r.ok ? tr('token_pushed') + (d.token_status?.seconds_remaining) + 's' : tr('failed') + (d.error?.message || d.error));
        } catch (e) { alert(tr('network_error') + e); }
    }

    // Push ALL cookies (including httpOnly) to proxy for Chromium login
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
            const cookies = await getAllCookies();
            if (!cookies.length) { alert(tr('no_cookies')); return; }

            if (btn) btn.textContent = tr('pushing');
            const r = await gmFetch(base + '/admin/cookie/inject', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cookies, username: getUsername() || undefined })
            });
            const d = await r.json();
            alert(r.ok ? tr('cookies_pushed') + d.message + '\n' + tr('httponly_included') + cookies.filter(c => c.httpOnly).length + ')' : tr('failed') + (d.error?.message || d.error));
        } catch (e) {
            alert(tr('error') + e);
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = tr('push_cookies'); }
        }
    }

    // Copy token to clipboard
    function copyToken() {
        if (!latestToken) { alert(tr('no_token_copy')); return; }
        navigator.clipboard.writeText(latestToken).then(() => alert(tr('token_copied'))).catch(() => alert(tr('copy_failed')));
    }

    // One-click: push cookies first (to login Chromium), then push token
    async function oneClickSetup() {
        const base = getProxyBase();
        if (!base) { alert(tr('enter_proxy_first')); return; }
        if (!latestToken) { alert(tr('no_token_ws')); return; }

        const btn = document.getElementById('m365-one-click');
        btn.textContent = tr('working');
        btn.disabled = true;

        try {
            // Step 1: Push cookies (if GM_cookie available) to login Chromium
            if (hasGMCookie()) {
                btn.textContent = tr('pushing_cookies');
                const cookies = await getAllCookies();
                if (cookies.length) {
                    await gmFetch(base + '/admin/cookie/inject', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ cookies, username: getUsername() || undefined })
                    });
                    // Wait for Chromium to process cookies and reload
                    await new Promise(r => setTimeout(r, 3000));
                }
            }

            // Step 2: Push token
            btn.textContent = '2/2 Pushing token...';
            const username = getUsername();
            const r = await gmFetch(base + '/admin/token/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: latestToken, username: username || undefined })
            });
            const d = await r.json();
            if (r.ok) {
                alert(tr('setup_complete') + (d.token_status?.seconds_remaining) + tr('proxy_ready'));
            } else {
                alert(tr('token_push_failed') + (d.error?.message || d.error));
            }
        } catch (e) {
            alert(tr('error') + e);
        } finally {
            btn.textContent = tr('one_click');
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
            alert(r.ok ? tr('pushed_n_payloads').replace('{n}', capturedPayloads.length) : tr('failed') + (d.error?.message || d.error));
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
                    <button id="m365-lang-toggle" style="margin-left:auto; padding:3px 12px; border:1px solid #334155;
                            border-radius:8px; background:transparent; color:#60f2ff; cursor:pointer;
                            font-weight:600; font-size:11px; transition:all 0.2s;"
                            onmouseover="this.style.borderColor='#60f2ff'" onmouseout="this.style.borderColor='#334155'">
                        ${tr('lang_btn')}
                    </button>
                </div>

                <div style="margin-bottom:12px;">
                    <div style="font-size:11px; color:#94a3b8; margin-bottom:5px; font-weight:500;">${tr('proxy_url')}</div>
                    <input id="m365-proxy-url" type="text" placeholder="http://your-server:8000"
                        value="${PROXY_BASE}"
                        style="width:100%; box-sizing:border-box; padding:8px 12px; background:#0f172a; border:1px solid #334155;
                               border-radius:8px; color:#e2e8f0; font-size:12px; font-family:monospace;
                               outline:none; transition:border-color 0.2s;"
                        onfocus="this.style.borderColor='#60f2ff'" onblur="this.style.borderColor='#334155'">
                </div>

                <div style="border-top:1px solid #1e293b; margin:0 0 12px; padding-top:12px;">
                    <div style="font-size:12px; color:#60f2ff; font-weight:700; margin-bottom:8px; display:flex; align-items:center;">
                        <span style="display:flex; align-items:center;">${ic('bolt')}${tr('quick_setup')}</span>
                        <span style="margin-left:auto; font-weight:500; font-size:10px; display:flex; gap:8px;">
                            <span style="color:${latestToken ? '#22c55e' : '#f59e0b'};">${tr('token')} ${latestToken ? '&#10003;' : '&#9888;'}</span>
                            <span style="color:${hasGMCookie() ? '#22c55e' : '#f59e0b'};">Cookie ${hasGMCookie() ? '&#10003;' : '&#9888;'}</span>
                        </span>
                    </div>
                    <div style="font-size:10px; color:#64748b; margin-bottom:8px;">${tr('quick_setup_desc')}</div>
                    <button id="m365-one-click" style="width:100%; padding:10px 0; border:none;
                            border-radius:10px; background:linear-gradient(135deg,#60f2ff,#8c6bff 55%,#ffd76f); color:#050815;
                            cursor:pointer; font-weight:700; font-size:13px; letter-spacing:0.3px;
                            transition:opacity 0.2s;" onmouseover="this.style.opacity=0.85" onmouseout="this.style.opacity=1">
                        &#128640; ${tr('one_click')}
                    </button>
                </div>

                <details style="border-top:1px solid #1e293b; margin:0 0 12px; padding-top:12px;">
                    <summary style="font-size:12px; color:#60f2ff; font-weight:700; cursor:pointer; list-style:none; outline:none;">${ic('gear')}${tr('manual_config')} <span style="color:#475569; font-weight:400;">${tr('click_expand')}</span></summary>

                    <div style="font-size:11px; color:#94a3b8; margin:10px 0 5px; font-weight:500; display:flex; align-items:center;"><span>${tr('token')}</span><span style="margin-left:auto; color:${latestToken ? '#22c55e' : '#f59e0b'};">${latestToken ? tr('token_captured') : tr('token_not_captured')}</span></div>
                    <div style="display:flex; gap:8px;">
                        <button id="m365-copy-token" style="flex:1; padding:8px 0; border:none;
                                border-radius:8px; background:#0ea5e9; color:#fff;
                                cursor:pointer; font-weight:600; font-size:12px;
                                transition:opacity 0.2s;" onmouseover="this.style.opacity=0.85" onmouseout="this.style.opacity=1">
                            &#128203; ${tr('copy_token')}
                        </button>
                        <button id="m365-push-token" style="flex:1; padding:8px 0; border:none;
                                border-radius:8px; background:#22c55e; color:#fff;
                                cursor:pointer; font-weight:600; font-size:12px;
                                transition:opacity 0.2s;" onmouseover="this.style.opacity=0.85" onmouseout="this.style.opacity=1">
                            &#128228; ${tr('push_token')}
                        </button>
                    </div>

                    <div style="font-size:11px; color:#94a3b8; margin:12px 0 8px; font-weight:500; display:flex; align-items:center;"><span>${tr('cookie_login')}</span><span style="margin-left:auto; color:${hasGMCookie() ? '#22c55e' : '#f59e0b'};">${hasGMCookie() ? tr('gm_available') : tr('gm_unavailable')}</span></div>
                    <button id="m365-push-cookies" style="width:100%; padding:8px 0; border:none;
                            border-radius:8px; background:linear-gradient(135deg,#8c6bff,#7c3aed); color:#fff;
                            cursor:pointer; font-weight:600; font-size:12px;
                            transition:opacity 0.2s;" onmouseover="this.style.opacity=0.85" onmouseout="this.style.opacity=1">
                        &#127850; ${tr('push_cookies')}
                    </button>
                </details>

                <details style="border-top:1px solid #1e293b; margin:0 0 12px; padding-top:12px;">
                    <summary style="font-size:12px; color:#60f2ff; font-weight:700; cursor:pointer; list-style:none; outline:none;">${ic('scope')}${tr('mode_capture')} <span style="color:#475569; font-weight:400;">${tr('click_expand')}</span></summary>
                    <div style="font-size:10px; color:#64748b; margin:8px 0;">${tr('mode_capture_desc')}</div>
                    <div id="m365-captured" style="background:#0f172a; padding:8px 12px; border-radius:8px; border:1px solid #334155; max-height:160px; overflow-y:auto; margin-bottom:8px;">
                        <span style="color:#475569">${tr('no_capture')}</span>
                    </div>
                    <button id="m365-push-payload" style="width:100%; padding:8px 0; border:none;
                            border-radius:8px; background:linear-gradient(135deg,#f59e0b,#ef4444); color:#fff;
                            cursor:pointer; font-weight:600; font-size:12px;
                            transition:opacity 0.2s;" onmouseover="this.style.opacity=0.85" onmouseout="this.style.opacity=1">
                        &#128228; ${tr('push_payloads')}
                    </button>
                </details>

                <div style="border-top:1px solid #1e293b; margin:0; padding-top:12px; display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:10px; color:#475569">${tr('toggle_hint')}</span>
                    <button id="m365-close-panel" style="padding:6px 16px; border:1px solid #334155;
                            border-radius:8px; background:transparent; color:#94a3b8;
                            cursor:pointer; font-weight:500; font-size:12px;
                            transition:all 0.2s;" onmouseover="this.style.borderColor=#ef4444;this.style.color=#ef4444" onmouseout="this.style.borderColor=#334155;this.style.color=#94a3b8">
                        ${tr('close')}
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(panel);

        const langBtn = document.getElementById('m365-lang-toggle');
        if (langBtn) langBtn.onclick = () => toggleLang();
        document.getElementById('m365-copy-token').onclick = () => copyToken();
        document.getElementById('m365-push-token').onclick = () => pushToken();
        document.getElementById('m365-push-cookies').onclick = () => pushCookies();
        document.getElementById('m365-one-click').onclick = () => oneClickSetup();
        const pushPayloadBtn = document.getElementById('m365-push-payload');
        if (pushPayloadBtn) pushPayloadBtn.onclick = () => pushPayload();
        document.getElementById('m365-close-panel').onclick = () => panel.remove();
        renderCaptured();
    }

    // Show panel on demand via keyboard shortcut (Ctrl+Shift+M)
    pageWindow.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.shiftKey && e.key === 'M') {
            showPanel();
        }
    });
})();
