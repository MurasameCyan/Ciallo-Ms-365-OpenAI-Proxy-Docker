"""Windows profile-lock cleanup must kill by --user-data-dir, never by image name.

The POSIX branch of `_cleanup_profile_locks` scans /proc and terminates only the
processes whose cmdline carries the target `--user-data-dir`. Windows had no such
branch at all: it deleted Singleton files and left stale browsers holding the
profile, so the next gate run failed to bind its CDP port.

The load-bearing safety property of the Windows branch is that it is *narrow*.
One browser launch spawns a dozen helpers that share a --user-data-dir, while an
unrelated Edge -- the operator's own browsing session, with its logins and tabs
-- carries a different one and must survive untouched.
"""

from __future__ import annotations

from pathlib import Path

import m365_copilot_openai_proxy.refresh_chromium as rc


MINE = r"C:\work\.probe\consumer_profile"
THEIRS = r"C:\Users\Me\AppData\Local\Microsoft\Edge\User Data"


def _fake_cim(rows: list[tuple[int, str]]):
    """Return a subprocess.run stand-in that answers the CIM query with `rows`."""

    def run(command, *args, **kwargs):
        class Completed:
            stdout = "\n".join(f"{pid}|{cmd}" for pid, cmd in rows)

        if command and command[0] == "powershell":
            return Completed()
        return Completed()

    return run


def _capture(monkeypatch, rows: list[tuple[int, str]]) -> list[list[str]]:
    """Record every taskkill invocation while the CIM query returns `rows`."""
    calls: list[list[str]] = []
    cim = _fake_cim(rows)

    def run(command, *args, **kwargs):
        if command and command[0] == "taskkill":
            calls.append(list(command))

            class Completed:
                stdout = ""

            return Completed()
        return cim(command, *args, **kwargs)

    monkeypatch.setattr(rc.platform, "system", lambda: "Windows")
    monkeypatch.setattr(rc.subprocess, "run", run)
    monkeypatch.setattr(rc.time, "sleep", lambda _seconds: None)
    return calls


def test_windows_cleanup_spares_an_unrelated_edge(monkeypatch, tmp_path):
    # The operator's own Edge shares the image name but not the profile. Killing
    # it would close their tabs, so image-name matching is never acceptable.
    profile = tmp_path / "consumer_profile"
    profile.mkdir()
    rows = [
        (100, f'"msedge.exe" --user-data-dir={profile} --no-first-run'),
        (200, f'"msedge.exe" --user-data-dir={THEIRS} --restore-last-session'),
        (300, f'"msedge.exe" --user-data-dir={THEIRS} --type=renderer'),
    ]
    calls = _capture(monkeypatch, rows)
    rc._cleanup_profile_locks(profile)

    killed = {call[2] for call in calls}
    assert killed == {"100"}, f"only the matching profile may be killed, got {killed}"


def test_windows_cleanup_kills_every_helper_of_the_target_profile(monkeypatch, tmp_path):
    # A single launch spawns browser + renderer + GPU + utility processes, all
    # sharing the profile. Any survivor keeps the Singleton lock alive.
    profile = tmp_path / "consumer_profile"
    profile.mkdir()
    rows = [
        (11, f'"msedge.exe" --user-data-dir={profile}'),
        (12, f'"msedge.exe" --user-data-dir={profile} --type=renderer'),
        (13, f'"msedge.exe" --user-data-dir={profile} --type=gpu-process'),
    ]
    calls = _capture(monkeypatch, rows)
    rc._cleanup_profile_locks(profile)

    assert {call[2] for call in calls} == {"11", "12", "13"}


def test_windows_cleanup_escalates_to_force_after_a_grace_period(monkeypatch, tmp_path):
    # Mirrors the POSIX SIGTERM-then-SIGKILL shape: a polite pass first, then /F
    # for whatever still holds the profile.
    profile = tmp_path / "consumer_profile"
    profile.mkdir()
    calls = _capture(monkeypatch, [(42, f'"msedge.exe" --user-data-dir={profile}')])
    rc._cleanup_profile_locks(profile)

    assert calls[0] == ["taskkill", "/PID", "42"], "first pass must be graceful"
    assert calls[-1] == ["taskkill", "/PID", "42", "/F"], "stragglers must be forced"


def test_windows_cleanup_still_removes_singleton_locks(monkeypatch, tmp_path):
    # Lock-file removal is the behaviour Windows already had; it must not regress.
    profile = tmp_path / "consumer_profile"
    profile.mkdir()
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        (profile / name).write_text("stale", encoding="utf-8")
    _capture(monkeypatch, [])
    rc._cleanup_profile_locks(profile)

    assert not list(profile.iterdir()), "stale Singleton files must be gone"


def test_windows_cleanup_survives_a_failing_cim_query(monkeypatch, tmp_path):
    # PowerShell may be absent or blocked. Cleanup must degrade to lock removal
    # rather than raise into the gate's launch path.
    profile = tmp_path / "consumer_profile"
    profile.mkdir()
    (profile / "SingletonLock").write_text("stale", encoding="utf-8")

    def boom(command, *args, **kwargs):
        raise OSError("powershell is not available")

    monkeypatch.setattr(rc.platform, "system", lambda: "Windows")
    monkeypatch.setattr(rc.subprocess, "run", boom)
    rc._cleanup_profile_locks(profile)

    assert not (profile / "SingletonLock").exists()


def test_posix_branch_is_untouched_by_the_windows_addition(monkeypatch, tmp_path):
    # Guard against the Windows branch swallowing the /proc path: on Linux the
    # cleanup must not shell out to taskkill.
    profile = tmp_path / "consumer_profile"
    profile.mkdir()
    calls: list[list[str]] = []

    def run(command, *args, **kwargs):
        calls.append(list(command))

        class Completed:
            stdout = ""

        return Completed()

    monkeypatch.setattr(rc.platform, "system", lambda: "Linux")
    monkeypatch.setattr(rc.subprocess, "run", run)
    monkeypatch.setattr(rc, "Path", Path)
    rc._cleanup_profile_locks(profile)

    assert not any(call and call[0] == "taskkill" for call in calls)
