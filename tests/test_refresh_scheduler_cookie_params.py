from __future__ import annotations

from m365_copilot_openai_proxy.refresh_scheduler import _cdp_cookie_params


def test_cdp_cookie_params_converts_tampermonkey_cookie_shape_for_cdp():
    params, expires, session_persisted = _cdp_cookie_params(
        {
            "name": "ESTSAUTH",
            "value": "token-value",
            "domain": ".login.microsoftonline.com",
            "path": "/",
            "sameSite": "no_restriction",
            "secure": True,
            "httpOnly": True,
            "expirationDate": 1_783_394_000_000,
        },
        now=1_783_390_000,
    )

    assert params["url"] == "https://login.microsoftonline.com/"
    assert params["domain"] == ".login.microsoftonline.com"
    assert params["sameSite"] == "None"
    assert params["expires"] == 1_783_394_000
    assert expires == 1_783_394_000
    assert session_persisted is False


def test_cdp_cookie_params_omits_domain_for_host_prefix_cookie():
    params, expires, session_persisted = _cdp_cookie_params(
        {
            "name": "__Host-MSAAUTH",
            "value": "token-value",
            "domain": "login.microsoftonline.com",
            "path": "/account",
            "secure": False,
        },
        now=1_783_390_000,
    )

    assert params["url"] == "https://login.microsoftonline.com/"
    assert "domain" not in params
    assert params["path"] == "/"
    assert params["secure"] is True
    assert expires == 1_783_390_000 + 12 * 60 * 60
    assert session_persisted is True
