"""Background reclaim of idle sessions and their cloud conversations.

Every conversation this proxy opens leaves a row in that account's M365 chat
history, and nothing upstream ever removes it: a pool that has been serving for a
while accumulates thousands of abandoned conversations -- noise in the account's
real Copilot UI, and exactly the shape of usage that gets an account looked at.
``/admin`` and ``/user`` have a manual cleanup, but "somebody remembers to press
the button" is not a retention policy.

So a conversation is treated as a cache entry: using a session refreshes it, and
this loop reclaims what went cold. Two independent knobs, both runtime settings
and both 0 = off:

* ``session_idle_hours`` drops local sessions nobody continued. Off by default,
  because dropping a session means the next turn of that conversation opens a
  fresh upstream thread with no history -- a visible behaviour change, not just
  housekeeping.
* ``cloud_cleanup_idle_hours`` deletes cloud conversations older than the
  threshold that **no surviving local session points at**, so a reclaim can never
  break a conversation still in use. Also off by default, and for a sharper
  reason: "no local session points at it" includes the conversations the account's
  owner had in the Copilot web UI themselves, so on a real person's work account
  this deletes their own chat history. It is an opt-in for dedicated pool
  accounts, not a default. Consumer (personal Copilot) accounts are skipped
  outright -- they have no cloud conversation API at all.

The two compose: prune first, and the conversations of the sessions just dropped
stop being protected, so they are the ones the cloud pass reclaims.

Design reference: HEXUXIU/M365-Copilot2API (MIT), internal/web/auto_cleanup.go.
"""
from __future__ import annotations

import asyncio

from .m365_cloud_client import CloudSessionError, cleanup_conversations
from .runtime_flags import elog

# How often the loop wakes up while cleanup is disabled, so that enabling it in
# /admin takes effect without a restart.
_DISABLED_POLL_SECONDS = 60.0


async def auto_cleanup_once(
    app,
    *,
    session_idle_seconds: float,
    cloud_idle_seconds: float,
) -> tuple[list[str], list[str]]:
    """One reclaim pass. Returns (dropped store keys, deleted conversation ids)."""
    store = app.state.session_store
    removed: list[str] = []
    if session_idle_seconds > 0:
        # Per tenant, never one global sweep: on a shared deployment a busy
        # tenant's traffic must not decide when a quiet tenant's sessions go.
        for tenant in sorted({key.partition(":")[0] for key, _ in store.items()}):
            removed.extend(store.prune(prefix=f"{tenant}:", older_than=session_idle_seconds))

    deleted: list[str] = []
    if cloud_idle_seconds > 0:
        live = {
            session.conversation_id
            for _key, session in store.items()
            if session.conversation_id
        }
        for account in app.state.account_store.list():
            if getattr(account, "provider", "m365") != "m365":
                continue
            try:
                _count, ids = await cleanup_conversations(
                    app.state.account_store,
                    account.id,
                    older_than=cloud_idle_seconds,
                    protected=live,
                )
            except CloudSessionError as exc:
                # Expected for an account with no verified refresh token; the
                # next account still gets its sweep.
                elog(f"auto-cleanup: cloud unavailable for {account.id}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - one bad account, not a dead loop
                elog(f"auto-cleanup: cloud sweep failed for {account.id}: {exc!r}")
                continue
            deleted.extend(ids)

    if removed or deleted:
        elog(
            f"auto-cleanup: dropped {len(removed)} idle sessions, "
            f"deleted {len(deleted)} cloud conversations"
        )
    return removed, deleted


async def _loop(app) -> None:
    stop: asyncio.Event = app.state.auto_cleanup_stop
    while True:
        # Read the tunables every tick so an admin change lands without a
        # restart, including switching the whole thing on or off.
        interval = float(getattr(app.state, "auto_cleanup_minutes", 0) or 0) * 60
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=interval if interval > 0 else _DISABLED_POLL_SECONDS
            )
            return
        except asyncio.TimeoutError:
            pass
        if interval <= 0:
            continue
        try:
            await auto_cleanup_once(
                app,
                session_idle_seconds=float(getattr(app.state, "session_idle_hours", 0) or 0) * 3600,
                cloud_idle_seconds=float(getattr(app.state, "cloud_cleanup_idle_hours", 0) or 0) * 3600,
            )
        except Exception as exc:  # noqa: BLE001 - a failed pass must not kill the loop
            elog(f"auto-cleanup pass failed: {exc!r}")


def start_auto_cleanup(app) -> None:
    """Launch the background reclaim loop (idempotent)."""
    task = getattr(app.state, "auto_cleanup_task", None)
    if task is not None and not task.done():
        return
    app.state.auto_cleanup_stop = asyncio.Event()
    app.state.auto_cleanup_task = asyncio.create_task(_loop(app))


async def stop_auto_cleanup(app) -> None:
    """Signal the loop to stop and await its exit (best-effort)."""
    stop = getattr(app.state, "auto_cleanup_stop", None)
    if stop is not None:
        stop.set()
    task = getattr(app.state, "auto_cleanup_task", None)
    if task is not None:
        try:
            await asyncio.wait_for(task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
        except Exception:  # noqa: BLE001 - shutdown never fails on this
            pass
    app.state.auto_cleanup_task = None
