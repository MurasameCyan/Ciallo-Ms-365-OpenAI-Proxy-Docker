from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .call_log_store import append_call_log, record_response_text
from .config import Settings
from .models import OpenAIResponsesRequest
from .response_helpers import (
    _REQUIRED_TOOL_CHOICE_ERROR,
    _resolve_responses_tool_calls,
    _responses_function_call_items,
    _responses_message_item,
    _responses_object,
    _responses_required_tool_retry_prompt,
    _responses_stream,
    _responses_stream_with_tools,
)
from .routes_api_common import (
    apply_request_model,
    effective_run_permission,
    request_model_alias,
    upstream_http_error,
)
from .routes_media_proxy import request_media_rewriter
from .session_helpers import (
    _decode_responses_response_claims,
    _decode_responses_session_id,
    _encode_responses_session_id,
    _persistent_session,
    _responses_session_key,
    _responses_store_key,
    _responses_store_key_belongs_to_request,
)
from .substrate_client import SubstrateCopilotClient, SubstrateCopilotError
from .tone_resolver import normalized_session_model
from .tool_call_parser import (
    _RETRY_INSTRUCTION,
    _has_read_only_intent,
    _looks_like_fake_file_claim,
    _strip_tool_call_blocks,
)
from .translator import (
    _responses_content_text,
    _responses_last_action_index,
    responses_tool_config,
    translate_responses_request,
)


class _ResponsesStreamingResponse(StreamingResponse):
    """Own the request lock until the SSE transport has fully terminated."""

    def __init__(
        self,
        stream: AsyncIterator[str],
        *,
        on_request_done: Callable[[bool], None],
        response_lock=None,
        **kwargs,
    ) -> None:
        super().__init__(stream, **kwargs)
        self._on_request_done = on_request_done
        self._response_lock = response_lock

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                close = getattr(self.body_iterator, "aclose", None)
                if close is not None:
                    await close()
            finally:
                try:
                    self._on_request_done(False)
                finally:
                    if self._response_lock is not None:
                        self._response_lock.release()


