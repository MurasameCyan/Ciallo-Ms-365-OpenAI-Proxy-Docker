"""Atomic small-file writes: temp file + rename.

A plain ``write_text`` truncates the target first, so a crash, a kill, or a full
disk mid-write leaves the file empty or half-written -- and every reader here
treats an unparseable/empty file as "not set", i.e. a torn write silently reverts
a setting, a token, or a secret. ``rename`` is atomic on both POSIX and Windows
(``Path.replace``), so a reader sees either the whole old value or the whole new
one.

The JSON stores that hold credentials (key_store, account_store) write through
here; session_store, call_log_store and metrics_store still open-code the same
pattern and can converge if they are ever touched again.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path


def _fsync_dir(directory: Path) -> None:
    """Flush the rename itself, so a crash cannot resurrect the old directory entry.

    Best effort, unlike the file's own fsync: Windows cannot open a directory and
    some filesystems refuse to fsync one, and by this point the new value is
    already visible -- raising would tell the caller a save failed that did not.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_text_atomic(
    path: Path, text: str, *, mode: int | None = None, durable: bool = False
) -> None:
    """Replace ``path`` with ``text`` atomically, creating parents as needed.

    ``mode`` is applied to the temp file *before* the rename, so a secret is
    never briefly readable under the default umask.

    The temp name carries a random suffix because two writers of the same file
    (an admin save racing a userscript push) would otherwise share one temp path
    and the loser's rename would hit a file the winner already moved.

    ``durable`` adds the fsync pair -- the bytes before the rename, the directory
    after -- for files whose loss cannot be recovered: a refresh token nobody can
    re-issue, an API key a client is already configured with. It is off by default
    because the hot writer here (usage stats, one write per API call) would pay a
    real disk flush per request for numbers that only feed a dashboard. A failing
    fsync of the temp file propagates: the rename has not happened yet, so the
    old value is still whole and "saved" would be a lie.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            if durable:
                handle.flush()
                os.fsync(handle.fileno())
        if mode is not None:
            try:
                tmp.chmod(mode)
            except OSError:
                pass
        tmp.replace(path)
        if durable:
            _fsync_dir(path.parent)
    finally:
        tmp.unlink(missing_ok=True)
