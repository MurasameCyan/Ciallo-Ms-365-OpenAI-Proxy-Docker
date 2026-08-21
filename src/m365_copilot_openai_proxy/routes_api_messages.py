from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .call_log_store import append_call_log, record_response_text
from .config import Settings
from .models import AnthropicMessagesRequest
from .response_helpers import _anthropic_stream
from .routes_api_common import (
    TOOL_CALLING_HEADER,
    apply_request_model,
    effective_run_permission,
    effective_tool_planning_mode,
    no_tool_calls_note,
    prose_with_reason,
    request_model_alias,
    required_tool_call_error,
    upstream_http_error,
)
from .routes_media_proxy import request_media_rewriter
from .session_helpers import (
    _messages_session_key,
    _persistent_session,
    _studio_session_namespace,
)
from .session_store import PersistentSession
from .sse_stream import ANTHROPIC_PING, keepalive_stream, merge_sse_headers
from .substrate_client import SubstrateCopilotClient, SubstrateCopilotError, SubstrateThrottled
from .studio_planner import (
    PlannerTurn,
    planned_or_answered,
    planned_or_streamed,
)
from .tone_options import effective_tool_calling, tone_tool_calling
from .tone_resolver import normalized_session_model
from .tool_call_parser import (
    _RETRY_INSTRUCTION,
    _extract_prose_write,
    _extract_tool_calls,
    _filter_read_only_tool_calls,
    _filter_schema_valid_tool_calls,
    _has_read_only_intent,
    _looks_like_fake_file_claim,
    _strip_tool_call_blocks,
    split_no_tool_marker,
)
from .translator import (
    _anthropic_tools_as_openai,
    effective_tools,
    flatten_content,
    normalize_tool_choice,
    tool_description_lines,
    translate_anthropic_request,
)
from .tool_router import build_router_prompt, routed_or_answered, routed_or_streamed, router_applies
from .usage_store import estimate_upstream_input_tokens
from .usage_store import anthropic_usage, usage_for_record


