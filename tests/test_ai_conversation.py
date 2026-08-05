from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src import strings
from src.database.engine import Database
from src.database.models import AIUsage
from src.services.ai import (
    AIConversationService,
    AIDisabledError,
    AIProvider,
    AIRateLimitedError,
    AIUpstreamError,
    AIUsageService,
    ChatMessage,
    ConversationMemory,
    InMemoryRateLimiter,
    QuotaExceededError,
)
from src.services.common import taipei_today

GUILD_ID = 1
CHANNEL_ID = 2
USER_ID = 3


class FakeProvider(AIProvider):
    def __init__(self, response: str = "你好", *, error: BaseException | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, list[ChatMessage]]] = []

    async def list_models(self) -> list[str]:
        return ["fake-model"]

    async def chat(self, *, model: str, messages: list[ChatMessage]) -> str:
        self.calls.append((model, messages))
        if self.error is not None:
            raise self.error
        return self.response

    async def close(self) -> None:
        return None


def _service(db: Database, **overrides) -> AIConversationService:
    params = {
        "provider": FakeProvider(),
        "quota": AIUsageService(db),
        "memory": ConversationMemory(),
        "rate_limiter": InMemoryRateLimiter(5),
        "default_model": "default-model",
        "max_response_chars": 8_000,
    }
    return AIConversationService(**(params | overrides))


async def _respond(service: AIConversationService, **overrides) -> str:
    params = {
        "guild_id": GUILD_ID,
        "channel_id": CHANNEL_ID,
        "user_id": USER_ID,
        "prompt": "在嗎",
        "guild_model": "guild-model",
        "guild_quota": 10,
        "user_quota": 10,
    }
    return await service.respond(**(params | overrides))


async def _usage_counts(db: Database) -> tuple[int, int]:
    """直接查 DB 才能證明補償真的寫回去了，而不只是服務內部的旗標。"""

    async def operation(session: AsyncSession) -> tuple[int, int]:
        usage = await session.get(AIUsage, (GUILD_ID, USER_ID, taipei_today()))
        return (usage.request_count, usage.character_count) if usage else (0, 0)

    return await db.run_transaction(operation)


async def test_successful_turn_records_memory_and_usage(db):
    service = _service(db, provider=FakeProvider("你好呀"))
    response = await _respond(service)
    assert response == "你好呀"
    model, messages = service.provider.calls[0]
    assert model == "guild-model"
    assert messages[0] == ChatMessage("system", strings.AI_SYSTEM_PROMPT)
    history = service.memory.get(GUILD_ID, CHANNEL_ID)
    assert [(item.role, item.content) for item in history] == [
        ("user", "在嗎"),
        ("assistant", "你好呀"),
    ]
    assert await _usage_counts(db) == (1, len("你好呀"))


async def test_history_is_replayed_on_the_next_turn(db):
    service = _service(db, rate_limiter=InMemoryRateLimiter(0))
    await _respond(service, prompt="第一題")
    await _respond(service, prompt="第二題")
    _, messages = service.provider.calls[1]
    assert [item.role for item in messages] == ["system", "user", "assistant", "user"]
    assert messages[-1].content == "第二題"


async def test_missing_model_is_disabled_without_consuming_quota(db):
    service = _service(db, default_model="")
    with pytest.raises(AIDisabledError):
        await _respond(service, guild_model=None)
    assert service.provider.calls == []
    assert await _usage_counts(db) == (0, 0)


async def test_second_call_within_cooldown_is_rate_limited(db):
    service = _service(db)
    await _respond(service)
    with pytest.raises(AIRateLimitedError):
        await _respond(service)
    assert len(service.provider.calls) == 1
    assert (await _usage_counts(db))[0] == 1


async def test_exhausted_quota_raises(db):
    service = _service(db, rate_limiter=InMemoryRateLimiter(0))
    await _respond(service, user_quota=1)
    with pytest.raises(QuotaExceededError):
        await _respond(service, user_quota=1)
    assert len(service.provider.calls) == 1


async def test_upstream_failure_releases_reserved_quota(db):
    service = _service(db, provider=FakeProvider(error=AIUpstreamError("上游炸了")))
    with pytest.raises(AIUpstreamError):
        await _respond(service)
    assert await _usage_counts(db) == (0, 0)
    assert service.memory.get(GUILD_ID, CHANNEL_ID) == []


async def _usage_count_on(db: Database, day: date) -> int:
    async def operation(session: AsyncSession) -> int:
        usage = await session.get(AIUsage, (GUILD_ID, USER_ID, day))
        return usage.request_count if usage else 0

    return await db.run_transaction(operation)


async def test_quota_release_lands_on_the_day_the_request_was_reserved(db):
    """配額按台北日期分列；跨午夜失敗若讓 release 重算日期會扣在昨天、退在今天。"""
    # 台北時間 23:59（UTC+8）：此刻預留、稍後才失敗的請求最容易踩到跨日。
    # 日期刻意取一個永遠不會等於「今天」的過去日，否則 release 重算日期的
    # 錯誤行為會剛好落在同一天，測試就抓不到。
    late_night = datetime(2020, 1, 1, 15, 59, tzinfo=UTC)
    reserved_day = taipei_today(late_night)
    next_day = taipei_today(late_night + timedelta(minutes=2))
    assert reserved_day != next_day

    succeeding = _service(db, rate_limiter=InMemoryRateLimiter(0))
    await _respond(succeeding, now=late_night)
    assert await _usage_count_on(db, reserved_day) == 1

    failing = _service(
        db,
        rate_limiter=InMemoryRateLimiter(0),
        provider=FakeProvider(error=AIUpstreamError("上游炸了")),
    )
    with pytest.raises(AIUpstreamError):
        await _respond(failing, now=late_night)

    # 失敗那次要退回「預留當下」那一天，成功那次的計數不受影響。
    assert await _usage_count_on(db, reserved_day) == 1
    assert await _usage_count_on(db, next_day) == 0


async def test_cancellation_also_releases_reserved_quota(db):
    """互動逾時或使用者取消會丟 CancelledError，那同樣沒有真的用掉配額。"""
    service = _service(db, provider=FakeProvider(error=asyncio.CancelledError()))

    with pytest.raises(asyncio.CancelledError):
        await _respond(service)

    assert await _usage_counts(db) == (0, 0)


async def test_known_secret_is_redacted_both_ways(db):
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    service = _service(
        db,
        provider=FakeProvider(f"你的金鑰是 {secret}"),
        known_secrets=(secret,),
    )
    response = await _respond(service, prompt=f"請記住 {secret}")
    assert secret not in response
    assert strings.REDACTED in response
    _, messages = service.provider.calls[0]
    assert secret not in messages[-1].content


async def test_empty_prompt_falls_back_to_placeholder(db):
    service = _service(db)
    await _respond(service, prompt="")
    _, messages = service.provider.calls[0]
    assert messages[-1].content == strings.AI_EMPTY_PROMPT


async def test_long_response_is_truncated(db):
    service = _service(db, provider=FakeProvider("字" * 50), max_response_chars=10)
    response = await _respond(service)
    assert response == "字" * 10 + strings.AI_RESPONSE_TRUNCATED
