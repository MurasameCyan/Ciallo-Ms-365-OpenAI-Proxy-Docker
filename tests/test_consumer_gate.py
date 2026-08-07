"""Edge/CDP recovery for consumer Copilot's interactive verification gate."""

import asyncio
import json

import pytest

from m365_copilot_openai_proxy.consumer_client import (
    ClearanceRequired,
    ConsumerCopilotError,
)
from m365_copilot_openai_proxy.consumer_gate import (
    CdpSession,
    ConsumerBrowserGate,
    click_verification_box,
    export_consumer_auth,
    _wait_for_copilot_page,
    find_verification_box,
    recover_consumer_auth,
    send_browser_warmup,
)


class _FakeCdp:
    def __init__(self):
        self.calls = []

    async def call(self, method, params=None, timeout=10.0):
        self.calls.append((method, params))
        if method == "Accessibility.getFullAXTree":
            return {"nodes": [
                {"role": {"value": "checkbox"},
                 "name": {"value": "请验证您是真人"},
                 "backendDOMNodeId": 42},
            ]}
        if method == "DOM.getBoxModel":
            assert params == {"backendNodeId": 42}
            return {"model": {"border": [470, 279, 771, 279, 771, 344, 470, 344],
                              "width": 301, "height": 65}}
        if method == "Input.dispatchMouseEvent":
            return {}
        raise AssertionError(method)


def test_accessibility_tree_pierces_the_closed_shadow_verification_widget():
    box = asyncio.run(find_verification_box(_FakeCdp()))

    assert box == {"x": 470, "y": 279, "w": 301, "h": 65}


def test_verification_click_uses_trusted_cdp_mouse_events_at_checkbox_offset():
    cdp = _FakeCdp()

    assert asyncio.run(click_verification_box(cdp)) is True

    events = [params for method, params in cdp.calls
              if method == "Input.dispatchMouseEvent"]
    assert [event["type"] for event in events] == [
        "mouseMoved", "mousePressed", "mouseReleased",
    ]
    assert all(event["x"] == 500 and event["y"] == 311.5 for event in events)


class _Wire:
    def __init__(self):
        self.sent = []
        self.incoming = asyncio.Queue()

    async def send(self, raw):
        request = json.loads(raw)
        self.sent.append(request)
        if request["method"] == "Network.enable":
            await self.incoming.put({
                "method": "Network.webSocketCreated",
                "params": {
                    "requestId": "chat-1",
                    "url": (
                        "wss://copilot.microsoft.com/c/api/chat?api-version=2"
                        "&accessToken=socket%20token&X-UserIdentityType=Google"
                    ),
                },
            })
        await self.incoming.put({"id": request["id"], "result": {"ok": True}})

    async def recv(self):
        return json.dumps(await self.incoming.get())


async def _exercise_cdp_router():
    wire = _Wire()
    cdp = CdpSession(wire)
    try:
        assert await cdp.call("Network.enable") == {"ok": True}
        cdp.begin_warmup()
        await wire.incoming.put({
            "method": "Network.webSocketCreated",
            "params": {
                "requestId": "warmup-chat",
                "url": (
                    "wss://copilot.microsoft.com/c/api/chat?api-version=2"
                    "&accessToken=warmup%20token&X-UserIdentityType=Google"
                ),
            },
        })
        await wire.incoming.put({
            "method": "Network.webSocketFrameSent",
            "params": {
                "requestId": "warmup-chat",
                "response": {"payloadData": '{"event":"send"}'},
            },
        })
        await wire.incoming.put({
            "method": "Network.webSocketFrameReceived",
            "params": {
                "requestId": "warmup-chat",
                "response": {
                    "payloadData": (
                        '{"event":"challenge","method":null}'
                        '{"event":"appendText","text":"ok"}'
                    ),
                },
            },
        })
        await asyncio.sleep(0)
        return cdp, wire
    finally:
        await cdp.close()


def test_cdp_router_keeps_one_reader_for_commands_and_chat_events():
    cdp, wire = asyncio.run(_exercise_cdp_router())

    assert cdp.access_token == "warmup token"
    assert cdp.identity_type == "Google"
    assert cdp.challenge_seen is True
    assert cdp.replied is True
    assert wire.sent[0]["method"] == "Network.enable"


