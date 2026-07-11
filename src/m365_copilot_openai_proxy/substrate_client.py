from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from urllib.parse import quote

import websockets

from .session_store import PersistentSession
from .substrate_parse import (
    _capture_suspicious_response_event,
    _combine_text,
    _dedupe_signature,
    _extract_image_urls,
    _image_markdown,
    _is_image_loading_placeholder,
    _message_content,
    _remaining_fallback_text,
)
from .token_store import decode_jwt_payload, is_substrate_token_claims

# Re-exported from substrate_parse so existing imports and test monkeypatches
# that reference these names via `substrate_client.<name>` keep working after
# the parsing helpers were split out into substrate_parse.
__all__ = [
    "SIGNALR_SEP",
    "SubstrateCopilotClient",
    "SubstrateCopilotError",
    "_capture_suspicious_response_event",
    "_combine_text",
    "_dedupe_signature",
    "_extract_image_urls",
    "_image_markdown",
    "_is_image_loading_placeholder",
    "_message_content",
    "_remaining_fallback_text",
]

SIGNALR_SEP = "\x1e"
_WS_BASE = "wss://substrate.office.com/m365Copilot/Chathub"

# Chat-only WebSocket timeouts (do NOT affect cookie/CDP refresh in refresh_scheduler).
# _WS_OPEN_TIMEOUT: cap the TCP+TLS+HTTP-upgrade handshake.
# _WS_IDLE_TIMEOUT: max seconds to wait for the NEXT frame. SignalR type=6 keepalives
#   and every streamed delta reset this window, so a slow-but-alive long answer never
#   trips it; only a genuinely stalled upstream (no frames at all) does.
# _SESSION_LOCK_TIMEOUT: max wait to acquire a per-session lock. Cross-user requests use
#   different sessions/locks (see session_helpers), so this only bounds same-session,
#   same-conversation serialization; a stuck holder self-aborts via _WS_IDLE_TIMEOUT.
_WS_OPEN_TIMEOUT = 15.0
# Default max seconds to wait for the NEXT frame (heartbeats/deltas reset it). Raised
# to 300s so a long "thinking" gap with no interim frames is tolerated; overridable
# per-client via the idle_timeout constructor arg (admin global / per-user setting).
_WS_IDLE_TIMEOUT = 300.0
_SESSION_LOCK_TIMEOUT = 300.0

_VARIANTS = (
    "EnableMcpServerWidgets,feature.EnableMcpServerWidgets,feature.EnableLuForChatCIQ,"
    "feature.enableChatCIQPlugin,EnableRequestPlugins,feature.EnableSensitivityLabels,"
    "EnableUnsupportedUrlDetector,feature.IsCustomEngineCopilotEnabled,feature.bizchatfluxv3,"
    "feature.enablechatpages,feature.enableCodeCanvas,feature.turnOnWorkTabRecommendation,"
    "feature.turnOnDARecommendation,feature.IsStreamingModeInChatRequestEnabled,"
    "IncludeSourceAttributionsConcise,SkipPublishEmptyMessage,"
    "feature.EnableDeduplicatingSourceAttributions,Enable3PActionProgressMessages,"
    "feature.enableClientWebRtc,feature.EnableMeetingRecapOfSeriesMeetingWithCiq,"
    "feature.EnableReferencesListCompleteSignal,feature.StorageMessageSplitDisabled,"
    "feature.EnableCuaTakeControlApi,SingletonEnvOn,feature.cwcallowedos,"
    "feature.EnableMergingPureDeltas,feature.disabledisallowedmsgs,"
    "feature.enableCitationsForSynthesisData,feature.EnableConversationShareApis,"
    "feature.enableGenerateGraphicArtOptionsSet,cdximagen,"
    "feature.EnableUpdatedUXForConfirmationDialog,"
    "feature.EnableContentApiandDocTypeHtmlInRichAnswers,"
    "cdxgrounding_api_v2_rich_web_answers_reference_bottom_force,"
    "cdxenablerenderforisocomp,feature.EnableClientFileURLSupportForOfficeWebPaidCopilot,"
    "feature.EnableDesignEditorImageGrounding,feature.EnableDesignerEditor,"
    "feature.EnableSkipRehydrationForSpeCIdImages,feature.EnableSkipEmittingMessageOnFlush,"
    "feature.EnableRemoveEmptySourceAttributions,feature.EnableRemoveStreamingMode,"
    "feature.OfficeWebToHelix,feature.OfficeDesktopToHelix,feature.M365TeamsHubToHelix,"
    "feature.OwaHubToHelix,feature.MonarchHubToHelix,feature.Win32OutlookHubToHelix,"
    "feature.MacOutlookHubToHelix,Agt_bizchat_enableGpt5ForHelix"
)

