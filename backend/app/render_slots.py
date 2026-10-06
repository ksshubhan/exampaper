"""How many renders may run at once — one per user, a handful in total.

The daily cap bounds how many PDFs an account gets in a day; it says nothing
about how many it can have in flight. Fifty requests fired together are fifty
requests inside every limit we had, and the threadpool would happily start
dozens of Chromiums at once, each holding a few hundred megabytes. On a small
box the first thing that happens is the kernel killing the API.

Two limits, in front of the render rather than inside it:

* **one per user.** Nobody legitimately needs two PDFs building at the same
  moment — the paper and its mark scheme are downloaded one after the other —
  so a second concurrent request is refused outright rather than queued;
* **a few globally.** A short queue with a deadline, so a burst from several
  accounts waits its turn instead of arriving all at once, and a request that
  waits too long is told we are busy rather than left hanging.

Both pieces of state live in this process. That is only correct because
production runs a **single uvicorn worker** — with two workers each would keep
its own set and its own semaphore, and the real ceiling would quietly double.
See the deploy checklist in `docs/accounts-and-payments.md`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, HTTPException, status

from .auth import get_current_user
from .config import get_settings
from .models import User

IN_PROGRESS_DETAIL = {"code": "render_in_progress"}
BUSY_DETAIL = {"code": "render_busy"}


class RenderBusy(RuntimeError):
    """No concurrency slot came free in time. Answered 503 by the route.

    Not an `HTTPException`: the route has a render counted against the user by
    then and must give it back before refusing, so the refusal is its job.
    """


#: Accounts with a render in flight right now. Added to before the render
#: starts and removed on the way out of the request, whatever the outcome.
_in_flight: set[uuid.UUID] = set()

#: The global ceiling, built on first use so it reads the settings a test may
#: have changed. One `asyncio.Semaphore` is enough because there is one event
#: loop; see the module docstring on why that is a deployment constraint.
_slots: asyncio.Semaphore | None = None


def reset_render_slots() -> None:
    """Forget all concurrency state. For tests, between cases.

    A semaphore binds itself to the loop of whichever task first *waits* on
    it, so a suite that contends on one deliberately has to drop it along with
    the loop that owned it.
    """
    _in_flight.clear()
    global _slots
    _slots = None


def _semaphore() -> asyncio.Semaphore:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(get_settings().max_concurrent_renders)
    return _slots


def render_in_progress() -> HTTPException:
    """The refusal for a second simultaneous render by one account."""
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=IN_PROGRESS_DETAIL,
    )


async def hold_render_slot(
    user: User = Depends(get_current_user),
) -> AsyncIterator[None]:
    """FastAPI dependency: claim this account's one render, or refuse.

    Declared on the route ahead of `count_render`, so a request refused here
    has spent no render — it never started one.

    `async def` on purpose, and with no `await` between the test and the
    `add`: that pair has to be atomic against the other requests in flight,
    and on the event loop it is. A sync dependency would run in the threadpool,
    where two real threads could both read an empty set.
    """
    if user.id in _in_flight:
        raise render_in_progress()
    _in_flight.add(user.id)
    try:
        yield
    finally:
        # Runs on every exit — a 500 from the renderer, a 504 from the budget,
        # a cancelled request — or an account would lock itself out until the
        # process restarted.
        _in_flight.discard(user.id)


@asynccontextmanager
async def render_slot() -> AsyncIterator[None]:
    """Hold one of the global render slots, or raise `RenderBusy`.

    Wrapped around the threadpool hop only, so queueing time is not charged
    against the render's own wall-clock budget: waiting for a slot is not the
    document being slow.
    """
    settings = get_settings()
    try:
        await asyncio.wait_for(
            _semaphore().acquire(), timeout=settings.render_slot_wait_seconds
        )
    except TimeoutError as exc:
        raise RenderBusy(
            f"no render slot within {settings.render_slot_wait_seconds}s"
        ) from exc
    try:
        yield
    finally:
        _semaphore().release()