def register_responses_routes(
    app: FastAPI,
    get_settings: Callable[[], Settings],
    get_copilot_client: Callable[[Request], SubstrateCopilotClient],
) -> None:
    @app.post("/v1/responses")
    async def openai_responses(
        raw: Request,
        settings: Settings = Depends(get_settings),
    ):
        log = logging.getLogger("copilot_proxy")
        model_alias = request_model_alias(app, raw, settings)
        try:
            body = await raw.json()
            request = OpenAIResponsesRequest.model_validate(body)
            choice, tools = responses_tool_config(
                request.tools,
                request.tool_choice,
                request.parallel_tool_calls,
            )
            tool_names = {
                tool.function.name
                for tool in tools
                if tool.function is not None
            }
            tool_namespaces = {
                tool.function.name: tool.function.namespace
                for tool in tools
                if tool.function is not None
                and isinstance(getattr(tool.function, "namespace", None), str)
                and tool.function.namespace.strip()
            }
            strict_tool_schemas = {
                tool.function.name: tool.function.parameters or {"type": "object"}
                for tool in tools
                if tool.function is not None
                and getattr(tool.function, "strict", False) is True
            }
            # Apply the provider-specific upstream selector: M365 tone or
            # Consumer mode. Session suffix normalization remains M365-specific.
            client, resolved_tone, is_consumer = apply_request_model(
                app, raw, get_copilot_client, request.model
            )
            key_obj = getattr(raw.state, "api_key_obj", None)
            key_system_prompt = (
                (key_obj.system_prompt if key_obj is not None else "") or ""
            ).strip()
            system_override = key_system_prompt or getattr(
                app.state, "system_prompt", ""
            )
            run_permission = effective_run_permission(app, key_obj)
            user_texts = (
                [request.input]
                if isinstance(request.input, str)
                else [
                    _responses_content_text(item.get("content"))
                    for item in request.input
                    if isinstance(item, dict) and item.get("role") == "user"
                ]
            )
            latest_user_text = user_texts[-1] if user_texts else ""
            read_only_guard = (
                run_permission == "read_only"
                or _has_read_only_intent(latest_user_text)
            )
            previous_session_key = _decode_responses_session_id(
                request.previous_response_id,
                app.state.media_proxy_secret,
            )
            previous_session = (
                app.state.session_store.get_existing(previous_session_key)
                if (
                    not is_consumer
                    and previous_session_key is not None
                    and _responses_store_key_belongs_to_request(
                        raw, previous_session_key
                    )
                )
                else None
            )
            response_claims = (
                _decode_responses_response_claims(
                    request.previous_response_id,
                    app.state.media_proxy_secret,
                )
                if not is_consumer
                else None
            )
            if not is_consumer and request.previous_response_id is not None:
                if (
                    previous_session is None
                    or response_claims is None
                    or response_claims[0] != previous_session_key
                ):
                    raise ValueError(
                        "Invalid or expired Responses previous_response_id."
                    )
            incremental_output_ids = {
                str(item.get("call_id") or "").strip()
                for item in request.input
                if isinstance(request.input, list)
                and isinstance(item, dict)
                and item.get("type") == "function_call_output"
            }
            incremental_output_ids.discard("")
            last_action_index = _responses_last_action_index(request.input)
            is_tool_output_continuation = (
                last_action_index is not None
                and isinstance(request.input[last_action_index], dict)
                and request.input[last_action_index].get("type")
                == "function_call_output"
            )
            translated = translate_responses_request(
                request,
                system_override=system_override,
                consumer_tool_max_chars=(
                    settings.consumer_prompt_max_chars if is_consumer else None
                ),
                allow_unmatched_function_call_outputs=(
                    previous_session is not None
                ),
            )
            required_tool_retry_prompt = _responses_required_tool_retry_prompt(
                choice,
                tool_names,
                translated.prompt,
            )
            if (
                previous_session is None
                and read_only_guard
                and required_tool_retry_prompt
                and not any(
                    name.lower()
                    in {"read", "grep", "glob", "ls", "searchcodebase"}
                    for name in tool_names
                )
            ):
                raise ValueError(
                    "Required tool_choice conflicts with read-only permission."
                )
            media_rewriter = request_media_rewriter(app, raw)
            session_key = None
            session = None
            if not is_consumer:
                if previous_session is not None:
                    session = previous_session
                    session_key = previous_session_key
                else:
                    fallback_key = _responses_session_key(request)
                    if (
                        request.previous_response_id is None
                        and not (raw.headers.get("x-m365-session-id") or "").strip()
                        and not normalized_session_model(request.model).endswith(":persist")
                    ):
                        fallback_key = f"responses_{uuid.uuid4().hex}"
                    session = _persistent_session(
                        app,
                        raw,
                        normalized_session_model(request.model),
                        fallback_key,
                    )
                    session_key = _responses_store_key(app, session)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        continuation_id = (
            request.previous_response_id
            if not is_consumer and previous_session is not None
            else None
        )
        resp_id = (
            _encode_responses_session_id(
                session_key,
                app.state.media_proxy_secret,
            )
            if session_key
            else f"resp_{uuid.uuid4().hex}"
        )
        pending_response_calls: list[str] | None = None
        continuation_reservation: str | None = None
        response_lock = session.response_lock if session is not None else None
        lock_owned = False

        try:
            if response_lock is not None:
                await response_lock.acquire()
                lock_owned = True

            if previous_session is not None:
                if previous_session.latest_response_id != request.previous_response_id:
                    if request.previous_response_id in previous_session.consumed_response_ids:
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                "Responses previous_response_id has already been "
                                "submitted."
                            ),
                        )
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "M365 previous_response_id must reference the latest "
                            "response."
                        ),
                    )
                if not previous_session.allows_response_outputs(
                    request.previous_response_id or "",
                    incremental_output_ids,
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Responses function_call_output does not match the issued "
                            "previous_response_id; all issued outputs must be "
                            "submitted together."
                        ),
                    )
                if is_tool_output_continuation:
                    read_only_guard = (
                        read_only_guard
                        or previous_session.response_is_read_only(
                            request.previous_response_id or ""
                        )
                    )

            if read_only_guard and required_tool_retry_prompt and not any(
                name.lower() in {"read", "grep", "glob", "ls", "searchcodebase"}
                for name in tool_names
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Required tool_choice conflicts with read-only permission.",
                )

            if continuation_id is not None:
                continuation_reservation = (
                    previous_session.begin_response_continuation(continuation_id)
                )
                if continuation_reservation is None:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Responses previous_response_id has already been submitted."
                        ),
                    )

            def record_issued_response(response_id: str, call_ids: list[str]) -> None:
                nonlocal pending_response_calls
                if session is None:
                    return
                if continuation_id is None:
                    session.record_response(response_id, call_ids, read_only_guard)
                    return
                pending_response_calls = list(call_ids)

            def finish_continuation(success: bool) -> None:
                if continuation_id is None or continuation_reservation is None:
                    return
                if success and pending_response_calls is not None:
                    previous_session.complete_response_continuation(
                        continuation_id,
                        continuation_reservation,
                        resp_id,
                        pending_response_calls,
                        read_only_guard,
                    )
                    return
                previous_session.finish_response_continuation(
                    continuation_id,
                    continuation_reservation,
                    False,
                )

            call_record = {
                "api": "responses",
                "endpoint": "/v1/responses",
                "time": time.strftime("%H:%M:%S"),
                "ts": time.time(),
                "stream": request.stream,
                "tools": sorted(tool_names),
                "tool_choice": choice[0],
                "parallel_tool_calls": choice[2],
                "messages": len(request.input) if isinstance(request.input, list) else 1,
                "model": request.model,
                "tone": resolved_tone,
                "run_permission": run_permission,
                "read_only_guard": read_only_guard,
                "tool_calls_result": None if request.stream else [],
            }

            # Echo the canonical Responses value. Input validation accepts harmless
            # case/whitespace variations, but the SDK only accepts the lower-case
            # enum (or the named-function object).
            response_tool_choice = (
                {"type": "function", "name": choice[1]}
                if choice[0] == "tool"
                else choice[0]
            )
            response_tools = request.tools or []

            if request.stream:
                call_record["streaming"] = True
                append_call_log(app.state, call_record)
                if tool_names:
                    stream = _responses_stream_with_tools(
                        model_alias,
                        client,
                        translated.prompt,
                        translated.additional_context,
                        session,
                        on_text_done=lambda text: record_response_text(
                            app.state, call_record, text
                        ),
                        text_transform=media_rewriter,
                        response_id=resp_id,
                        images=translated.images,
                        response_tools=response_tools,
                        tool_choice=response_tool_choice,
                        parallel_tool_calls=choice[2],
                        previous_response_id=request.previous_response_id,
                        instructions=request.instructions,
                        tool_names=tool_names,
                        strict_tool_schemas=strict_tool_schemas,
                        tool_namespaces=tool_namespaces,
                        read_only_guard=read_only_guard,
                        call_record=call_record,
                        required_tool_retry_prompt=required_tool_retry_prompt,
                        on_response_issued=record_issued_response,
                        on_request_done=finish_continuation,
                    )
                else:
                    stream = _responses_stream(
                        model_alias,
                        client,
                        translated.prompt,
                        translated.additional_context,
                        session,
                        on_text_done=lambda text: record_response_text(
                            app.state, call_record, text
                        ),
                        text_transform=media_rewriter,
                        response_id=resp_id,
                        images=translated.images,
                        response_tools=response_tools,
                        tool_choice=response_tool_choice,
                        parallel_tool_calls=choice[2],
                        previous_response_id=request.previous_response_id,
                        instructions=request.instructions,
                        call_record=call_record,
                        on_response_issued=record_issued_response,
                        on_request_done=finish_continuation,
                    )
                response = _ResponsesStreamingResponse(
                    stream,
                    on_request_done=finish_continuation,
                    response_lock=response_lock,
                    media_type="text/event-stream",
                )
                lock_owned = False
                return response

            return await _complete_nonstream_response(
                app=app,
                client=client,
                translated=translated,
                session=session,
                model_alias=model_alias,
                resp_id=resp_id,
                request=request,
                response_tools=response_tools,
                response_tool_choice=response_tool_choice,
                tool_names=tool_names,
                strict_tool_schemas=strict_tool_schemas,
                tool_namespaces=tool_namespaces,
                read_only_guard=read_only_guard,
                choice=choice,
                required_tool_retry_prompt=required_tool_retry_prompt,
                media_rewriter=media_rewriter,
                call_record=call_record,
                record_issued_response=record_issued_response,
                finish_continuation=finish_continuation,
                log=log,
            )
        finally:
            if lock_owned:
                if continuation_id is not None and continuation_reservation is not None:
                    previous_session.finish_response_continuation(
                        continuation_id,
                        continuation_reservation,
                        False,
                    )
                response_lock.release()