def _tool_use_blocks(tool_calls: list[dict]) -> list[dict]:
    """Convert parsed OpenAI-shaped tool_calls into Anthropic ``tool_use`` blocks.

    Anthropic carries the arguments as a decoded ``input`` object, not the JSON
    string OpenAI uses, so a client that cannot parse a string payload still sees
    a usable tool call.
    """
    blocks: list[dict] = []
    for call in tool_calls:
        fn = call.get("function") or {}
        raw = fn.get("arguments")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError, ValueError):
            parsed = None
        blocks.append({
            "type": "tool_use",
            "id": call.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
            "name": fn.get("name") or "tool",
            "input": parsed if isinstance(parsed, dict) else {"raw": raw},
        })
    return blocks


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
    ):
        _log = logging.getLogger("copilot_proxy")
        model_alias = request_model_alias(app, raw_request, settings)
        # Effective list, not the raw one: tool_choice={"type":"none"} empties it so
        # parsing and the corrective retry are disabled along with the prompt
        # injection, and {"type":"tool","name":X} narrows it to X.
        choice = normalize_tool_choice(request.tool_choice)
        _tools = effective_tools(request.tools, choice)
        tool_names = {t.name for t in _tools if getattr(t, "name", "")} if _tools else set()
        # Anthropic calls the argument schema input_schema; OpenAI calls it
        # parameters. Same thing, and the same use here: validate what we parsed
        # back out of prose before handing it to the client.
        tool_schemas = {
            t.name: getattr(t, "input_schema", None)
            for t in (_tools or [])
            if getattr(t, "name", "")
        }
        try:
            # Apply the provider-specific upstream selector: M365 tone or
            # Consumer mode. Session suffix normalization remains M365-specific.
            client, resolved_tone, is_consumer = apply_request_model(
                app, raw_request, get_copilot_client, request.model
            )
            # System prompt: the key's own override wins, else the global one --
            # same precedence the OpenAI chat route uses.
            _key_obj = getattr(raw_request.state, "api_key_obj", None)
            _key_sp = ((_key_obj.system_prompt if _key_obj is not None else "") or "").strip()
            _system_override = _key_sp or getattr(app.state, "system_prompt", "")
            run_permission = effective_run_permission(app, _key_obj)
            read_only_guard = run_permission == "read_only" or _has_read_only_intent(
                *(flatten_content(m.content) for m in request.messages if m.role == "user")
            )
            translated = translate_anthropic_request(
                request,
                system_override=_system_override,
                consumer_tool_max_chars=(
                    settings.consumer_prompt_max_chars if is_consumer else None
                ),
            )
            session = None
            if not is_consumer:
                session = _persistent_session(
                    app,
                    raw_request,
                    normalized_session_model(request.model),
                    _messages_session_key(request),
                    request,
                )
            media_rewriter = request_media_rewriter(app, raw_request)
            # Router mode: see routes_api_chat for the reasoning. Same shape, same
            # non-incremental tool-contract-free view of the conversation, and the
            # same Consumer handling (its prompt ceiling is the adapter's job).
            router_prompt = ""
            planning_mode = effective_tool_planning_mode(app, _key_obj)
            actual_planning = planning_mode
            studio_client = None
            studio_session = None
            studio_translated = None
            studio_snapshot = None
            studio_fallback = ""
            if _tools and planning_mode == "studio":
                account = getattr(raw_request.state, "account", None)
                if is_consumer:
                    actual_planning = "router"
                    studio_fallback = "unsupported_provider"
                else:
                    studio_snapshot = (
                        app.state.account_store.studio_client_snapshot(account.id)
                        if account is not None
                        else None
                    )
                if not is_consumer and studio_snapshot is None:
                    actual_planning = "router"
                    studio_fallback = "not_ready"
                elif not is_consumer:
                    studio_token, studio_agent_id = studio_snapshot
                    studio_client = get_copilot_client(
                        raw_request,
                        studio_agent_id=studio_agent_id,
                        token_override=studio_token,
                    )
                    studio_client._tone = resolved_tone
                    studio_session = _persistent_session(
                        app,
                        raw_request,
                        normalized_session_model(request.model),
                        _messages_session_key(request),
                        request,
                        namespace=_studio_session_namespace(studio_agent_id),
                    )
                    if studio_session is not None:
                        studio_translated = translate_anthropic_request(
                            request,
                            incremental=studio_session.turn_count > 0,
                            system_override=_system_override,
                            consumer_tool_max_chars=(
                                settings.consumer_prompt_max_chars
                                if is_consumer
                                else None
                            ),
                        )
                    actual_planning = "studio"
            if _tools and router_applies(actual_planning, resolved_tone):
                full_view = translate_anthropic_request(
                    request.model_copy(update={"tools": None, "tool_choice": None})
                )
                router_prompt = build_router_prompt(
                    "\n\n".join([*full_view.additional_context, f"User: {full_view.prompt}"]),
                    tool_description_lines(_anthropic_tools_as_openai(_tools)),
                    choice,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        call_record = {
            "api": "anthropic",
            "endpoint": "/v1/messages",
            "time": time.strftime("%H:%M:%S"),
            "ts": time.time(),
            "stream": request.stream,
            "tools": sorted(tool_names),
            "tool_choice": choice[0],
            "messages": len(request.messages),
            "model": request.model,
            "tone": resolved_tone,
            "run_permission": run_permission,
            "read_only_guard": read_only_guard,
            "tool_calls_result": None if request.stream else [],
            "usage_input_tokens": estimate_upstream_input_tokens(
                (studio_translated or translated).prompt,
                (studio_translated or translated).additional_context,
            ),
        }
        # Tool calling is tone-dependent (see tone_options.TONE_TOOL_CALLING). This
        # is the shape Claude Code speaks, so it is the path where a silently
        # ignored tool list looked most like a broken proxy. Header carries the
        # effective status, log and call record the measured one -- see the chat route.
        tool_status = tone_tool_calling(resolved_tone) if tool_names else ""
        extra_headers = (
            {
                TOOL_CALLING_HEADER: (
                    actual_planning
                    if planning_mode == "studio"
                    else effective_tool_calling(resolved_tone, planning_mode)
                )
            }
            if tool_names else None
        )
        shortfall_note = ""
        declined_note = ""
        if tool_names:
            shortfall_note = no_tool_calls_note(
                app,
                model_str=request.model,
                tone=resolved_tone,
                choice=choice,
                tool_count=len(tool_names),
                read_only_guard=read_only_guard,
                planning_mode=actual_planning,
            )
            # Both variants up front: only the generator learns which one applies.
            declined_note = no_tool_calls_note(
                app,
                model_str=request.model,
                tone=resolved_tone,
                choice=choice,
                tool_count=len(tool_names),
                read_only_guard=read_only_guard,
                declined=True,
                planning_mode=actual_planning,
            )
        if tool_status in {"unsupported", "flaky"}:
            _log.warning(
                "  %s is measured %s the tool-calling contract "
                "(%d tool(s) requested)%s", resolved_tone,
                "NOT to honour" if tool_status == "unsupported" else "to honour only sometimes",
                len(tool_names),
                "; planning this turn with a router turn instead"
                if router_prompt and actual_planning == "router"
                else "",
            )
        if tool_names:
            call_record["tool_calling"] = tool_status
        if studio_client is not None:
            call_record["tool_planning"] = "studio"
        elif router_prompt:
            call_record["tool_planning"] = "router"
        if studio_fallback:
            call_record["studio_fallback"] = studio_fallback

        if request.stream:
            call_record["streaming"] = True
            append_call_log(app.state, call_record)
            if tool_names:
                # Tools present: buffer the turn so tool_call blocks can be parsed
                # out and re-emitted as Anthropic tool_use content blocks.
                stream = _anthropic_stream_with_tools(
                        model_alias,
                        client,
                        translated.prompt,
                        translated.additional_context,
                        session,
                        call_record=call_record,
                        tool_names=tool_names,
                        tool_schemas=tool_schemas,
                        read_only_guard=read_only_guard,
                        text_transform=media_rewriter,
                        images=translated.images,
                        on_text_done=lambda text: record_response_text(app.state, call_record, text),
                        shortfall_note=shortfall_note,
                        declined_note=declined_note,
                        router_prompt=router_prompt,
                        router_shortfall_note=no_tool_calls_note(
                            app,
                            model_str=request.model,
                            tone=resolved_tone,
                            choice=choice,
                            tool_count=len(tool_names),
                            read_only_guard=read_only_guard,
                            planning_mode="router",
                        ),
                        router_declined_note=no_tool_calls_note(
                            app,
                            model_str=request.model,
                            tone=resolved_tone,
                            choice=choice,
                            tool_count=len(tool_names),
                            read_only_guard=read_only_guard,
                            declined=True,
                            planning_mode="router",
                        ),
                        studio_turn=(
                            PlannerTurn(
                                studio_client,
                                studio_translated.prompt,
                                studio_translated.additional_context,
                                studio_session,
                                studio_translated.images,
                            )
                            if studio_client is not None
                            else None
                        ),
                )
                if studio_client is not None:
                    extra_headers = {TOOL_CALLING_HEADER: actual_planning}
                return StreamingResponse(
                    keepalive_stream(stream, heartbeat=ANTHROPIC_PING),
                    media_type="text/event-stream",
                    headers=merge_sse_headers(extra_headers),
                )
            return StreamingResponse(
                keepalive_stream(
                    _anthropic_stream(
                        model_alias,
                        client,
                        translated.prompt,
                        translated.additional_context,
                        session,
                        on_text_done=lambda text: record_response_text(app.state, call_record, text),
                        call_record=call_record,
                        text_transform=media_rewriter,
                        images=translated.images,
                    ),
                    heartbeat=ANTHROPIC_PING,
                ),
                media_type="text/event-stream",
                headers=merge_sse_headers(),
            )

        try:
            async def router_answer() -> str:
                return await routed_or_answered(
                    client,
                    router_prompt,
                    translated.prompt,
                    translated.additional_context,
                    session,
                    translated.images,
                )

            async def studio_fallback_answer() -> str:
                nonlocal actual_planning, shortfall_note, declined_note
                actual_planning = "router"
                call_record["tool_planning"] = "router"
                call_record["studio_fallback"] = "upstream_error"
                call_record["usage_input_tokens"] = estimate_upstream_input_tokens(
                    translated.prompt,
                    translated.additional_context,
                )
                shortfall_note = no_tool_calls_note(
                    app,
                    model_str=request.model,
                    tone=resolved_tone,
                    choice=choice,
                    tool_count=len(tool_names),
                    read_only_guard=read_only_guard,
                    planning_mode="router",
                )
                declined_note = no_tool_calls_note(
                    app,
                    model_str=request.model,
                    tone=resolved_tone,
                    choice=choice,
                    tool_count=len(tool_names),
                    read_only_guard=read_only_guard,
                    declined=True,
                    planning_mode="router",
                )
                return await router_answer()

            raw_text = (
                await planned_or_answered(
                    studio_turn=PlannerTurn(
                        studio_client,
                        studio_translated.prompt,
                        studio_translated.additional_context,
                        studio_session,
                        studio_translated.images,
                    ),
                    fallback_turn=studio_fallback_answer,
                )
                if studio_client is not None
                else await router_answer()
            )
            if tool_names and planning_mode == "studio":
                extra_headers = {TOOL_CALLING_HEADER: actual_planning}
        except SubstrateCopilotError as exc:
            call_record["error"] = str(exc)
            call_record["tool_calls_result"] = []
            record_response_text(app.state, call_record, "")
            append_call_log(app.state, call_record)
            raise upstream_http_error(exc) from exc

        # Parse the RAW model text, never the media-rewritten one. The rewriter
        # base64-encodes the source URL into a ?u= parameter, which destroys the
        # file extension _looks_like_fake_file_claim keys on -- so a natively
        # generated file (hosted URL, no tool_call) slipped past the corrective
        # retry. Rewriting is a delivery concern and is applied further down, to
        # the prose only, so it can also never touch a Write's file content.
        # The explicit no-action token is protocol chatter, not answer text, so it
        # comes off before anything reads the reply -- and `declined` decides
        # whether the synthesizing fallbacks below are appropriate at all.
        declined = False
        if tool_names:
            raw_text, declined = split_no_tool_marker(raw_text)
        tool_calls = _resolve_tool_calls(raw_text, tool_names, read_only_guard, declined)
        if not tool_calls and tool_names and not read_only_guard and not declined and _looks_like_fake_file_claim(raw_text):
            _log.info("  fake file claim detected, forcing corrective retry")
            try:
                retry_uses_studio = (
                    studio_client is not None and actual_planning == "studio"
                )
                retry_client = studio_client if retry_uses_studio else client
                retry_text = await retry_client.chat(
                    _RETRY_INSTRUCTION,
                    (
                        studio_translated.additional_context
                        if retry_uses_studio
                        else translated.additional_context
                    ),
                    studio_session if retry_uses_studio else session,
                )
                retry_calls = _resolve_tool_calls(retry_text, tool_names, read_only_guard)
                if retry_calls:
                    raw_text, tool_calls = retry_text, retry_calls
                    call_record["retried"] = True
            except SubstrateCopilotError:
                pass  # Keep original response if retry fails
        # Judged last: only calls we would otherwise deliver are worth checking.
        rejected: list[str] = []
        if tool_calls:
            tool_calls, rejected = _filter_schema_valid_tool_calls(tool_calls, tool_schemas)
            if rejected:
                _log.warning("  dropped unusable tool_call(s): %s", "; ".join(rejected))

        record_response_text(app.state, call_record, raw_text)
        call_record["tool_calls_result"] = [b["name"] for b in _tool_use_blocks(tool_calls)] if tool_calls else []
        if declined:
            call_record["tool_declined"] = True
        if rejected:
            call_record["tool_calls_rejected"] = rejected
        append_call_log(app.state, call_record)

        # Buffered path: nothing has been written yet, so a demanded-but-absent
        # call is still reportable as an HTTP error rather than prose with 200.
        required_error = required_tool_call_error(
            app,
            model_str=request.model,
            tone=resolved_tone,
            choice=choice,
            tool_calls=tool_calls,
            read_only_guard=read_only_guard,
            declined=declined,
            rejected=rejected,
            planning_mode=actual_planning,
        )
        if required_error:
            raise HTTPException(status_code=400, detail=required_error)

        if tool_calls:
            remaining = media_rewriter(_strip_tool_call_blocks(raw_text))
            content: list[dict] = []
            if remaining:
                content.append({"type": "text", "text": remaining})
            content.extend(_tool_use_blocks(tool_calls))
            return JSONResponse({
                "id": f"msg_{uuid.uuid4().hex}",
                "type": "message",
                "role": "assistant",
                "model": model_alias,
                "content": content,
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": anthropic_usage(call_record.get("usage")),
            }, headers=extra_headers)

        # Tools were offered but no tool_use is being delivered: say why as a
        # trailing text block rather than returning a plain answer that reads as a
        # broken proxy.
        blocks = [{"type": "text", "text": media_rewriter(raw_text)}]
        reason = prose_with_reason(
            "",
            shortfall_note=shortfall_note,
            declined_note=declined_note,
            declined=declined,
            rejected=rejected,
        )
        if reason:
            blocks.append({"type": "text", "text": reason})
        return JSONResponse({
            "id": f"msg_{uuid.uuid4().hex}",
            "type": "message",
            "role": "assistant",
            "model": model_alias,
            "content": blocks,
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": anthropic_usage(call_record.get("usage")),
        }, headers=extra_headers)


def _resolve_tool_calls(
    text: str, tool_names: set, read_only_guard: bool, declined: bool = False
) -> list[dict]:
    """Parse tool_calls out of model text, applying the same guards as the chat path."""
    if not tool_names:
        return []
    _log = logging.getLogger("copilot_proxy")
    tool_calls = _extract_tool_calls(text)
    if read_only_guard and tool_calls:
        blocked = len(tool_calls)
        tool_calls = _filter_read_only_tool_calls(tool_calls)
        if len(tool_calls) != blocked:
            _log.info("  read-only guard filtered mutating tool_call(s)")
    if not tool_calls and not read_only_guard and not declined:
        tool_calls = _extract_prose_write(text, tool_names)
        if tool_calls:
            _log.info("  prose fallback synthesized Write tool_call")
    return tool_calls


async def _anthropic_stream_with_tools(
    model_alias: str,
    client: SubstrateCopilotClient,
    prompt: str,
    additional_context: list[str],
    session: PersistentSession | None = None,
    call_record: dict | None = None,
    tool_names: set | None = None,
    tool_schemas: dict | None = None,
    read_only_guard: bool = False,
    text_transform: Callable[[str], str] | None = None,
    images: list | None = None,
    on_text_done: Callable[[str], None] | None = None,
    shortfall_note: str = "",
    declined_note: str = "",
    router_prompt: str = "",
    router_shortfall_note: str = "",
    router_declined_note: str = "",
    studio_turn: PlannerTurn | None = None,
) -> AsyncIterator[str]:
    """Buffer the turn, then emit Anthropic tool_use blocks if tool_calls are found.

    Mirrors ``_openai_stream_with_tools``: the tool_call contract is prompt-based,
    so the fenced block only becomes parseable once the whole answer has arrived.
    ``shortfall_note``/``declined_note`` ride along in the text block when the turn
    yields no tool_use at all -- headers are already flushed by then, and which
    reason applies is only known once the turn has landed.
    """
    _log = logging.getLogger("copilot_proxy")
    msg_id = f"msg_{uuid.uuid4().hex}"

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    preamble_sent = False
    try:
        chunks: list[str] = []

        async def router_stream() -> AsyncIterator[str]:
            nonlocal shortfall_note, declined_note
            if studio_turn is not None and call_record is not None:
                call_record["tool_planning"] = "router"
                call_record["studio_fallback"] = "upstream_error"
                call_record["usage_input_tokens"] = estimate_upstream_input_tokens(
                    prompt,
                    additional_context,
                )
                shortfall_note = router_shortfall_note
                declined_note = router_declined_note
            async for item in routed_or_streamed(
                client, router_prompt, prompt, additional_context, session, images
            ):
                yield item

        stream = (
            planned_or_streamed(
                studio_turn=studio_turn,
                fallback_turn=router_stream,
            )
            if studio_turn is not None
            else router_stream()
        )
        yield sse("message_start", {"type": "message_start", "message": {"id": msg_id, "type": "message", "role": "assistant", "content": [], "model": model_alias, "stop_reason": None, "stop_sequence": None, "usage": anthropic_usage(usage_for_record(call_record))}})
        yield sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
        yield sse("ping", {"type": "ping"})
        preamble_sent = True

        async for delta in stream:
            chunks.append(delta)
        # Parsing runs on the RAW text: the media rewriter base64-encodes the
        # source URL into a ?u= parameter, erasing the file extension that
        # _looks_like_fake_file_claim needs to spot a natively generated file.
        # Rewriting happens at delivery time, over the prose only.
        full_text = "".join(chunks)

        full_text, declined = split_no_tool_marker(full_text)
        tool_calls = _resolve_tool_calls(full_text, tool_names or set(), read_only_guard, declined)
        if not tool_calls and tool_names and not read_only_guard and not declined and _looks_like_fake_file_claim(full_text):
            _log.info("  fake file claim detected, forcing corrective retry")
            retry_chunks: list[str] = []
            retry_uses_studio = (
                studio_turn is not None
                and (
                    call_record is None
                    or call_record.get("tool_planning") == "studio"
                )
            )
            retry_client = studio_turn.client if retry_uses_studio else client
            retry_context = (
                studio_turn.additional_context
                if retry_uses_studio
                else additional_context
            )
            retry_session = studio_turn.session if retry_uses_studio else session
            async for delta in retry_client.chat_stream(
                _RETRY_INSTRUCTION, retry_context, retry_session
            ):
                retry_chunks.append(delta)
            retry_text = "".join(retry_chunks)
            retry_calls = _resolve_tool_calls(retry_text, tool_names or set(), read_only_guard)
            if retry_calls:
                full_text, tool_calls = retry_text, retry_calls
                if call_record is not None:
                    call_record["retried"] = True
        rejected: list[str] = []
        if tool_calls and tool_schemas is not None:
            tool_calls, rejected = _filter_schema_valid_tool_calls(tool_calls, tool_schemas)
            if rejected:
                _log.warning("  dropped unusable tool_call(s): %s", "; ".join(rejected))
    except SubstrateCopilotError as exc:
        error_text = f"⚠️ 上游错误：{exc}"
        if call_record is not None:
            call_record["error"] = str(exc)
        if isinstance(exc, SubstrateThrottled):
            yield sse("error", {
                "type": "error",
                "error": {
                    "type": "rate_limit_error",
                    "message": str(exc),
                },
            })
            if on_text_done is not None:
                on_text_done("".join(chunks))
            return
        if not preamble_sent:
            yield sse("message_start", {"type": "message_start", "message": {"id": msg_id, "type": "message", "role": "assistant", "content": [], "model": model_alias, "stop_reason": None, "stop_sequence": None, "usage": anthropic_usage(usage_for_record(call_record))}})
            yield sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
        yield sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": error_text}})
        yield sse("content_block_stop", {"type": "content_block_stop", "index": 0})
        if on_text_done is not None:
            on_text_done(error_text)
        yield sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": anthropic_usage(usage_for_record(call_record))})
        yield sse("message_stop", {"type": "message_stop"})
        return

    blocks = _tool_use_blocks(tool_calls)
    text_out = _strip_tool_call_blocks(full_text) if tool_calls else full_text
    if text_transform is not None:
        text_out = text_transform(text_out)
    if not blocks:
        text_out = prose_with_reason(
            text_out,
            shortfall_note=shortfall_note,
            declined_note=declined_note,
            declined=declined,
            rejected=rejected,
        )
    if call_record is not None:
        call_record["tool_calls_result"] = [b["name"] for b in blocks]
        if declined:
            call_record["tool_declined"] = True
        if rejected:
            call_record["tool_calls_rejected"] = rejected
    if blocks:
        _log.info("[anthropic_stream_with_tools] tool_use blocks: %s", [b["name"] for b in blocks])

    index = 0
    if text_out:
        yield sse("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": text_out}})
    yield sse("content_block_stop", {"type": "content_block_stop", "index": index})

    for block in blocks:
        index += 1
        yield sse("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}})
        # Anthropic streams tool arguments as incremental input_json_delta; the
        # buffered payload is sent as a single complete chunk.
        yield sse("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"], ensure_ascii=False)}})
        yield sse("content_block_stop", {"type": "content_block_stop", "index": index})

    stop_reason = "tool_use" if blocks else "end_turn"
    if on_text_done is not None:
        on_text_done(full_text)
    yield sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None}, "usage": anthropic_usage(usage_for_record(call_record))})
    yield sse("message_stop", {"type": "message_stop"})
