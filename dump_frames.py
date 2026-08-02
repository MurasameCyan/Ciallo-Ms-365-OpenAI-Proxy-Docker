"""Dump every SignalR frame of one M365 Copilot turn, to hunt for a server-side
mode enumeration.

Diagnostic sibling of ``scan_tones.py``: that one asks "does this tone work?" one
guess at a time, this one asks "does the backend ever tell us the list?". It
reuses the production client, so the outbound payload and the frames are exactly
what the proxy sees -- only the frames are archived instead of thrown away.

    $env:PYTHONPATH = "<repo>\\src"
    $env:M365_ACCESS_TOKEN = "<substrate access token>"
    python dump_frames.py [tone] [prompt]

Writes one JSON object per line to ``$env:TEMP\\m365_frames.jsonl`` and prints
every distinct tone-shaped / model-shaped string it saw. One real Copilot
request per run (spends quota).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys

import m365_copilot_openai_proxy.substrate_client as sc
from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotClient

# Every non-ping frame passes through this hook on its way to the parser, so
# replacing it captures the whole stream without touching connection logic.
# ponytail: if that call site moves, this dumper goes quiet rather than wrong --
# the "frames: 0" line in the output is the tell.
_FRAMES: list[dict] = []
sc._capture_suspicious_response_event = lambda sink, msg: _FRAMES.append(msg)

# Tone/model-shaped strings worth surfacing out of ~MBs of frame JSON.
INTERESTING = re.compile(
    r"\b(?:Gpt_5_\d+_\w+|Claude_[A-Z]\w*|conversationTone|respondingEndpoint|"
    r"switchRespondingEndpoint|modelId|gptId|availableTones|supportedTones|tone)\b",
    re.IGNORECASE,
)

OUT_PATH = os.path.join(os.environ.get("TEMP", "."), "m365_frames.jsonl")


async def main() -> int:
    token = os.environ.get("M365_ACCESS_TOKEN", "")
    if not token:
        print("no token: set $M365_ACCESS_TOKEN")
        return 1
    tone = sys.argv[1] if len(sys.argv) > 1 else "Magic"
    prompt = sys.argv[2] if len(sys.argv) > 2 else "Reply with the single word: ok"

    client = SubstrateCopilotClient(token, time_zone="Asia/Shanghai", tone=tone)
    try:
        answer = (await client.chat(prompt, [])).strip()
    except Exception as exc:  # noqa: BLE001 - a failed turn still leaves frames worth reading
        answer = f"<{type(exc).__name__}: {exc}>"

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        for frame in _FRAMES:
            fh.write(json.dumps(frame, ensure_ascii=False) + "\n")

    print(f"tone={tone} frames={len(_FRAMES)} answer={answer[:120]!r}")
    print(f"dump: {OUT_PATH}")

    blob = json.dumps(_FRAMES, ensure_ascii=False)
    hits = sorted(set(INTERESTING.findall(blob)))
    print(f"\ninteresting keys/values ({len(hits)}):")
    for hit in hits:
        print(f"  {hit}")

    # Top-level shape of each frame type, so a list-bearing field that my regex
    # does not know about is still visible.
    shapes: dict[str, set[str]] = {}
    for frame in _FRAMES:
        key = f"type={frame.get('type')} target={frame.get('target')}"
        keys = shapes.setdefault(key, set())
        for arg in frame.get("arguments") or []:
            if isinstance(arg, dict):
                keys.update(arg.keys())
        if isinstance(frame.get("item"), dict):
            keys.update(f"item.{k}" for k in frame["item"])
        if isinstance(frame.get("result"), dict):
            keys.update(f"result.{k}" for k in frame["result"])
    print("\nframe shapes:")
    for key, keys in shapes.items():
        print(f"  {key}: {', '.join(sorted(keys))}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