async def _complete_nonstream_response(
    *,
    app,
    client,
    translated,
    session,
    model_alias,
    resp_id,
    request,
    response_tools,
    response_tool_choice,
    tool_names,
    strict_tool_schemas,
    tool_namespaces,
    read_only_guard,
    choice,
    required_tool_retry_prompt,
    media_rewriter,
    call_record,
    record_issued_response,
    finish_continuation,
    log,
):
    try:
        raw_text = await client.chat(
            translated.prompt,
            translated.additional_context,
            session,
            translated.images,
        )
    except SubstrateCopilotError as exc:
        finish_continuation(False)
        call_record["error"] = str(exc)
        call_record["tool_calls_result"] = []
        record_response_text(app.state, call_record, "")
        append_call_log(app.state, call_record)
        raise upstream_http_error(exc) from exc

    tool_calls = _resolve_responses_tool_calls(
        raw_text,
        tool_names,
        read_only_guard,
        choice[2],
        strict_tool_schemas,
        tool_namespaces,
    )
    if not tool_calls and required_tool_retry_prompt:
        try:
            raw_text = await client.chat(
                required_tool_retry_prompt,
                translated.additional_context,
                session,
                translated.images,
            )
        except SubstrateCopilotError as exc:
            finish_continuation(False)
            call_record["retried"] = True
            call_record["error"] = str(exc)
            call_record["tool_calls_result"] = []
            record_response_text(app.state, call_record, raw_text)
            append_call_log(app.state, call_record)
            raise upstream_http_error(exc) from exc
        tool_calls = _resolve_responses_tool_calls(
            raw_text,
            tool_names,
            read_only_guard,
            choice[2],
            strict_tool_schemas,
            tool_namespaces,
        )
        call_record["retried"] = True
        if not tool_calls:
            finish_continuation(False)
            call_record["tool_calls_result"] = []
            record_response_text(app.state, call_record, raw_text)
            append_call_log(app.state, call_record)
            raise HTTPException(
                status_code=502,
                detail=_REQUIRED_TOOL_CHOICE_ERROR,
            )
    elif (
        not tool_calls
        and tool_names
        and not read_only_guard
        and _looks_like_fake_file_claim(raw_text)
    ):
        log.info("  fake file claim detected, forcing corrective retry")
        try:
            retry_prompt = (
                f"{_RETRY_INSTRUCTION}\n\nOriginal request:\n{translated.prompt}"
            )
            retry_text = await client.chat(
                retry_prompt,
                translated.additional_context,
                session,
                translated.images,
            )
            retry_calls = _resolve_responses_tool_calls(
                retry_text,
                tool_names,
                read_only_guard,
                choice[2],
                strict_tool_schemas,
                tool_namespaces,
            )
            if retry_calls:
                raw_text, tool_calls = retry_text, retry_calls
                call_record["retried"] = True
        except SubstrateCopilotError:
            pass

    call_record["tool_calls_result"] = [
        (call.get("function") or {}).get("name")
        for call in tool_calls
    ]
    record_response_text(app.state, call_record, raw_text)
    append_call_log(app.state, call_record)

    text = _strip_tool_call_blocks(raw_text) if tool_names else raw_text
    text = media_rewriter(text)
    output: list[dict] = []
    if text or not tool_calls:
        output.append(_responses_message_item(text))
    output.extend(_responses_function_call_items(tool_calls))
    if session is not None:
        record_issued_response(
            resp_id,
            [
                item["call_id"]
                for item in output
                if item["type"] == "function_call"
            ],
        )
    finish_continuation(True)
    return JSONResponse(_responses_object(
        resp_id,
        model_alias,
        int(time.time()),
        "completed",
        output,
        response_tools=response_tools,
        tool_choice=response_tool_choice,
        parallel_tool_calls=choice[2],
        previous_response_id=request.previous_response_id,
        instructions=request.instructions,
        include_usage=True,
    ))
