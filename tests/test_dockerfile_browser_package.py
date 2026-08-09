from __future__ import annotations

from pathlib import Path


DOCKERFILE = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")


def test_dockerfile_installs_full_chromium_only():
    # The chromium-headless-shell package pulls a different Chromium build that
    # fails to bind the CDP debug port during the on-demand refresh flow
    # ("[Errno 99] Cannot assign requested address"). Match the known-good v8
    # setup: install full Chromium only.
    assert "chromium-headless-shell" not in DOCKERFILE
    assert "chromium \\" in DOCKERFILE
    assert "chromium-common" in DOCKERFILE


def test_dockerfile_installs_the_project_after_copying_its_source():
    # This project is an editable install, so the install step records a path
    # mapping to the package dir as it exists right then. Installing it before
    # COPY src/ writes no .pth at all, yet still installs the console script --
    # so the build passes and every container start dies with
    # ModuleNotFoundError: No module named 'm365_copilot_openai_proxy'.
    #
    # Order matters, not mere presence: the dependency sync must stay before
    # COPY src/ (that is what keeps it, and the ~936 MB camoufox fetch, cached
    # across source-only changes) while the project install must come after.
    lines = DOCKERFILE.splitlines()

    def line_of(predicate) -> int:
        hits = [i for i, line in enumerate(lines) if predicate(line)]
        assert len(hits) >= 1, "no matching line in Dockerfile"
        return hits[0]

    copy_src = line_of(lambda s: s.startswith("COPY") and "src/ src/" in s)
    deps_sync = line_of(lambda s: "uv sync" in s and "--no-install-project" in s)
    project_sync = line_of(lambda s: "uv sync" in s and "--no-install-project" not in s)

    assert deps_sync < copy_src, "dependency sync must precede COPY src/ to stay cached"
    assert copy_src < project_sync, "project install must follow COPY src/"


def test_dockerfile_proves_the_package_imports_at_build_time():
    # A venv missing the editable .pth still has a working console script, so
    # nothing about the broken state is visible until the container starts. Fail
    # the build instead.
    assert "import m365_copilot_openai_proxy" in DOCKERFILE


def test_dockerfile_pins_uv():
    # An unpinned uv is what turned the pre-existing install-before-COPY ordering
    # into a broken image: a newer uv stopped writing the editable .pth for a
    # project whose package dir is absent, and said nothing. The tool that
    # installs this project must not drift on its own.
    assert "pip install --no-cache-dir uv==" in DOCKERFILE


def test_dockerfile_keeps_both_syncs_on_the_same_extras():
    # The -camoufox image is defined by that extra. If only one of the two sync
    # steps carries it, the second reconciles the venv against the lock without
    # it and strips camoufox back out -- the same trap the entrypoint's
    # --no-sync comment already documents.
    syncs = [line for line in DOCKERFILE.splitlines() if "uv sync" in line]
    assert len(syncs) == 4, f"expected 4 sync lines (2 steps x 2 branches), got {len(syncs)}"
    assert sum("--extra camoufox" in line for line in syncs) == 2
