"""Packaging invariants for the optional Camoufox browser.

Camoufox ships as a `uv` extra, and two places can silently undo that: a `uv run`
that re-syncs without the extra strips it back out, and a Dockerfile that never
passes the build arg never installs it. Neither failure shows up in a unit test
of the gate itself -- the import just starts failing in the built image -- so
they are pinned here.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
COMPOSE_TEXT = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def _uncomment_optional_blocks(text: str) -> str:
    """Enable the commented-out network lines the way a reader would.

    Only structural lines are touched; the prose explaining them stays comments.
    """
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if re.match(r"^#\s*(networks:|- ai-internal|ai-internal:|external:)", stripped):
            out.append(indent + re.sub(r"^#\s?", "", stripped))
        else:
            out.append(line)
    return "\n".join(out)


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


def test_dockerfile_asserts_the_browser_landed_where_the_app_user_looks():
    """The cache dir comes from $HOME, which BuildKit and gosu each derive
    separately. They agree today; if that ever breaks, fail the build rather than
    re-download during the first refresh."""
    assert "test -d /home/app/.cache/camoufox/browsers" in DOCKERFILE


# ------------------------------------------------------------------ docker-compose

def test_compose_ships_the_lean_image_and_a_durable_token_mount():
    """The -camoufox image is opt-in, and the token mount cannot be tmpfs: it
    holds the Microsoft account session the unattended refresh renews from."""
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load(COMPOSE_TEXT)
    service = compose["services"]["ciallo-proxy-multi"]
    assert service["image"].endswith(":multi")
    assert "token-data:/home/app/token" in service["volumes"]
    assert "token-data" in compose["volumes"]


def test_compose_optional_network_is_commented_out_by_default():
    """Enabled by default it would break every deployment lacking the external
    network, since compose refuses to start rather than creating one."""
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load(COMPOSE_TEXT)
    assert "networks" not in compose
    assert "networks" not in compose["services"]["ciallo-proxy-multi"]


def test_compose_optional_network_parses_once_uncommented():
    """A commented block is never parsed, so a typo in one survives until someone
    follows the instructions. This checks the indentation actually works."""
    yaml = pytest.importorskip("yaml")
    enabled = yaml.safe_load(_uncomment_optional_blocks(COMPOSE_TEXT))
    assert enabled["services"]["ciallo-proxy-multi"]["networks"] == ["ai-internal"]
    assert enabled["networks"] == {"ai-internal": {"external": True}}


def test_compose_documents_what_the_optional_blocks_are_for():
    """Commented config with no stated purpose is config nobody dares enable."""
    assert "docker network create ai-internal" in COMPOSE_TEXT
    assert "multi-camoufox" in COMPOSE_TEXT
