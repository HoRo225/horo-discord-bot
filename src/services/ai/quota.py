from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src import strings
from src.database.engine import Database
from src.database.models import AIUsage
from src.services.common import DomainError, taipei_today


class QuotaExceededError(DomainError):
    pass


class AIUsageService:
    """以「先扣後補」的方式管住每日請求數，確保併發下不會超賣配額。"""

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
