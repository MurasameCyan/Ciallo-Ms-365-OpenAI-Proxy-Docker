from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.startup_warnings import report_startup_warnings


def test_report_startup_warnings_prints_open_api_and_admin_warnings(capsys):
    report_startup_warnings(Settings(API_KEY="", ADMIN_PASSWORD=""))

    out = capsys.readouterr().out

    assert "API_KEY is not set" in out
    assert "Web admin page is open without authentication" in out


def test_report_startup_warnings_uses_api_key_as_admin_secret(capsys):
    report_startup_warnings(Settings(API_KEY="api-key", ADMIN_PASSWORD=""))

    out = capsys.readouterr().out

    assert "API_KEY is not set" not in out
    assert "Web admin page is open without authentication" not in out


def test_create_app_keeps_startup_warning_behavior(tmp_path, capsys):
    TestClient(create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="")))

    out = capsys.readouterr().out

    assert "API_KEY is not set" in out
    assert "Web admin page is open without authentication" in out
