from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import websockets

from .session_store import PersistentSession
from .substrate_parse import (
    _capture_suspicious_response_event,
    _combine_text,
    _cumulative_catchup,
    _dedupe_repeated_delta,
    _dedupe_signature,
    _extract_image_urls,
    _image_markdown,
    _is_image_loading_placeholder,
    _message_content,
    _final_fallback_remainder,
    _split_snapshot_lead,
    clean_m365_citations,
)
from .token_store import decode_jwt_payload, is_substrate_token_claims

# Re-exported from substrate_parse so existing imports and test monkeypatches
# that reference these names via `substrate_client.<name>` keep working after
# the parsing helpers were split out into substrate_parse.
__all__ = [
    "SIGNALR_SEP",
    "SubstrateCopilotClient",
    "SubstrateCopilotError",
    "SubstrateThrottled",
    "_capture_suspicious_response_event",
    "_combine_text",
    "_cumulative_catchup",
    "_dedupe_repeated_delta",
    "_dedupe_signature",
    "_extract_image_urls",
    "_image_markdown",
    "_is_image_loading_placeholder",
    "_message_content",
    "_final_fallback_remainder",
    "_split_snapshot_lead",
    "clean_m365_citations",
]

SIGNALR_SEP = "\x1e"
_WS_BASE = "wss://substrate.office.com/m365Copilot/Chathub"
_log = logging.getLogger(__name__)

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

# Images per turn a caller may hand us. The count is caller-controlled and every
# image costs a serial upload (a remote one costs a download of up to 20 MiB plus
# ~1.37x that as base64 in memory), so an uncapped list turns one request into an
# arbitrarily long fetch-and-buffer loop. 10 matches the multi-image-in-turn
# ceiling the reference implementation uses.
_MAX_IMAGES_PER_TURN = 10

