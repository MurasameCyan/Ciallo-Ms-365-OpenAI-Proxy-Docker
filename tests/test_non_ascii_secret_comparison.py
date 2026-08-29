"""Non-ASCII secrets must compare, not crash.

``secrets.compare_digest``/``hmac.compare_digest`` raise TypeError when handed
str arguments containing any codepoint above U+007F. Four comparisons in this
codebase put an outside caller's string on one side, so that TypeError was
reachable from a request:

  * ``routes_web.admin_login``      -- password from the request body
  * ``admin_auth.is_admin_authenticated`` -- ``admin_auth`` cookie
  * ``media_proxy.verify_signed_media_proxy_params`` -- ``sig`` query param
  * ``session_helpers._decode_responses_session_id`` -- ``previous_response_id``

Measured before the fix with a live TestClient: one Chinese character in the
``/admin/login`` body was an unhandled HTTP 500, and an anonymous
``GET /v1/m365-media?...&sig=<non-ascii>`` was an unhandled HTTP 500 too.

The login case was worse than a crash. The exception fires *before* any
comparison, so an admin whose ADMIN_PASSWORD contained non-ASCII characters
could never log in even with the correct password -- and right and wrong guesses
were indistinguishable, both 500.

These tests are about the comparison, not about accepting non-ASCII secrets as
policy: a wrong non-ASCII guess must still be rejected, and the ASCII controls
must keep working, which is what stops the fix from degenerating into "compare
loosely".
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi.testclient import TestClient
from starlette.requests import Request

from m365_copilot_openai_proxy.admin_auth import AdminAuth
from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.auth_helpers import constant_time_equals
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.media_proxy import verify_signed_media_proxy_params
from m365_copilot_openai_proxy.session_helpers import (
    _RESP_ID_PREFIX,
    _decode_responses_session_id,
    _encode_responses_session_id,
)

CHINESE_PASSWORD = "中文密码123"
NON_ASCII = "\u01e9中文签名"
SOURCE_IMAGE_URL = (
    "https://designerapp.officeapps.live.com/designerapp/document.ashx"
    "?path=%2Fgenerated.png&fileToken=abc"
)


def _client(tmp_path, admin_password: str) -> TestClient:
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="api-key", ADMIN_PASSWORD=admin_password)
    )
    return TestClient(app, raise_server_exceptions=False)


# ----------------------------------------------------------------- the helper

def test_constant_time_equals_matches_equality_for_non_ascii():
    """The whole point: a non-ASCII secret compares instead of raising."""
    assert constant_time_equals(CHINESE_PASSWORD, CHINESE_PASSWORD) is True
    assert constant_time_equals(CHINESE_PASSWORD, "wrong") is False
    assert constant_time_equals("中文", "中乂") is False


def test_constant_time_equals_keeps_ascii_semantics():
    assert constant_time_equals("abc", "abc") is True
    assert constant_time_equals("abc", "abd") is False
    assert constant_time_equals("", "") is True
    assert constant_time_equals("", "a") is False


def test_constant_time_equals_survives_lone_surrogates():
    """A mangled header or JSON escape can carry an unpaired surrogate, which
    plain UTF-8 encoding rejects -- that would trade one unhandled exception for
    another, so the helper encodes with ``surrogatepass``."""
    assert constant_time_equals("\ud800", "\ud800") is True
    assert constant_time_equals("\ud800", "a") is False


# ------------------------------------------------------------- /admin/login

def test_admin_login_accepts_a_correct_non_ascii_password(tmp_path):
    """Was HTTP 500: the correct password could never authenticate."""
    client = _client(tmp_path, CHINESE_PASSWORD)

    response = client.post("/admin/login", json={"password": CHINESE_PASSWORD})

    assert response.status_code == 200
    # The session cookie is what proves it really authenticated rather than
    # merely avoiding the crash.
    assert client.get("/admin/summary").status_code == 200


def test_admin_login_rejects_a_wrong_guess_against_a_non_ascii_password(tmp_path):
    client = _client(tmp_path, CHINESE_PASSWORD)

    response = client.post("/admin/login", json={"password": "wrong-ascii"})

    assert response.status_code == 401
    assert client.get("/admin/summary").status_code == 401


def test_admin_login_rejects_a_non_ascii_guess_against_an_ascii_password(tmp_path):
    """The reverse direction: attacker-supplied non-ASCII against an ASCII
    secret was the same 500, reachable on an unauthenticated endpoint."""
    client = _client(tmp_path, "admin-pass")

    response = client.post("/admin/login", json={"password": CHINESE_PASSWORD})

    assert response.status_code == 401


def test_admin_login_still_works_with_an_ascii_password(tmp_path):
    """Control: the fix must not disturb the path everyone actually uses."""
    client = _client(tmp_path, "admin-pass")

    assert client.post("/admin/login", json={"password": "admin-pass"}).status_code == 200
    assert client.get("/admin/summary").status_code == 200


# ------------------------------------------------------- the admin_auth cookie
#
# Driven from a raw ASGI scope rather than the TestClient on purpose. httpx
# refuses to encode a non-ASCII str into a header, so a client-level attempt
# measures the client and concludes "unreachable" -- which is what an earlier
# pass of this audit wrongly concluded. A raw socket sends arbitrary bytes and
# Starlette decodes header bytes as latin-1, mapping 0x80-0xFF to U+0080-U+00FF:
# every one of them above U+007F, which is exactly what compare_digest rejects.
# Measured that way, the cookie value really does arrive as a non-ASCII str.


def _cookie_request(raw_cookie: bytes) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/admin/summary",
        "headers": [(b"cookie", raw_cookie)],
        "query_string": b"",
    })


def test_admin_cookie_with_raw_non_ascii_bytes_is_rejected_not_fatal():
    auth = AdminAuth(admin_secret="admin-pass", admin_session_token="a" * 64)
    raw = b"admin_auth=" + bytes([0xE4, 0xB8, 0xAD]) + b"token"

    # The assertion is that this returns at all; before the fix it raised.
    assert auth.is_admin_authenticated(_cookie_request(raw)) is False


def test_a_correct_admin_cookie_still_authenticates():
    """Control: proves the test above is not passing because auth broke."""
    token = "b" * 64
    auth = AdminAuth(admin_secret="admin-pass", admin_session_token=token)

    request = _cookie_request(f"admin_auth={token}".encode("ascii"))

    assert auth.is_admin_authenticated(request) is True


# ------------------------------------------------------- /v1/m365-media sig

def test_media_proxy_rejects_a_non_ascii_signature(tmp_path):
    """Was HTTP 500 from an anonymous caller -- this route needs no API key."""
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="api-key", ADMIN_PASSWORD="admin-pass")
    )
    app.state.media_proxy_secret = "secret"
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/v1/m365-media",
        params={
            "u": SOURCE_IMAGE_URL,
            "account_id": "acct_1",
            "exp": "4102444800",
            "sig": NON_ASCII,
        },
    )

    assert response.status_code == 403
    assert app.state.media_proxy_events[-1]["phase"] == "invalid_signature"


def test_verify_signed_media_params_returns_none_for_a_non_ascii_signature():
    """Unit-level: fail-closed (None), never an exception."""
    assert verify_signed_media_proxy_params(
        "acct_1", "aHR0cHM6Ly9leGFtcGxlLmNvbQ", "4102444800", NON_ASCII, "secret"
    ) is None


# --------------------------------------------- previous_response_id signature

def test_response_id_parser_returns_none_for_a_non_ascii_signature():
    """``previous_response_id`` is a request-body field, so its signature
    segment is attacker-controlled; the parser must decline, not raise."""
    resp_id = f"{_RESP_ID_PREFIX}dG9rZW4.nonce.{NON_ASCII}"

    assert _decode_responses_session_id(resp_id, "secret") is None


def test_response_id_parser_still_accepts_a_correctly_signed_id():
    """Control: proves the test above is not passing because signing broke.

    Built with the real encoder rather than a hand-assembled id. The token
    segment is base64 of a JSON payload, so a plausible-looking literal like
    ``dG9rZW4`` decodes to nothing and the parser returns None for a reason that
    has nothing to do with the signature -- a control that would have passed
    while proving the opposite of what it claims.
    """
    secret = "secret"
    resp_id = _encode_responses_session_id("key_1", secret)

    assert _decode_responses_session_id(resp_id, secret) == "key_1"
