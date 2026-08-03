from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.services.ai.base import ChatMessage
from src.services.ai.governance import (
    AIUsageService,
    ConversationMemory,
    InMemoryRateLimiter,
    QuotaExceededError,
    redact_sensitive,
)


def test_sensitive_data_is_redacted():
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    assert secret not in redact_sensitive(f"key={secret}", known_secrets=(secret,))
    assert "abc@example.com" in redact_sensitive("abc@example.com")


def test_memory_is_bounded_and_expires():
    memory = ConversationMemory(max_messages=2, max_characters=20, ttl=timedelta(hours=24))
    now = datetime(2026, 8, 3, tzinfo=UTC)
    memory.add(1, 2, ChatMessage("user", "old"), now=now - timedelta(days=2))
    memory.add(1, 2, ChatMessage("user", "1234567890"), now=now)
    memory.add(1, 2, ChatMessage("assistant", "abcdefghij"), now=now)
    assert [item.content for item in memory.get(1, 2, now=now)] == [
        "1234567890",
        "abcdefghij",
    ]
    memory.add(1, 2, ChatMessage("user", "new"), now=now)
    assert len(memory.get(1, 2, now=now)) == 2


def test_rate_limiter():
    limiter = InMemoryRateLimiter(5)
    assert limiter.allow(1, 2, now=10)
    assert not limiter.allow(1, 2, now=12)
    assert limiter.allow(1, 2, now=15)


async def test_user_and_guild_ai_quotas(db):
    service = AIUsageService(db)
    now = datetime(2026, 8, 3, tzinfo=UTC)
    assert await service.reserve(guild_id=1, user_id=10, guild_quota=2, user_quota=1, now=now) == (
        1,
        1,
    )
    with pytest.raises(QuotaExceededError):
        await service.reserve(guild_id=1, user_id=10, guild_quota=2, user_quota=1, now=now)
    assert await service.reserve(guild_id=1, user_id=20, guild_quota=2, user_quota=1, now=now) == (
        2,
        1,
    )
    with pytest.raises(QuotaExceededError):
        await service.reserve(guild_id=1, user_id=30, guild_quota=2, user_quota=1, now=now)
    await service.release(guild_id=1, user_id=20, now=now)
    assert await service.reserve(guild_id=1, user_id=30, guild_quota=2, user_quota=1, now=now) == (
        2,
        1,
    )
