from __future__ import annotations

import argparse
import asyncio
import json
import logging
import platform
import re
import select
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn
import websockets

from . import runtime_flags
from .app import create_app
from .config import Settings
from .token_store import decode_jwt_payload, is_substrate_token_claims, read_token as read_token_from_store, write_token as write_token_to_store, write_username, read_username
from .cli_cdp import (
    _cdp_capture_websocket_token,
    _cdp_extract_resource_tokens,
    _cdp_extract_token,
    _cdp_nudge_and_wait_for_token,
    _cdp_tab_summary,
    _capture_token_to_env,
    _classify_resource_token,
    _ensure_first_page_navigates_to_m365,
    _find_m365_page,
    _is_m365_page_url,
    _is_substrate_token,
    _m365_chat_url,
    _navigate_tab_to_m365,
    _needs_substrate_token,
    _select_substrate_token,
    _startup_capture_loop,
    _summarize_cdp_tabs,
    _token_identity_email,
    _wait_for_m365_page,
    _wait_for_substrate_websocket_token,
)



class _SuppressCtrlC(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "CTRL+C" not in record.getMessage()


logging.getLogger("uvicorn.error").addFilter(_SuppressCtrlC())


# High-frequency, low-value access-log lines: web admin/user page polling, the
# container health check, favicon, the bare landing page and the media proxy all
# emit one INFO line each and drown out real traffic. When SUPPRESS_ACCESS_LOG is
# on (default), drop the SUCCESSFUL ones so the log stays readable. Real API
# traffic, state-changing requests and any non-2xx/3xx response (auth failures,
# expired media signatures, 404s) are always kept so problems surface.
# The toggle is read live from runtime_flags so the admin UI can flip it without
# a restart (this filter is registered at import, before app.state exists).
_NOISY_EXACT_PATHS = frozenset({"/", "/favicon.ico", "/healthz"})
_NOISY_PATH_PREFIXES = ("/admin", "/user", "/v1/m365-media")
# uvicorn access format: '1.2.3.4:5 - "GET /admin/tone HTTP/1.1" 200 OK'
_ACCESS_LINE_RE = re.compile(
    r'"(?P<method>[A-Z]+)\s+(?P<path>\S+)\s+HTTP/[\d.]+"\s+(?P<status>\d{3})'
)


def _is_noisy_access_path(path: str) -> bool:
    path = path.split("?", 1)[0]
    if path in _NOISY_EXACT_PATHS:
        return True
    return any(path == pre or path.startswith(pre + "/") for pre in _NOISY_PATH_PREFIXES)


class _SuppressPollingAccess(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not runtime_flags.SUPPRESS_ACCESS_LOG:
            return True
        m = _ACCESS_LINE_RE.search(record.getMessage())
        if not m:
            return True
        # Keep 4xx/5xx so failures stay visible; only suppress noisy 2xx/3xx.
        if m.group("status")[0] not in ("2", "3"):
            return True
        # POST/PUT/PATCH/DELETE are user actions, not polling. Their completion
        # line is useful evidence even when successful.
        if m.group("method") not in ("GET", "HEAD"):
            return True
        return not _is_noisy_access_path(m.group("path"))


logging.getLogger("uvicorn.access").addFilter(_SuppressPollingAccess())


def _try_auto_refresh(cdp_port: int, *, allow_nudge: bool = True) -> bool:
    token = asyncio.run(_cdp_extract_token(cdp_port, allow_nudge=allow_nudge))
    if not token:
        return False
    _write_token(token)
    print("Token refreshed automatically.")
    return True


def _read_token() -> str | None:
    return read_token_from_store()


def _seconds_remaining(token: str) -> int:
    claims = decode_jwt_payload(token)
    return int(claims["exp"]) - int(time.time())


def _auto_refresh_loop(
    cdp_port: int,
    refresh_before_seconds: int,
    retry_seconds: int,
    stop_event: threading.Event,
    app_state=None,
) -> None:
    while not stop_event.is_set():
        # Respect on-demand mode: if auto_refresh disabled, sleep and check again
        if app_state is not None and not app_state.auto_refresh_enabled:
            stop_event.wait(10)
            continue

        # Idle detection: if no /v1/ requests for idle_timeout_minutes, pause auto-refresh
        if app_state is not None:
            last_req = getattr(app_state, 'last_request_time', 0)
            # last_request_time=0 means no /v1/ request ever received, stay paused
            if last_req == 0:
                app_state.auto_refresh_enabled = False
                stop_event.wait(10)
                continue
            idle_seconds = time.time() - last_req
            idle_timeout = getattr(app_state, 'idle_timeout_minutes', 30) * 60
            if idle_seconds > idle_timeout:
                app_state.auto_refresh_enabled = False
                print(f"No /v1/ requests for {idle_seconds:.0f}s (> {idle_timeout}s); auto-refresh paused (on-demand mode).")
                stop_event.wait(10)
                continue

        token = _read_token()
        if not token:
            stop_event.wait(retry_seconds)
            continue

        try:
            remaining = _seconds_remaining(token)
        except Exception as exc:
            print(f"Auto-refresh skipped: cannot decode current token: {exc}")
            stop_event.wait(retry_seconds)
            continue

        current_refresh_before = getattr(app_state, 'refresh_before_seconds', refresh_before_seconds) if app_state is not None else refresh_before_seconds
        if remaining > current_refresh_before:
            wait_seconds = min(remaining - current_refresh_before, 300)
            stop_event.wait(wait_seconds)
            continue

        print(f"Token expires in {max(remaining, 0)} seconds; refreshing from Edge...")
        if not _try_auto_refresh(cdp_port):
            print("Auto-refresh failed; will retry later.")
        stop_event.wait(retry_seconds)


def _write_token(token: str) -> None:
    write_token_to_store(token)
    # Also extract and persist username from JWT if not already set
    existing = read_username()
    if not existing or len(existing) <= 1:
        try:
            claims = decode_jwt_payload(token)
            name = claims.get("name") or claims.get("upn") or ""
            if isinstance(name, str):
                name = name.strip()
                if "@" in name and " " not in name:
                    name = name.split("@")[0]
            if name and len(name) > 1:
                write_username(name)
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(prog="copilot-openai-proxy")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("set-token").set_defaults(func=set_token_command)
    capture_parser = subparsers.add_parser("capture-token")
    capture_parser.add_argument("--cdp-port", type=int, default=9222)
    capture_parser.add_argument("--timeout-seconds", type=int, default=60)
    capture_parser.set_defaults(func=capture_token_command)

    launch_parser = subparsers.add_parser("launch-edge")
    launch_parser.add_argument("--cdp-port", type=int, default=9222)
    launch_parser.set_defaults(func=launch_edge_command)

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--cdp-port", type=int, default=9222)
    serve_parser.add_argument("--no-auto-refresh", action="store_true")
    serve_parser.add_argument("--no-launch-edge", action="store_true")
    serve_parser.add_argument("--no-capture-on-start", action="store_true")
    serve_parser.add_argument("--capture-timeout-seconds", type=int, default=180)
    serve_parser.add_argument("--refresh-before-seconds", type=int, default=300)
    serve_parser.add_argument("--refresh-retry-seconds", type=int, default=60)
    serve_parser.set_defaults(func=serve_command)

    args = parser.parse_args()
    # Pin localhost into NO_PROXY before any CDP call. websockets>=15 and httpx
    # both honour the proxy env vars by default, so a developer with HTTPS_PROXY
    # set would otherwise have every localhost CDP connection routed through it.
    # serve re-applies this from the persisted setting via create_app().
    from .runtime_settings import apply_proxy_env

    apply_proxy_env("")
    args.func(args)


def launch_edge_command(args: argparse.Namespace) -> None:
    _launch_debug_edge(args.cdp_port)


def _launch_debug_edge(cdp_port: int) -> None:
    profile_dir = Path.home() / ".m365-copilot-openai-proxy" / "edge-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    if platform.system() == "Windows":
        edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    elif platform.system() == "Darwin":
        edge_path = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    else:
        # Linux: try chromium first, then edge
        import shutil
        edge_path = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("microsoft-edge") or shutil.which("microsoft-edge-stable") or "chromium"

    from .refresh_chromium import chromium_proxy_args

    subprocess.Popen([
        edge_path,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={profile_dir}",
        *chromium_proxy_args(),
        "--no-first-run",
        "https://m365.cloud.microsoft/chat",
    ])
    print(f"Browser launched with remote debugging on port {cdp_port}.")
    print(f"Dedicated profile: {profile_dir}")
    print("Sign in to M365 Copilot in that window once, then retry refresh.")


def set_token_command(_args) -> None:
    print("Paste the full WebSocket URL (or just the access_token value), then press Enter:")
    raw = input().strip()
    match = re.search(r"access_token=([^&\s]+)", raw)
    token = match.group(1) if match else raw
    if not token.startswith("eyJ"):
        print("Error: could not find a valid token. Make sure you copied the full WebSocket URL.")
        return
    if not _is_substrate_token(token):
        print("Error: token is not a substrate.office.com WebSocket token.")
        print("Copy the full wss://substrate.office.com/... URL from the Network WebSocket request.")
        return
    _write_token(token)
    print("Token file updated.")


def capture_token_command(args: argparse.Namespace) -> None:
    print("Listening for a Substrate WebSocket token...")
    print("In the debug Edge M365 Copilot tab, click the message box and type one character. Do not need to send.")
    token = asyncio.run(_cdp_capture_websocket_token(args.cdp_port, args.timeout_seconds))
    if not token:
        print("Error: no Substrate WebSocket token captured before timeout.")
        return
    _write_token(token)
    print("Token file updated with Substrate token.")


def serve_command(args: argparse.Namespace) -> None:
    cdp_port: int = args.cdp_port
    log_level = Settings().log_level.strip().lower() or "info"
    logging.getLogger().setLevel(log_level.upper())
    while True:
        app = create_app()
        config = uvicorn.Config(app, host=args.host, port=args.port, log_level=log_level)
        server = uvicorn.Server(config)
        stop_auto_refresh = threading.Event()
        auto_refresh_thread = None
        capture_thread = None

        if not args.no_launch_edge:
            _launch_debug_edge(cdp_port)

        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        # On-demand mode: skip startup capture, token will be captured when /v1/ requests come in
        if not args.no_auto_refresh:
            auto_refresh_thread = threading.Thread(
                target=_auto_refresh_loop,
                args=(
                    cdp_port,
                    args.refresh_before_seconds,
                    args.refresh_retry_seconds,
                    stop_auto_refresh,
                    app.state,
                ),
                daemon=True,
            )
            auto_refresh_thread.start()

        while not server.started and thread.is_alive():
            time.sleep(0.05)
        auto_refresh_label = "off" if args.no_auto_refresh else "on-demand"
        capture_label = "off" if getattr(args, 'no_capture_on_start', True) else "on"
        print(
            f"\n  [q] quit    [r] refresh token"
            f"    auto-refresh: {auto_refresh_label}"
            f"    startup-capture: {capture_label}\n"
        )

        action = None
        while thread.is_alive():
            if platform.system() == "Windows":
                import msvcrt as _msvcrt
                if _msvcrt.kbhit():
                    key = _msvcrt.getwch().lower()
                    if key == "q":
                        action = "quit"
                        server.should_exit = True
                        break
                    elif key == "r":
                        action = "refresh"
                        server.should_exit = True
                        break
            else:
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    key = sys.stdin.readline().strip().lower()
                    if key == "q":
                        action = "quit"
                        server.should_exit = True
                        break
                    elif key == "r":
                        action = "refresh"
                        server.should_exit = True
                        break
            time.sleep(0.05)

        stop_auto_refresh.set()
        thread.join()
        if auto_refresh_thread:
            auto_refresh_thread.join(timeout=1)
        if capture_thread:
            capture_thread.join(timeout=1)

        if action == "refresh":
            print("Refreshing token...")
            if not _try_auto_refresh(cdp_port):
                print("Auto-refresh failed (Edge not running with --remote-debugging-port).")
                print("Falling back to manual mode.")
                set_token_command(None)
            print("Restarting server...")
        else:
            break


if __name__ == "__main__":
    main()
