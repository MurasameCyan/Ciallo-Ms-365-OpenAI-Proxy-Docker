from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

_logger = logging.getLogger(__name__)


def rate_limit_error_payload(path: str, message: str) -> dict:
    if path.rstrip("/") == "/v1/messages":
        return {
            "type": "error",
            "error": {"type": "rate_limit_error", "message": message},
        }
    return {
        "error": {
            "message": message,
            "type": "rate_limit_error",
            "code": "rate_limit_exceeded",
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # Log the real exception server-side but never leak internal details
        # (file paths, hostnames, library internals) to the client.
        _logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "Internal server error", "type": "internal_error"}},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        headers = {"Access-Control-Allow-Origin": "*"}
        headers.update(exc.headers or {})
        content = (
            rate_limit_error_payload(request.url.path, str(exc.detail))
            if exc.status_code == 429
            else {"error": {"message": exc.detail, "type": "http_error"}}
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=headers,
        )
