from __future__ import annotations

from pathlib import Path


DOCKERFILE = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")


def test_dockerfile_installs_headless_shell_before_full_chromium_fallback():
    assert "chromium-headless-shell" in DOCKERFILE
    assert DOCKERFILE.index("chromium-headless-shell") < DOCKERFILE.index("chromium \\")
