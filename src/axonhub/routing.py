import asyncio
import time
from collections.abc import Callable

from sqlalchemy import or_, update

from axonhub.db import Channel, Database


class ChannelRouter:
    """Smooth weighted round-robin with process-local failure cooldowns."""

    def __init__(
        self,
        failure_threshold: int,
        cooldown_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self._scores: dict[int, int] = {}
        self._failures: dict[int, int] = {}
        self._until: dict[int, float] = {}
        self._lock = asyncio.Lock()

    async def order(self, channels: list[Channel]) -> list[Channel]:
        async with self._lock:
            now = self.clock()
            candidates = [
                c
                for c in channels
                if self._until.get(c.id, 0) <= now
                and (c.request_budget is None or c.requests_sent < c.request_budget)
            ]
            if not candidates:
                return []
            for channel in candidates:
                self._scores[channel.id] = self._scores.get(channel.id, 0) + channel.weight
            selected = max(candidates, key=lambda c: self._scores[c.id])
            self._scores[selected.id] -= sum(c.weight for c in candidates)
            return [selected] + [c for c in candidates if c.id != selected.id]

    def failure(self, channel_id: int, *, immediate: bool = False) -> None:
        failures = self._failures.get(channel_id, 0) + 1
        self._failures[channel_id] = failures
        if immediate or failures >= self.failure_threshold:
            self._until[channel_id] = self.clock() + self.cooldown_seconds

    def success(self, channel_id: int) -> None:
        self._failures.pop(channel_id, None)
        self._until.pop(channel_id, None)

    def cooling(self, channel_id: int) -> bool:
        return self._until.get(channel_id, 0) > self.clock()


async def reserve_attempt(database: Database, channel_id: int) -> bool:
    """Atomically reserve a local request allowance, including failed dispatches."""
    async with database.sessions() as session:
        result = await session.execute(
            update(Channel)
            .where(
                Channel.id == channel_id,
                Channel.enabled.is_(True),
                or_(
                    Channel.request_budget.is_(None), Channel.requests_sent < Channel.request_budget
                ),
            )
            .values(requests_sent=Channel.requests_sent + 1)
        )
        await session.commit()
        return result.rowcount == 1