_VARIANTS = (
    "EnableMcpServerWidgets,feature.EnableMcpServerWidgets,feature.EnableLuForChatCIQ,"
    "feature.enableChatCIQPlugin,EnableRequestPlugins,feature.EnableSensitivityLabels,"
    "EnableUnsupportedUrlDetector,feature.IsCustomEngineCopilotEnabled,feature.bizchatfluxv3,"
    "feature.enablechatpages,feature.enableCodeCanvas,feature.turnOnWorkTabRecommendation,"
    "turnOffWorkTabUpsellFromClient,"
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

# Chat payload optionsSets. Kept in sync with observed M365 web traffic and
# cross-checked against public protocol notes (HEXUXIU/M365-Copilot2API).
# See docs/protocol-options-diff.md for the full A/B matrix and rationale.
# The six code_interpreter entries below do NOT gate server-side execution on this
# tenant: A/B'd 2026-08-25 with one real turn per cell (.probe/ci_ab.py), stripping
# all six left tone=Magic still answering the SHA-256 of a freshly minted nonce and
# an exact 12x12-digit product, still with GeneratedCode frames on the wire. They
# are kept because they mirror browser traffic, not because they buy the
# interpreter; the chart-shaped ones were not exercised by that oracle.
_OPTIONS_SETS = [
    "search_result_progress_messages_with_search_queries",
    "update_textdoc_response_after_streaming",
    "deepleo_networking_timeout_10minutes_canmore",
    "cwc_flux_image",
    "cwc_code_interpreter",
    "cwc_code_interpreter_amsfix",
    "cwcfluxgptv",
    "flux_v3_gptv_enable_upload_multi_image_in_turn_wo_ch",
    "gptvnorm2048",
    "cwc_code_interpreter_citation_fix",
    "code_interpreter_interactive_charts",
    # Bare `code_interpreter_` prefix, like its two siblings above/below: the
    # `cwc_`-prefixed spelling this line used to carry appears in no browser
    # capture or upstream reference, i.e. it was a silently ignored no-op.
    "code_interpreter_interactive_charts_inline_image",
    "code_interpreter_matplotlib_patching",
    "cwc_fileupload_odb",
    "update_memory_plugin",
    "add_custom_instructions",
    "cwc_flux_v3",
    "flux_v3_progress_messages",
    "enable_batch_token_processing",
    "enable_gg_gpt",
    "flux_v3_references",
    "flux_v3_references_entities",
    "flux_v3_image_gen_enable_dimensions",
    "flux_v3_image_gen_enable_non_watermarked_storage",
    "flux_v3_image_gen_enable_icon_dimensions",
    "flux_v3_image_gen_enable_system_text_with_params",
    "flux_v3_image_gen_enable_designer_dimensions_meta_prompting_in_system_prompts",
    "flux_v3_image_gen_enable_story",
    "rich_responses",
    "pages_citations",
    "pages_citations_multiturn",
    "enable_structured_output",
    "precise_mode",
]


def _tz_offset_hours(time_zone: str) -> int:
    """Hours east of UTC for ``time_zone``, right now.

    Sent next to the zone name in every turn's ``locationInfo``. It used to be a
    hardcoded 9 while the name beside it was configurable, so an account on the
    default Asia/Shanghai told the model its local clock was an hour ahead of the
    zone it had just named.

    ponytail: whole hours, truncated, so a half-hour zone (Asia/Kolkata) loses
    the :30 -- the browser field is an integer and no capture shows a fractional
    value. An unknown zone name falls back to +8, matching the default zone.
    """
    try:
        offset = datetime.now(ZoneInfo(time_zone)).utcoffset()
    except (ZoneInfoNotFoundError, ValueError, KeyError, OSError):
        return 8
    return int(offset.total_seconds() // 3600) if offset else 0


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

# M365 refuses a turn it will not answer -- a `tone` the account may not use
# among the causes -- by sending ONE canned line as the whole answer, with no
# streamed deltas. Passed through, that reads as a normal reply, so a mode the
# account cannot use looks like it "works" while every answer is this sentence.
#
# Raw-frame capture of such a turn (2026-08-02, tone Claude_Fable) showed the
# completion frame also marks it structurally, which is what the code keys off
# first: `item.turnState == "Failed"` and `item.result.value == "InternalError"`
# (a successful turn: "Completed"/"Success"), and the refusal message carries
# `contentOrigin: "BotConnection"` rather than "DeepLeo". The same sentence is
# substrate's generic error text -- `POST /m365Copilot/GetUserSettings {}`
# answers with it under `result.value == "InvalidRequest"` -- so it says
# "request rejected", not "the model declined".
# ponytail: the text match is kept as a second signal for builds that send the
# line on a turn marked Completed. Ceiling: a reworded line AND a Completed turn
# would restore the silent pass-through; nothing short of both.
_M365_REFUSAL_TEXTS = frozenset({
    "Sorry, I wasn't able to respond to that. Is there something else I can help with?",
})

# Stable markers in the two tone-failure error texts. scan_tones.py imports these
# to tell "M365 knows this mode but will not serve it" from "M365 does not know
# this value at all", so the wording below can be reworded without silently
# breaking that classification.
_REFUSED_TURN_MARKER = "refused this turn"
_EMPTY_TURN_MARKER = "empty response twice"


class SubstrateCopilotError(RuntimeError):
    pass


class SubstrateThrottled(SubstrateCopilotError):
    """M365 accepted the turn shape but temporarily refused it as throttled."""

    upstream_result = "Throttled"


class SubstrateCopilotClient:
    def __init__(self, access_token: str, time_zone: str = "Asia/Shanghai", tone: str = "Magic", extra_tool_prompt: str = "", idle_timeout: float | None = None, studio_agent_id: str = ""):
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
        self._studio_agent_id = str(studio_agent_id or "")
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
        studio_agent_id = str(getattr(self, "_studio_agent_id", "") or "").strip()
        agent_surface = (
            f"&gptId={quote(studio_agent_id, safe='')}&agent=Agent"
            if studio_agent_id
            else "&agent=web"
        )
        return (
            f"{_WS_BASE}/{self._oid}@{self._tid}"
            f"?ClientRequestId={req_id}"
            f"&X-SessionId={session_id}"
            f"&ConversationId={conv_id}"
            f"&access_token={token}"
            f"&variants={getattr(self, '_variants', _VARIANTS)}"
            f"&source=officeweb&product=Office&agentHost=Bizchat.FullScreen"
            f"&licenseType=Starter{agent_surface}&scenario=OfficeWebIncludedCopilot"
        )

    def _chat_invoke(
        self,
        text: str,
        conv_id: str,
        session_id: str,
        req_id: str,
        is_start_of_session: bool,
        annotations: list[dict] | None = None,
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
                "optionsSets": list(getattr(self, "_options_sets", _OPTIONS_SETS)),
                "streamingMode": "ConciseWithPadding",
                "spokenTextMode": "None",
                "options": {},
                "extraExtensionParameters": {},
                "allowedMessageTypes": _ALLOWED_MESSAGE_TYPES,
                "sliceIds": [],
                "threadLevelGptId": {},
                "productThreadType": "Office",
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
                    "locationInfo": {
                        "timeZoneOffset": _tz_offset_hours(self._time_zone),
                        "timeZone": self._time_zone,
                    },
                    "locale": "en-us",
                    "messageType": "Chat",
                    "experienceType": "Default",
                    "adaptiveCards": [],
                    "clientPreferences": {},
                    **({"messageAnnotations": annotations} if annotations else {}),
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
        studio_agent_id = getattr(self, "_studio_agent_id", "")
        if studio_agent_id:
            argument = payload["arguments"][0]
            argument["threadLevelGptId"] = {
                "id": studio_agent_id,
                "source": "MOS3",
            }
            argument["gpts"] = [{
                "id": studio_agent_id,
                "source": "MOS3",
                "version": "1.0.0",
                "clientOverrides": {
                    "capabilities": [],
                    "deepResearchModels@odata.type": "Collection(String)",
                },
            }]
            argument.pop("plugins", None)
        return json.dumps(payload, ensure_ascii=False) + SIGNALR_SEP

    async def _upload_images(self, images: list | None) -> list[dict]:
        """Upload inbound images and return their messageAnnotations entries.

        Uploads happen once per request (before the retry loop) against a
        throwaway upload conversation id; the returned docId annotations are
        reusable across the actual chat turn and any retry. Failed uploads are
        skipped so the turn can still proceed as text-only."""
        if not images:
            return []
        if len(images) > _MAX_IMAGES_PER_TURN:
            # Never silently: the turn proceeds without the dropped images, so the
            # log line is the only way to tell "the model ignored image 11" apart
            # from "the model answered badly".
            _log.warning(
                "turn carries %d images; uploading the first %d and dropping the rest",
                len(images),
                _MAX_IMAGES_PER_TURN,
            )
            images = images[:_MAX_IMAGES_PER_TURN]
        from .substrate_upload import upload_image
        upload_conv_id = str(uuid.uuid4())
        annotations: list[dict] = []
        for image in images:
            annotation = await upload_image(
                self._token, self._oid, self._tid, upload_conv_id, image
            )
            if annotation:
                annotations.append(annotation)
        return annotations

    async def chat_stream(
        self,
        prompt: str,
        additional_context: list[str],
        session: PersistentSession | None = None,
        images: list | None = None,
    ) -> AsyncIterator[str]:
        text = _combine_text(prompt, additional_context, self._tone)
        annotations = await self._upload_images(images)
        if session is None:
            async for chunk in self._stream_turn_with_retry(
                text=text,
                conv_id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()),
                is_start_of_session=True,
                annotations=annotations,
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
            streamed_any = False
            try:
                async for chunk in self._stream_turn_with_retry(
                    text=text,
                    conv_id=turn.conversation_id,
                    session_id=turn.client_session_id,
                    is_start_of_session=turn.is_start_of_session,
                    annotations=annotations,
                ):
                    streamed_any = True
                    yield chunk
            except SubstrateCopilotError as exc:
                # A reused persistent conversation can rot: after some turns the
                # upstream starts refusing every CONTINUATION (turnState=Failed /
                # canned refusal) while the same tone still answers in a brand-new
                # conversation. When that happens before anything is streamed,
                # abandon the poisoned conversation and retry ONCE as a fresh
                # start-of-session turn -- and keep the reset, so following turns run
                # on the new conversation too instead of the user having to open a
                # new chat. The retry re-posts only the incremental turn, so it loses
                # prior context (the same tradeoff the empty-response retry already
                # accepts), but returns an answer instead of a dead thread.
                #
                # Scope, narrow on purpose:
                #  - continuation turns only: a start-of-session turn refusing is a
                #    genuine tone/account outage, and a second fresh conversation
                #    would refuse identically.
                #  - refusals only (_REFUSED_TURN_MARKER): an empty turn is already
                #    retried on a throwaway conversation inside _stream_turn_with_retry.
                #  - nothing streamed yet: once bytes are on the wire a retry would
                #    duplicate content, so the partial answer is kept and the error
                #    propagates.
                if (
                    streamed_any
                    or turn.is_start_of_session
                    or _REFUSED_TURN_MARKER not in str(exc)
                ):
                    raise
                session.reset_conversation()
                healed = session.reserve_turn()
                async for chunk in self._stream_turn_with_retry(
                    text=text,
                    conv_id=healed.conversation_id,
                    session_id=healed.client_session_id,
                    is_start_of_session=healed.is_start_of_session,
                    annotations=annotations,
                ):
                    yield chunk
        finally:
            session.lock.release()

    async def _stream_turn_with_retry(
        self,
        text: str,
        conv_id: str,
        session_id: str,
        is_start_of_session: bool,
        annotations: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """Stream one turn; if the upstream returns a clean-but-empty response
        (connected, invoked, ended with no text/image), retry ONCE, then fail.

        The retry always runs on a brand-new throwaway conversation (fresh
        conv_id/session_id, is_start_of_session=True) so a persistent session's
        user message is never posted twice -- at worst the retry loses prior
        context, which is preferable to a duplicated turn. A retry only happens
        when the first attempt yielded nothing at all; any real error raises
        SubstrateCopilotError and propagates without retrying. All yields from
        _chat_stream_for_turn are non-empty, so tracking yielded_any is exact.

        Two empty attempts raise rather than returning "": an empty answer reads
        as a working-but-mute model in every client. Measured cause (2026-08-02):
        a `tone` M365 does not recognise makes substrate drop the invoke outright
        -- the turn ends with no update and no completion frame at all, unlike a
        tone it knows but will not serve, which fails loudly enough for
        _chat_stream_for_turn to catch.
        """
        yielded_any = False
        async for chunk in self._chat_stream_for_turn(
            text=text,
            conv_id=conv_id,
            session_id=session_id,
            is_start_of_session=is_start_of_session,
            annotations=annotations,
        ):
            yielded_any = True
            yield chunk
        if yielded_any:
            return
        # Empty upstream response: retry once on a fresh throwaway conversation.
        retried_any = False
        async for chunk in self._chat_stream_for_turn(
            text=text,
            conv_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            is_start_of_session=True,
            annotations=annotations,
        ):
            retried_any = True
            yield chunk
        if not retried_any:
            raise SubstrateCopilotError(
                f"M365 Copilot returned an {_EMPTY_TURN_MARKER} (conversation mode "
                f"'{self._tone}'). A mode M365 does not recognise always does this: "
                f"check the mode list against a scan_tones.py run."
            )

    async def _chat_stream_for_turn(
        self,
        text: str,
        conv_id: str,
        session_id: str,
        is_start_of_session: bool,
        annotations: list[dict] | None = None,
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
                await ws.send(self._chat_invoke(text, conv_id, session_id, req_id, is_start_of_session, annotations))
                fallback_text = ""
                streamed_text = ""
                # Run that a cumulative snapshot delivered ahead of the deltas, kept
                # so deltas replaying it are not shown to the reader a second time.
                snapshot_lead = ""
                yielded_images: set[str] = set()
                yielded_any = False
                # Non-empty once the completion frame says the turn failed; holds the
                # upstream's own verdict string so the error names it.
                turn_failure = ""
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
                                delta = clean_m365_citations(delta)
                                if not delta:
                                    continue
                                # A snapshot that landed before any delta holds the
                                # opening of the answer -- the deltas do not always
                                # rewind to it. Deliver it now that a real delta
                                # proves the turn is streaming (emitting it earlier
                                # would defeat the refusal check below), and record
                                # it so the delta it overlaps is not sent twice.
                                if not yielded_any and fallback_text:
                                    yield fallback_text
                                    streamed_text += fallback_text
                                    snapshot_lead = fallback_text
                                    yielded_any = True
                                # A snapshot may already have delivered the run this
                                # delta is about to replay; emit only what is new.
                                if snapshot_lead:
                                    split = _split_snapshot_lead(snapshot_lead, delta)
                                    if split is not None:
                                        snapshot_lead, delta = split
                                        if not delta:
                                            continue
                                    else:
                                        snapshot_lead = ""
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
                                # The snapshot is cumulative. When it runs ahead of
                                # the deltas it holds the only copy of the skipped
                                # run, so deliver that run NOW to keep the answer in
                                # order -- the final frame would append it last.
                                catchup = _cumulative_catchup(streamed_text, fallback_text)
                                if catchup:
                                    yield catchup
                                    streamed_text += catchup
                                    snapshot_lead += catchup
                                    yielded_any = True
                        if t == 2:
                            item = msg.get("item") or {}
                            item_msgs = item.get("messages") or []
                            for entry in reversed(item_msgs):
                                if entry.get("author") != "user":
                                    fallback_text = _message_content(entry)
                                    break
                            # The completion frame states the verdict for the whole
                            # turn; a rejected tone lands here as Failed/InternalError.
                            result = item.get("result") or {}
                            result_value = str(result.get("value") or "")
                            if item.get("turnState") == "Failed" or (result_value and result_value != "Success"):
                                turn_failure = result_value or "Failed"
                        for image_url in _extract_image_urls(msg):
                            if image_url not in yielded_images:
                                markdown = ("\n\n" if streamed_text else "") + _image_markdown(image_url)
                                yield markdown
                                streamed_text += markdown
                                yielded_images.add(image_url)
                                yielded_any = True
                        if t == 3:
                            remaining = _final_fallback_remainder(streamed_text, fallback_text)
                            # Nothing streamed and the turn was marked failed (or its
                            # whole answer is the canned refusal) => report it as an
                            # upstream failure instead of returning it as the reply.
                            if not yielded_any and (turn_failure or remaining.strip() in _M365_REFUSAL_TEXTS):
                                detail = f" (upstream result: {turn_failure})" if turn_failure else ""
                                message = (
                                    f"M365 Copilot {_REFUSED_TURN_MARKER} instead of answering "
                                    f"(conversation mode '{self._tone}'){detail}. If every request "
                                    f"in this mode does this, the mode is not available for this "
                                    f"account -- switch to another mode."
                                )
                                if (turn_failure or "").strip().casefold() == "throttled":
                                    raise SubstrateThrottled(message)
                                raise SubstrateCopilotError(message)
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
        images: list | None = None,
    ) -> str:
        chunks: list[str] = []
        async for chunk in self.chat_stream(prompt, additional_context, session, images):
            chunks.append(chunk)
        return "".join(chunks)
