from __future__ import annotations

"""Resolve an incoming OpenAI-style model name to an M365 conversation tone.

Each admin-configured tone is exposed as an independent model via /v1/models,
in two variants:

    <display_name>            -> normal (auto-grouped) session
    <display_name>-持续        -> persistent session (server remembers turns)

A client may address a tone either by its display name (label) or by its raw
underlying tone value (e.g. "Magic"). Both the "-持续" display suffix and the
legacy ":persist" model suffix mark the persistent variant. When a model name
matches no tone, the caller falls back to the global default tone.
"""

# Persistent-session markers accepted on an incoming model name. ":persist" is
# the legacy/underlying suffix already understood by _persistent_session; the
# "-持续" suffix is the human-facing variant shown in /v1/models.
PERSIST_MODEL_SUFFIX = ":persist"
PERSIST_DISPLAY_SUFFIX = "-持续"


def split_persist(model_str: str | None) -> tuple[str, bool]:
    """Split a model name into (base_without_persist_marker, is_persist)."""
    text = (model_str or "").strip()
    if not text:
        return "", False
    if text.lower().endswith(PERSIST_MODEL_SUFFIX):
        return text[: -len(PERSIST_MODEL_SUFFIX)].strip(), True
    if text.endswith(PERSIST_DISPLAY_SUFFIX):
        return text[: -len(PERSIST_DISPLAY_SUFFIX)].strip(), True
    return text, False


def resolve_tone(
    model_str: str | None,
    tone_options: list[dict],
    default_tone: str,
) -> tuple[str, bool]:
    """Map an incoming model name to (tone_value, is_persist).

    Matches the base name against each tone's raw value first, then its display
    label (case-insensitive). Unmatched names fall back to ``default_tone`` so a
    client that sends an arbitrary model string still works.
    """
    base, is_persist = split_persist(model_str)
    if base:
        base_low = base.lower()
        for option in tone_options:
            value = str(option.get("value") or "")
            if base == value:
                return value, is_persist
            label = str(option.get("label") or option.get("label_zh") or "")
            if label and base_low == label.lower():
                return value, is_persist
    return default_tone, is_persist


def build_models_list(tone_options: list[dict], created: int) -> list[dict]:
    """Produce the /v1/models data list: each tone yields a normal and a
    persistent (-持续) model entry, addressed by display name."""
    data: list[dict] = []
    seen: set[str] = set()
    for option in tone_options:
        label = str(option.get("label") or option.get("value") or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        for model_id in (label, f"{label}{PERSIST_DISPLAY_SUFFIX}"):
            data.append({
                "id": model_id,
                "object": "model",
                "created": created,
                "owned_by": "microsoft-365-copilot",
            })
    return data


def normalized_session_model(model_str: str | None) -> str:
    """Normalize an incoming model name for _persistent_session's suffix check.

    _persistent_session decides persistence by testing ``model.endswith(":persist")``.
    Client models may instead carry the human-facing ``-持续`` suffix, so we
    rewrite any recognized persist marker to the canonical ``:persist`` suffix
    (and strip it otherwise) so the existing session logic keeps working
    unchanged regardless of which variant the client addressed."""
    base, is_persist = split_persist(model_str)
    return f"{base}{PERSIST_MODEL_SUFFIX}" if is_persist else base
