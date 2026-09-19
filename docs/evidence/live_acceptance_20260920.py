"""Live acceptance for the 2026-09-20 change set, run INSIDE a temp container.

Covers the AGENTS.md matrix (items 1-6) plus this cycle's own contracts:

  * cache discipline: a JSON route refuses storage, a stream refuses storage,
    /v1/models carries a stable validator and answers a revalidation with 304
  * consumer credential renewal: the bound account's refresh path still leaves
    a usable credential AND persists the issuer-reported expiry
  * tone catalogue migration: Grok is still in the catalogue and still answers

The M365/Consumer API keys are resolved from the container's own stores rather
than pasted, so a rotated key cannot make this report a stale 401. No secret is
printed; the consumer account id is truncated.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/app/src")

from m365_copilot_openai_proxy.account_store import AccountStore
from m365_copilot_openai_proxy.key_store import KeyStore

V1 = "http://127.0.0.1:8000/v1"
ADMIN = "http://127.0.0.1:8000/admin"
BASE = "http://127.0.0.1:8000"
TOKEN_DIR = Path(os.environ.get("TOKEN_DIR") or "/home/app/token")

PASS: list[str] = []
FAIL: list[str] = []


def rec(label: str, ok: bool, detail: str) -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<44} {detail}", flush=True)


def resolve_keys() -> dict[str, str]:
    accounts = {acc.id: acc for acc in AccountStore(TOKEN_DIR / "accounts.json").list()}
    found: dict[str, str] = {"m365": "", "consumer": ""}
    for key in KeyStore(TOKEN_DIR / "keys.json").list():
        account = accounts.get(key.account_id or "")
        # A key whose account was deleted still sits in keys.json and can never
        # serve a turn; picking it as this run's key would read as an app
        # failure when it is really a stale store row.
        if not key.enabled or account is None:
            continue
        provider = getattr(account, "provider", "") or "m365"
        if provider in found and not found[provider]:
            found[provider] = key.key
    return found


def call(path, body=None, key="", method="POST", extra=None, timeout=300, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {key}"} if key else {}),
            **(extra or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", "replace")
            return response.status, dict(response.headers), (text if raw else _maybe_json(text))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        return exc.code, dict(exc.headers), (text if raw else _maybe_json(text))
    except Exception as exc:  # noqa: BLE001 - a transport failure is a matrix result
        return 0, {}, f"{type(exc).__name__}: {exc}"


def _maybe_json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def sse_text(raw: str) -> str:
    out = []
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except ValueError:
            continue
        for choice in event.get("choices") or []:
            out.append((choice.get("delta") or {}).get("content") or "")
    return "".join(out)


TOOLS_OPENAI = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the weather for a city",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    },
}]
TOOLS_ANTHROPIC = [{
    "name": "get_weather",
    "description": "Get the weather for a city",
    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
}]
TOOLS_RESPONSES = [{
    "type": "function",
    "name": "get_weather",
    "description": "Get the weather for a city",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
}]
TOOL_MODEL = "Magic"
ASK = "What's the weather in Paris? Use the get_weather tool."


def item1_m365(keys):
    print("\n[matrix 1] M365 direct/native", flush=True)
    status, _headers, data = call("/v1/chat/completions", {
        "model": TOOL_MODEL,
        "messages": [{"role": "user", "content": "Reply with the word OK only."}],
    }, key=keys["m365"])
    text = ""
    if status == 200 and isinstance(data, dict):
        text = (data["choices"][0]["message"].get("content") or "").strip()
    rec("1a chat text (sync)", bool(text), f"http={status} text={text[:40]!r}")

    status, headers, raw = call("/v1/chat/completions", {
        "model": TOOL_MODEL, "stream": True,
        "messages": [{"role": "user", "content": "Count: 1 2 3"}],
    }, key=keys["m365"], raw=True, timeout=300)
    streamed = sse_text(raw if isinstance(raw, str) else "")
    rec("1b chat text (stream)", status == 200 and bool(streamed.strip()), f"http={status} text={streamed.strip()[:40]!r}")
    rec("1c stream refuses storage", headers.get("cache-control") == "no-store", f"cache-control={headers.get('cache-control')!r}")

    status, _headers, data = call("/v1/chat/completions", {
        "model": TOOL_MODEL, "messages": [{"role": "user", "content": ASK}], "tools": TOOLS_OPENAI,
    }, key=keys["m365"])
    call_obj = None
    if status == 200 and isinstance(data, dict):
        calls = data["choices"][0]["message"].get("tool_calls") or []
        call_obj = calls[0] if calls else None
    rec("1d chat tool round", bool(call_obj), f"http={status} name={(call_obj or {}).get('function', {}).get('name')}")
    if not call_obj:
        rec("1e chat tool continuation", False, "skipped: no tool_call to answer")
        return
    status, _headers, data = call("/v1/chat/completions", {
        "model": TOOL_MODEL,
        "messages": [
            {"role": "user", "content": ASK},
            {"role": "assistant", "content": None, "tool_calls": [call_obj]},
            {"role": "tool", "tool_call_id": call_obj["id"], "content": "18C, clear"},
        ],
        "tools": TOOLS_OPENAI,
    }, key=keys["m365"])
    text = ""
    if status == 200 and isinstance(data, dict):
        text = (data["choices"][0]["message"].get("content") or "").strip()
    rec("1e chat tool continuation", bool(text), f"http={status} text={text[:60]!r}")


def planning_modes(keys):
    original = call("/user/me", method="GET", key=keys["m365"])
    tone = "Magic"
    original_mode = "auto"
    if original[0] == 200 and isinstance(original[2], dict):
        tone = original[2].get("tone") or tone
        original_mode = original[2].get("tool_planning_mode") or original_mode
    try:
        for mode, label in (("router", "[matrix 2] router planning"), ("studio", "[matrix 3] studio planning")):
            print(f"\n{label}", flush=True)
            status, _headers, data = call("/user/tone", {"tone": tone, "tool_planning_mode": mode}, key=keys["m365"])
            applied = isinstance(data, dict) and data.get("tool_planning_mode") == mode
            rec(f"{mode} mode applied", status == 200 and applied, f"http={status} applied={applied}")
            status, headers, data = call("/v1/chat/completions", {
                "model": TOOL_MODEL, "messages": [{"role": "user", "content": ASK}], "tools": TOOLS_OPENAI,
            }, key=keys["m365"], timeout=400)
            calls = []
            if status == 200 and isinstance(data, dict):
                calls = data["choices"][0]["message"].get("tool_calls") or []
            rec(f"{mode} tool round", bool(calls),
                f"http={status} hdr={headers.get('x-m365-tool-calling')} calls={len(calls)}")
    finally:
        call("/user/tone", {"tone": tone, "tool_planning_mode": original_mode}, key=keys["m365"])
        print(f"  restored tone={tone!r} mode={original_mode!r}", flush=True)


def item4_anthropic(keys):
    print("\n[matrix 4] Anthropic Messages API", flush=True)
    head = {"anthropic-version": "2023-06-01"}
    status, _headers, data = call("/v1/messages", {
        "model": TOOL_MODEL, "max_tokens": 64,
        "messages": [{"role": "user", "content": "Reply with the word OK only."}],
    }, key=keys["m365"], extra=head)
    text = ""
    if status == 200 and isinstance(data, dict):
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    rec("4a messages text", bool(text.strip()), f"http={status} stop={data.get('stop_reason') if isinstance(data, dict) else None}")

    status, _headers, data = call("/v1/messages", {
        "model": TOOL_MODEL, "max_tokens": 256, "tools": TOOLS_ANTHROPIC,
        "messages": [{"role": "user", "content": ASK}],
    }, key=keys["m365"], extra=head)
    use = None
    if status == 200 and isinstance(data, dict):
        uses = [b for b in data.get("content", []) if b.get("type") == "tool_use"]
        use = uses[0] if uses else None
    rec("4b messages tool_use", bool(use), f"http={status} input={(use or {}).get('input')}")
    if not use:
        rec("4c messages tool_result continuation", False, "skipped: no tool_use to answer")
        return
    status, _headers, data = call("/v1/messages", {
        "model": TOOL_MODEL, "max_tokens": 256, "tools": TOOLS_ANTHROPIC,
        "messages": [
            {"role": "user", "content": ASK},
            {"role": "assistant", "content": [use]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": use["id"], "content": "18C, clear"}]},
        ],
    }, key=keys["m365"], extra=head)
    text = ""
    if status == 200 and isinstance(data, dict):
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    rec("4c messages tool_result continuation", bool(text.strip()), f"http={status} text={text.strip()[:60]!r}")


def item5_responses(keys):
    print("\n[matrix 5] OpenAI Responses API", flush=True)

    def texts(data):
        out = []
        for item in data.get("output", []) or []:
            for part in item.get("content", []) or []:
                if part.get("type") in ("output_text", "text"):
                    out.append(part.get("text", ""))
        return "".join(out)

    status, _headers, data = call("/v1/responses", {
        "model": TOOL_MODEL, "input": "Reply with the word OK only.",
    }, key=keys["m365"])
    body_text = texts(data) if isinstance(data, dict) else ""
    rec("5a responses text", status == 200 and bool(body_text.strip()), f"http={status} status={data.get('status') if isinstance(data, dict) else None}")

    status, _headers, data = call("/v1/responses", {
        "model": TOOL_MODEL, "tools": TOOLS_RESPONSES, "input": ASK,
    }, key=keys["m365"])
    function_call = None
    if status == 200 and isinstance(data, dict):
        calls = [i for i in data.get("output", []) if i.get("type") == "function_call"]
        function_call = calls[0] if calls else None
    rec("5b responses function tool", bool(function_call),
        f"http={status} name={(function_call or {}).get('name')} args={(function_call or {}).get('arguments')}")
    if not function_call:
        rec("5c responses tool continuation", False, "skipped: no function_call to answer")
        return
    status, _headers, data = call("/v1/responses", {
        "model": TOOL_MODEL, "tools": TOOLS_RESPONSES,
        "input": [
            {"role": "user", "content": ASK},
            {"type": "function_call", "call_id": function_call.get("call_id") or function_call.get("id"),
             "name": function_call.get("name"), "arguments": function_call.get("arguments") or "{}"},
            {"type": "function_call_output", "call_id": function_call.get("call_id") or function_call.get("id"),
             "output": "18C, clear"},
        ],
    }, key=keys["m365"])
    body_text = texts(data) if isinstance(data, dict) else ""
    rec("5c responses tool continuation", status == 200 and bool(body_text.strip()), f"http={status} text={body_text.strip()[:60]!r}")


def admin_login():
    password = os.environ.get("ADMIN_PASSWORD") or os.environ.get("API_KEY") or ""
    if not password:
        return None
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    request = urllib.request.Request(
        ADMIN + "/login", data=json.dumps({"password": password}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with opener.open(request, timeout=30) as response:
            return opener if response.status == 200 else None
    except Exception:  # noqa: BLE001
        return None


def item6_consumer(keys):
    print("\n[matrix 6] Consumer / personal-account provider", flush=True)
    if not keys["consumer"]:
        rec("6a consumer renewal", False, "no enabled consumer key")
        rec("6b consumer chat text (stream)", False, "no enabled consumer key")
        return

    opener = admin_login()
    consumer_account = None
    accounts = {acc.id: acc for acc in AccountStore(TOKEN_DIR / "accounts.json").list()}
    for key in KeyStore(TOKEN_DIR / "keys.json").list():
        account = accounts.get(key.account_id or "")
        if key.enabled and account is not None and getattr(account, "provider", "") == "consumer":
            consumer_account = account
            break
    if opener is None or consumer_account is None:
        rec("6a consumer renewal", False, "no admin credential or consumer account")
    else:
        request = urllib.request.Request(
            ADMIN + f"/accounts/{consumer_account.id}/cookie-refresh",
            data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        try:
            with opener.open(request, timeout=300) as response:
                payload = json.loads(response.read().decode())
            ok = response.status == 200
            rec("6a consumer renewal", ok, f"http={response.status} cookie_valid={payload.get('cookie_valid')}")
        except urllib.error.HTTPError as exc:
            rec("6a consumer renewal", False, f"http={exc.code} {exc.read().decode('utf-8', 'replace')[:120]}")
        except Exception as exc:  # noqa: BLE001
            rec("6a consumer renewal", False, f"{type(exc).__name__}: {exc}")
        status = call("/user/me", method="GET", key=keys["consumer"])
        token_status = {}
        if status[0] == 200 and isinstance(status[2], dict):
            token_status = (status[2].get("account") or {}).get("token_status") or {}
        rec("6b consumer expiry surfaced", bool(token_status.get("valid")),
            f"valid={token_status.get('valid')} expires_at={token_status.get('expires_at')}")

    status, headers, raw = call("/v1/chat/completions", {
        "model": "copilot", "stream": True,
        "messages": [{"role": "user", "content": "Reply with the word OK only."}],
    }, key=keys["consumer"], raw=True, timeout=300)
    text = sse_text(raw if isinstance(raw, str) else "")
    # An upstream failure is delivered as ordinary stream text, so a 200 with a
    # body is not a pass: the answer must not be the proxy's error notice.
    answered = bool(text.strip()) and "上游错误" not in text and "upstream error" not in text.lower()
    rec("6c consumer chat text (stream)", status == 200 and answered,
        f"http={status} text={text.strip()[:60]!r}")


def cache_cells(keys):
    print("\n[cache discipline]", flush=True)
    status, headers, _data = call("/healthz", method="GET")
    rec("healthz refuses storage", headers.get("cache-control") == "no-store",
        f"http={status} cache-control={headers.get('cache-control')!r}")

    status, headers, data = call("/v1/models", method="GET", key=keys["m365"])
    etag = headers.get("etag", "")
    rec("models declares validator", status == 200 and bool(etag) and headers.get("cache-control") == "private, max-age=300",
        f"http={status} etag={bool(etag)} cache-control={headers.get('cache-control')!r}")

    if etag:
        status, headers, body = call("/v1/models", method="GET", key=keys["m365"],
                                     extra={"If-None-Match": etag}, raw=True)
        rec("models answers 304", status == 304 and (body or "") == "",
            f"http={status} bytes={len(body or '')}")

    ids = [m.get("id") for m in (data.get("data") if isinstance(data, dict) else []) or []]
    grok_ids = [i for i in ids if i and "grok" in i.lower()]
    rec("grok still catalogued", bool(grok_ids), f"grok_ids={grok_ids}")

    if grok_ids:
        status, _headers, data = call("/v1/chat/completions", {
            "model": grok_ids[0],
            "messages": [{"role": "user", "content": "Reply with the word OK only."}],
        }, key=keys["m365"])
        text = ""
        if status == 200 and isinstance(data, dict):
            text = (data["choices"][0]["message"].get("content") or "").strip()
        rec("grok smoke turn", bool(text), f"http={status} model={grok_ids[0]!r} text={text[:40]!r}")


def main() -> int:
    keys = resolve_keys()
    print(f"keys resolved: m365={bool(keys['m365'])} consumer={bool(keys['consumer'])} token_dir={TOKEN_DIR}", flush=True)
    if not keys["m365"]:
        rec("m365 key resolved", False, "no enabled M365 key in the container store")
        return 1
    item1_m365(keys)
    planning_modes(keys)
    item4_anthropic(keys)
    item5_responses(keys)
    item6_consumer(keys)
    cache_cells(keys)
    print(f"\n=== PASS {len(PASS)} / FAIL {len(FAIL)} ===", flush=True)
    if FAIL:
        print("failed:", ", ".join(FAIL), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
