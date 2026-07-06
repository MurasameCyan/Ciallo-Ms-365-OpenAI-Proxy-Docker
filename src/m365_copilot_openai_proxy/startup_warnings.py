from __future__ import annotations

from .config import Settings


def report_startup_warnings(settings: Settings) -> None:
    if not settings.api_key:
        print("WARNING: API_KEY is not set. All /v1/ API endpoints are open without authentication. Set API_KEY in .env to secure your instance.")
    admin_secret = settings.admin_password or settings.api_key
    if not admin_secret:
        print("WARNING: Neither API_KEY nor ADMIN_PASSWORD is set. Web admin page is open without authentication. Set ADMIN_PASSWORD in .env to secure it.")