_OPTIONS_SETS = [
    "search_result_progress_messages_with_search_queries",
    "cwc_flux_image",
    "cwc_code_interpreter",
    "cwc_code_interpreter_amsfix",
    "cwcfluxgptv",
    "flux_v3_gptv_enable_upload_multi_image_in_turn_wo_ch",
    "cwc_code_interpreter_citation_fix",
    "code_interpreter_interactive_charts",
    "cwc_code_interpreter_interactive_charts_inline_image",
    "code_interpreter_matplotlib_patching",
    "cwc_fileupload_odb",
    "update_memory_plugin",
    "add_custom_instructions",
    "cwc_flux_v3",
    "flux_v3_progress_messages",
    "enable_batch_token_processing",
    "enable_gg_gpt",
    "flux_v3_image_gen_enable_dimensions",
    "flux_v3_image_gen_enable_system_text_with_params",
    "flux_v3_image_gen_enable_designer_dimensions_meta_prompting_in_system_prompts",
    "enable_structured_output",
    "precise_mode",
]

_ALLOWED_MESSAGE_TYPES = [
    "Chat", "Suggestion", "InternalSearchQuery", "Disengaged",
    "InternalLoaderMessage", "Progress", "GeneratedCode", "RenderCardRequest",
    "AdsQuery", "SemanticSerp", "GenerateContentQuery", "GenerateGraphicArt",
    "SearchQuery", "ConfirmationCard", "AuthError", "DeveloperLogs",
    "TriggerPlugin", "HintInvocation", "MemoryUpdate", "EndOfRequest",
    "TriggerConfirmation", "ResumeInvokeAction", "ResumeUserInputRequest",
    "TriggerUserInputRequest", "EscapeHatch", "TriggerPluginAuth",
    "ResumePluginAuth", "SideBySide", "ReferencesListComplete",
    "SwitchRespondingEndpoint",
]


class SubstrateCopilotError(RuntimeError):
    pass


