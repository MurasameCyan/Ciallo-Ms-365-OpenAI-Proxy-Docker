from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.error_handlers import register_error_handlers


def test_register_error_handlers_returns_json_for_http_exceptions():
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/http-error")
    async def http_error():
        raise HTTPException(status_code=418, detail="teapot")

    response = TestClient(app).get("/http-error")

    assert response.status_code == 418
    assert response.json() == {"error": {"message": "teapot", "type": "http_error"}}
    assert response.headers["Access-Control-Allow-Origin"] == "*"


def test_http_exception_headers_are_preserved():
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/limited")
    async def limited():
        raise HTTPException(
            status_code=429,
            detail="quota",
            headers={"Retry-After": "42"},
        )

    response = TestClient(app).get("/limited")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "42"
    assert response.headers["Access-Control-Allow-Origin"] == "*"


def test_register_error_handlers_returns_json_for_unhandled_exceptions():
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert response.json() == {"error": {"message": "Internal server error", "type": "internal_error"}}
    assert response.headers["Access-Control-Allow-Origin"] == "*"
