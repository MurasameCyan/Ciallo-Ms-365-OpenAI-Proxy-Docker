from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.cli import (
    _m365_chat_url,
    _select_substrate_token,
    _token_identity_email,
)


def _substrate_jwt(email: str = "", *, expired: bool = False) -> str:
    """Build a decodable (unsigned) substrate JWT for the given identity.

    aud must start with https://substrate.office.com/ to satisfy
    is_substrate_token_claims, and exp must be comfortably in the future so
    _is_substrate_token treats it as usable (it rejects tokens within 30s of exp).
    """
    exp = int(time.time()) + (-3600 if expired else 3600)
    claims: dict = {"aud": "https://substrate.office.com/", "exp": exp}
    if email:
        claims["email"] = email
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.sig"


def test_token_identity_email_reads_email_claim_lowercased():
    token = _substrate_jwt("Gayhub@office.bo.edu.kg")
    assert _token_identity_email(token) == "gayhub@office.bo.edu.kg"


def test_token_identity_email_empty_for_undecodable_token():
    assert _token_identity_email("not-a-jwt") == ""


def test_select_prefers_matching_identity_over_first_valid():
    yuzu = _substrate_jwt("yuzu@office.bo.edu.kg")
    gayhub = _substrate_jwt("gayhub@office.bo.edu.kg")
    # yuzu comes first, but the expected identity is gayhub -> must skip yuzu.
    assert _select_substrate_token([yuzu, gayhub], "gayhub@office.bo.edu.kg") == gayhub


def test_select_returns_none_when_no_candidate_matches_expected():
    yuzu = _substrate_jwt("yuzu@office.bo.edu.kg")
    assert _select_substrate_token([yuzu], "gayhub@office.bo.edu.kg") is None


def test_select_falls_back_to_first_valid_without_expected_email():
    yuzu = _substrate_jwt("yuzu@office.bo.edu.kg")
    gayhub = _substrate_jwt("gayhub@office.bo.edu.kg")
    assert _select_substrate_token([yuzu, gayhub], "") == yuzu


def test_select_skips_expired_tokens():
    expired = _substrate_jwt("gayhub@office.bo.edu.kg", expired=True)
    fresh = _substrate_jwt("gayhub@office.bo.edu.kg")
    assert _select_substrate_token([expired, fresh], "gayhub@office.bo.edu.kg") == fresh


def test_m365_chat_url_plain_without_hint():
    assert _m365_chat_url("") == "https://m365.cloud.microsoft/chat"


def test_m365_chat_url_appends_encoded_login_hint():
    assert (
        _m365_chat_url("gayhub@office.bo.edu.kg")
        == "https://m365.cloud.microsoft/chat?login_hint=gayhub%40office.bo.edu.kg"
    )
