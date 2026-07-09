from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.refresh_scheduler import (
    _identity_conflict,
    _is_logged_out_shell,
)


def _jwt(claims: dict) -> str:
    """Build a decodable (unsigned) JWT whose payload carries the given claims."""
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.sig"


def test_is_logged_out_shell_flags_no_account_on_start():
    assert _is_logged_out_shell("https://m365.cloud.microsoft/chat?from=NoAccountOnStart") is True


def test_is_logged_out_shell_ignores_authenticated_chat_url():
    assert _is_logged_out_shell("https://m365.cloud.microsoft/chat") is False


def test_identity_conflict_true_when_emails_differ():
    token = _jwt({"email": "yuzu@office.bo.edu.kg"})
    assert _identity_conflict("gayhub@office.bo.edu.kg", token) is True


def test_identity_conflict_false_when_emails_match_case_insensitive():
    token = _jwt({"email": "Gayhub@office.bo.edu.kg"})
    assert _identity_conflict("gayhub@office.bo.edu.kg", token) is False


def test_identity_conflict_permissive_when_account_has_no_email():
    token = _jwt({"email": "anyone@example.com"})
    assert _identity_conflict("", token) is False


def test_identity_conflict_permissive_when_token_has_no_email():
    token = _jwt({"sub": "no-email-claim"})
    assert _identity_conflict("gayhub@office.bo.edu.kg", token) is False
