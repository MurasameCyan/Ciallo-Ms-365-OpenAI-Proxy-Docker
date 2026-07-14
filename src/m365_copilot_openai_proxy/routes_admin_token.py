from __future__ import annotations

import json
import re
from collections.abc import Callable

from fastapi import FastAPI, Request

from .account_store import extract_identity
from .response_helpers import _json_err
from .token_identity import update_username_from_token
from .token_store import write_token, write_username


def register_admin_token_routes(app: FastAPI, require_admin: Callable[[Request], object | None], *, admin_cdp_enabled: bool = False) -> None:
    @app.get("/admin/token/status")
    async def token_status(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        status = app.state.token_store.status()
        status["auto_refresh"] = app.state.auto_refresh_enabled
        status["username"] = (getattr(app.state, 'username', '') or None) if len(getattr(app.state, 'username', '')) > 1 else None
        # Expose whether the shared admin CDP endpoints are registered so the
        # admin UI can skip polling /admin/chromium/login-status (which is not
        # registered when CDP is off) and avoid a recurring 404 every minute.
        status["admin_cdp_enabled"] = admin_cdp_enabled
        return status

    @app.post("/admin/token/auto-refresh-toggle")
    async def toggle_auto_refresh(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        app.state.auto_refresh_enabled = not app.state.auto_refresh_enabled
        return {"status": "ok", "auto_refresh": app.state.auto_refresh_enabled}

    @app.post("/admin/token/update")
    async def update_token(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        body = await request.json()
        token = body.get("token", "").strip()
        username = body.get("username", "").strip()
        if not token:
            return _json_err(400, "Token is empty")
        # Extract token from full WebSocket URL if needed
        match = re.search(r"access_token=([^&\s]+)", token)
        if match:
            token = match.group(1)
        if not token.startswith("eyJ"):
            return _json_err(400, "Not a valid JWT token")
        # Write to isolated token file
        write_token(token)
        # Update in-memory store
        app.state.token_store._token = token
        app.state.token_store._mtime_ns = None
        if username and len(username) > 1:
            app.state.username = username
            write_username(username)
        else:
            update_username_from_token(token, app.state)
        _, email = extract_identity(token)
        if email:
            acc = app.state.account_store.find_by_email(email)
            if acc is not None:
                app.state.account_store.push_token(acc.id, token)
        return {"status": "ok", "message": "Token updated", "token_status": app.state.token_store.status()}

    # The endpoints below all talk to the shared admin CDP Chromium on the primary
    # port (9222). When that browser is not started (pool deployments), skip
    # registering them entirely so callers get a clean 404 instead of a connection
    # error, and no misleading CDP failure logs are emitted.
    if not admin_cdp_enabled:
        return

    @app.post("/admin/token/auto-capture")
    async def auto_capture_token(request: Request) -> dict:
        """Auto-capture token from Chromium CDP running inside the container."""
        err = require_admin(request)
        if err: return err
        from .cli import _cdp_extract_token
        cdp_port = int(getattr(app.state, "cdp_port", 9222))
        try:
            token = await _cdp_extract_token(cdp_port, allow_nudge=True)
        except Exception as exc:
            return _json_err(502, f"CDP capture failed: {exc}")
        if not token:
            return _json_err(404, "No substrate token found. Make sure M365 Copilot is open and logged in in Chromium.")
        # Write to token file and update in-memory
        write_token(token)
        app.state.token_store._token = token
        app.state.token_store._mtime_ns = None
        update_username_from_token(token, app.state)
        return {"status": "ok", "message": "Token auto-captured", "token_status": app.state.token_store.status()}

    @app.post("/admin/cookie/inject")
    async def inject_cookie(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        body = await request.json()
        cookies = body.get("cookies", [])
        username = body.get("username", "")
        if username and len(str(username).strip()) > 1:
            app.state.username = str(username).strip()
            write_username(str(username).strip())
        if not cookies:
            return _json_err(400, "No cookies provided")
        import asyncio as _async
        import httpx as _httpx
        import websockets as _ws

        cdp_port = int(getattr(app.state, "cdp_port", 9222))
        try:
            async with _httpx.AsyncClient(timeout=3) as client:
                tabs = (await client.get(f"http://localhost:{cdp_port}/json")).json()
        except Exception as exc:
            return _json_err(502, f"Cannot connect to Chromium CDP: {exc}")

        tab = next((t for t in tabs if t.get("type") == "page" and t.get("url", "").startswith("https://m365.cloud.microsoft/")), None)
        if not tab:
            tab = next((t for t in tabs if t.get("type") == "page"), None)
        if not tab:
            return _json_err(404, "No browser tab found in Chromium")

        injected = 0
        try:
            async with _ws.connect(tab["webSocketDebuggerUrl"]) as ws:
                await ws.send(json.dumps({"id": 2, "method": "Network.clearBrowserCookies"}))
                try:
                    await _async.wait_for(ws.recv(), timeout=2)
                except (_async.TimeoutError, Exception):
                    pass
                if "m365.cloud.microsoft" not in tab.get("url", ""):
                    await ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": "https://m365.cloud.microsoft/chat"}}))
                    await _async.sleep(3)
                    try:
                        await _async.wait_for(ws.recv(), timeout=2)
                    except (_async.TimeoutError, Exception):
                        pass

                for i, cookie in enumerate(cookies):
                    cookie_params = {
                        "name": cookie.get("name", ""),
                        "value": cookie.get("value", ""),
                        "domain": cookie.get("domain", ".microsoft.com"),
                        "path": cookie.get("path", "/"),
                        "secure": cookie.get("secure", True),
                        "httpOnly": cookie.get("httpOnly", False),
                    }
                    ss = cookie.get("sameSite", "")
                    if ss:
                        ss_cap = ss.capitalize()
                        if ss_cap in ("Strict", "Lax", "None"):
                            cookie_params["sameSite"] = ss_cap
                    # sameSite=None requires secure=true in CDP
                    if cookie_params.get("sameSite") == "None":
                        cookie_params["secure"] = True
                    if cookie.get("expirationDate") or cookie.get("expires"):
                        cookie_params["expires"] = cookie.get("expirationDate") or cookie.get("expires")
                    await ws.send(json.dumps({"id": 100 + i, "method": "Network.setCookie", "params": cookie_params}))
                    try:
                        resp = await _async.wait_for(ws.recv(), timeout=5)
                        result = json.loads(resp)
                        if result.get("result", {}).get("success"):
                            injected += 1
                    except (_async.TimeoutError, Exception):
                        pass

                # Navigate to M365 chat (full load, not just reload)
                await ws.send(json.dumps({"id": 998, "method": "Page.navigate", "params": {"url": "https://m365.cloud.microsoft/chat"}}))
                # Wait for page to load and potentially complete auth redirect
                await _async.sleep(8)
                # Drain any pending CDP messages
                try:
                    while True:
                        await _async.wait_for(ws.recv(), timeout=0.5)
                except (_async.TimeoutError, Exception):
                    pass
        except Exception as exc:
            return _json_err(502, f"CDP cookie injection failed: {exc}")

        return {"status": "ok", "message": f"Injected {injected}/{len(cookies)} cookies. Page navigating to M365...", "injected": injected, "total": len(cookies)}

    @app.get("/admin/chromium/login-status")
    async def chromium_login_status(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        import httpx as _httpx
        import websockets as _ws
        import asyncio as _async

        cdp_port = int(getattr(app.state, "cdp_port", 9222))
        # Check CDP availability
        try:
            async with _httpx.AsyncClient(timeout=3) as client:
                tabs = (await client.get(f"http://localhost:{cdp_port}/json")).json()
        except Exception:
            return {"chromium_running": False, "logged_in": False, "url": None, "title": None, "cookies": []}

        # Find M365 tab
        tab = next((t for t in tabs if t.get("type") == "page" and "m365.cloud.microsoft" in t.get("url", "")), None)
        if not tab:
            tab = next((t for t in tabs if t.get("type") == "page"), None)

        if not tab:
            return {"chromium_running": True, "logged_in": False, "url": None, "title": None, "cookies": []}

        # Try to detect login state via CDP
        logged_in = False
        page_title = tab.get("title", "")
        page_url = tab.get("url", "")
        cookie_details = []
        # Extract username: prefer CDP extraction, fallback to app.state.username (set by get_token.js push)
        username = getattr(app.state, 'username', '') or None
        try:
            async with _ws.connect(tab["webSocketDebuggerUrl"]) as ws:
                # Get page cookies for M365 domain
                await ws.send(json.dumps({"id": 1, "method": "Network.getCookies", "params": {"urls": ["https://m365.cloud.microsoft", "https://login.microsoftonline.com", "https://microsoft.com", "https://office.com"]}}))
                resp = await _async.wait_for(ws.recv(), timeout=5)
                result = json.loads(resp)
                cookies = result.get("result", {}).get("cookies", [])
                cookie_details = [{"name": c.get("name", ""), "domain": c.get("domain", ""), "httpOnly": c.get("httpOnly", False), "secure": c.get("secure", False)} for c in cookies]
                # Check for authentication cookies
                auth_cookie_names = {"SignInStateCookie", "ESTSAUTH", "ESTSAUTHPERSISTENT", "brcap", "MUID"}
                found = any(c.get("name", "") in auth_cookie_names for c in cookies)
                # Also check URL — if redirected to login page, not logged in
                if "login.microsoftonline.com" in page_url or "login.windows.net" in page_url:
                    logged_in = False
                elif found or "m365.cloud.microsoft/chat" in page_url:
                    logged_in = True
                else:
                    logged_in = False
                # Extract username from page JS (try multiple sources)
                if logged_in:
                    try:
                        _USER_JS = """(() => {
                            try { const s = sessionStorage.getItem('ms-m365-shell-session-data'); if (s) { const d = JSON.parse(s); if (d && d.userDisplayName) return d.userDisplayName; if (d && d.upn) return d.upn.split('@')[0]; } } catch {}
                            try {
                                const av = document.querySelectorAll('[data-testid="header-person-menu"], [data-testid="persona"], button[aria-label*="Account"], button[aria-label*="Manager"], [role="button"][aria-label*="for "], [role="button"][title*="for "], [role="button"][aria-label*="概要"]');
                                for (const el of av) {
                                    const a = el.getAttribute('aria-label') || el.getAttribute('title') || '';
                                    const m = a.match(/(?:for\\s+|的[帐账]户(?:管理器)?[：:]?\\s*)(.+)/i) || a.match(/^(.+?)(?:\\s*\\(|\\s*-|\\s*的)/);
                                    if (m && m[1] && m[1].trim().length > 1 && m[1].trim().length < 80) return m[1].trim();
                                    if (a && a.length > 1 && a.length < 80 && !/^(home|copilot|apps|chat|create|menu|back|close)$/i.test(a)) return a.trim();
                                }
                            } catch {}
                            try {
                                const els = document.querySelectorAll('[data-testid="header-person-menu"], [data-testid="persona"], [aria-label*="Account"], [aria-label*="Profiles"], .ms-Icon--People, button[title*="Account"], span[id*="person"]');
                                for (const el of els) { const t = el.textContent.trim(); if (t && t.length > 1 && t.length < 80) return t; }
                            } catch {}
                            try {
                                const profile = document.querySelector('div[class*="persona"] span, div[class*="UserProfile"] span, img[alt]'); if (profile) { const a = profile.getAttribute('alt') || profile.textContent; if (a && a.trim() && a.trim().length > 1) return a.trim(); } } catch {}
                            try {
                                const fus = document.querySelectorAll('span.fui-Text, span[class*="fai-bebop"]');
                                const skip = /^(home|copilot|apps|chat|create|new|file|edit|view|insert|format|tools|help|share|send|save|open|close|settings|back|next|previous|more|menu|search|filter|sort|refresh|delete|cancel|ok|yes|no)$/i;
                                for (const el of fus) { const t = el.textContent.trim(); if (t && t.length > 1 && t.length < 80 && !skip.test(t)) return t; }
                            } catch {}
                            return null;
                        })()"""
                        next_id = 2
                        # Drain any pending CDP messages before sending
                        while True:
                            try:
                                await _async.wait_for(ws.recv(), timeout=0.1)
                            except (_async.TimeoutError, Exception):
                                break
                        await ws.send(json.dumps({"id": next_id, "method": "Runtime.evaluate", "params": {"expression": _USER_JS}}))
                        # Wait for the specific response by id
                        deadline = _async.get_event_loop().time() + 3
                        while _async.get_event_loop().time() < deadline:
                            raw_msg = await _async.wait_for(ws.recv(), timeout=2)
                            msg = json.loads(raw_msg)
                            if msg.get("id") == next_id:
                                name_val = msg.get("result", {}).get("result", {}).get("value")
                                if name_val and isinstance(name_val, str) and len(name_val.strip()) > 1:
                                    username = name_val.strip()
                                    app.state.username = username
                                    write_username(username)
                                break
                    except Exception:
                        pass
        except Exception:
            logged_in = "m365.cloud.microsoft/chat" in page_url

        # Fallback to persisted username if CDP extraction returned nothing
        if not username:
            username = getattr(app.state, 'username', '') or None

        return {
            "chromium_running": True,
            "logged_in": logged_in,
            "username": username,
            "url": page_url,
            "title": page_title,
            "cookies": cookie_details,
        }

    @app.post("/admin/chromium/logout")
    async def chromium_logout(request: Request) -> dict:
        """Logout from M365 in Chromium by clearing cookies and navigating to login page."""
        err = require_admin(request)
        if err: return err
        import httpx as _httpx
        import websockets as _ws
        import asyncio as _async

        cdp_port = int(getattr(app.state, "cdp_port", 9222))
        try:
            async with _httpx.AsyncClient(timeout=3) as client:
                tabs = (await client.get(f"http://localhost:{cdp_port}/json")).json()
        except Exception as exc:
            return _json_err(502, f"Cannot connect to Chromium CDP: {exc}")

        tab = next((t for t in tabs if t.get("type") == "page" and "m365.cloud.microsoft" in t.get("url", "")), None)
        if not tab:
            tab = next((t for t in tabs if t.get("type") == "page"), None)
        if not tab:
            return _json_err(404, "No browser tab found in Chromium")

        try:
            async with _ws.connect(tab["webSocketDebuggerUrl"]) as ws:
                # Clear all cookies for Microsoft domains
                await ws.send(json.dumps({"id": 1, "method": "Network.getCookies", "params": {"urls": ["https://m365.cloud.microsoft", "https://login.microsoftonline.com", "https://microsoft.com", "https://office.com"]}}))
                resp = await _async.wait_for(ws.recv(), timeout=5)
                result = json.loads(resp)
                cookies = result.get("result", {}).get("cookies", [])
                cleared = 0
                for i, c in enumerate(cookies):
                    await ws.send(json.dumps({"id": 100 + i, "method": "Network.deleteCookies", "params": {"name": c.get("name", ""), "domain": c.get("domain", "")}}))
                    try:
                        await _async.wait_for(ws.recv(), timeout=2)
                        cleared += 1
                    except Exception:
                        pass
                # Clear sessionStorage and localStorage
                await ws.send(json.dumps({"id": 500, "method": "Runtime.evaluate", "params": {"expression": "sessionStorage.clear();localStorage.clear();true"}}))
                try:
                    await _async.wait_for(ws.recv(), timeout=3)
                except Exception:
                    pass
                # Navigate to login page
                await ws.send(json.dumps({"id": 501, "method": "Page.navigate", "params": {"url": "https://m365.cloud.microsoft/chat"}}))
                try:
                    await _async.wait_for(ws.recv(), timeout=5)
                except Exception:
                    pass
        except Exception as exc:
            return _json_err(502, f"CDP logout failed: {exc}")

        app.state.username = ""
        write_username("")
        return {"status": "ok", "message": f"Logged out. Cleared {cleared}/{len(cookies)} cookies.", "username": ""}
