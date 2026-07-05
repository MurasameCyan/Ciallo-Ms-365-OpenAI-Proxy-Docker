from __future__ import annotations

import json
import re as _re
import uuid

_READ_ONLY_INTENT_RE = _re.compile(
    r"(只分析|仅分析|只读|不要修改|不要改|不要写|不要保存|不要创建|不要删除|不要执行|不要运行|不修改文件|不改文件|"
    r"analy[sz]e only|read[- ]only|do not modify|don't modify|no changes|do not write|don't write|do not save|don't save|do not run|don't run)",
    _re.IGNORECASE,
)
_READ_ONLY_TOOL_NAMES = {"read", "grep", "glob", "ls", "searchcodebase"}


def _has_read_only_intent(*parts: str) -> bool:
    return any(_READ_ONLY_INTENT_RE.search(part or "") for part in parts)


def _tool_call_name(tool_call: dict) -> str:
    try:
        return str(tool_call.get("function", {}).get("name", "")).strip()
    except AttributeError:
        return ""


def _filter_read_only_tool_calls(tool_calls: list[dict]) -> list[dict]:
    return [tc for tc in tool_calls if _tool_call_name(tc).lower() in _READ_ONLY_TOOL_NAMES]

# Primary: fenced ```tool_call blocks. Fallback: ```json blocks that look like a tool call.
# Note: closing/opening newlines are optional — the model often emits the closing ``` right
# after the JSON (e.g. `}}``` ) with no preceding newline, which would otherwise fail to match.
_TOOL_CALL_RE = _re.compile(
    r"```tool_call\s*(\{.*?\})\s*```",
    _re.DOTALL,
)
_JSON_BLOCK_RE = _re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    _re.DOTALL,
)


