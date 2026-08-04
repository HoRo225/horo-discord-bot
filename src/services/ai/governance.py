"""只放沒有 DB 依賴的治理工具，讓遮罩、記憶體、限流可以被單純的單元測試涵蓋。

需要交易的配額記帳住在 quota.py。
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src import strings
from src.services.ai.base import ChatMessage

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
