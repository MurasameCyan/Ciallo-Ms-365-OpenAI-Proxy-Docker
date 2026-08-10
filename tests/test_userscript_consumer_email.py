from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


SCRIPT = (Path(__file__).resolve().parents[1] / "get_token.user.js").read_text(encoding="utf-8")
START_MARKER = "    // ---- Consumer account email resolution --------------------------------"
END_MARKER = "    // ---- End consumer account email resolution -----------------------------"


def _email_resolution_source() -> str:
    assert START_MARKER in SCRIPT
    assert END_MARKER in SCRIPT
    return SCRIPT.split(START_MARKER, 1)[1].split(END_MARKER, 1)[0]


def _resolve_in_sequence(steps: list[dict]) -> list[str]:
    source = _email_resolution_source()
    program = f"""
const storageValues = {{}};
const localStorage = {{
    get length() {{ return Object.keys(storageValues).length; }},
    key(index) {{ return Object.keys(storageValues)[index] ?? null; }},
    getItem(key) {{ return Object.prototype.hasOwnProperty.call(storageValues, key) ? storageValues[key] : null; }},
}};
{source}
const steps = {json.dumps(steps)};
const results = [];
for (const step of steps) {{
    for (const key of Object.keys(storageValues)) delete storageValues[key];
    Object.assign(storageValues, step.storage);
    results.push(getConsumerAccountEmail(step.cookies || []));
}}
process.stdout.write(JSON.stringify(results));
"""
    completed = subprocess.run(
        ["node", "-e", program],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _resolve_identity(
    storage: dict, cookies: list[dict] | None = None, access_token: str = ""
) -> dict:
    source = _email_resolution_source()
    program = f"""
const storageValues = {json.dumps(storage)};
const localStorage = {{
    get length() {{ return Object.keys(storageValues).length; }},
    key(index) {{ return Object.keys(storageValues)[index] ?? null; }},
    getItem(key) {{ return Object.prototype.hasOwnProperty.call(storageValues, key) ? storageValues[key] : null; }},
}};
{source}
const email = getConsumerAccountEmail({json.dumps(cookies or [])}, {json.dumps(access_token)});
process.stdout.write(JSON.stringify({{email, account_id: getConsumerAccountId()}}));
"""
    completed = subprocess.run(
        ["node", "-e", program],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _account(home_id: str, local_id: str, email: str | None) -> str:
    record = {
        "homeAccountId": home_id,
        "localAccountId": local_id,
        "tenantId": "consumer",
    }
    if email is not None:
        record["username"] = email
    return json.dumps(record)


def _access_token(home_id: str, local_id: str, token: str) -> str:
    return json.dumps(
        {
            "credentialType": "AccessToken",
            "homeAccountId": home_id,
            "localAccountId": local_id,
            "target": "ChatAI.ReadWrite",
            "secret": token,
        }
    )


def test_userscript_prefers_active_msal_account_email():
    storage = {
        "msal.account.keys": json.dumps(["account-a", "account-b"]),
        "account-a": _account("home-a", "local-a", "old@example.com"),
        "account-b": _account("home-b", "local-b", "Active.Person@Example.COM"),
        "msal.client.active-account-filters": json.dumps(
            {"homeAccountId": "home-b", "localAccountId": "local-b", "tenantId": "consumer"}
        ),
    }

    assert _resolve_in_sequence([{"storage": storage}]) == ["active.person@example.com"]
    assert _resolve_identity(storage) == {
        "email": "active.person@example.com",
        "account_id": "home:home-b",
    }


def test_userscript_only_falls_back_to_a_unique_structured_account():
    unique_storage = {
        "msal.account.keys": json.dumps(["account-a"]),
        "account-a": _account("home-a", "local-a", "Only.Person@Example.COM"),
    }
    ambiguous_storage = {
        "msal.account.keys": json.dumps(["account-a", "account-b"]),
        "account-a": _account("home-a", "local-a", "one@example.com"),
        "account-b": _account("home-b", "local-b", "two@example.com"),
    }

    assert _resolve_in_sequence(
        [{"storage": unique_storage}, {"storage": ambiguous_storage}]
    ) == ["only.person@example.com", ""]


def test_userscript_does_not_treat_chat_content_as_account_email():
    storage = {
        "copilot.chat.history": json.dumps(
            {"messages": [{"text": "Please write to someone-from-chat@example.com"}]}
        )
    }

    assert _resolve_in_sequence([{"storage": storage}]) == [""]


def test_userscript_email_cache_is_bound_to_the_active_account_id():
    account_a = {
        "msal.account.keys": json.dumps(["account-a", "account-b"]),
        "account-a": _account("home-a", "local-a", "a@example.com"),
        "account-b": _account("home-b", "local-b", None),
        "msal.client.active-account-filters": json.dumps({"homeAccountId": "home-a"}),
    }
    account_a_temporarily_missing_email = {
        **account_a,
        "account-a": _account("home-a", "local-a", None),
    }
    account_b = {
        **account_a_temporarily_missing_email,
        "msal.client.active-account-filters": json.dumps({"homeAccountId": "home-b"}),
    }

    assert _resolve_in_sequence(
        [
            {"storage": account_a},
            {"storage": account_a_temporarily_missing_email},
            {"storage": account_b},
        ]
    ) == ["a@example.com", "a@example.com", ""]


@pytest.mark.parametrize("cookie_name", ["MSPPre", "JSHP"])
def test_userscript_uses_explicit_identity_cookie_email_as_secondary_fallback(cookie_name):
    storage = {
        "msal.account.keys": json.dumps(["account-a"]),
        "account-a": _account("home-a", "local-a", None),
        "msal.client.active-account-filters": json.dumps({"homeAccountId": "home-a"}),
    }
    cookies = [
        {"name": "chat-history", "value": "wrong-from-chat@example.com"},
        {"name": cookie_name, "value": "login%3Dcookie.person%40example.com"},
    ]

    assert _resolve_in_sequence([{"storage": storage, "cookies": cookies}]) == [
        "cookie.person@example.com"
    ]


def test_userscript_consumer_push_includes_email_without_dom_or_tailwind_scraping():
    source = _email_resolution_source()

    assert "getConsumerAccountEmail(cookies, latestConsumerToken)" in SCRIPT
    assert "consumer_account_id: consumerAccountId" in SCRIPT
    assert "document." not in source
    assert "querySelector" not in source
    assert "class*=" not in source


def test_userscript_rejects_a_captured_token_after_the_active_account_switches():
    storage = {
        "msal.account.keys": json.dumps(["account-a", "account-b"]),
        "account-a": _account("home-a", "local-a", "a@example.com"),
        "account-b": _account("home-b", "local-b", "b@example.com"),
        "token-a": _access_token("home-a", "local-a", "token-from-socket-a"),
        "token-b": _access_token("home-b", "local-b", "other-token-b"),
        "msal.client.active-account-filters": json.dumps(
            {"homeAccountId": "home-b", "localAccountId": "local-b"}
        ),
    }

    assert _resolve_identity(storage, access_token="token-from-socket-a") == {
        "email": "",
        "account_id": "",
    }


def test_userscript_accepts_a_token_matching_the_active_account():
    storage = {
        "msal.account.keys": json.dumps(["account-a", "account-b"]),
        "account-a": _account("home-a", "local-a", "a@example.com"),
        "account-b": _account("home-b", "local-b", "b@example.com"),
        "token-a": _access_token("home-a", "local-a", "token-from-socket-a"),
        "msal.client.active-account-filters": json.dumps(
            {"homeAccountId": "home-a", "localAccountId": "local-a"}
        ),
    }

    assert _resolve_identity(storage, access_token="token-from-socket-a") == {
        "email": "a@example.com",
        "account_id": "home:home-a",
    }


def test_userscript_rejects_a_token_without_one_matching_msal_subject():
    storage = {
        "msal.account.keys": json.dumps(["account-a"]),
        "account-a": _account("home-a", "local-a", "a@example.com"),
        "msal.client.active-account-filters": json.dumps({"homeAccountId": "home-a"}),
    }

    assert _resolve_identity(storage, access_token="unmatched-token") == {
        "email": "",
        "account_id": "",
    }
    assert "if (!consumerAccountId)" in SCRIPT
