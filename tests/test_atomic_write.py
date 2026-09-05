from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from m365_copilot_openai_proxy.account_store import AccountStore
from m365_copilot_openai_proxy.atomic_write import write_text_atomic
from m365_copilot_openai_proxy.key_store import KeyStore
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


# ---- durability: the credential files a power cut must not roll back ---------

def _fsync_spy(monkeypatch) -> list[str]:
    """Record fsync/rename order, keeping the real calls."""
    events: list[str] = []
    real_fsync, real_replace = os.fsync, Path.replace

    def spy_fsync(fd):
        kind = "dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
        events.append("fsync-" + kind)
        return real_fsync(fd)

    def spy_replace(self, target):
        events.append("rename")
        return real_replace(self, target)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(Path, "replace", spy_replace)
    return events


def test_durable_write_flushes_the_bytes_before_the_rename(tmp_path, monkeypatch):
    """Renaming a file whose bytes are still in page cache is how a crash yields
    an empty-but-committed accounts.json: the fsync has to come first."""
    events = _fsync_spy(monkeypatch)
    target = tmp_path / "accounts.json"
    write_text_atomic(target, '{"a": 1}', durable=True)

    assert events[:2] == ["fsync-file", "rename"], events
    assert target.read_text(encoding="utf-8") == '{"a": 1}'


@pytest.mark.skipif(os.name == "nt", reason="Windows cannot open a directory to fsync it")
def test_durable_write_flushes_the_directory_entry_after_the_rename(tmp_path, monkeypatch):
    events = _fsync_spy(monkeypatch)
    write_text_atomic(tmp_path / "accounts.json", "{}", durable=True)

    assert events == ["fsync-file", "rename", "fsync-dir"], events


def test_the_default_write_pays_nothing_for_durability(tmp_path, monkeypatch):
    """usage_store writes once per API call; it must not fsync per request."""
    events = _fsync_spy(monkeypatch)
    write_text_atomic(tmp_path / "usage.json", "{}")

    assert events == ["rename"], events


def test_credential_stores_persist_durably(tmp_path, monkeypatch):
    events = _fsync_spy(monkeypatch)
    accounts = tmp_path / "accounts.json"
    keys = tmp_path / "keys.json"
    AccountStore(persist_path=accounts).add(name="acc", token="tok")
    KeyStore(persist_path=keys).add(name="k")

    assert events.count("fsync-file") == 2, events
    assert json.loads(accounts.read_text(encoding="utf-8"))
    assert json.loads(keys.read_text(encoding="utf-8"))
    assert [p.name for p in tmp_path.glob("*.tmp")] == []
