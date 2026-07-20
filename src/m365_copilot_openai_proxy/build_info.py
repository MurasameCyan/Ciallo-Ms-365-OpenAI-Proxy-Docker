"""Local build id + optional GitHub update check.

Pattern aligned with GrokRegisterAgent (beta) ``updateCheck.ts``:
- Display BUILD_ID as git short SHA
- Resolve: env → baked file → ``git rev-parse`` (dev)
- Update check only on user click; compare short SHA against branch HEAD
"""

from __future__ import annotations

import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

# Public GitHub repo; multi branch is this project's deploy line (GRA uses beta).
_DEFAULT_REPO = "MurasameCyan/Ciallo-Ms-365-OpenAI-Proxy-Docker"
_DEFAULT_REF = "multi"
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def _repo_slug() -> str:
    raw = (os.environ.get("GITHUB_REPO") or _DEFAULT_REPO).strip()
    if raw.startswith("https://github.com/"):
        raw = raw.removeprefix("https://github.com/").rstrip("/")
    return raw or _DEFAULT_REPO


def _track_ref() -> str:
    return (os.environ.get("GITHUB_TRACK_REF") or _DEFAULT_REF).strip() or _DEFAULT_REF


def _repo_url() -> str:
    return f"https://github.com/{_repo_slug()}"


def short_sha(raw: str) -> str:
    text = (raw or "").strip().split()[0] if (raw or "").strip() else ""
    if not text:
        return ""
    if text.lower() in {"unknown", "null", "none", "n/a"}:
        return ""
    if _SHA_RE.match(text):
        return text[:7].lower()
    return text[:32]


def _read_build_file(path: Path) -> str:
    try:
        line = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, UnicodeError, IndexError):
        return ""
    return short_sha(line)


def _hash_from_env() -> str:
    for key in (
        "REGISTER_BUILD",
        "GIT_COMMIT",
        "GIT_SHA",
        "SOURCE_COMMIT",
        "COMMIT_SHA",
        "GITHUB_SHA",
        "BUILD_ID",
    ):
        h = short_sha(os.environ.get(key, ""))
        if h:
            return h
    return ""


def _hash_from_file() -> str:
    candidates = [
        Path(__file__).resolve().parent / "GIT_COMMIT",
        Path(__file__).resolve().parent / "BUILD_ID",
        Path("/app/GIT_COMMIT"),
        Path("/app/BUILD_ID"),
        Path("/home/app/GIT_COMMIT"),
        Path("/home/app/BUILD_ID"),
    ]
    for path in candidates:
        h = _read_build_file(path)
        if h:
            return h
    return ""


def _hash_from_git() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return short_sha(proc.stdout)


@lru_cache(maxsize=1)
def current_build_id() -> str:
    """Resolve current runtime BUILD_ID (short hash preferred)."""
    return _hash_from_env() or _hash_from_file() or _hash_from_git() or "unknown"


@lru_cache(maxsize=1)
def resolve_build_info() -> dict[str, str]:
    """Return display fields for the admin sidebar."""
    full_env = _hash_from_env() or _hash_from_file() or _hash_from_git()
    # Prefer full SHA when env/file held a long hex; short_sha already applied in helpers.
    # Keep a longer value for titles when available from env raw.
    raw_full = ""
    for key in ("GIT_COMMIT", "SOURCE_COMMIT", "COMMIT_SHA", "GITHUB_SHA", "REGISTER_BUILD"):
        v = (os.environ.get(key) or "").strip().split()[0] if os.environ.get(key) else ""
        if _SHA_RE.match(v):
            raw_full = v
            break
    build = current_build_id()
    short = short_sha(build) or build
    repo = _repo_url()
    ref = _track_ref()
    if raw_full:
        commit_url = f"{repo}/commit/{raw_full}"
        full = raw_full
    elif full_env and _SHA_RE.match(full_env):
        # may already be short
        commit_url = f"{repo}/commit/{full_env}"
        full = full_env
    else:
        commit_url = f"{repo}/commits/{ref}"
        full = short if short != "unknown" else ""
    return {
        "hash": short if short != "unknown" else "n/a",
        "full": full,
        "build_id": short,
        "repo_url": repo,
        "commit_url": commit_url,
        "track_ref": ref,
    }


def inject_build_info(html: str) -> str:
    """Replace admin HTML placeholders with resolved build metadata."""
    info = resolve_build_info()
    return (
        html.replace("__APP_GIT_HASH__", info["hash"])
        .replace("__APP_GIT_URL__", info["commit_url"])
        .replace("__APP_GIT_FULL__", info["full"] or info["hash"])
        .replace("__APP_GIT_REPO__", info["repo_url"])
    )


async def check_for_update() -> dict:
    """Compare local BUILD_ID to GitHub track-ref HEAD (user-triggered only)."""
    import httpx

    info = resolve_build_info()
    current = info["build_id"] if info["build_id"] != "n/a" else current_build_id()
    repo = _repo_slug()
    ref = _track_ref()
    base = {
        "current": current,
        "latest": None,
        "hasUpdate": False,
        "htmlUrl": f"https://github.com/{repo}/commits/{ref}",
        "publishedAt": None,
        "buildId": current,
        "error": None,
    }
    url = f"https://api.github.com/repos/{repo}/commits/{ref}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "ciallo-ms365-openai-proxy",
                },
            )
    except Exception as exc:  # noqa: BLE001 — surface to UI
        return {**base, "error": str(exc)}

    if resp.status_code == 404:
        return {**base, "error": f"分支 {ref} 不可用"}
    if resp.status_code >= 400:
        return {**base, "error": f"GitHub 返回 HTTP {resp.status_code}"}

    try:
        data = resp.json()
    except ValueError:
        return {**base, "error": "GitHub 返回非 JSON"}

    latest_full = str(data.get("sha") or "").strip()
    latest = short_sha(latest_full) or None
    local_norm = short_sha(current)
    remote_norm = latest or ""
    both_hash = bool(_SHA_RE.match(local_norm) and _SHA_RE.match(remote_norm))
    has_update = (
        local_norm.lower() != remote_norm.lower()
        if both_hash
        else bool(latest and latest != current)
    )
    commit_meta = data.get("commit") or {}
    published = (
        ((commit_meta.get("committer") or {}).get("date"))
        or ((commit_meta.get("author") or {}).get("date"))
        or None
    )
    return {
        "current": current,
        "latest": latest,
        "hasUpdate": has_update,
        "htmlUrl": data.get("html_url") or base["htmlUrl"],
        "publishedAt": published,
        "buildId": current,
        "error": None,
    }
