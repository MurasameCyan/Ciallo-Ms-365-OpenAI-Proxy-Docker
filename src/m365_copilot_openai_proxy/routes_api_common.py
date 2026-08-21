from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request

from .config import Settings
from .consumer_client import AccountThrottled
from .key_store import ApiKey
from .runtime_settings import (
    _BUILTIN_CONSUMER_MODE_OPTIONS,
    _RUN_PERMISSIONS,
)
from .substrate_client import (
    _EMPTY_TURN_MARKER,
    _REFUSED_TURN_MARKER,
    SubstrateThrottled,
)
from .tone_options import TONE_OPTIONS as _BUILTIN_TONE_OPTIONS
from .tone_options import (
    CONSUMER_MODE_TOOL_CALLING,
    TOOL_PLANNING_MODES,
    effective_tool_calling,
    tool_planning_mode,
    tone_tool_calling,
)
from .tone_resolver import resolve_tone, verified_tool_tone_labels

# Advisory response header carrying the requested tone's measured tool-calling
# status, so an operator can tell a degraded turn from a working one without
# reading the body.
TOOL_CALLING_HEADER = "X-M365-Tool-Calling"
TOOL_OUTCOME_HEADER = "X-M365-Tool-Outcome"
REQUIRED_NO_CALL_OUTCOME = "required_no_call"
REQUIRED_REJECTED_CALL_OUTCOME = "required_rejected_call"


def upstream_http_error(
    exc: Exception, *, now: datetime | None = None
) -> HTTPException:
    """Map a SubstrateCopilotError onto the status code its cause deserves.

    Every failure used to surface as 502, so a turn M365 simply would not answer
    looked identical to a broken gateway: clients retried a refusal that no retry
    can fix, and the operator had nothing to distinguish "this mode is
    unavailable for this account" from "the upstream connection died".

    A refused or twice-empty turn is upstream declining the request itself, so it
    maps to 400 -- the request as phrased will not be served. Everything else
    (idle timeout, closed socket, unusable token) stays 502.

    Consumer quota refusals use the typed ``AccountThrottled`` cause preserved by
    the adapter, so their reset timestamp becomes ``Retry-After`` without parsing
    error text. Refused/empty M365 turns retain the historical marker mapping
    because the substrate client does not expose typed subclasses for them.
    """
    detail = str(exc)
    throttled = exc if isinstance(exc, SubstrateThrottled) else exc.__cause__
    if isinstance(throttled, SubstrateThrottled):
        # M365 does not currently include a reset timestamp in this frame. Do not
        # invent Retry-After; the typed status lets clients apply their own backoff.
        return HTTPException(status_code=429, detail=detail)
    throttled = exc if isinstance(exc, AccountThrottled) else exc.__cause__
    if isinstance(throttled, AccountThrottled):
        headers = None
        seconds = throttled.retry_after_seconds(now)
        if seconds is not None:
            headers = {"Retry-After": str(max(1, math.ceil(seconds)))}
        return HTTPException(status_code=429, detail=detail, headers=headers)
    refused = _REFUSED_TURN_MARKER in detail or _EMPTY_TURN_MARKER in detail
    return HTTPException(status_code=400 if refused else 502, detail=detail)


def request_model_alias(app: FastAPI, raw_request: Request, settings: Settings) -> str:
    """Resolve the model alias for a request: the key's own override wins, then
    the admin-configured global alias, then the settings default."""
    key_obj = getattr(raw_request.state, "api_key_obj", None)
    return getattr(key_obj, "model_alias", "") or getattr(app.state, "model_alias", settings.model_alias)


def _tone_options(app: FastAPI) -> list[dict]:
    return getattr(app.state, "tone_options", None) or _BUILTIN_TONE_OPTIONS


def resolve_request_tone(app: FastAPI, model_str: str | None) -> tuple[str, bool]:
    """Resolve an incoming request model name to (tone_value, is_persist).

    Each tone is exposed as its own model via /v1/models, so the requested
    model name now selects the conversation tone. Unmatched names fall back to
    the global default tone (app.state.current_tone)."""
    default_tone = getattr(app.state, "current_tone", "Magic") or "Magic"
    return resolve_tone(model_str, _tone_options(app), default_tone)


def _verified_models(app: FastAPI, selector: str = "") -> str:
    """Model names this key can actually get tool calls from.

    Keyed on which namespace the selector came from: a Consumer key addresses
    modes and cannot reach a tone at all, so naming a tone in its error would
    recommend a model that key gets rejected for asking about.
    """
    if selector in CONSUMER_MODE_TOOL_CALLING:
        labels = [
            str(option.get("model") or "")
            for option in _consumer_mode_options(app)
            if tone_tool_calling(option.get("mode")) == "verified"
        ]
    else:
        labels = verified_tool_tone_labels(_tone_options(app))
    return ", ".join(dict.fromkeys(label for label in labels if label)) or "（当前无）"


