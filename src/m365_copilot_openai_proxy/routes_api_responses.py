from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .call_log_store import append_call_log, record_response_text
from .config import Settings
from .models import OpenAIResponsesRequest
from .response_helpers import _responses_stream
from .routes_api_common import request_model_alias
from .routes_media_proxy import request_media_rewriter
from .session_helpers import _persistent_session, _responses_session_key
from .substrate_client import SubstrateCopilotClient, SubstrateCopilotError
from .translator import translate_responses_request


def register_responses_routes(
    app: FastAPI,
    get_settings: Callable[[], Settings],
    get_copilot_client: Callable[[Request], SubstrateCopilotClient],
) -> None:
    @app.post("/v1/responses")
    async def openai_responses(
        raw: Request,
        settings: Settings = Depends(get_settings),
        client: SubstrateCopilotClient = Depends(get_copilot_client),
    ):
        model_alias = request_model_alias(app, raw, settings)
        body = await raw.json()
        try:
            request = OpenAIResponsesRequest.model_validate(body)
            translated = translate_responses_request(request)
            session = _persistent_session(app, raw, request.model, _responses_session_key(request))
            media_rewriter = request_media_rewriter(app, raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        _key_obj = getattr(raw.state, "api_key_obj", None)
        call_record = {
            "api": "responses",
            "endpoint": "/v1/responses",
            "time": time.strftime("%H:%M:%S"),
            "ts": time.time(),
            "stream": request.stream,
            "tools": [],
            "messages": len(request.input) if isinstance(request.input, list) else 1,
            "model": request.model,
            "tone": (_key_obj.tone if _key_obj is not None else getattr(app.state, 'current_tone', 'Magic')) or 'Magic',
            "tool_calls_result": None if request.stream else [],
        }

        if request.stream:
            call_record["streaming"] = True
            append_call_log(app.state, call_record)
            return StreamingResponse(
                _responses_stream(
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
            "id": f"resp_{uuid.uuid4().hex}",
            "object": "response",
            "created_at": int(time.time()),
            "model": model_alias,
            "output": [{
                "type": "message",
                "id": f"msg_{uuid.uuid4().hex}",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }],
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        })
