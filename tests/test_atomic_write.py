from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from m365_copilot_openai_proxy.atomic_write import write_text_atomic
from m365_copilot_openai_proxy import token_store


def test_writes_value_creating_parents_and_leaves_no_temp(tmp_path):
    target = tmp_path / "profiles" / "acc-1" / "token"
    write_text_atomic(target, "tok-1")

    assert target.read_text(encoding="utf-8") == "tok-1"
    assert [p.name for p in target.parent.iterdir()] == ["token"]


def test_overwrite_replaces_value_and_leaves_no_temp(tmp_path):
    target = tmp_path / "tone"
    write_text_atomic(target, "Magic")
    write_text_atomic(target, "Reasoning")

    assert target.read_text(encoding="utf-8") == "Reasoning"
    assert [p.name for p in tmp_path.iterdir()] == ["tone"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not modelled on Windows")
def test_mode_applies_to_the_final_file(tmp_path):
    target = tmp_path / "token"
    write_text_atomic(target, "tok-1", mode=0o600)

    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_failed_write_keeps_the_old_value_and_cleans_up(tmp_path, monkeypatch):
    """The point of the temp file: a write that dies never truncates the target."""
    target = tmp_path / "token"
    write_text_atomic(target, "tok-old")

    def boom(self, _target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError):
        write_text_atomic(target, "tok-new")

    assert target.read_text(encoding="utf-8") == "tok-old"
    assert [p.name for p in tmp_path.iterdir()] == ["token"]


def test_profile_writers_go_through_the_atomic_path(tmp_path, monkeypatch):
    # setattr rather than init_token_dir(): the module globals are process-wide, and
    # a later test reading a profile must not land in this deleted tmp dir.
    monkeypatch.setattr(token_store, "_TOKEN_DIR", tmp_path)
    monkeypatch.setattr(token_store, "_TOKEN_FILE", tmp_path / "token")
    token_store.write_tone("Magic")

    assert token_store.read_tone() == "Magic"
    assert [p.name for p in tmp_path.iterdir()] == ["tone"]
