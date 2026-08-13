"""Prompt compaction for the small Consumer Copilot text channel.

M365 does not use this module. Consumer sends one text part per turn and the
upstream currently rejects payloads somewhere between 10k and 12k characters,
so keep the current turn and agent-loop state while dropping old transcript.
"""

from __future__ import annotations


_SEPARATOR = "\n\n---\n\n"
_OMISSION = "\n\n[... omitted for Consumer Copilot prompt budget ...]\n\n"
_TOOL_CONTRACT_PREFIX = "Consumer tool contract:"
_SYSTEM_PREFIX = "System instructions:"
_TRANSCRIPT_PREFIX = "Prior conversation transcript:"


def _head_tail(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(_OMISSION) + 2:
        return text[:limit]
    available = limit - len(_OMISSION)
    head = available // 2
    return text[:head] + _OMISSION + text[-(available - head):]


def _latest_tool_result(transcript: str) -> str:
    """Return the newest tool-result suffix, if this transcript has one."""
    positions = [
        transcript.rfind("\nTool: Tool result"),
        transcript.rfind("\nTool: Tool error"),
        transcript.rfind("\nTool result"),
    ]
    position = max(positions)
    return transcript[position + 1 :] if position >= 0 else ""


def _join(context: list[str], prompt: str) -> str:
    return ("\n\n".join(context) + _SEPARATOR + prompt) if context else prompt


def validate_consumer_required_content(
    prompt: str,
    contract: str,
    max_chars: int,
) -> None:
    """Reject a tool contract that would truncate an otherwise fitting turn."""
    required_chars = len(_join([contract], prompt))
    contract_overhead = len(_join([contract], ""))
    if contract_overhead >= max_chars or (
        len(prompt) <= max_chars and required_chars > max_chars
    ):
        raise ValueError(
            f"Consumer prompt exceeds {max_chars}-character budget: required "
            f"tool signatures and current user prompt need {required_chars} "
            "characters; reduce tools/schema or prompt."
        )


def _context_capacity(selected: list[str], prompt: str, max_chars: int) -> int:
    """Characters a new context part may use without displacing ``prompt``."""
    separator = 2 if selected else len(_SEPARATOR)
    return max_chars - len(_join(selected, prompt)) - separator


def compact_consumer_prompt(
    prompt: str,
    context: list[str],
    max_chars: int,
) -> str:
    """Build one Consumer text part no longer than ``max_chars``.

    Compact tool contracts are mandatory. The current turn is next, followed by
    the latest tool result, recent transcript tail, and system head/tail.
    """
    if max_chars <= 0:
        raise ValueError("Consumer prompt budget must be positive")

    contracts = [part for part in context if part.startswith(_TOOL_CONTRACT_PREFIX)]
    transcripts = [part for part in context if part.startswith(_TRANSCRIPT_PREFIX)]
    systems = [part for part in context if part.startswith(_SYSTEM_PREFIX)]
    others = [
        part for part in context
        if part not in contracts and part not in transcripts and part not in systems
    ]

    # Preserve legacy byte-for-byte behaviour while it fits.
    original = _join(context, prompt)
    if len(original) <= max_chars:
        return original

    contract = "\n\n".join(contracts)
    if contract:
        validate_consumer_required_content(prompt, contract, max_chars)
    mandatory_context = [contract] if contract else []
    mandatory_overhead = len(_join(mandatory_context, "")) if mandatory_context else 0
    prompt_limit = max_chars - mandatory_overhead
    if prompt_limit < 0:
        raise ValueError("Consumer tool contract exceeds the prompt budget")
    compact_prompt = _head_tail(prompt, prompt_limit)

    selected = list(mandatory_context)

    transcript = "\n".join(transcripts)
    latest_tool = _latest_tool_result(transcript)
    capacity = _context_capacity(selected, compact_prompt, max_chars)
    if latest_tool and capacity > 0:
        tool_piece = _head_tail(latest_tool, capacity)
        selected.append(tool_piece)

    # Old transcript is lower priority than the current turn/tool result. Keep
    # its newest suffix only; this naturally retains the latest conversational
    # state and discards the oldest history first.
    recent_source = transcript[:-len(latest_tool)] if latest_tool else transcript
    capacity = _context_capacity(selected, compact_prompt, max_chars)
    if recent_source and capacity > 0:
        recent = recent_source[-capacity:]
        if recent and recent not in selected:
            selected.insert(len(mandatory_context), recent)

    low_priority = "\n\n".join(systems + others)
    capacity = _context_capacity(selected, compact_prompt, max_chars)
    if low_priority and capacity > 0:
        selected.insert(
            len(mandatory_context),
            _head_tail(low_priority, capacity),
        )

    result = _join(selected, compact_prompt)
    if len(result) > max_chars:
        raise AssertionError("Consumer prompt compaction exceeded its budget")
    return result
