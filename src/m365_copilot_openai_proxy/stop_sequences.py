"""Client-requested stop sequences, enforced on our side.

M365's ChatHub has no stop-sequence parameter -- the turn runs to its own end no
matter what the client asked for -- so honouring `stop` (OpenAI) and
`stop_sequences` (Anthropic) is entirely a delivery-side job: read the whole
upstream turn, hand the client only the text that precedes the first hit.

WHY THE UPSTREAM TURN IS STILL DRAINED. Truncation happens at the boundary to the
client, never by abandoning the turn: usage totals, the session's stored
assistant message and the completion frame's own bookkeeping all arrive with (or
after) the last delta. Breaking out of ``chat_stream`` early to save a few
hundred milliseconds would trade a correct usage row and a correct session
transcript for latency the client cannot even observe -- it already has its text.

THE STREAMING HALF NEEDS A HOLD-BACK, which is the only subtle part. Deltas split
wherever upstream chose to split them, so "STOP" can arrive as "ST" + "OP". A
forwarder that checks each delta in isolation never sees the sequence and leaks
it; one that forwards a delta whose tail is a prefix of a stop sequence has
already leaked it by the time the rest lands. So ``StopSequenceTrimmer`` keeps
the longest suffix that could still grow into a match and releases it only once
it cannot. The stream we emit is append-only: text handed out is never revoked.

Both spellings collapse to one list here. The difference between them is in the
response shape, not the matching: OpenAI reports a plain ``finish_reason:
"stop"`` (no field names the sequence), Anthropic reports ``stop_reason:
"stop_sequence"`` plus the ``stop_sequence`` that hit, so callers ask
``matched_sequence`` for it.
"""
from __future__ import annotations

# Anthropic's documented ceiling; OpenAI's is 4. Applying the looser of the two
# to both keeps one rule, and a client that sends more gets the excess dropped
# rather than a 400 -- the request is still answerable, just not with every
# sequence it hoped for.
MAX_STOP_SEQUENCES = 8


def normalize_stop(raw: object) -> list[str]:
    """The stop sequences in ``raw``, as a clean list.

    Accepts OpenAI's ``str | list[str]`` and Anthropic's ``list[str]``. Empty
    strings are dropped rather than honoured: an empty needle matches at position
    zero, which would truncate every answer to nothing.
    """
    if raw is None:
        return []
    values = [raw] if isinstance(raw, str) else raw
    if not isinstance(values, (list, tuple)):
        return []
    out: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        if value in out:
            continue
        out.append(value)
        if len(out) >= MAX_STOP_SEQUENCES:
            break
    return out


def apply_stop(text: str, stops: list[str]) -> tuple[str, str]:
    """``(text_up_to_the_first_hit, the_sequence_that_hit)``.

    "First" is by POSITION, not by the order the client listed them: two
    sequences that both appear must resolve to the earlier cut, or the answer
    keeps text the client asked to have withheld. Ties at the same position go to
    the longer sequence, so the reported ``stop_sequence`` is the more specific
    of the two.
    """
    if not text or not stops:
        return text, ""
    best_index = len(text)
    best_stop = ""
    for stop in stops:
        index = text.find(stop)
        if index < 0:
            continue
        if index < best_index or (index == best_index and len(stop) > len(best_stop)):
            best_index, best_stop = index, stop
    if not best_stop:
        return text, ""
    return text[:best_index], best_stop


def _held_suffix_len(pending: str, stops: list[str]) -> int:
    """How many trailing characters of ``pending`` must not be released yet.

    A suffix is held when it is a proper prefix of some stop sequence: it may be
    the front of a match whose remainder is still in flight. The longest such
    suffix wins, since releasing any part of it would leak text that a later
    delta could turn into a hit.
    """
    longest = 0
    for stop in stops:
        # A full occurrence is not this function's business (apply_stop already
        # cut there); only strictly shorter prefixes can still grow.
        limit = min(len(stop) - 1, len(pending))
        for size in range(limit, longest, -1):
            if pending[-size:] == stop[:size]:
                longest = size
                break
    return longest


class StopSequenceTrimmer:
    """Forwards stream text until a stop sequence hits, holding back partials.

    Usage per turn::

        trimmer = StopSequenceTrimmer(stops)
        for delta in upstream:
            out = trimmer.feed(delta)
            if out:
                yield out
            if trimmer.stopped:
                break_forwarding_but_keep_draining()
        yield trimmer.flush()

    ``feed`` returns only text that is safe forever. Once ``stopped`` is true it
    returns "" for every later delta, so a caller that keeps draining the turn
    (which it should) cannot accidentally emit past the cut.
    """

    __slots__ = ("_stops", "_pending", "_stopped", "_matched", "_released")

    def __init__(self, stops: list[str] | None):
        self._stops = [s for s in (stops or []) if s]
        self._pending = ""
        self._stopped = False
        self._matched = ""
        self._released = ""

    @property
    def active(self) -> bool:
        """Whether this trimmer can ever change the stream. False = pass-through."""
        return bool(self._stops)

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def matched_sequence(self) -> str:
        """The sequence that hit, or "" -- Anthropic reports this on the wire."""
        return self._matched

    @property
    def released_text(self) -> str:
        """Everything handed to the client so far, for usage/session bookkeeping.

        The record must agree with what was delivered, not with what upstream
        sent: a transcript holding text the client never saw would make the next
        turn reference invisible content.
        """
        return self._released

    def feed(self, delta: str) -> str:
        """Text to emit for this delta -- possibly "", never anything unsafe."""
        if self._stopped:
            return ""
        if not self._stops:
            self._released += delta
            return delta
        if not delta:
            return ""
        self._pending += delta
        cut, matched = apply_stop(self._pending, self._stops)
        if matched:
            self._stopped = True
            self._matched = matched
            self._pending = ""
            self._released += cut
            return cut
        hold = _held_suffix_len(self._pending, self._stops)
        if hold:
            out, self._pending = self._pending[:-hold], self._pending[-hold:]
        else:
            out, self._pending = self._pending, ""
        self._released += out
        return out

    def flush(self) -> str:
        """The held-back tail, once no further delta can arrive.

        A partial that never completed is ordinary answer text and must be
        delivered -- holding it back would silently truncate answers that merely
        end in something resembling a stop sequence.
        """
        if self._stopped or not self._pending:
            return ""
        out, self._pending = self._pending, ""
        self._released += out
        return out
