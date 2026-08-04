from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src import strings
from src.database.engine import Database
from src.database.models import AIUsage
from src.services.ai.base import ChatMessage
from src.services.common import DomainError, taipei_today


class QuotaExceededError(DomainError):
    pass


SENSITIVE_PATTERNS = (
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:mfa\.)?[A-Za-z\d_-]{20,}\.[A-Za-z\d_-]{6,}\.[A-Za-z\d_-]{20,}\b"),
    re.compile(r"(?i)\b(?:authorization|api[_ -]?key|token)\s*[:=]\s*\S+"),
)


def redact_sensitive(text: str, *, known_secrets: tuple[str, ...] = ()) -> str:
    redacted = text
    for secret in known_secrets:
        if secret:
            redacted = redacted.replace(secret, strings.REDACTED)
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub(strings.REDACTED, redacted)
    return redacted


@dataclass(frozen=True, slots=True)
class _MemoryItem:
    timestamp: datetime
    message: ChatMessage


class ConversationMemory:
    def __init__(
        self,
        *,
        max_messages: int = 20,
        max_characters: int = 12_000,
        ttl: timedelta = timedelta(hours=24),
    ) -> None:
        self.max_messages = max_messages
        self.max_characters = max_characters
        self.ttl = ttl
        self._channels: dict[tuple[int, int], deque[_MemoryItem]] = defaultdict(deque)

    def add(
        self,
        guild_id: int,
        channel_id: int,
        message: ChatMessage,
        *,
        now: datetime | None = None,
    ) -> None:
        current = now or datetime.now(UTC)
        queue = self._channels[(guild_id, channel_id)]
        queue.append(_MemoryItem(current, message))
        self._prune(queue, current)

    def get(
        self,
        guild_id: int,
        channel_id: int,
        *,
        now: datetime | None = None,
    ) -> list[ChatMessage]:
        current = now or datetime.now(UTC)
        queue = self._channels[(guild_id, channel_id)]
        self._prune(queue, current)
        return [item.message for item in queue]

    def _prune(self, queue: deque[_MemoryItem], now: datetime) -> None:
        cutoff = now - self.ttl
        while queue and queue[0].timestamp < cutoff:
            queue.popleft()
        while len(queue) > self.max_messages:
            queue.popleft()
        total = sum(len(item.message.content) for item in queue)
        while queue and total > self.max_characters:
            total -= len(queue.popleft().message.content)


class InMemoryRateLimiter:
    def __init__(self, interval_seconds: float) -> None:
        self.interval = interval_seconds
        self._last_used: dict[tuple[int, int], float] = {}

    def allow(self, guild_id: int, user_id: int, *, now: float | None = None) -> bool:
        current = now if now is not None else time.monotonic()
        key = (guild_id, user_id)
        previous = self._last_used.get(key)
        if previous is not None and current - previous < self.interval:
            return False
        self._last_used[key] = current
        return True


class AIUsageService:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def reserve(
        self,
        *,
        guild_id: int,
        user_id: int,
        guild_quota: int,
        user_quota: int,
        now: datetime | None = None,
    ) -> tuple[int, int]:
        if guild_quota <= 0 or user_quota <= 0:
            raise QuotaExceededError(strings.AI_QUOTA)
        today = taipei_today(now)

        async def operation(session: AsyncSession) -> tuple[int, int]:
            usage = await session.get(AIUsage, (guild_id, user_id, today))
            user_count = usage.request_count if usage else 0
            guild_count = int(
                await session.scalar(
                    select(func.coalesce(func.sum(AIUsage.request_count), 0)).where(
                        AIUsage.guild_id == guild_id, AIUsage.usage_date == today
                    )
                )
                or 0
            )
            if user_count >= user_quota or guild_count >= guild_quota:
                raise QuotaExceededError(strings.AI_QUOTA)
            if usage is None:
                usage = AIUsage(
                    guild_id=guild_id,
                    user_id=user_id,
                    usage_date=today,
                    request_count=0,
                    character_count=0,
                )
                session.add(usage)
            usage.request_count += 1
            return guild_count + 1, user_count + 1

        return await self.db.run_transaction(operation)

    async def record_characters(
        self,
        *,
        guild_id: int,
        user_id: int,
        character_count: int,
        now: datetime | None = None,
    ) -> None:
        today = taipei_today(now)

        async def operation(session: AsyncSession) -> None:
            usage = await session.get(AIUsage, (guild_id, user_id, today))
            if usage is not None:
                usage.character_count += max(0, character_count)

        await self.db.run_transaction(operation)

    async def release(
        self,
        *,
        guild_id: int,
        user_id: int,
        now: datetime | None = None,
    ) -> None:
        today = taipei_today(now)

        async def operation(session: AsyncSession) -> None:
            usage = await session.get(AIUsage, (guild_id, user_id, today))
            if usage is not None and usage.request_count > 0:
                usage.request_count -= 1

        await self.db.run_transaction(operation)