async def _exercise_warmup_reply_correlation():
    wire = _Wire()
    cdp = CdpSession(wire)
    try:
        await cdp.call("Network.enable")
        cdp.begin_warmup()
        await wire.incoming.put({
            "method": "Network.webSocketFrameReceived",
            "params": {
                "requestId": "chat-1",
                "response": {"payloadData": '{"event":"appendText","text":"old"}'},
            },
        })
        await asyncio.sleep(0)
        old_reply_ignored = not cdp.replied
        await wire.incoming.put({
            "method": "Network.webSocketFrameSent",
            "params": {
                "requestId": "chat-1",
                "response": {"payloadData": '{"event":"send"}'},
            },
        })
        await wire.incoming.put({
            "method": "Network.webSocketFrameReceived",
            "params": {
                "requestId": "other-chat",
                "response": {"payloadData": '{"event":"appendText","text":"other"}'},
            },
        })
        await asyncio.sleep(0)
        other_socket_ignored = not cdp.replied
        await wire.incoming.put({
            "method": "Network.webSocketFrameReceived",
            "params": {
                "requestId": "chat-1",
                "response": {"payloadData": '{"event":"appendText","text":"warm"}'},
            },
        })
        await asyncio.sleep(0)
        return old_reply_ignored, other_socket_ignored, cdp.replied
    finally:
        await cdp.close()


def test_cdp_counts_only_a_reply_after_this_warmup_send():
    assert asyncio.run(_exercise_warmup_reply_correlation()) == (True, True, True)


class _AuthCdp:
    access_token = "socket-token"
    identity_type = "Google"

    def __init__(self, cache_token="cache-token"):
        self.cache_token = cache_token
        self.expressions = []

    async def evaluate(self, expression, timeout=10.0):
        self.expressions.append(expression)
        return self.cache_token

    async def cookies(self):
        return [
            {"name": "_C_Auth", "value": "parent", "domain": ".microsoft.com"},
            {"name": "_C_Auth", "value": "host", "domain": "copilot.microsoft.com"},
            {"name": "__cf_bm", "value": "bm", "domain": ".copilot.microsoft.com"},
            {"name": "unrelated", "value": "secret", "domain": ".example.com"},
            {
                "name": "_C_Auth",
                "value": "spoofed",
                "domain": "copilot.microsoft.com.attacker.test",
            },
        ]


def test_auth_export_prefers_socket_token_and_host_specific_cookies():
    cdp = _AuthCdp()

    auth = asyncio.run(export_consumer_auth(cdp))

    assert auth == {
        "cookies": {"_C_Auth": "host", "__cf_bm": "bm"},
        "access_token": "socket-token",
        "identity_type": "Google",
    }
    assert "ChatAI" in cdp.expressions[0]


def test_auth_export_requires_a_chat_scoped_token():
    cdp = _AuthCdp(cache_token="")
    cdp.access_token = ""

    with pytest.raises(ConsumerCopilotError, match="ChatAI"):
        asyncio.run(export_consumer_auth(cdp))


class _NativeTurnCdp:
    def __init__(self, controls):
        self.controls = list(controls)
        self.calls = []

    async def evaluate(self, expression, timeout=10.0):
        assert "consumer:native-turn" in expression
        return json.dumps(self.controls.pop(0))

    async def call(self, method, params=None, timeout=10.0):
        self.calls.append((method, params))
        return {}


def test_browser_warmup_clicks_a_spa_owned_starter_prompt():
    cdp = _NativeTurnCdp([
        {"kind": "starter", "x": 400, "y": 500, "w": 160, "h": 40},
    ])

    assert asyncio.run(send_browser_warmup(cdp, poll_interval=0)) is True

    events = [params for method, params in cdp.calls
              if method == "Input.dispatchMouseEvent"]
    assert [event["type"] for event in events] == [
        "mouseMoved", "mousePressed", "mouseReleased",
    ]
    assert all(event["x"] == 480 and event["y"] == 520 for event in events)


def test_browser_warmup_uses_new_chat_before_the_starter_prompt():
    cdp = _NativeTurnCdp([
        {"kind": "new-chat", "x": 6, "y": 60, "w": 248, "h": 40},
        {"kind": "starter", "x": 400, "y": 500, "w": 160, "h": 40},
    ])

    assert asyncio.run(send_browser_warmup(cdp, poll_interval=0)) is True

    releases = [params for method, params in cdp.calls
                if method == "Input.dispatchMouseEvent"
                and params["type"] == "mouseReleased"]
    assert [(event["x"], event["y"]) for event in releases] == [
        (130, 80), (480, 520),
    ]


class _GateCdp(_AuthCdp):
    def __init__(self, *, reply_after_click=True):
        super().__init__()
        self.calls = []
        self.replied = False
        self.challenge_seen = True
        self.reply_after_click = reply_after_click
        self.active = ["TEXTAREA|hi", "TEXTAREA|"]

    def begin_warmup(self):
        self.replied = False

    async def call(self, method, params=None, timeout=10.0):
        self.calls.append((method, params))
        if method == "Accessibility.getFullAXTree":
            return {"nodes": [{
                "name": {"value": "Verify you are human"},
                "backendDOMNodeId": 9,
            }]}
        if method == "DOM.getBoxModel":
            return {"model": {
                "border": [20, 40, 320, 40, 320, 100, 20, 100],
                "width": 300,
                "height": 60,
            }}
        if method == "Input.dispatchMouseEvent" and params["type"] == "mouseReleased":
            self.replied = self.reply_after_click
        return {}

    async def evaluate(self, expression, timeout=10.0):
        if "consumer:native-turn" in expression:
            return json.dumps({
                "kind": "starter", "x": 400, "y": 500, "w": 160, "h": 40,
            })
        if "ChatAI" in expression:
            return "cache-token"
        raise AssertionError(expression)


