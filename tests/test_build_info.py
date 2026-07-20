from __future__ import annotations

from m365_copilot_openai_proxy.build_info import inject_build_info, resolve_build_info
from m365_copilot_openai_proxy.templates import _ADMIN_HTML


def test_admin_shell_has_side_version_placeholders():
    assert 'class="side-version"' in _ADMIN_HTML
    assert "__APP_GIT_HASH__" in _ADMIN_HTML
    assert "__APP_GIT_URL__" in _ADMIN_HTML
    assert "side-gh-ico" in _ADMIN_HTML


def test_inject_build_info_replaces_placeholders(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "abcdef1234567890")
    resolve_build_info.cache_clear()
    try:
        html = inject_build_info(
            '<a class="side-version" href="__APP_GIT_URL__" title="GitHub __APP_GIT_FULL__">'
            '<span class="side-hash">__APP_GIT_HASH__</span></a>'
        )
    finally:
        resolve_build_info.cache_clear()

    assert "__APP_GIT_HASH__" not in html
    assert "__APP_GIT_URL__" not in html
    assert "abcdef1" in html
    assert "abcdef1234567890" in html
    assert "github.com" in html and "/commit/" in html


def test_resolve_build_info_uses_env_short_hash(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "deadbeefcafebabe")
    resolve_build_info.cache_clear()
    try:
        info = resolve_build_info()
    finally:
        resolve_build_info.cache_clear()
    assert info["hash"] == "deadbee"
    assert info["full"] == "deadbeefcafebabe"
    assert info["commit_url"].endswith("/commit/deadbeefcafebabe")


def test_collapsed_css_hides_side_version():
    from m365_copilot_openai_proxy.template_admin_css import _ADMIN_CSS

    assert 'body[data-collapsed="1"] .side-version{display:none!important}' in _ADMIN_CSS


def test_dockerfile_and_ci_bake_git_commit():
    from pathlib import Path

    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/docker.yml").read_text(encoding="utf-8")
    assert "ARG GIT_COMMIT" in dockerfile
    assert "/app/GIT_COMMIT" in dockerfile
    assert "GIT_COMMIT=${{ github.sha }}" in workflow
    assert "build-args:" in workflow