def tool_calling_note(
    app: FastAPI,
    model_str: str | None,
    tone: str,
    tool_count: int,
    planning_mode: str = "native",
) -> str:
    """Readable reason a tools-bearing turn is expected to produce no tool_calls.

    Sending ``tools`` to a tone that ignores the injected contract used to return
    ordinary prose with HTTP 200 and no signal whatsoever, which is
    indistinguishable from a broken proxy -- that silence is the actual defect,
    not the pipeline. Returns "" for tones not measured as broken, so an untested
    tone is never slandered.

    ``flaky`` gets its own wording because the advice differs: a Consumer mode
    that complied once in six can succeed on retry, and telling its user that
    retrying is pointless would be the same kind of wrong answer as saying
    nothing.

    Keyed on the EFFECTIVE status, so a routed turn gets a routed turn's wording.
    Observed live 2026-08-19: the router declined in its own words instead of the
    marker, the answer turn was fine, and the reply still told its user the model
    was unreliable and to switch -- advice about the one shape that did not plan
    that turn, and flatly wrong when routing had just made it reliable. This note
    is only ever reached on a routed turn when the router produced no readable
    decision (unreadable, or the classification turn failed and we fell back), so
    "no usable decision, and no call in the answer either" is what it says.

    Neither wording claims there is prose above it: measured live 2026-08-19, a
    flaky Consumer mode can answer a tools-bearing turn with *nothing at all*, and
    "上面返回的是普通回复" pointing at an empty response is its own small lie.
    ``prose_with_reason`` states the empty case, which is the only place that knows.
    """
    if tool_planning_mode(planning_mode) == "studio":
        return (
            f"⚠️ 模型 '{model_str or ''}'（{tone}）本轮声明的 {tool_count} 个工具没有被调用："
            f"本轮由绑定的 Studio Agent 规划，但它没有给出可用的工具调用。"
            f"重试可能就好；如果这轮本该调用工具，请检查 Studio Agent 的工具说明、参数约束和发布状态。"
        )
    status = effective_tool_calling(tone, planning_mode)
    if status == "router":
        return (
            f"⚠️ 模型 '{model_str or ''}'（{tone}）本轮声明的 {tool_count} 个工具没有被调用："
            f"本轮由工具路由器规划，它没有给出可用的调用决定，随后的普通回复里也没有工具调用。"
            f"重试可能就好；如果这轮本该调用工具，请检查工具描述是否说清了何时调用、参数怎么取。"
        )
    if status == "flaky":
        return (
            f"⚠️ 模型 '{model_str or ''}'（mode={tone}）的本地工具调用不稳定："
            f"本轮声明的 {tool_count} 个工具没有被调用。"
            f"重试可能就好了；实测稳定的模型：{_verified_models(app, tone)}。"
        )
    if status != "unsupported":
        return ""
    return (
        f"⚠️ 模型 '{model_str or ''}'（tone={tone}）不支持本地工具调用："
        f"本轮声明的 {tool_count} 个工具被忽略了。"
        f"实测支持工具调用的模型：{_verified_models(app, tone)}。"
    )


