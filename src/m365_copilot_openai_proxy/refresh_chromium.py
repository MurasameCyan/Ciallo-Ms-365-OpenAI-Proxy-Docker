from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import signal
import subprocess
import time
from pathlib import Path

_LOGGED_CHROMIUM_PATH: str | None = None


def _chromium_path() -> str:
    """Locate a Chromium/Edge binary and log the resolved path once per change."""
    resolved = _resolve_chromium_path()
    global _LOGGED_CHROMIUM_PATH
    if resolved != _LOGGED_CHROMIUM_PATH:
        _LOGGED_CHROMIUM_PATH = resolved
        print(f"Chromium binary resolved to: {resolved}", flush=True)
    return resolved


def _resolve_chromium_path() -> str:
    """Locate a Chromium/Edge binary for the current platform."""
    if platform.system() == "Windows":
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for c in candidates:
            if Path(c).exists():
                return c
        return shutil.which("chromium") or shutil.which("chrome") or "chromium"
    if platform.system() == "Darwin":
        return "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    configured = os.environ.get("CHROME_BIN")
    if configured and shutil.which(configured):
        return configured
    # Linux (container default): prefer full Chromium. The headless-shell build
    # cannot complete the Microsoft SSO redirect chain (it lands on
    # login.microsoftonline.com and fails to capture a fresh substrate token),
    # so it must never be preferred for the refresh flow.
    return (
        shutil.which("chromium")
        or shutil.which("chromium-browser")
        or shutil.which("microsoft-edge")
        or shutil.which("microsoft-edge-stable")
        or "chromium"
    )


async def _close_chromium_gracefully(cdp_port: int, proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        import httpx
        import websockets
        async with httpx.AsyncClient(timeout=2) as client:
            info = (await client.get(f"http://localhost:{cdp_port}/json/version")).json()
        ws_url = info.get("webSocketDebuggerUrl")
        if ws_url:
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
        await asyncio.to_thread(proc.wait, timeout=10)
    except Exception:
        try:
            proc.terminate()
            await asyncio.to_thread(proc.wait, timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _cleanup_profile_locks(profile_dir: Path) -> None:
    """Stop stale Chromium processes for this profile and remove Singleton locks."""
    profile = str(profile_dir.resolve())
    profile_arg = str(profile_dir)
    if platform.system() != "Windows":
        proc_root = Path("/proc")
        if proc_root.exists():
            for entry in proc_root.iterdir():
                if not entry.name.isdigit() or int(entry.name) == os.getpid():
                    continue
                try:
                    raw = (entry / "cmdline").read_bytes().decode("utf-8", "ignore")
                except Exception:
                    continue
                if "--user-data-dir=" in raw and (profile in raw or profile_arg in raw):
                    pid = int(entry.name)
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except Exception:
                        pass
            time.sleep(0.3)
            for entry in proc_root.iterdir():
                if not entry.name.isdigit() or int(entry.name) == os.getpid():
                    continue
                try:
                    raw = (entry / "cmdline").read_bytes().decode("utf-8", "ignore")
                except Exception:
                    continue
                if "--user-data-dir=" in raw and (profile in raw or profile_arg in raw):
                    try:
                        os.kill(int(entry.name), signal.SIGKILL)
                    except Exception:
                        pass
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (profile_dir / name).unlink(missing_ok=True)
        except Exception:
            pass
