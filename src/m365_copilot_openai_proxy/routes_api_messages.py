from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .call_log_store import append_call_log, record_response_text
from .config import Settings
from .models import AnthropicMessagesRequest
from .response_helpers import _anthropic_stream
from .routes_api_common import request_model_alias
from .routes_media_proxy import request_media_rewriter
from .session_helpers import _messages_session_key, _persistent_session
from .substrate_client import SubstrateCopilotClient, SubstrateCopilotError
from .translator import translate_anthropic_request


def register_messages_routes(
    app: FastAPI,
    get_settings: Callable[[], Settings],
    get_copilot_client: Callable[[Request], SubstrateCopilotClient],
) -> None:
    @app.post("/v1/messages")
    async def anthropic_messages(
        raw_request: Request,
        request: AnthropicMessagesRequest,
        settings: Settings = Depends(get_settings),
        client: SubstrateCopilotClient = Depends(get_copilot_client),
    ):
        model_alias = request_model_alias(app, raw_request, settings)
        try:
            translated = translate_anthropic_request(request)
            session = _persistent_session(app, raw_request, request.model, _messages_session_key(request), request)
            media_rewriter = request_media_rewriter(app, raw_request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        _key_obj = getattr(raw_request.state, "api_key_obj", None)
        call_record = {
            "api": "anthropic",
            "endpoint": "/v1/messages",
            "time": time.strftime("%H:%M:%S"),
            "ts": time.time(),
            "stream": request.stream,
            "tools": [],
            "messages": len(request.messages),
            "model": request.model,
            "tone": (_key_obj.tone if _key_obj is not None else getattr(app.state, 'current_tone', 'Magic')) or 'Magic',
            "tool_calls_result": None if request.stream else [],
        }

        if request.stream:
            call_record["streaming"] = True
            append_call_log(app.state, call_record)
            return StreamingResponse(
                _anthropic_stream(
                    model_alias,
                    client,
                    translated.prompt,
                    translated.additional_context,
                    session,
                    on_text_done=lambda text: record_response_text(app.state, call_record, text),
                    text_transform=media_rewriter,
                ),
                media_type="text/event-stream",
            )

        try:
            text = media_rewriter(await client.chat(translated.prompt, translated.additional_context, session))
        except SubstrateCopilotError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        record_response_text(app.state, call_record, text)
        append_call_log(app.state, call_record)

        return JSONResponse({
            "id": f"msg_{uuid.uuid4().hex}",
            "type": "message",
            "role": "assistant",
            "model": model_alias,
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        })