def test_recovery_drives_the_page_native_turn_clicks_gate_and_exports_auth():
    cdp = _GateCdp()

    auth = asyncio.run(recover_consumer_auth(cdp, timeout=1, poll_interval=0))

    assert auth["access_token"] == "socket-token"
    methods = [method for method, _params in cdp.calls]
    assert methods[:6] == [
        "Page.enable", "Network.enable", "Runtime.enable", "DOM.enable",
        "Accessibility.enable", "Page.addScriptToEvaluateOnNewDocument",
    ]
    assert "Page.navigate" not in methods
    assert "Input.dispatchMouseEvent" in methods
    assert "Input.insertText" not in methods
    assert "Input.dispatchKeyEvent" not in methods


def test_recovery_fails_instead_of_returning_stale_auth_when_gate_stays_closed():
    cdp = _GateCdp(reply_after_click=False)

    with pytest.raises(ClearanceRequired, match="did not pass"):
        asyncio.run(recover_consumer_auth(cdp, timeout=0, poll_interval=0))


def test_recovery_names_the_missing_native_turn_controls(monkeypatch):
    async def no_native_turn(*args, **kwargs):
        return False

    monkeypatch.setattr(
        "m365_copilot_openai_proxy.consumer_gate.send_browser_warmup",
        no_native_turn,
    )
    cdp = _GateCdp()

    with pytest.raises(ConsumerCopilotError, match="New chat.*Starter prompt"):
        asyncio.run(recover_consumer_auth(cdp, timeout=0, poll_interval=0))


def test_local_cdp_discovery_ignores_system_proxy_settings(monkeypatch):
    clients = []

    class _Response:
        def json(self):
            return [{
                "type": "page",
                "url": "https://copilot.microsoft.com/",
                "webSocketDebuggerUrl": "ws://edge/page",
            }]

    class _Client:
        def __init__(self, **kwargs):
            clients.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            assert url == "http://127.0.0.1:9333/json"
            return _Response()

    monkeypatch.setattr(
        "m365_copilot_openai_proxy.consumer_gate.httpx.AsyncClient",
        _Client,
    )

    page = asyncio.run(_wait_for_copilot_page(9333, 0))

    assert page["webSocketDebuggerUrl"] == "ws://edge/page"
    assert clients == [{"timeout": 2, "trust_env": False}]


def test_browser_gate_reuses_an_existing_edge_without_closing_it(tmp_path):
    launched = []
    closed = []

    async def wait_for_page(port, timeout):
        return {"webSocketDebuggerUrl": "ws://edge/page"}

    async def run_page(url):
        assert url == "ws://edge/page"
        return {"cookies": {"_C_Auth": "live"}, "access_token": "token"}

    gate = ConsumerBrowserGate(
        tmp_path,
        cdp_port=9333,
        wait_for_page=wait_for_page,
        launch=lambda *args, **kwargs: launched.append(True),
        run_page=run_page,
        close=lambda *args: closed.append(True),
    )

    assert asyncio.run(gate()) == {
        "cookies": {"_C_Auth": "live"},
        "access_token": "token",
    }
    assert launched == []
    assert closed == []


def test_browser_gate_serializes_instances_for_the_same_profile_and_port(tmp_path):
    active = 0
    max_active = 0

    async def wait_for_page(port, timeout):
        return {"webSocketDebuggerUrl": "ws://edge/page"}

    async def run_page(url):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"cookies": {}, "access_token": "token"}

    gates = [
        ConsumerBrowserGate(
            tmp_path,
            cdp_port=9333,
            wait_for_page=wait_for_page,
            run_page=run_page,
        )
        for _ in range(2)
    ]

    async def run_both():
        return await asyncio.gather(*(gate() for gate in gates))

    asyncio.run(run_both())

    assert max_active == 1


def test_browser_gate_launches_and_closes_only_the_edge_it_owns(tmp_path):
    pages = iter([None, {"webSocketDebuggerUrl": "ws://edge/page"}])
    proc = object()
    launched = []
    closed = []

    async def wait_for_page(port, timeout):
        return next(pages)

    def launch(profile, port, headless):
        launched.append((profile, port, headless))
        return proc

    async def run_page(url):
        return {"cookies": {}, "access_token": "token"}

    async def close(port, process):
        closed.append((port, process))

    gate = ConsumerBrowserGate(
        tmp_path,
        cdp_port=9444,
        headless=False,
        wait_for_page=wait_for_page,
        launch=launch,
        run_page=run_page,
        close=close,
    )

    assert asyncio.run(gate())["access_token"] == "token"
    assert launched == [(tmp_path, 9444, False)]
    assert closed == [(9444, proc)]
