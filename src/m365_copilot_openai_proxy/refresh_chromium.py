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
from .runtime_flags import ulog

_LOGGED_CHROMIUM_PATH: str | None = None


def _chromium_path() -> str:
    """Locate a Chromium/Edge binary and log the resolved path once per change."""
    resolved = _resolve_chromium_path()
    global _LOGGED_CHROMIUM_PATH
    if resolved != _LOGGED_CHROMIUM_PATH:
        _LOGGED_CHROMIUM_PATH = resolved
        ulog(f"Chromium binary resolved to: {resolved}")
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


def chromium_proxy_args() -> list[str]:
    """Chromium proxy flags for the configured proxy, or [] when unset.

    Read from the environment rather than app.state so the CLI and the refresh
    paths behave identically; runtime_settings.apply_proxy_env() is what puts it
    there. The bypass list must keep the CDP host direct -- routing Chromium's
    own loopback traffic through a proxy breaks the debugging channel.
    """
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
    if not proxy:
        return []
    # socks5h/socks4a are a curl/Python convention for "resolve DNS at the
    # proxy". Chromium does not parse them and would reject the flag outright,
    # so map them onto the schemes it knows -- its socks5:// already resolves
    # remotely, making socks5h equivalent rather than a downgrade.
    scheme, sep, rest = proxy.partition("://")
    chromium_scheme = {"socks5h": "socks5", "socks4a": "socks4"}.get(scheme.lower())
    if sep and chromium_scheme:
        proxy = f"{chromium_scheme}://{rest}"
    return [
        f"--proxy-server={proxy}",
        "--proxy-bypass-list=localhost;127.0.0.1;[::1]",
    ]


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


def _windows_profile_pids(profile: str, profile_arg: str) -> list[int]:
    """PIDs of Chromium processes launched with this exact --user-data-dir.

    Windows has no /proc, so command lines come from CIM. Matching is on the
    profile path and never on the image name alone: one browser launch spawns a
    dozen helper processes that all carry the same --user-data-dir, while an
    unrelated Edge (the user's own browsing session) carries a different one and
    must never be touched.
    """
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -like '*--user-data-dir=*' } | "
        "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        return []
    pids: list[int] = []
    for line in completed.stdout.splitlines():
        pid_text, _, command = line.partition("|")
        if not command or not pid_text.strip().isdigit():
            continue
        if profile not in command and profile_arg not in command:
            continue
        pid = int(pid_text.strip())
        if pid != os.getpid():
            pids.append(pid)
    return pids


def _windows_kill(pid: int, force: bool) -> None:
    command = ["taskkill", "/PID", str(pid)]
    if force:
        command.append("/F")
    try:
        subprocess.run(command, capture_output=True, timeout=10)
    except Exception:
        pass


def _cleanup_profile_locks(profile_dir: Path) -> None:
    """Stop stale Chromium processes for this profile and remove Singleton locks."""
    profile = str(profile_dir.resolve())
    profile_arg = str(profile_dir)
    if platform.system() == "Windows":
        # Same two-step as the POSIX branch: ask politely, then force whatever
        # is still holding the profile.
        pids = _windows_profile_pids(profile, profile_arg)
        for pid in pids:
            _windows_kill(pid, force=False)
        if pids:
            time.sleep(0.3)
            for pid in _windows_profile_pids(profile, profile_arg):
                _windows_kill(pid, force=True)
    else:
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
