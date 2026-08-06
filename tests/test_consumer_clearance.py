"""Unit tests for the browser-side Turnstile harvest.

Covers the pieces that decide whether a harvest is worth anything and that no
live browser would reveal cheaply: the cookie precedence rule, the checkbox
coordinate, the CDP event router that extracts the chat token, and the
earned/not-earned verdict.
"""

import asyncio

import pytest

from m365_copilot_openai_proxy import consumer_clearance as cc


def test_host_scoped_cookie_beats_the_parent_domain_copy():
    # Microsoft sets _C_Auth on both copilot.microsoft.com and .microsoft.com;
    # the host-scoped one is what the real client sends.
    picked = cc._pick_cookies([
        {"name": "_C_Auth", "value": "parent", "domain": ".microsoft.com"},
        {"name": "_C_Auth", "value": "host", "domain": "copilot.microsoft.com"},
    ])
    assert picked["_C_Auth"] == "host"


def test_empty_values_and_foreign_domains_are_dropped():
    picked = cc._pick_cookies([
        {"name": "cf_clearance", "value": "abc", "domain": ".copilot.microsoft.com"},
        {"name": "blank", "value": "", "domain": "copilot.microsoft.com"},
        {"name": "elsewhere", "value": "x", "domain": ".example.com"},
    ])
    assert picked == {"cf_clearance": "abc"}


def test_checkbox_point_stays_left_of_centre_on_a_wide_widget():
    x, y = cc._checkbox_point({"x": 100.0, "y": 200.0, "w": 300.0, "h": 65.0})
    assert (x, y) == (130.0, 232.5)


def test_checkbox_point_halves_a_narrow_widget_instead_of_overshooting():
    x, _ = cc._checkbox_point({"x": 0.0, "y": 0.0, "w": 40.0, "h": 40.0})
    assert x == 20.0


class _Sink:
    """Just the attributes ``_Cdp._on_event`` touches."""

    access_token = ""
    identity_type = ""
    replied = False
    challenge_seen = False


def test_chat_token_is_lifted_out_of_the_page_socket_url():
    sink = _Sink()
    cc._Cdp._on_event(sink, {
        "method": "Network.webSocketCreated",
        "params": {"url": (
            "wss://copilot.microsoft.com/c/api/chat?api-version=2"
            "&accessToken=ey.a%2Fb%3D%3D&X-UserIdentityType=MSA"
        )},
    })
    # parse_qs decodes, so downstream gets the raw token and re-quotes it itself.
    assert sink.access_token == "ey.a/b=="
    assert sink.identity_type == "MSA"


def test_a_socket_without_a_token_is_ignored():
    sink = _Sink()
    cc._Cdp._on_event(sink, {
        "method": "Network.webSocketCreated",
        "params": {"url": "wss://copilot.microsoft.com/c/api/chat?api-version=2"},
    })
    assert sink.access_token == ""


@pytest.mark.parametrize(
    "payload, replied, challenged",
    [
        ('{"event":"appendText","text":"hi"}', True, False),
        ('{"event":"challenge","method":null}', False, True),
        ('{"event":"connected"}', False, False),
    ],
)
def test_frames_are_routed_to_the_right_signal(payload, replied, challenged):
    sink = _Sink()
    cc._Cdp._on_event(sink, {
        "method": "Network.webSocketFrameReceived",
        "params": {"response": {"payloadData": payload}},
    })
    assert (sink.replied, sink.challenge_seen) == (replied, challenged)


class _FakeCdp:
    """Scripted CDP stand-in: answers the three evaluates ``_run_harvest`` makes."""

    def __init__(self, *, signed_in=True, box=None, replied=False, clearance=""):
        self.signed_in = signed_in
        self.box = box
        self.replied = replied
        self._clearance = clearance
        self.challenge_seen = False
        self.access_token = "tok"
        self.identity_type = "MSA"
        self.keys_typed = 0

    async def call(self, method, params=None, timeout=10.0):
        if method == "Input.dispatchKeyEvent":
            self.keys_typed += 1
        return None

    async def evaluate(self, expression, timeout=10.0):
        if "challenges.cloudflare.com" in expression:
            return self.box
        if "account.keys" in expression:
            return self.signed_in
        return True  # the composer focus probe

    async def cookies(self):
        return [{"name": "_C_Auth", "value": "live", "domain": "copilot.microsoft.com"}]

    async def clearance(self):
        return self._clearance


def _harvest(cdp, monkeypatch, **kwargs):
    async def _no_sleep(_seconds):
        return None

    # The harvest's fixed 3s navigate + 1s settle waits are the whole runtime here.
    monkeypatch.setattr(cc.asyncio, "sleep", _no_sleep)
    session = cc.ConsumerSession(cookies={}, access_token="", identity_type="", earned=False)
    return asyncio.run(_run(cdp, session, kwargs))


async def _run(cdp, session, kwargs):
    return await cc._run_harvest(cdp, session, timeout=kwargs.get("timeout", 0.05),
                                 warmup=kwargs.get("warmup", True))


def test_a_streamed_warmup_reply_counts_as_earned(monkeypatch):
    session = _harvest(_FakeCdp(replied=True), monkeypatch)
    assert session.earned is True
    assert session["access_token"] == "tok"
    assert session["cookies"] == {"_C_Auth": "live"}


def test_a_silent_turn_is_not_earned_even_though_cookies_came_back(monkeypatch):
    # The datacenter-IP case: Cloudflare escalates past a clickable checkbox, so
    # the cookies are real but the next turn will still be refused.
    session = _harvest(_FakeCdp(), monkeypatch)
    assert session.earned is False
    assert session["cookies"] == {"_C_Auth": "live"}


def test_a_signed_out_profile_skips_the_warmup_turn(monkeypatch):
    cdp = _FakeCdp(signed_in=False)
    session = _harvest(cdp, monkeypatch)
    assert cdp.keys_typed == 0
    assert session["signed_in"] is False


def test_a_zero_sized_turnstile_host_is_not_clicked():
    # Copilot keeps a hidden Turnstile iframe mounted at all times, and the box
    # JS returns null for it; clicking anyway would fire a stray mouse event into
    # the page on every harvest.
    assert asyncio.run(cc._click_turnstile(_FakeCdp(box=None))) is False


def test_a_visible_turnstile_host_is_clicked():
    cdp = _FakeCdp(box='{"x": 10, "y": 20, "w": 300, "h": 65}')
    assert asyncio.run(cc._click_turnstile(cdp)) is True
