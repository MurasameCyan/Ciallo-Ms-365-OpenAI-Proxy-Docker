from __future__ import annotations

from m365_copilot_openai_proxy.build_info import (
    check_for_update,
    current_build_id,
    inject_build_info,
    resolve_build_info,
    short_sha,
)
from m365_copilot_openai_proxy.templates import _ADMIN_HTML


def test_admin_shell_has_gra_style_update_ui():
    assert "side-update-bar" in _ADMIN_HTML
    assert "side-build-chip" in _ADMIN_HTML
    assert "side-update-btn" in _ADMIN_HTML
    assert "side-repo-btn" in _ADMIN_HTML
    assert "__APP_GIT_HASH__" in _ADMIN_HTML
    assert "__APP_GIT_REPO__" in _ADMIN_HTML
    assert "checkAdminUpdate" in _ADMIN_HTML


def test_inject_build_info_replaces_placeholders(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "abcdef1234567890")
    resolve_build_info.cache_clear()
    current_build_id.cache_clear()
    try:
        html = inject_build_info(
            '<span class="side-build-chip">__APP_GIT_HASH__</span>'
            '<a href="__APP_GIT_REPO__" title="__APP_GIT_FULL__">r</a>'
            '<a href="__APP_GIT_URL__">c</a>'
        )
    finally:
        resolve_build_info.cache_clear()
        current_build_id.cache_clear()

    assert "__APP_GIT_HASH__" not in html
    assert "__APP_GIT_URL__" not in html
    assert "__APP_GIT_REPO__" not in html
    assert "abcdef1" in html
    assert "abcdef1234567890" in html
    assert "github.com" in html


def test_resolve_build_info_uses_env_short_hash(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "deadbeefcafebabe")
    resolve_build_info.cache_clear()
    current_build_id.cache_clear()
    try:
        info = resolve_build_info()
        bid = current_build_id()
    finally:
        resolve_build_info.cache_clear()
        current_build_id.cache_clear()
    assert info["hash"] == "deadbee"
    assert bid == "deadbee"
    assert "deadbeefcafebabe" in info["commit_url"] or info["commit_url"].endswith("/commit/deadbeefcafebabe")


def test_short_sha_normalizes():
    assert short_sha("ABCDEF123456") == "abcdef1"
    assert short_sha("n/a") == ""
    assert short_sha("") == ""


def test_collapsed_css_hides_update_bar():
    from m365_copilot_openai_proxy.template_admin_css import _ADMIN_CSS

    assert 'body[data-collapsed="1"] .side-update-bar{display:none!important}' in _ADMIN_CSS


def test_dockerfile_and_ci_bake_git_commit():
    from pathlib import Path

    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/docker.yml").read_text(encoding="utf-8")
    assert "ARG GIT_COMMIT" in dockerfile
    assert "/app/GIT_COMMIT" in dockerfile
    assert "GIT_COMMIT=${{ github.sha }}" in workflow
    assert "build-args:" in workflow


def test_check_for_update_compares_short_sha(monkeypatch):
    import asyncio

    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "sha": "deadbeefaaaaaaaa",
                "html_url": "https://github.com/MurasameCyan/Ciallo-Ms-365-OpenAI-Proxy-Docker/commit/deadbeefaaaaaaaa",
                "commit": {"committer": {"date": "2026-07-20T00:00:00Z"}},
            }

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return FakeResp()

    monkeypatch.setenv("GIT_COMMIT", "cafebabeeeeeeeee")
    resolve_build_info.cache_clear()
    current_build_id.cache_clear()
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    try:
        result = asyncio.run(check_for_update())
    finally:
        resolve_build_info.cache_clear()
        current_build_id.cache_clear()
    assert result["current"] == "cafebab"
    assert result["latest"] == "deadbee"
    assert result["hasUpdate"] is True
    assert result["error"] is None