def required_tool_call_error(
    app: FastAPI,
    *,
    model_str: str | None,
    tone: str,
    choice: tuple[str, str | None, bool],
    tool_calls: list,
    read_only_guard: bool,
    declined: bool = False,
    rejected: Sequence[str] = (),
    planning_mode: str = "native",
) -> str:
    """Explain a demanded tool call that produced none, or return ``""``.

    Keyed on the actual outcome rather than on TONE_TOOL_CALLING, so a tone that
    quietly starts or stops complying needs no table update, and an unmeasured
    tone is never rejected for a call it did in fact make.

    Only ``required``/named choices are enforced: under ``auto`` a prose answer is
    a legitimate outcome. ``read_only_guard`` is exempt because dropping mutating
    calls is our own policy decision, not an upstream shortfall. Callers choose
    the protocol-appropriate transport: HTTP 400 before a buffered response, or a
    terminal readable event after streaming response headers have already gone.

    ``declined``/``rejected`` only change the *diagnosis*, never the outcome: a
    demanded call is still missing. Both replace the "the tone ignores our
    contract" sentence, which would be false -- a model that emitted
    NO_TOOL_NEEDED, or one whose call we dropped for violating the client's own
    schema, did honour the contract.
    """
    if tool_calls or read_only_guard or choice[0] not in {"required", "tool"}:
        return ""
    demanded = (
        f"tool_choice 指定了函数 {choice[1]}"
        if choice[0] == "tool" and choice[1]
        else "tool_choice=required"
    )
    if rejected:
        return f"{demanded}，但{rejected_calls_note(rejected)}"
    if declined:
        planner = (
            "绑定的 Studio Agent"
            if tool_planning_mode(planning_mode) == "studio"
            else f"模型 '{model_str or ''}'（tone={tone}）"
        )
        return (
            f"{demanded}，但{planner}明确判断本轮不需要任何"
            f"工具（返回 NO_TOOL_NEEDED）。它遵守了调用契约，所以换模型不一定有用："
            f"先检查工具描述是否说明了该在什么时候调用，以及本轮请求是否真的需要工具。"
        )
    if tool_planning_mode(planning_mode) == "studio":
        return (
            f"{demanded}，但绑定的 Studio Agent 本轮没有产出任何 tool_call，只回了普通文本。"
            f"请检查 Studio Agent 的工具说明、参数约束和发布状态；重试也可能恢复。"
        )
    if effective_tool_calling(tone, planning_mode) == "router":
        # Checked before the measured statuses: under ``auto`` the routed selectors
        # are exactly the broken ones, so keying on the measurement here would name
        # the one shape that did NOT plan this turn.
        return (
            f"{demanded}，但模型 '{model_str or ''}'（{tone}）本轮没有产出任何 "
            f"tool_call，只回了普通文本。本轮由工具路由器规划，说明它没能读出一个可用的"
            f"调用决定；重试可能就好，也可以检查工具描述是否说清了参数取值。"
        )
    if tone_tool_calling(tone) == "flaky":
        # Same demand, opposite advice: this selector does comply sometimes, so
        # "retrying will not help" would send the caller off changing models over
        # what is actually a coin flip.
        return (
            f"{demanded}，但模型 '{model_str or ''}'（mode={tone}）本轮没有产出任何 "
            f"tool_call，只回了普通文本。该模式实测不稳定，重试可能就好了；"
            f"实测稳定的模型：{_verified_models(app, tone)}。"
        )
    return (
        f"{demanded}，但模型 '{model_str or ''}'（tone={tone}）本轮没有产出任何 "
        f"tool_call，只回了普通文本。重试不会改变结果：工具调用是否生效取决于 "
        f"tone 是否遵守注入的调用契约。实测可用的模型：{_verified_models(app, tone)}。"
    )


def rejected_calls_note(rejected: Sequence[str]) -> str:
    """Readable reason parsed tool_calls were dropped before reaching the client."""
    if not rejected:
        return ""
    return (
        "⚠️ 上游产出的工具调用不符合客户端声明的工具定义，已丢弃（发给客户端只会在那边报错）："
        + "；".join(rejected)
    )


def prose_with_reason(
    text: str,
    *,
    shortfall_note: str,
    declined_note: str = "",
    declined: bool = False,
    rejected: Sequence[str] = (),
) -> str:
    """Deliver a tools-bearing turn's prose together with why no tool_call came.

    Appended, never substituted -- the model's own answer is still the response.
    Precedence: what we observed (calls we dropped) beats what the model says it
    decided (NO_TOOL_NEEDED) beats what we merely expect of the tone.

    An empty turn is stated, not glossed over: a 200 carrying neither a tool_call
    nor a single character is the exact silence this whole path exists to break,
    and without the sentence the note reads as if prose were printed above it.
    """
    note = rejected_calls_note(rejected) or (declined_note if declined else shortfall_note)
    if not note:
        return text
    if text:
        return f"{text}\n\n{note}"
    return f"⚠️ 上游本轮没有返回任何文字。\n\n{note}"


def no_tool_calls_note(
    app: FastAPI,
    *,
    model_str: str | None,
    tone: str,
    choice: tuple[str, str | None, bool],
    tool_count: int,
    read_only_guard: bool,
    declined: bool = False,
    planning_mode: str = "native",
) -> str:
    """What to say if this tools-bearing turn ends up with no tool_calls at all.

    Computed before the answer exists so a streaming route can hand it to its
    generator: the outcome is only known once the turn has been buffered, and by
    then the response headers are long gone and HTTP 400 is no longer available.
    Buffered routes share the same value -- when they do reach the append the turn
    produced no call either, and when they don't they raise 400 first.

    A demanded-but-absent call outranks the advisory note: it is the stronger
    statement and already names both the tone and the working alternatives.
    Streaming callers ask for both the ``declined=False`` and ``declined=True``
    variants up front and let the generator pick once the turn has arrived.
    """
    if read_only_guard:
        return ""
    demanded = required_tool_call_error(
        app,
        model_str=model_str,
        tone=tone,
        choice=choice,
        tool_calls=[],
        read_only_guard=False,
        declined=declined,
        planning_mode=planning_mode,
    )
    if demanded:
        return demanded
    # A model that explicitly declined honoured the contract, so there is no
    # shortfall to advertise -- that is the whole point of the marker.
    return (
        ""
        if declined
        else tool_calling_note(app, model_str, tone, tool_count, planning_mode)
    )


