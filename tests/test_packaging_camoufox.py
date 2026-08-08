"""Packaging invariants for the optional Camoufox browser.

Camoufox ships as a `uv` extra, and two places can silently undo that: a `uv run`
that re-syncs without the extra strips it back out, and a Dockerfile that never
passes the build arg never installs it. Neither failure shows up in a unit test
of the gate itself -- the import just starts failing in the built image -- so
they are pinned here.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_camoufox_is_an_optional_extra_not_a_hard_dependency():
    """An M365-only deployment must not pay ~936 MB for a consumer feature."""
    extras = PYPROJECT["project"]["optional-dependencies"]
    assert any("camoufox" in dep for dep in extras["camoufox"])
    assert not any("camoufox" in dep for dep in PYPROJECT["project"]["dependencies"])


def test_entrypoint_does_not_resync_the_venv_at_startup():
    """`uv run` reconciles against the lock without extras, which would uninstall
    camoufox on every container start of the -camoufox image."""
    assert "uv run --no-sync copilot-openai-proxy serve" in ENTRYPOINT


def test_dockerfile_installs_the_extra_only_when_asked():
    assert "ARG WITH_CAMOUFOX=false" in DOCKERFILE
    assert "uv sync --frozen --no-dev --extra camoufox" in DOCKERFILE
    # And the plain path is still there for the default image.
    assert "uv sync --frozen --no-dev;" in DOCKERFILE


def test_dockerfile_fetches_the_browser_at_build_time():
    """Otherwise the first refresh pays a ~936 MB download inside a request."""
    assert "python -m camoufox fetch" in DOCKERFILE


def test_dockerfile_installs_xvfb_for_the_virtual_display():
    """The gate defaults to headless="virtual" on Linux; that needs xvfb."""
    assert "xvfb" in DOCKERFILE
