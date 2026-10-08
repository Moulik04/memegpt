"""
Each visitor's daily allowance, counted in memes rather than requests: a
Lore run that makes five uses five.

Two limits, over a rolling 24 hours:

  - per browser (the anonymous id): settings.daily_memes_per_browser;
  - per network address: settings.daily_memes_per_address, higher, so an
    office or campus behind one address is not sharing a single browser's
    worth. It is also what clearing cookies runs into: a new browser id is
    a fresh browser allowance, on the same address.

The address ceiling only means something when the address can be believed
(visitor.py). With no PROXY_SHARED_SECRET configured it is skipped, since
"the address" would be the frontend's server for everybody. With one
configured, a request that proves nothing is counted against its
connection, which is the strict reading.

Counts live in this process and nowhere else: no database, no log. A
restart forgets them, which hands out a second allowance at worst.

An allowance is reserved before any model call and handed back for whatever
was not made, so requests arriving together cannot each see the same
remaining count and overrun it. The pre-made budget memes and other notices
are never counted: nothing was made.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from config import get_settings
from visitor import Visitor

_WINDOW_SECONDS = 24 * 3600.0
_SWEEP_EVERY = 500  # reservations between sweeps of keys that have gone quiet

_made: dict[str, deque[float]] = {}
_reservations_since_sweep = 0

LIMITED_BY_BROWSER = "browser"
LIMITED_BY_ADDRESS = "address"


def reset() -> None:
    _made.clear()


def _used(key: str, now: float) -> int:
    stamps = _made.get(key)
    if not stamps:
        return 0
    while stamps and stamps[0] <= now - _WINDOW_SECONDS:
        stamps.popleft()
    if not stamps:
        del _made[key]
        return 0
    return len(stamps)


def _sweep(now: float) -> None:
    for key in list(_made):
        _used(key, now)


def _limits(visitor: Visitor) -> list[tuple[str, str, int]]:
    """(which limit, bucket key, size) for every limit that applies."""
    settings = get_settings()
    limits: list[tuple[str, str, int]] = []
    if settings.daily_memes_per_browser > 0:
        # No browser id: one shared browser's worth per address, so leaving
        # the id off is never worth more than sending one.
        browser = f"id:{visitor.browser}" if visitor.browser else f"none:{visitor.address}"
        limits.append((LIMITED_BY_BROWSER, f"browser:{browser}", settings.daily_memes_per_browser))
    if settings.daily_memes_per_address > 0 and settings.proxy_shared_secret:
        limits.append((LIMITED_BY_ADDRESS, f"address:{visitor.address}", settings.daily_memes_per_address))
    return limits


@dataclass(frozen=True)
class Allowance:
    remaining: int | None  # None: no limit applies
    limited_by: str | None  # which limit is the tighter one right now
    limit: int | None  # that limit's size, for the message

    @property
    def exhausted(self) -> bool:
        return self.remaining is not None and self.remaining <= 0

    def cap(self, wanted: int | None) -> int | None:
        """`wanted` memes, or as many of them as are left."""
        if wanted is None or self.remaining is None:
            return wanted
        return min(wanted, max(self.remaining, 0))


def allowance(visitor: Visitor) -> Allowance:
    now = time.time()
    tightest: tuple[int, str, int] | None = None
    for which, key, size in _limits(visitor):
        left = size - _used(key, now)
        if tightest is None or left < tightest[0]:
            tightest = (left, which, size)
    if tightest is None:
        return Allowance(remaining=None, limited_by=None, limit=None)
    return Allowance(remaining=max(tightest[0], 0), limited_by=tightest[1], limit=tightest[2])


class Reservation:
    """`granted` memes set aside for one request. settle() hands back the
    ones that were not made."""

    def __init__(self, visitor: Visitor, keys: list[str], wanted: int, granted: int):
        self._visitor = visitor
        self._keys = keys
        self.wanted = wanted
        self.granted = granted
        self._unreleased = granted
        self._settled = False

    def allowance_now(self) -> Allowance:
        return allowance(self._visitor)

    def ran_out(self) -> bool:
        """The visitor asked for more than they had left and has nothing
        left now. False if memes were handed back since (a failed pick, say):
        they can simply ask again."""
        return self.granted < self.wanted and self.allowance_now().exhausted

    def release(self, count: int) -> None:
        count = min(count, self._unreleased)
        if count <= 0:
            return
        self._unreleased -= count
        for key in self._keys:
            stamps = _made.get(key)
            for _ in range(min(count, len(stamps) if stamps else 0)):
                stamps.pop()
            if stamps is not None and not stamps:
                del _made[key]

    def settle(self, made: int) -> None:
        """The request is over and `made` memes came out of it. Only the
        first call counts."""
        if self._settled:
            return
        self._settled = True
        self.release(self.granted - made)


def reserve(visitor: Visitor, wanted: int) -> Reservation:
    """Set aside up to `wanted` memes. No await between the check and the
    write, so two requests cannot both take the last one."""
    global _reservations_since_sweep
    now = time.time()
    _reservations_since_sweep += 1
    if _reservations_since_sweep >= _SWEEP_EVERY:
        _reservations_since_sweep = 0
        _sweep(now)

    current = allowance(visitor)
    granted = wanted if current.remaining is None else max(min(wanted, current.remaining), 0)
    keys = [key for _, key, _ in _limits(visitor)]
    for key in keys:
        _made.setdefault(key, deque()).extend([now] * granted)
    return Reservation(visitor, keys, wanted, granted)
