"""Container-only, real-upstream acceptance for the Consumer follow-up.

Run with CANDIDATE_ROOT pointing at a private directory containing src/ and
candidate-manifest.json. Uses a real loopback Uvicorn server, not TestClient or
mocked upstream responses. Production credentials are read only: M365 copies
the access token, never its refresh grant; Consumer starts a separate browser
profile with cookies, never a copied refresh grant/profile. All test state and
rotated test grants stay beneath CANDIDATE_ROOT.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(os.environ["CANDIDATE_ROOT"]).resolve()
assert ROOT.parent == Path("/tmp") and ROOT.name.startswith("consumer-acceptance-")
sys.path.insert(0, str(ROOT / "src"))
os.environ["TOKEN_DIR"] = str(ROOT / "state")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from m365_copilot_openai_proxy.account_store import Account, AccountStore  # noqa: E402
from m365_copilot_openai_proxy.account_crypto import AccountCipher  # noqa: E402
from m365_copilot_openai_proxy.app import create_app  # noqa: E402
from m365_copilot_openai_proxy.config import Settings  # noqa: E402
from m365_copilot_openai_proxy.consumer_camoufox import CamoufoxConsumerGate  # noqa: E402
import m365_copilot_openai_proxy.consumer_refresh_via_rt as rt_module  # noqa: E402
from m365_copilot_openai_proxy.runtime_settings import _tone_default_without  # noqa: E402


RESULTS: list[dict] = []
NETWORK: list[dict] = []
PRIVATE: set[str] = set()
STARTED = time.time()
MANIFEST = json.loads((ROOT / "candidate-manifest.json").read_text())
OPTIONS = json.loads((ROOT / "run-options.json").read_text()) if (ROOT / "run-options.json").exists() else {}
MODEL = OPTIONS.get("m365_model", "gpt-5.6")
TONE = OPTIONS.get("m365_tone", "Gpt_5_6_Reasoning")
TOOL = "read_acceptance_inventory"
SCHEMA = {
    "type": "object",
    "properties": {"release": {"type": "string"}},
    "required": ["release"],
    "additionalProperties": False,
}
DESCRIPTION = "Read the deterministic release acceptance inventory. Do not guess its contents."
CHAT_TOOLS = [{"type": "function", "function": {
    "name": TOOL, "description": DESCRIPTION, "parameters": SCHEMA,
}}]
MESSAGE_TOOLS = [{"name": TOOL, "description": DESCRIPTION, "input_schema": SCHEMA}]
RESPONSE_TOOLS = [{"type": "function", "name": TOOL, "description": DESCRIPTION, "parameters": SCHEMA}]
MATRIX_CHECKS = {
    "m365_native": ["native.stream", "native.history_continuation"],
    "router": ["router.stream_tool_call", "router.stream_tool_result"],
    "studio": ["studio.stream_tool_call", "studio.stream_tool_result"],
    "anthropic_messages": ["messages.stream_tool_use", "messages.stream_tool_result"],
    "openai_responses": ["responses.stream_function_call", "responses.previous_response_id_tool_output"],
    "consumer": ["consumer.concurrent_browser_refresh", "consumer.concurrent_rt_refresh",
                 "consumer.rt_persisted_encrypted", "consumer.proactive_expiry_concurrency",
                 "consumer.background_known_expiry", "consumer.stream", "consumer.history_continuation",
                 "consumer.credentials_survive_app_restart", "consumer.rotated_grant_redeemed_after_restart",
                 "consumer_after_restart.stream", "consumer_after_restart.history_continuation"],
}
PROMPT = (
    "Validate release consumer-followup-20260918. First call read_acceptance_inventory "
    "with release=consumer-followup-20260918; the inventory is only available through "
    "that tool. After its result arrives, report the sum of case counts and copy the "
    "evidence_code exactly. Do not invent an inventory or call unrelated tools."
)


def remember(account) -> None:
    for field in ("token", "consumer_token", "refresh_token", "consumer_refresh_token",
                  "email", "consumer_account_id", "proxy_url"):
        value = str(getattr(account, field, "") or "")
        if value:
            PRIVATE.add(value)
    proxy = urlsplit(str(getattr(account, "proxy_url", "") or ""))
    if proxy.hostname:
        PRIVATE.add(proxy.hostname)
    if proxy.password:
        PRIVATE.add(proxy.password)
    for cookie in getattr(account, "cookies", []) or []:
        value = str(cookie.get("value") or "")
        if len(value) >= 12:
            PRIVATE.add(value)


def clean(value) -> str:
    text = str(value)
    for secret in sorted(PRIVATE, key=len, reverse=True):
        text = text.replace(secret, "<REDACTED>")
    text = re.sub(r"sk-[A-Za-z0-9_-]{16,}", "<API_KEY>", text)
    text = re.sub(r"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "<JWT>", text)
    text = re.sub(r"acct_[0-9a-f]{12}", "<ACCOUNT>", text)
    return text


def fingerprint() -> str:
    files = {p.relative_to(ROOT / "src").as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted((ROOT / "src").rglob("*.py"))}
    assert files == MANIFEST["files"], "Candidate source changed during acceptance"
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def save() -> None:
    report = {
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(STARTED)),
        "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_fingerprint": fingerprint(), "source_files": len(MANIFEST["files"]),
        "transport": "real HTTP over container loopback; real Microsoft upstream",
        "runtime": {"uid": os.getuid(), "home": os.environ.get("HOME")},
        "isolation": "private source/state/profile; production refresh grants never copied",
        "instrumentation": "counting wrappers delegate unchanged to real OAuth HTTP and Camoufox",
        "fixture_changes": "test-only expiry/backoff timestamps; deterministic API-client tool results",
        "configuration": {"m365_model": MODEL, "m365_tone": TONE, "protocol_planner": "studio",
                          "consumer_proxy_override": bool(OPTIONS.get("consumer_proxy"))},
        "results": RESULTS, "network_operations": NETWORK,
    }
    path = ROOT / "results.json"
    path.write_text(clean(json.dumps(report, ensure_ascii=False, indent=2)), encoding="utf-8")
    path.chmod(0o600)


def record(label: str, ok: bool | None, **detail) -> None:
    item = {"check": label, "status": "BLOCKED" if ok is None else ("PASS" if ok else "FAIL"), **detail}
    RESULTS.append(item)
    save()
    print("ACCEPTANCE " + clean(json.dumps(item, ensure_ascii=False)), flush=True)


async def counted_rt(**kwargs):
    item = {"kind": "oauth_refresh", "started": time.time()}
    NETWORK.append(item)
    try:
        response = await ORIGINAL_RT(**kwargs)
        item["http"] = response.status_code
        if response.status_code == 200:
            payload = response.json()
            for key in ("access_token", "refresh_token"):
                if payload.get(key):
                    PRIVATE.add(payload[key])
            item["issuer_expires_in"] = payload.get("expires_in")
            item["rotated_grant_returned"] = bool(payload.get("refresh_token"))
            item["client_info_present"] = bool(payload.get("client_info"))
        return response
    except Exception as exc:
        item["error"] = clean(f"{type(exc).__name__}: {exc}")[:240]
        raise
    finally:
        item["seconds"] = round(time.time() - item["started"], 3)


async def counted_gate(self):
    item = {"kind": "browser_refresh", "started": time.time()}
    NETWORK.append(item)
    try:
        result = await ORIGINAL_GATE(self)
        for key in ("access_token", "refresh_token", "account_id"):
            if result.get(key):
                PRIVATE.add(result[key])
        item["token_returned"] = bool(result.get("access_token"))
        item["grant_returned"] = bool(result.get("refresh_token"))
        return result
    except Exception as exc:
        item["error"] = clean(f"{type(exc).__name__}: {exc}")[:240]
        raise
    finally:
        item["seconds"] = round(time.time() - item["started"], 3)


ORIGINAL_RT = rt_module._post_token
ORIGINAL_GATE = CamoufoxConsumerGate.__call__
rt_module._post_token = counted_rt
CamoufoxConsumerGate.__call__ = counted_gate


def counts(start: int) -> dict:
    operations = NETWORK[start:]
    return {"oauth_requests": sum(x["kind"] == "oauth_refresh" for x in operations),
            "browser_attempts": sum(x["kind"] == "browser_refresh" for x in operations)}


def final_verdict() -> dict:
    by_name = {item["check"]: item for item in RESULTS}
    matrix = {}
    for group, labels in MATRIX_CHECKS.items():
        missing = [label for label in labels if label not in by_name]
        states = [by_name[label]["status"] for label in labels if label in by_name]
        status = "FAIL" if "FAIL" in states else ("BLOCKED" if missing or "BLOCKED" in states else "PASS")
        matrix[group] = {"status": status, "missing_checks": missing, "checks": labels}
    required_extra = ["candidate.isolation", "consumer.invalid_expiry_ingress",
                      "catalogue.server_owned_version", "catalogue.custom_removal_survives_restart",
                      "quota.live_reading", "quota.deleted_account_rejects_late_callback"]
    missing_extra = [label for label in required_extra if label not in by_name]
    success = not missing_extra and all(item["status"] == "PASS" for item in RESULTS)
    success = success and all(item["status"] == "PASS" for item in matrix.values())
    return {"exit_code": 0 if success else 1, "matrix": matrix, "missing_extra_checks": missing_extra,
            "counts": {state: sum(item["status"] == state for item in RESULTS) for state in ("PASS", "FAIL", "BLOCKED")}}


class LiveApp:
    def __init__(self):
        self.password = secrets.token_urlsafe(32)
        PRIVATE.add(self.password)
        self.settings = Settings(TOKEN_DIR=str(ROOT / "state"), ADMIN_PASSWORD=self.password,
                                 API_KEY="", LOG_USER_VERBOSE=False, LOG_USER_ERRORS=False,
                                 LOG_LEVEL="WARNING")
        self.app = None
        self.client = None

    async def start(self):
        self.app = create_app(self.settings)
        assert str(sys.modules["m365_copilot_openai_proxy.app"].__file__).startswith(str(ROOT / "src"))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        config = uvicorn.Config(self.app, host="127.0.0.1", port=self.port,
                                log_level="warning", access_log=False, lifespan="on")
        self.server = uvicorn.Server(config)
        self.task = asyncio.create_task(self.server.serve(sockets=[sock]))
        for _ in range(300):
            if self.server.started:
                break
            if self.task.done():
                await self.task
                raise RuntimeError("Candidate server exited before startup")
            await asyncio.sleep(0.1)
        assert self.server.started
        await self.app.state.refresh_scheduler.stop_keepalive()
        self.client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{self.port}",
                                        timeout=httpx.Timeout(240, connect=15), trust_env=False)
        r = await self.client.post("/admin/login", json={"password": self.password})
        assert r.status_code == 200

    async def stop(self):
        if self.client is not None:
            await self.client.aclose()
        if getattr(self, "server", None) is not None:
            self.server.should_exit = True
            await asyncio.wait_for(self.task, timeout=45)

    def keys(self):
        return {k.name: k for k in self.app.state.key_store.list()}

    def account(self, provider: str):
        return next(a for a in self.app.state.account_store.list() if a.provider == provider)

    async def stream(self, endpoint: str, body: dict, key, session: str = "") -> dict:
        headers = {"Authorization": f"Bearer {key.key}"}
        if endpoint == "/v1/messages":
            headers = {"x-api-key": key.key, "anthropic-version": "2023-06-01"}
        if session:
            headers["x-m365-session-id"] = session
        before = len(self.app.state.call_log)
        started = time.monotonic()
        result = {"events": [], "done": False, "first_event_seconds": None}
        async with self.client.stream("POST", endpoint, headers=headers, json={**body, "stream": True}) as response:
            result["http"] = response.status_code
            result["content_type"] = response.headers.get("content-type", "")
            result["tool_header"] = response.headers.get("x-m365-tool-calling")
            if response.status_code != 200:
                result["error"] = clean((await response.aread()).decode(errors="replace"))[:400]
            else:
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    if result["first_event_seconds"] is None:
                        result["first_event_seconds"] = round(time.monotonic() - started, 3)
                    if data == "[DONE]":
                        result["done"] = True
                        continue
                    event = json.loads(data)
                    result["events"].append(event)
                    if "error" in event or event.get("type") in {"error", "response.failed"}:
                        result["error"] = clean(event)[:400]
        result["seconds"] = round(time.monotonic() - started, 3)
        result["call_records"] = [
            {k: row.get(k) for k in ("provider", "tone", "tool_planning", "studio_fallback", "tool_calls", "status", "error") if row.get(k) is not None}
            for row in self.app.state.call_log[before:]
        ]
        failures = [row["error"] for row in result["call_records"] if row.get("error")]
        if failures:
            result["error"] = clean("; ".join(str(error) for error in failures))[:400]
        return result


def chat_result(wire: dict):
    text, calls, finish = "", {}, None
    for event in wire["events"]:
        for choice in event.get("choices", []):
            delta = choice.get("delta") or {}
            text += delta.get("content") or ""
            finish = choice.get("finish_reason") or finish
            for piece in delta.get("tool_calls") or []:
                call = calls.setdefault(piece.get("index", 0), {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                call["id"] += piece.get("id") or ""
                for field in ("name", "arguments"):
                    call["function"][field] += (piece.get("function") or {}).get(field) or ""
    return text, list(calls.values()), finish


def message_result(wire: dict):
    blocks, partial, stop = {}, {}, None
    for event in wire["events"]:
        kind, index = event.get("type"), event.get("index", 0)
        if kind == "content_block_start":
            blocks[index] = dict(event["content_block"])
        elif kind == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta":
                blocks[index]["text"] = blocks[index].get("text", "") + delta.get("text", "")
            elif delta.get("type") == "input_json_delta":
                partial[index] = partial.get(index, "") + delta.get("partial_json", "")
        elif kind == "message_delta":
            stop = (event.get("delta") or {}).get("stop_reason") or stop
    for index, value in partial.items():
        blocks[index]["input"] = json.loads(value)
    return list(blocks.values()), stop


def response_result(wire: dict):
    return next((e["response"] for e in reversed(wire["events"]) if e.get("type") == "response.completed"), {})


def wire_detail(wire: dict) -> dict:
    return {k: v for k, v in wire.items() if k != "events"} | {
        "event_count": len(wire["events"]),
        "event_types": sorted({e.get("type", "chat.chunk") for e in wire["events"]}),
    }


def payload_result():
    code = "ACCEPT" + secrets.token_hex(4).upper()
    return {"release": "consumer-followup-20260918", "case_counts": [58, 21, 9],
            "evidence_code": code, "note": "Deterministic acceptance fixture, not production inventory"}, code


def valid_call(name: str, arguments) -> bool:
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    return name == TOOL and arguments == {"release": "consumer-followup-20260918"}


def total_observed(text: str, code: str) -> bool:
    return re.search(r"(?<![0-9A-Za-z])88(?![0-9A-Za-z])", text.replace(code, "")) is not None


def descending_counts_observed(text: str, code: str) -> bool:
    return re.search(r"(?<!\d)58(?!\d)[\s\S]*?(?<!\d)21(?!\d)[\s\S]*?(?<!\d)9(?!\d)", text.replace(code, "")) is not None


async def chat_loop(live: LiveApp, mode: str):
    key = live.keys()[mode]
    session = "accept-" + secrets.token_hex(12)
    initial = {"model": MODEL, "messages": [{"role": "user", "content": PROMPT}],
               "tools": CHAT_TOOLS, "tool_choice": "required"}
    first = await live.stream("/v1/chat/completions", initial, key, session)
    text, calls, finish = chat_result(first)
    ok = first["http"] == 200 and "error" not in first and first["done"] and finish == "tool_calls" and len(calls) == 1
    ok = ok and valid_call(calls[0]["function"]["name"], calls[0]["function"]["arguments"])
    used_modes = [r.get("tool_planning") for r in first["call_records"]]
    if mode == "native":
        ok = ok and key.tool_planning_mode == "native" and not any(used_modes)
    else:
        ok = ok and mode in used_modes
    record(f"{mode}.stream_tool_call", ok, finish_reason=finish, tool_count=len(calls), **wire_detail(first))
    if not calls:
        record(f"{mode}.stream_tool_result", None, blocker="No tool call was returned by the first request")
        return
    result, code = payload_result()
    messages = initial["messages"] + [
        {"role": "assistant", "content": text or None, "tool_calls": calls},
        {"role": "tool", "tool_call_id": calls[0]["id"], "content": json.dumps(result)},
    ]
    second = await live.stream("/v1/chat/completions", {**initial, "messages": messages, "tool_choice": "auto"}, key, session)
    text, repeated, finish = chat_result(second)
    record(f"{mode}.stream_tool_result", second["http"] == 200 and "error" not in second and second["done"]
           and finish == "stop" and not repeated and code in text and total_observed(text, code),
           expected_code_observed=code in text, expected_sum_observed=total_observed(text, code),
           finish_reason=finish, text_excerpt=clean(text)[:220], **wire_detail(second))


async def messages_loop(live: LiveApp):
    key, session = live.keys()["studio"], "accept-" + secrets.token_hex(12)
    initial = {"model": MODEL, "max_tokens": 1024, "tools": MESSAGE_TOOLS,
               "tool_choice": {"type": "any"}, "messages": [{"role": "user", "content": PROMPT}]}
    first = await live.stream("/v1/messages", initial, key, session)
    blocks, stop = message_result(first)
    calls = [b for b in blocks if b.get("type") == "tool_use"]
    stopped = any(e.get("type") == "message_stop" for e in first["events"])
    ok = first["http"] == 200 and "error" not in first and stopped and stop == "tool_use" and len(calls) == 1
    ok = ok and valid_call(calls[0]["name"], calls[0]["input"])
    record("messages.stream_tool_use", ok, stop_reason=stop, tool_count=len(calls), **wire_detail(first))
    if not calls:
        record("messages.stream_tool_result", None, blocker="No tool_use was returned")
        return
    result, code = payload_result()
    second = await live.stream("/v1/messages", {**initial, "tool_choice": {"type": "auto"},
        "messages": initial["messages"] + [{"role": "assistant", "content": blocks},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": calls[0]["id"], "content": json.dumps(result)}]}]}, key, session)
    blocks, stop = message_result(second)
    text = "".join(b.get("text", "") for b in blocks)
    stopped = any(e.get("type") == "message_stop" for e in second["events"])
    record("messages.stream_tool_result", second["http"] == 200 and "error" not in second and stopped
           and stop == "end_turn" and code in text and total_observed(text, code),
           stop_reason=stop, expected_code_observed=code in text, expected_sum_observed=total_observed(text, code),
           text_excerpt=clean(text)[:220], **wire_detail(second))


async def responses_loop(live: LiveApp):
    key = live.keys()["studio"]
    first = await live.stream("/v1/responses", {"model": MODEL, "tools": RESPONSE_TOOLS,
                               "tool_choice": "required", "input": PROMPT}, key)
    response = response_result(first)
    calls = [x for x in response.get("output", []) if x.get("type") == "function_call"]
    ok = first["http"] == 200 and "error" not in first and response.get("status") == "completed" and len(calls) == 1
    ok = ok and valid_call(calls[0]["name"], calls[0]["arguments"])
    record("responses.stream_function_call", ok, tool_count=len(calls), response_status=response.get("status"), **wire_detail(first))
    if not calls:
        record("responses.previous_response_id_tool_output", None, blocker="No function_call was returned")
        return
    result, code = payload_result()
    second = await live.stream("/v1/responses", {"model": MODEL, "tools": RESPONSE_TOOLS,
        "previous_response_id": response["id"], "input": [{"type": "function_call_output",
            "call_id": calls[0]["call_id"], "output": json.dumps(result)}]}, key)
    final = response_result(second)
    text = "".join(p.get("text", "") for x in final.get("output", []) for p in (x.get("content") or []))
    record("responses.previous_response_id_tool_output", second["http"] == 200 and "error" not in second
           and final.get("status") == "completed" and code in text and total_observed(text, code),
           previous_response_id_only=True, expected_code_observed=code in text,
           expected_sum_observed=total_observed(text, code), text_excerpt=clean(text)[:220], **wire_detail(second))


async def consumer_refresh(live: LiveApp):
    account = live.account("consumer")
    path = f"/admin/accounts/{account.id}/refresh"
    before = len(NETWORK)
    replies = await asyncio.gather(*(live.client.post(path) for _ in range(5)))
    c = counts(before)
    success = all(r.status_code == 200 and r.json().get("refreshed") for r in replies)
    record("consumer.concurrent_browser_refresh", success and c["browser_attempts"] == 1,
           requests=5, http_statuses=[r.status_code for r in replies], **c)
    remember(account)
    if not account.consumer_refresh_token:
        for check in ("concurrent_rt_refresh", "rt_persisted_encrypted", "proactive_expiry_concurrency", "background_known_expiry"):
            record("consumer." + check, None, blocker="Fresh independent browser session did not expose a bound Consumer refresh grant")
        return
    before = len(NETWORK)
    replies = await asyncio.gather(*(live.client.post(path) for _ in range(5)))
    c = counts(before)
    record("consumer.concurrent_rt_refresh", all(r.status_code == 200 and r.json().get("refreshed") for r in replies)
           and c == {"oauth_requests": 1, "browser_attempts": 0}, requests=5,
           http_statuses=[r.status_code for r in replies], **c)
    reopened = AccountStore(persist_path=ROOT / "state" / "accounts.json").get(account.id)
    on_disk = (ROOT / "state" / "accounts.json").read_text()
    record("consumer.rt_persisted_encrypted", reopened.consumer_token == account.consumer_token
           and reopened.consumer_refresh_token == account.consumer_refresh_token
           and reopened.consumer_token_expires_at == account.consumer_token_expires_at
           and reopened.consumer_token_expires_at > time.time() + 300
           and account.consumer_token not in on_disk and account.consumer_refresh_token not in on_disk,
           access_token_matches=True if reopened.consumer_token == account.consumer_token else False,
           rotated_grant_matches=reopened.consumer_refresh_token == account.consumer_refresh_token,
           expiry_matches=reopened.consumer_token_expires_at == account.consumer_token_expires_at,
           issuer_seconds_remaining=round(account.consumer_token_expires_at - time.time()))
    # Advance only isolated expiry/backoff metadata; the credential and OAuth
    # response are real. Five real API requests enter the unchanged middleware.
    account.consumer_token_expires_at = time.time() + 60
    live.app.state.account_store._save()
    live.app.state.refresh_scheduler._consumer_attempted_at.pop(account.id, None)
    before = len(NETWORK)
    key = live.keys()["consumer"]
    replies = await asyncio.gather(*(live.client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"}) for _ in range(5)))
    c = counts(before)
    record("consumer.proactive_expiry_concurrency", all(r.status_code == 200 for r in replies)
           and account.consumer_token_expires_at > time.time() + 300
           and c == {"oauth_requests": 1, "browser_attempts": 0}, requests=5,
           fixture="isolated expiry set to now+60s; previous browser retry age cleared", **c)
    account.consumer_token_expires_at = time.time() + 60
    live.app.state.account_store._save()
    scheduler = live.app.state.refresh_scheduler
    scheduler._consumer_attempted_at.pop(account.id, None)
    before = len(NETWORK)
    scheduler.start_keepalive()
    for _ in range(600):
        if account.consumer_token_expires_at > time.time() + 300:
            break
        await asyncio.sleep(0.1)
    await scheduler.stop_keepalive()
    c = counts(before)
    record("consumer.background_known_expiry", account.consumer_token_expires_at > time.time() + 300
           and c == {"oauth_requests": 1, "browser_attempts": 0}, **c)


async def text_turns(live: LiveApp, prefix="consumer", provider="consumer"):
    key = live.keys()["consumer" if provider == "consumer" else "native"]
    model = "copilot" if provider == "consumer" else MODEL
    code = "TEXT" + secrets.token_hex(4).upper()
    prompt = ("For the proxy regression acceptance fixture, the three case counts are 58, 21 and 9. "
              f"Calculate the total and copy evidence code {code}. Use only these fixture values; do not browse.")
    history = [{"role": "user", "content": prompt}]
    before = len(NETWORK)
    first = await live.stream("/v1/chat/completions", {"model": model, "messages": history}, key)
    text, calls, finish = chat_result(first)
    ok = first["http"] == 200 and "error" not in first and first["done"] and finish == "stop" and code in text and total_observed(text, code)
    record(f"{prefix}.stream", ok,
           expected_code_observed=code in text, expected_sum_observed=total_observed(text, code),
           text_excerpt=clean(text)[:220], **counts(before), **wire_detail(first))
    if not ok:
        record(f"{prefix}.history_continuation", None, blocker="First upstream turn did not produce a valid answer")
        return
    history += [{"role": "assistant", "content": text}, {"role": "user", "content":
                "List the same three fixture counts in descending order, keeping the total and evidence code from the previous turn."}]
    second = await live.stream("/v1/chat/completions", {"model": model, "messages": history}, key)
    text, calls, finish = chat_result(second)
    record(f"{prefix}.history_continuation", second["http"] == 200 and "error" not in second and second["done"]
           and finish == "stop" and code in text and total_observed(text, code) and descending_counts_observed(text, code),
           expected_code_observed=code in text, expected_sum_observed=total_observed(text, code),
           descending_counts_observed=descending_counts_observed(text, code),
           text_excerpt=clean(text)[:220], **wire_detail(second))


async def consumer_ingress(live: LiveApp):
    account, key = live.account("consumer"), live.keys()["consumer"]
    before = (account.consumer_token, account.consumer_refresh_token, account.consumer_token_expires_at)
    body = {"access_token": account.consumer_token, "cookies": account.cookies,
            "identity_type": account.consumer_identity_type, "consumer_account_id": account.consumer_account_id}
    statuses = []
    for expiry in (-1, 0, 10 ** 400):
        reply = await live.client.post("/user/account/consumer", json={**body, "expires_at": expiry},
                                       headers={"Authorization": f"Bearer {key.key}"})
        statuses.append(reply.status_code)
    after = (account.consumer_token, account.consumer_refresh_token, account.consumer_token_expires_at)
    record("consumer.invalid_expiry_ingress", statuses == [400, 400, 400] and before == after,
           http_statuses=statuses, credentials_unchanged=before == after,
           values_tested=["negative", "zero", "overflowing integer"])


async def catalogue_restart(live: LiveApp):
    chosen = _tone_default_without("Grok_4_5")
    response = await live.client.post("/admin/runtime-settings", json={
        "tone_options": chosen, "tone_options_schema_version": 0,
        "auto_cleanup_minutes": 0, "user_log_verbose": False, "user_log_errors": False})
    saved = json.loads((ROOT / "state" / "runtime_settings.json").read_text())
    record("catalogue.server_owned_version", response.status_code == 200
           and saved["tone_options_schema_version"] >= 2
           and not any(x["value"] == "Grok_4_5" for x in saved["tone_options"]),
           http=response.status_code, requested_version=0, stored_version=saved["tone_options_schema_version"])
    consumer = live.account("consumer")
    persisted = (consumer.consumer_token, consumer.consumer_refresh_token, consumer.consumer_token_expires_at)
    await live.stop()
    await live.start()
    settings = (await live.client.get("/admin/runtime-settings")).json()["settings"]
    response = await live.client.get("/v1/models", headers={"Authorization": f"Bearer {live.keys()['native'].key}"})
    model_ids = [x["id"] for x in response.json().get("data", [])]
    record("catalogue.custom_removal_survives_restart", response.status_code == 200
           and not any(x["value"] == "Grok_4_5" for x in settings["tone_options"])
           and "grok-4.5" not in model_ids,
           application_restarted=True, model_count=len(model_ids), grok_present="grok-4.5" in model_ids)
    consumer = live.account("consumer")
    record("consumer.credentials_survive_app_restart", persisted == (
        consumer.consumer_token, consumer.consumer_refresh_token, consumer.consumer_token_expires_at),
        application_restarted=True)
    if consumer.consumer_refresh_token:
        before = len(NETWORK)
        response = await live.client.post(f"/admin/accounts/{consumer.id}/refresh")
        c = counts(before)
        record("consumer.rotated_grant_redeemed_after_restart", response.status_code == 200
               and response.json().get("refreshed") is True and c == {"oauth_requests": 1, "browser_attempts": 0},
               http=response.status_code, **c)
    else:
        record("consumer.rotated_grant_redeemed_after_restart", None, blocker="No bound grant captured from independent browser session")


async def quota_deletion(live: LiveApp):
    account = live.account("m365")
    # A fresh real upstream turn supplies a quota reading after app restart.
    reply = await live.stream("/v1/chat/completions", {"model": MODEL, "messages": [
        {"role": "user", "content": "Summarize in one sentence why a deleted account's late quota callback must not recreate its quota row."}]}, live.keys()["native"])
    text, _, _ = chat_result(reply)
    reading = live.app.state.conversation_quota_store.stats().get(account.id)
    record("quota.live_reading", reply["http"] == 200 and "error" not in reply and bool(text) and bool(reading),
           quota=reading, **wire_detail(reply))
    response = await live.client.delete(f"/admin/accounts/{account.id}")
    if reading:
        live.app.state.conversation_quota_store.record(account.id, reading)
    stats = (await live.client.get("/admin/stats")).json()
    present = account.id in (stats.get("cache", {}).get("conversation_quota") or {})
    record("quota.deleted_account_rejects_late_callback", response.status_code == 200 and bool(reading) and not present,
           delete_http=response.status_code, quota_present_after_callback=present,
           callback="replayed the last real upstream quota after real HTTP account deletion")


def setup_runtime():
    state = ROOT / "state"
    state.mkdir(mode=0o700, exist_ok=True)
    assert not (state / "accounts.json").exists(), "Use a new private run directory"
    production = Path("/home/app/token")
    settings = json.loads((production / "runtime_settings.json").read_text())
    settings.update(auto_cleanup_minutes=0, cloud_cleanup_idle_hours=0, session_idle_hours=0,
                    auto_refresh=False, user_log_verbose=False, user_log_errors=False,
                    log_level="WARNING", account_cdp_port_base=19322, rate_limit_rpm=0)
    path = state / "runtime_settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    path.chmod(0o600)


def read_production_accounts() -> list[Account]:
    """Strict read: no Store constructor, key creation, backfill or migration."""
    directory = Path("/home/app/token")
    raw_key = (directory / ".enc_key").read_bytes()
    try:
        key = base64.b64decode(raw_key, validate=True)
    except ValueError:
        key = raw_key
    assert len(key) == 32
    cipher = AccountCipher(key)
    wanted = {"id", "name", "email", "provider", "token", "cookies", "consumer_token",
              "consumer_identity_type", "consumer_account_id", "proxy_url", "studio_agent_id",
              "studio_agent_tenant_id", "studio_agent_object_id"}
    rows = json.loads((directory / "accounts.json").read_text())
    return [Account(**{key: cipher.decrypt_value(value) for key, value in row.items() if key in wanted})
            for row in rows.values()]


def seed_accounts(live: LiveApp):
    path = Path("/home/app/token/accounts.json")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    production = read_production_accounts()
    unchanged = before == hashlib.sha256(path.read_bytes()).hexdigest()
    assert unchanged, "Production accounts changed during the read; retry a consistent snapshot"
    accounts, keys = live.app.state.account_store, live.app.state.key_store
    for original in production:
        remember(original)
        if original.provider == "m365":
            assert original.token_status().get("valid"), "Refresh M365 using production's own API before this run"
            target = accounts.add(name="acceptance-m365", token=original.token, token_source="manual")
            if original.studio_agent_ready:
                accounts.set_studio_agent_id(target.id, original.studio_agent_id)
            accounts.set_proxy_url(target.id, original.proxy_url)
            for mode in ("native", "router", "studio"):
                key = keys.add(name=mode, account_id=target.id, tone=TONE)
                keys.update(key.id, tool_planning_mode=mode, run_permission="full", rate_limit_rpm=-1)
                PRIVATE.add(key.key)
        elif original.provider == "consumer":
            target = accounts.add(name="acceptance-consumer")
            accounts.set_proxy_url(target.id, OPTIONS.get("consumer_proxy") or original.proxy_url)
            accounts.set_consumer_auth(target.id, original.cookies, original.consumer_token,
                                      original.consumer_identity_type, consumer_account_id=original.consumer_account_id)
            key = keys.add(name="consumer", account_id=target.id)
            keys.update(key.id, tool_planning_mode="native", run_permission="full", rate_limit_rpm=-1)
            PRIVATE.add(key.key)
            remember(target)
    assert set(live.keys()) == {"native", "router", "studio", "consumer"}
    record("candidate.isolation", all(not a.refresh_token and not a.consumer_refresh_token for a in accounts.list()),
           source_fingerprint=fingerprint(), copied_refresh_grants=0, copied_browser_profiles=0,
           source_module_path_is_candidate=True, production_source_modified=False,
           production_account_file_unchanged_during_read=unchanged)


async def main():
    setup_runtime()
    live = LiveApp()
    try:
        await live.start()
        seed_accounts(live)
        await text_turns(live, "native", "m365")
        if os.environ.get("ACCEPTANCE_PHASE") == "preflight":
            return 0 if all(item["status"] == "PASS" for item in RESULTS) else 1
        for mode in ("router", "studio"):
            try:
                await chat_loop(live, mode)
            except Exception as exc:
                record(f"{mode}.exception", False, error=clean(f"{type(exc).__name__}: {exc}")[:500])
        for name, operation in [("messages", messages_loop), ("responses", responses_loop),
                                ("consumer_refresh", consumer_refresh), ("consumer_ingress", consumer_ingress),
                                ("consumer", text_turns), ("catalogue_restart", catalogue_restart),
                                ("consumer_after_restart", lambda app: text_turns(app, "consumer_after_restart")),
                                ("quota", quota_deletion)]:
            try:
                await operation(live)
            except Exception as exc:
                record(f"{name}.exception", False, error=clean(f"{type(exc).__name__}: {exc}")[:500])
    finally:
        await live.stop()
        rt_module._post_token = ORIGINAL_RT
        CamoufoxConsumerGate.__call__ = ORIGINAL_GATE
        save()
    verdict = final_verdict()
    (ROOT / "final.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    print("ACCEPTANCE_SUMMARY " + json.dumps(verdict), flush=True)
    return verdict["exit_code"]


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
