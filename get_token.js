// ==UserScript==
// @name         M365 Copilot Token Extractor
// @namespace    https://m365.cloud.microsoft
// @version      1.0
// @description  拦截 M365 Copilot Substrate WebSocket 连接，提取 access_token
// @match        https://m365.cloud.microsoft/*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    const SUBSTRATE_WS_RE = /wss:\/\/substrate\.office\.com\/.*[?&]access_token=([^&]+)/;

    // 拦截 WebSocket 构造
    const OrigWebSocket = window.WebSocket;
    window.WebSocket = function(url, protocols) {
        const match = url.match(SUBSTRATE_WS_RE);
        if (match) {
            const token = match[1];
            // 在页面右上角显示提取结果
            showTokenPanel(token);
        }
        return new OrigWebSocket(url, protocols);
    };
    window.WebSocket.prototype = OrigWebSocket.prototype;
    window.WebSocket.CONNECTING = OrigWebSocket.CONNECTING;
    window.WebSocket.OPEN = OrigWebSocket.OPEN;
    window.WebSocket.CLOSING = OrigWebSocket.CLOSING;
    window.WebSocket.CLOSED = OrigWebSocket.CLOSED;

    function showTokenPanel(token) {
        // 避免重复创建
        if (document.getElementById('m365-token-panel')) {
            document.getElementById('m365-token-panel').remove();
        }

        const panel = document.createElement('div');
        panel.id = 'm365-token-panel';
        panel.innerHTML = `
            <div style="position:fixed; top:10px; right:10px; z-index:99999;
                        background:#1a1a2e; color:#e0e0e0; padding:16px 20px;
                        border-radius:10px; font-family:monospace; font-size:13px;
                        box-shadow:0 4px 20px rgba(0,0,0,0.5); max-width:500px;
                        border:1px solid #16213e;">
                <div style="font-weight:bold; font-size:15px; margin-bottom:8px; color:#00d2ff;">
                    M365 Substrate Token
                </div>
                <div style="word-break:break-all; max-height:120px; overflow-y:auto;
                            background:#0f0f23; padding:8px; border-radius:6px;
                            font-size:11px; color:#a8b2d1; line-height:1.5;">
                    ${token}
                </div>
                <div style="margin-top:10px; display:flex; gap:8px;">
                    <button id="m365-copy-token" style="padding:6px 16px; border:none;
                            border-radius:6px; background:#00d2ff; color:#1a1a2e;
                            cursor:pointer; font-weight:bold; font-size:13px;">
                        Copy Token
                    </button>
                    <button id="m365-copy-url" style="padding:6px 16px; border:none;
                            border-radius:6px; background:#7b2ff7; color:#fff;
                            cursor:pointer; font-weight:bold; font-size:13px;">
                        Copy Full WS URL
                    </button>
                    <button id="m365-close-panel" style="padding:6px 16px; border:none;
                            border-radius:6px; background:#e94560; color:#fff;
                            cursor:pointer; font-weight:bold; font-size:13px;">
                        Close
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(panel);

        document.getElementById('m365-copy-token').onclick = () => {
            navigator.clipboard.writeText(token).then(() => {
                document.getElementById('m365-copy-token').textContent = 'Copied!';
                setTimeout(() => { document.getElementById('m365-copy-token').textContent = 'Copy Token'; }, 1500);
            });
        };
        document.getElementById('m365-copy-url').onclick = () => {
            const fullUrl = `wss://substrate.office.com/m365Copilot/Chathub?access_token=${token}`;
            navigator.clipboard.writeText(fullUrl).then(() => {
                document.getElementById('m365-copy-url').textContent = 'Copied!';
                setTimeout(() => { document.getElementById('m365-copy-url').textContent = 'Copy Full WS URL'; }, 1500);
            });
        };
        document.getElementById('m365-close-panel').onclick = () => {
            panel.remove();
        };
    }
})();