class SubstrateCopilotClient:
    def __init__(self, access_token: str, time_zone: str = "Asia/Shanghai", tone: str = "Magic", extra_tool_prompt: str = "", idle_timeout: float | None = None):
        if not access_token:
            raise SubstrateCopilotError(
                "M365_ACCESS_TOKEN is missing. Start the debug Edge window and let startup token capture complete, "
                "or run `uv run copilot-openai-proxy set-token`."
            )
        self._token = access_token
        self._time_zone = time_zone
        # Per-client idle timeout override (seconds). Falsy => module default.
        self._idle_timeout = float(idle_timeout) if idle_timeout else _WS_IDLE_TIMEOUT
        self._tone = tone or "Magic"
        self._extra_tool_prompt = extra_tool_prompt or ""
        self._response_debug_sink = None
        try:
            claims = decode_jwt_payload(access_token)
        except Exception as exc:
            raise SubstrateCopilotError(f"Cannot decode access token: {exc}") from exc
        if not is_substrate_token_claims(claims):
            raise SubstrateCopilotError("Access token is not a substrate.office.com token.")
        if time.time() > claims.get("exp", 0):
            raise SubstrateCopilotError(
                "Access token expired and could not be auto-refreshed. "
                "Re-push this account's token/cookies from the browser userscript "
                "(one-click push on the M365 Copilot page), or trigger a cookie "
                "refresh from the admin page for this account."
            )
        self._oid: str = claims["oid"]
        self._tid: str = claims["tid"]

    def _ws_url(self, conv_id: str, session_id: str, req_id: str) -> str:
        token = quote(self._token, safe="")
        return (
            f"{_WS_BASE}/{self._oid}@{self._tid}"
            f"?ClientRequestId={req_id}"
            f"&X-SessionId={session_id}"
            f"&ConversationId={conv_id}"
            f"&access_token={token}"
            f"&variants={_VARIANTS}"
            f"&source=officeweb&product=Office&agentHost=Bizchat.FullScreen"
            f"&licenseType=Starter&agent=web&scenario=OfficeWebIncludedCopilot"
        )

    def _chat_invoke(
        self,
        text: str,
        conv_id: str,
        session_id: str,
        req_id: str,
        is_start_of_session: bool,
    ) -> str:
        # If the prompt contains tool_call format instructions, prepend a strong reminder
        # directly into the user message (not just system prompt) for better compliance
        tool_reminder = ""
        if "tool_call" in text:
            tool_reminder = (
                "[INSTRUCTION] For ANY file action, your ONLY valid output format is a fenced code block:\n"
                "```tool_call\n"
                '{"name": "Write", "arguments": {"file_path": "...", "content": "..."}}\n'
                "```\n"
                "You MUST NOT:\n"
                "- Request Write/Edit/Delete/command execution when the user asks to only analyze/review/read or says not to modify/write/save/run/delete files\n"
                "- Say you cannot access files (the host does it for you)\n"
                "- Say a path does not exist (you don't know — the host checks)\n"
                "- Output code in ```bat / ```python blocks without a tool_call wrapper\n"
                "- Say 'file saved' or '已生成' without actually emitting the tool_call block\n"
                "You MUST emit the tool_call block immediately. No other format is accepted.[/INSTRUCTION]\n\n"
            )
            if self._extra_tool_prompt.strip():
                tool_reminder += "[CUSTOM INSTRUCTION] " + self._extra_tool_prompt.strip() + " [/CUSTOM INSTRUCTION]\n\n"
        payload = {
            "arguments": [{
                "source": "officeweb",
                "clientCorrelationId": req_id,
                "sessionId": session_id,
                "optionsSets": _OPTIONS_SETS,
                "streamingMode": "ConciseWithPadding",
                "spokenTextMode": "None",
                "options": {},
                "extraExtensionParameters": {},
                "allowedMessageTypes": _ALLOWED_MESSAGE_TYPES,
                "sliceIds": [],
                "threadLevelGptId": {},
                "traceId": req_id,
                "isStartOfSession": is_start_of_session,
                "clientInfo": {
                    "clientPlatform": "mcmcopilot-web",
                    "clientAppName": "Office",
                    "clientEntrypoint": "mcmcopilot-officeweb",
                    "clientSessionId": session_id,
                    "clientAppType": "Web",
                    "deviceOS": "Windows",
                    "deviceType": "Desktop",
                },
                "message": {
                    "author": "user",
                    "inputMethod": "Keyboard",
                    "text": tool_reminder + text,
                    "entityAnnotationTypes": ["People", "File", "Event", "Email", "TeamsMessage"],
                    "requestId": req_id,
                    "locationInfo": {"timeZoneOffset": 9, "timeZone": self._time_zone},
                    "locale": "en-us",
                    "messageType": "Chat",
                    "experienceType": "Default",
                    "adaptiveCards": [],
                    "clientPreferences": {},
                },
                "plugins": [{"Id": "BingWebSearch", "Source": "BuiltIn"}],
                "isSbsSupported": True,
                "tone": self._tone,
                "renderReferencesBehindEOS": True,
            }],
            "invocationId": "0",
            "target": "chat",
            "type": 4,
        }
        return json.dumps(payload, ensure_ascii=False) + SIGNALR_SEP

    async def chat_stream(
        self,
        prompt: str,
        additional_context: list[str],
        session: PersistentSession | None = None,
    ) -> AsyncIterator[str]:
        text = _combine_text(prompt, additional_context)
        if session is None:
            async for chunk in self._chat_stream_for_turn(
                text=text,
                conv_id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()),
                is_start_of_session=True,
            ):
                yield chunk
            return

        # Acquire the per-session lock with a timeout so a stuck stream on the SAME
        # session/conversation cannot block follow-up requests forever. Cross-user
        # requests use different sessions (different locks) and never wait here.
        try:
            await asyncio.wait_for(session.lock.acquire(), timeout=_SESSION_LOCK_TIMEOUT)
        except asyncio.TimeoutError as exc:
            raise SubstrateCopilotError(
                "Session is busy: a previous request on this conversation is still "
                "streaming. Retry shortly."
            ) from exc
        try:
            turn = session.reserve_turn()
            async for chunk in self._chat_stream_for_turn(
                text=text,
                conv_id=turn.conversation_id,
                session_id=turn.client_session_id,
                is_start_of_session=turn.is_start_of_session,
            ):
                yield chunk
        finally:
            session.lock.release()

    async def _chat_stream_for_turn(
        self,
        text: str,
        conv_id: str,
        session_id: str,
        is_start_of_session: bool,
    ) -> AsyncIterator[str]:
        req_id = str(uuid.uuid4())
        url = self._ws_url(conv_id, session_id, req_id)
        try:
            async with websockets.connect(
                url,
                additional_headers={
                    "Origin": "https://m365.cloud.microsoft",
                },
                open_timeout=_WS_OPEN_TIMEOUT,
                close_timeout=_WS_OPEN_TIMEOUT,
            ) as ws:
                idle_timeout = getattr(self, "_idle_timeout", None) or _WS_IDLE_TIMEOUT
                await ws.send(json.dumps({"protocol": "json", "version": 1}) + SIGNALR_SEP)
                await asyncio.wait_for(ws.recv(), timeout=idle_timeout)
                await ws.send(self._chat_invoke(text, conv_id, session_id, req_id, is_start_of_session))
                fallback_text = ""
                streamed_text = ""
                yielded_images: set[str] = set()
                yielded_any = False
                ws_iter = ws.__aiter__()
                while True:
                    try:
                        raw = await asyncio.wait_for(ws_iter.__anext__(), timeout=idle_timeout)
                    except asyncio.TimeoutError as exc:
                        raise SubstrateCopilotError(
                            "Upstream stopped sending data (idle timeout). The chat "
                            "connection was closed to avoid hanging."
                        ) from exc
                    except (StopAsyncIteration, websockets.ConnectionClosed):
                        break
                    for part in raw.split(SIGNALR_SEP):
                        part = part.strip()
                        if not part:
                            continue
                        try:
                            msg = json.loads(part)
                        except json.JSONDecodeError:
                            continue
                        t = msg.get("type")
                        if t == 6:
                            continue
                        _capture_suspicious_response_event(getattr(self, "_response_debug_sink", None), msg)
                        if t == 1 and msg.get("target") == "update":
                            args = (msg.get("arguments") or [{}])[0]
                            delta = args.get("writeAtCursor")
                            if delta and not _is_image_loading_placeholder(delta):
                                if not yielded_any and fallback_text:
                                    yield fallback_text
                                    streamed_text += fallback_text
                                yielded_any = True
                                yield delta
                                streamed_text += delta
                            msgs = args.get("messages")
                            if msgs:
                                entries = msgs if isinstance(msgs, list) else [msgs]
                                for entry in reversed(entries):
                                    if entry.get("author") != "user":
                                        fallback_text = _message_content(entry)
                                        break
                        if t == 2:
                            item_msgs = (msg.get("item") or {}).get("messages") or []
                            for entry in reversed(item_msgs):
                                if entry.get("author") != "user":
                                    fallback_text = _message_content(entry)
                                    break
                        for image_url in _extract_image_urls(msg):
                            if image_url not in yielded_images:
                                markdown = ("\n\n" if streamed_text else "") + _image_markdown(image_url)
                                yield markdown
                                streamed_text += markdown
                                yielded_images.add(image_url)
                                yielded_any = True
                        if t == 3:
                            remaining = _remaining_fallback_text(streamed_text, fallback_text)
                            if remaining:
                                yield remaining
                            return
        except SubstrateCopilotError:
            raise
        except Exception as exc:
            raise SubstrateCopilotError(str(exc)) from exc

    async def chat(
        self,
        prompt: str,
        additional_context: list[str],
        session: PersistentSession | None = None,
    ) -> str:
        chunks: list[str] = []
        async for chunk in self.chat_stream(prompt, additional_context, session):
            chunks.append(chunk)
        return "".join(chunks)