def _consumer_mode_options(app: FastAPI) -> list[dict]:
    return (
        getattr(app.state, "consumer_mode_options", None)
        or _BUILTIN_CONSUMER_MODE_OPTIONS
    )


def apply_request_model(
    app: FastAPI,
    raw_request: Request,
    client_factory: Callable[[Request], object],
    model_str: str | None,
) -> tuple[object, str, bool]:
    """Resolve the Provider selector before creating and configuring its client."""
    account = getattr(raw_request.state, "account", None)
    if getattr(account, "provider", "m365") == "consumer":
        mode_options = _consumer_mode_options(app)
        model_key = (model_str or "").strip().lower()
        option = next(
            (
                candidate
                for candidate in mode_options
                if candidate.get("model") == model_key
            ),
            None,
        )
        if option is None:
            available = ", ".join(
                str(candidate.get("model") or "") for candidate in mode_options
            )
            raise ValueError(
                f"Unknown Consumer model '{model_str or ''}'. Available Consumer "
                f"models: {available}"
            )
        client = client_factory(raw_request)
        client.mode = option["mode"]
        client.mode_status = option["status"]
        return client, option["mode"], True

    tone, _is_persist = resolve_request_tone(app, model_str)
    client = client_factory(raw_request)
    client._tone = tone
    return client, tone, False


def build_consumer_models_list(
    mode_options: list[dict], created: int, planning_mode: str | None = None,
) -> list[dict]:
    """Return the configured Consumer model catalogue in live order."""
    data = []
    for option in mode_options:
        status = effective_tool_calling(option.get("mode"), planning_mode)
        data.append({
            "id": option["model"],
            "object": "model",
            "created": created,
            "owned_by": "microsoft-copilot",
            # Measured per mode, same as the tone list (CONSUMER_MODE_TOOL_CALLING).
            # Consumer entries used to carry no tool hint at all, which a client
            # gating on the field reads as "no" -- the same pessimistic silence
            # this reports its way out of.
            "capabilities": {"tools": status != "unsupported"},
            "tool_calling": status,
        })
    return data


def effective_run_permission(app: FastAPI, k: ApiKey | None) -> str:
    """Resolve the run permission for a key, bounded by the global setting.

    The global value is a ceiling, not a default the key overrides: ``read_only``
    is the admin's "this proxy never hands a client a mutating tool call", and the
    per-key value is written by the caller's own /user page. Resolved as a plain
    override, a user escaped that policy with one POST /user/tone -- and the
    picker used to pin ``full`` on every save of the mode card, so a global later
    tightened to ``read_only`` applied to nobody who had ever saved it.

    Tightening still works in both directions, so a key may pin itself
    ``read_only`` under a ``full`` global. What it cannot do is widen: a per-key
    exception above a read-only global is deliberately not expressible, because
    nothing distinguishes an admin's grant from the user's own pin.
    """
    value = ((getattr(k, "run_permission", "") if k is not None else "") or "").strip()
    global_value = getattr(app.state, "run_permission", "full")
    if value not in _RUN_PERMISSIONS:
        return global_value
    return "read_only" if "read_only" in (value, global_value) else value


def effective_tool_planning_mode(app: FastAPI, k: ApiKey | None) -> str:
    """Resolve the tool planning mode for a key, falling back to the global setting.

    A plain override, unlike run_permission's ceiling: the choice is about how
    many upstream turns a tools-bearing request spends, not about what the model
    is allowed to do, and that cost lands on this key's own account (already
    bounded by its rate limit and per-account round cap). Which mode is right
    also depends on the tone this key is bound to -- see router_applies -- so the
    global value can only ever be a default.
    """
    value = ((getattr(k, "tool_planning_mode", "") if k is not None else "") or "").strip().lower()
    if value in TOOL_PLANNING_MODES:
        return value
    return getattr(app.state, "tool_planning_mode", "auto")
