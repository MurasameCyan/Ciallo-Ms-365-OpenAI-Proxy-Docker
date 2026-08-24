"""Per-account ceiling on how many upstream turns run at the same time.

An API-key pool multiplexes many clients onto one Microsoft account, so N
simultaneous requests mean N simultaneous substrate WebSockets on a single
identity. Nothing upstream queues on our behalf: past a handful of parallel
turns the account starts refusing them, and a refused turn costs more than a
turn that waited.

Requests **queue, they are never rejected**. Answering 429 here would be this
proxy inventing a failure the upstream never reported, and the callers are chat
clients that cope with "slow" far better than with "refused". The wait is
deliberately unbounded -- the caller's own read timeout is the ceiling.

Design reference: HEXUXIU/M365-Copilot2API (MIT), internal/web/account_concurrency.go.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from .runtime_flags import ulog


class AccountConcurrency:
    """One gate per account id, plus what is currently running or waiting on it."""

    def __init__(self) -> None:
        self._gates: dict[str, tuple[int, asyncio.Semaphore]] = {}
        self._inflight: dict[str, int] = {}
        self._waiting: dict[str, int] = {}

    def _gate(self, account_id: str, limit: int) -> asyncio.Semaphore:
        entry = self._gates.get(account_id)
        if entry is None or entry[0] != limit:
            # ponytail: a Semaphore cannot be resized, so changing the limit
            # installs a fresh one and abandons the old. Turns already holding
            # the old gate keep running, so for the length of one turn an
            # account can briefly exceed the new limit. The alternative is
            # tracking holders to migrate them, which buys nothing here.
            entry = (limit, asyncio.Semaphore(limit))
            self._gates[account_id] = entry
        return entry[1]

    @asynccontextmanager
    async def hold(self, account_id: str, limit: int):
        """Occupy one of this account's slots for the whole body. ``limit`` <= 0
        means unlimited -- still counted, just never made to wait."""
        gate = self._gate(account_id, limit) if limit > 0 else None
        if gate is not None:
            if gate.locked():
                # Otherwise a queued turn is indistinguishable from a hung one.
                ulog(
                    f"[concurrency] account {account_id}: {self._inflight.get(account_id, 0)} "
                    f"turns in flight (cap {limit}), waiting for a slot"
                )
            self._waiting[account_id] = self._waiting.get(account_id, 0) + 1
            try:
                await gate.acquire()
            finally:
                self._waiting[account_id] -= 1
        self._inflight[account_id] = self._inflight.get(account_id, 0) + 1
        try:
            yield
        finally:
            self._inflight[account_id] -= 1
            if gate is not None:
                gate.release()

    def stats(self) -> dict[str, dict[str, int]]:
        """Busy accounts only -- an idle pool reports nothing."""
        return {
            account_id: {"inflight": inflight, "waiting": self._waiting.get(account_id, 0)}
            for account_id, inflight in sorted(self._inflight.items())
            if inflight or self._waiting.get(account_id, 0)
        }


class ThrottledClient:
    """A copilot client whose turns go through one account's gate.

    Transparent on purpose: the /v1 routes assign to ``client.mode`` and
    ``client._tone`` on the way in and read attributes back out, and one test
    asserts the adapter type, so attribute reads, writes and ``isinstance`` all
    have to reach the wrapped client. Only the two turn-taking methods are
    intercepted.

    ``on_error`` sees every failed turn, whatever the provider. It exists so
    per-account bookkeeping that needs the turn's outcome can live at this one
    funnel instead of at the eleven call sites; classifying the exception is the
    caller's job, so this module stays free of provider imports.
    """

    # Deliberately odd names: everything else, including ``_client``, must fall
    # through to the wrapped object.
    __slots__ = ("_throttle_target", "_throttle_hold", "_throttle_on_error")

    def __init__(self, client, hold, on_error=None) -> None:
        object.__setattr__(self, "_throttle_target", client)
        object.__setattr__(self, "_throttle_hold", hold)
        object.__setattr__(self, "_throttle_on_error", on_error)

    @property
    def __class__(self):  # type: ignore[override]
        return self._throttle_target.__class__

    def __getattr__(self, name):
        return getattr(self._throttle_target, name)

    def __setattr__(self, name, value) -> None:
        setattr(self._throttle_target, name, value)

    def _throttle_note(self, exc: BaseException) -> None:
        hook = self._throttle_on_error
        if hook is None:
            return
        # Bookkeeping must never replace the turn's own error with its own, but a
        # hook that is quietly broken would also hide whatever it was recording.
        try:
            hook(exc)
        except Exception as hook_exc:  # pragma: no cover - defensive
            ulog(f"[concurrency] turn-error hook failed: {hook_exc!r}")

    async def chat(self, *args, **kwargs):
        async with self._throttle_hold():
            try:
                return await self._throttle_target.chat(*args, **kwargs)
            except Exception as exc:
                self._throttle_note(exc)
                raise

    async def chat_stream(self, *args, **kwargs):
        # Held for the whole iteration, not just the call: the upstream
        # WebSocket stays open until the last delta arrives.
        async with self._throttle_hold():
            try:
                async for delta in self._throttle_target.chat_stream(*args, **kwargs):
                    yield delta
            except Exception as exc:
                self._throttle_note(exc)
                raise
