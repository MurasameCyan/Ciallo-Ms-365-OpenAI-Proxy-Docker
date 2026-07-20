from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

# Public GitHub repo for the multi branch image / source.
_DEFAULT_REPO_URL = "https://github.com/MurasameCyan/Ciallo-Ms-365-OpenAI-Proxy-Docker"


def _normalize_hash(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    # Accept full SHA or short; strip noise from CI env values.
    text = text.split()[0]
    if text.lower() in {"unknown", "null", "none", "n/a"}:
        return ""
    return text


def _short_hash(value: str) -> str:
    h = _normalize_hash(value)
    return h[:7] if h else ""


def _repo_url() -> str:
    return (os.environ.get("GITHUB_REPO_URL") or _DEFAULT_REPO_URL).rstrip("/")


def _hash_from_env() -> str:
    for key in ("GIT_COMMIT", "SOURCE_COMMIT", "COMMIT_SHA", "GITHUB_SHA"):
        h = _normalize_hash(os.environ.get(key, ""))
        if h:
            return h
    return ""


def _hash_from_file() -> str:
    # Optional bake-in for Docker images without a .git directory.
    candidates = [
        Path(__file__).resolve().parent / "GIT_COMMIT",
        Path("/app/GIT_COMMIT"),
        Path("/home/app/GIT_COMMIT"),
    ]
    for path in candidates:
        try:
            h = _normalize_hash(path.read_text(encoding="utf-8"))
            if h:
                return h
        except (OSError, UnicodeError):
            continue
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
    return _normalize_hash(proc.stdout)


@lru_cache(maxsize=1)
def resolve_build_info() -> dict[str, str]:
    """Return display hash + GitHub links for the admin sidebar badge.

    Resolution order: env → baked file → live ``git rev-parse`` (dev).
    """
    full = _hash_from_env() or _hash_from_file() or _hash_from_git()
    short = _short_hash(full) or "n/a"
    repo = _repo_url()
    if full:
        commit_url = f"{repo}/commit/{full}"
    else:
        commit_url = f"{repo}/tree/multi"
    return {
        "hash": short,
        "full": full or "",
        "repo_url": repo,
        "commit_url": commit_url,
    }


def inject_build_info(html: str) -> str:
    """Replace admin HTML placeholders with resolved build metadata."""
    info = resolve_build_info()
    return (
        html.replace("__APP_GIT_HASH__", info["hash"])
        .replace("__APP_GIT_URL__", info["commit_url"])
        .replace("__APP_GIT_FULL__", info["full"] or info["hash"])
    )