def _coerce_tool_call(obj: dict) -> dict | None:
    """Turn a parsed JSON object into an OpenAI tool_call dict if it looks like one."""
    if not isinstance(obj, dict):
        return None
    # Accept {"name": ..., "arguments": {...}} or common variants
    name = obj.get("name") or obj.get("tool") or obj.get("tool_name") or obj.get("function")
    if not name or not isinstance(name, str):
        return None
    arguments = obj.get("arguments")
    if arguments is None:
        arguments = obj.get("parameters")
    if arguments is None:
        # Treat remaining keys (minus name markers) as the arguments
        arguments = {k: v for k, v in obj.items()
                     if k not in ("name", "tool", "tool_name", "function")}
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments, ensure_ascii=False)
    elif not isinstance(arguments, str):
        arguments = str(arguments)
    return {
        "id": f"call_{uuid.uuid4().hex[:24]}",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _extract_tool_calls(text: str) -> list[dict]:
    """Parse tool_call JSON blocks from model text output into OpenAI tool_calls format.

    Tolerant to several formats the M365 Copilot model may emit:
    1. ```tool_call fenced blocks (preferred)
    2. ```json (or bare ```) fenced blocks whose JSON has a "name" key
    """
    calls = []
    matched_spans: list[tuple[int, int]] = []

    # 1. Preferred tool_call blocks
    for m in _TOOL_CALL_RE.finditer(text):
        try:
            obj = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        tc = _coerce_tool_call(obj)
        if tc:
            calls.append(tc)
            matched_spans.append(m.span())

    # 2. Fallback: json/plain fenced blocks that look like tool calls
    for m in _JSON_BLOCK_RE.finditer(text):
        # Skip if this span overlaps an already-matched tool_call block
        if any(s <= m.start() < e for s, e in matched_spans):
            continue
        try:
            obj = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        tc = _coerce_tool_call(obj)
        if tc:
            calls.append(tc)

    return calls


# Prose fallback: model writes "save as `<path>`" then a fenced code block,
# instead of emitting a tool_call. Synthesize a Write tool_call ONLY when the
# code block's language tag matches the target file's extension — this avoids
# mistaking a usage example (e.g. ```bash python foo.py```) for the file content.
_PROSE_PATH_RE = _re.compile(
    r"`([A-Za-z]:[\\/][^`\n]+?\.[A-Za-z0-9]{1,8}|/[^`\n]+?\.[A-Za-z0-9]{1,8})`"
)
# Capture the language tag (group 1) and the body (group 2).
_PROSE_CODE_RE = _re.compile(r"```([A-Za-z0-9_+#.\-]*)[ \t]*\n(.*?)```", _re.DOTALL)

# Map a file extension to the set of fenced-code-block language tags that count
# as matching content for that extension.
_EXT_LANG = {
    "py": {"python", "py", "python3"},
    "pyw": {"python", "py"},
    "bat": {"bat", "batch", "cmd", "dos", "bat文件"},
    "cmd": {"bat", "batch", "cmd", "dos"},
    "sh": {"bash", "sh", "shell", "zsh"},
    "bash": {"bash", "sh", "shell"},
    "ps1": {"powershell", "ps1", "pwsh", "posh"},
    "js": {"javascript", "js", "node", "jsx"},
    "mjs": {"javascript", "js", "node"},
    "cjs": {"javascript", "js", "node"},
    "ts": {"typescript", "ts", "tsx"},
    "tsx": {"typescript", "tsx", "ts"},
    "jsx": {"javascript", "jsx", "js"},
    "json": {"json", "json5", "jsonc"},
    "html": {"html", "htm", "xhtml"},
    "htm": {"html", "htm"},
    "css": {"css"},
    "scss": {"scss", "sass", "css"},
    "less": {"less", "css"},
    "java": {"java"},
    "kt": {"kotlin", "kt"},
    "c": {"c"},
    "h": {"c", "cpp", "c++"},
    "cpp": {"cpp", "c++", "cxx", "cc"},
    "cc": {"cpp", "c++", "cc"},
    "cs": {"csharp", "cs", "c#"},
    "go": {"go", "golang"},
    "rs": {"rust", "rs"},
    "rb": {"ruby", "rb"},
    "php": {"php"},
    "swift": {"swift"},
    "yml": {"yaml", "yml"},
    "yaml": {"yaml", "yml"},
    "xml": {"xml"},
    "sql": {"sql"},
    "md": {"markdown", "md"},
    "txt": {"text", "txt", "plaintext", ""},
    "toml": {"toml"},
    "ini": {"ini", "cfg", "conf"},
    "cfg": {"ini", "cfg", "conf"},
    "conf": {"ini", "cfg", "conf"},
    "env": {"dotenv", "env", "bash", "sh", ""},
    "dockerfile": {"dockerfile", "docker"},
    "vue": {"vue", "html"},
    "r": {"r"},
    "lua": {"lua"},
    "pl": {"perl", "pl"},
    "scala": {"scala"},
    "dart": {"dart"},
    "gradle": {"gradle", "groovy"},
    "groovy": {"groovy"},
    "makefile": {"makefile", "make"},
}


def _extract_prose_write(text: str, tool_names: set[str]) -> list[dict]:
    """Fallback: synthesize a Write tool_call from a 'save as <path>' + code block prose.

    Strict matching to avoid corrupting files:
    - A Write-like tool must be available.
    - A LOCAL file path (drive letter or absolute unix path, not a URL) with an
      extension must be present.
    - A fenced code block whose language tag matches the file's extension must
      exist. This prevents usage-example blocks (```bash, ```text) from being
      mistaken for the file content and overwriting a correctly written file.
    """
    if not any(n.lower() == "write" for n in tool_names):
        return []

    # Collect candidate local paths (skip URLs).
    file_path = None
    target_ext = None
    for path_m in _PROSE_PATH_RE.finditer(text):
        candidate = path_m.group(1).strip()
        if "://" in candidate or candidate.lower().startswith("http"):
            continue
        ext = candidate.rsplit(".", 1)[-1].lower() if "." in candidate else ""
        if not ext:
            continue
        file_path = candidate
        target_ext = ext
        break
    if not file_path or not target_ext:
        return []

    allowed_langs = _EXT_LANG.get(target_ext)

    # Find a code block whose language matches the target extension.
    best_content = None
    for code_m in _PROSE_CODE_RE.finditer(text):
        lang = (code_m.group(1) or "").strip().lower()
        body = code_m.group(2)
        if allowed_langs is not None:
            if lang in allowed_langs:
                best_content = body
                break
        else:
            # Unknown extension: only accept an exactly-matching language tag.
            if lang == target_ext:
                best_content = body
                break
    if best_content is None:
        return []

    # Trim a single trailing newline that fenced blocks usually carry.
    if best_content.endswith("\n"):
        best_content = best_content[:-1]
    if not best_content.strip():
        return []

    write_name = next((n for n in tool_names if n.lower() == "write"), "Write")
    arguments = json.dumps({"file_path": file_path, "content": best_content}, ensure_ascii=False)
    return [{
        "id": f"call_{uuid.uuid4().hex[:24]}",
        "type": "function",
        "function": {"name": write_name, "arguments": arguments},
    }]


def _strip_tool_call_blocks(text: str) -> str:
    """Remove tool_call code blocks from text, keeping surrounding content."""
    cleaned = _TOOL_CALL_RE.sub("", text)
    # Also strip json/plain blocks that were parsed as tool calls
    def _maybe_strip(m):
        try:
            obj = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            return m.group(0)
        return "" if _coerce_tool_call(obj) else m.group(0)
    cleaned = _JSON_BLOCK_RE.sub(_maybe_strip, cleaned)
    return cleaned.strip()


# M365 Copilot has a native "generate a file" feature that hosts the file on its
# own object storage (asyncgw/Teams) and returns a download URL, instead of
# emitting our tool_call. From the model's view the task is "done", so prompt
# rules alone can't stop it. We detect this pattern and force a corrective retry.
_FILE_CLAIM_URL_RE = _re.compile(
    r"https?://[^\s`)]+?\.(?:py|js|ts|tsx|jsx|json|txt|md|html?|css|sh|bat|ps1|"
    r"java|kt|c|cpp|cc|h|cs|go|rs|rb|php|swift|ya?ml|xml|sql|ini|toml|cfg)\b",
    _re.IGNORECASE,
)
# Phrases that claim a file was produced (zh + en).
_FILE_CLAIM_PHRASE_RE = _re.compile(
    r"已生成|已创建|已保存|已写入|已经生成|已经创建|生成脚本|生成了|创建了|保存到|"
    r"file (?:created|saved|generated|written)|created the file|saved to|generated the",
    _re.IGNORECASE,
)


def _looks_like_fake_file_claim(text: str) -> bool:
    """True if the model claims to have produced a file but emitted no tool_call.

    Two triggers:
    1. A hosted attachment URL pointing at a code/text file (M365 native file gen).
    2. A "file created/生成" style phrase.
    The caller only invokes this when NO tool_call was parsed from the response.
    """
    if not text:
        return False
    if _FILE_CLAIM_URL_RE.search(text):
        return True
    if _FILE_CLAIM_PHRASE_RE.search(text):
        return True
    return False


_RETRY_INSTRUCTION = (
    "[SYSTEM] Your previous reply did NOT create any file on the host. "
    "You may have used a hosted attachment link or an out-of-band file feature — that does NOT work here; "
    "the host only creates files when you emit a tool_call block. "
    "Re-do the task NOW: output ONLY a fenced ```tool_call block whose JSON is "
    '{"name": "Write", "arguments": {"file_path": "<the exact path the user gave>", "content": "<the FULL file body>"}}. '
    "No prose, no links, no usage examples — just the tool_call block with the complete file content.[/SYSTEM]"
)
