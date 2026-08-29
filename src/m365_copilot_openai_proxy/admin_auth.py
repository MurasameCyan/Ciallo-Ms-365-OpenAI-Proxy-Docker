from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.responses import JSONResponse

from .auth_helpers import constant_time_equals
from .config import Settings


@dataclass
class AdminAuth:
    admin_secret: str
    admin_session_token: str | None
    login_failures: dict[str, list[float]] = field(default_factory=dict)
    login_rate_limit: int = 5
    login_lockout_sec: float = 60.0

    def is_admin_authenticated(self, request: Request) -> bool:
        if not self.admin_secret:
            return True
        if self.admin_session_token is None:
            return False
        cookie_val = request.cookies.get("admin_auth", "")
        return constant_time_equals(cookie_val, self.admin_session_token)

    def require_admin(self, request: Request):
        if self.admin_secret and not self.is_admin_authenticated(request):
            return JSONResponse({"error": {"message": "Admin authentication required", "type": "auth_error"}}, status_code=401)
        return None


def create_admin_auth(settings: Settings) -> AdminAuth:
    admin_secret = settings.admin_password or settings.api_key
    return AdminAuth(
        admin_secret=admin_secret,
        admin_session_token=secrets.token_hex(32) if admin_secret else None,
    )
