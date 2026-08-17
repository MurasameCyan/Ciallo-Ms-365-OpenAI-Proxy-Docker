"""Atomic small-file writes: temp file + rename.

A plain ``write_text`` truncates the target first, so a crash, a kill, or a full
disk mid-write leaves the file empty or half-written -- and every reader here
treats an unparseable/empty file as "not set", i.e. a torn write silently reverts
a setting, a token, or a secret. ``rename`` is atomic on both POSIX and Windows
(``Path.replace``), so a reader sees either the whole old value or the whole new
one.

The JSON stores (key_store, account_store, session_store, call_log_store,
metrics_store) each open-code this same pattern; this module is where the smaller
single-value files share it, and where those stores can converge if they are ever
touched again.
"""
from __future__ import annotations

import uuid
from pathlib import Path


def write_text_atomic(path: Path, text: str, *, mode: int | None = None) -> None:
    """Replace ``path`` with ``text`` atomically, creating parents as needed.

    ``mode`` is applied to the temp file *before* the rename, so a secret is
    never briefly readable under the default umask.

    The temp name carries a random suffix because two writers of the same file
    (an admin save racing a userscript push) would otherwise share one temp path
    and the loser's rename would hit a file the winner already moved.

    ponytail: no fsync, matching the JSON stores -- this buys atomicity (never a
    torn file), not durability. If a power cut must not lose the last write, fsync
    the temp file and its directory around the rename.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        if mode is not None:
            try:
                tmp.chmod(mode)
            except OSError:
                pass
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
