from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src import strings
from src.database.engine import Database
from src.database.models import AdminAudit, GuildSettings
from src.services.common import ValidationError


@dataclass(slots=True)
class SettingsService:
    db: Database

    async def get(self, guild_id: int) -> GuildSettings:
        async def operation(session: AsyncSession) -> GuildSettings:
            settings = await session.get(GuildSettings, guild_id)
            if settings is None:
                settings = GuildSettings(guild_id=guild_id)
                session.add(settings)
                await session.flush()
            return settings

        return await self.db.run_transaction(operation)

    async def update(
        self,
        guild_id: int,
        admin_user_id: int,
        *,
        action: str,
        values: dict[str, Any],
    ) -> GuildSettings:
        allowed = {
            "log_channel_id",
            "log_member_events",
            "log_message_events",
            "dashboard_channel_id",
            "dashboard_message_id",
            "currency_name",
            "daily_amount",
            "blackjack_min_bet",
            "blackjack_max_bet",
            "poll_creator_role_ids",
            "ai_channel_ids",
            "ai_role_ids",
            "ai_model",
            "ai_daily_guild_quota",
            "ai_daily_user_quota",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValidationError(
                strings.ERR_UNKNOWN_SETTINGS.format(fields=", ".join(sorted(unknown)))
            )
        if "currency_name" in values:
            name = str(values["currency_name"]).strip()
            if not 1 <= len(name) <= 50:
                raise ValidationError(strings.ERR_CURRENCY_LENGTH)
            values["currency_name"] = name
        for key in ("daily_amount", "blackjack_min_bet", "blackjack_max_bet"):
            if key in values and int(values[key]) < 0:
                raise ValidationError(strings.ERR_AMOUNT_NEGATIVE)
        for key in ("ai_daily_guild_quota", "ai_daily_user_quota"):
            if key in values and int(values[key]) <= 0:
                raise ValidationError(strings.ERR_AI_QUOTA_POSITIVE)
        if "ai_model" in values and values["ai_model"] is not None:
            model = str(values["ai_model"]).strip()
            if not 1 <= len(model) <= 200:
                raise ValidationError(strings.ERR_AI_MODEL_LENGTH)
            values["ai_model"] = model

        async def operation(session: AsyncSession) -> GuildSettings:
            settings = await session.get(GuildSettings, guild_id)
            if settings is None:
                settings = GuildSettings(guild_id=guild_id)
                session.add(settings)
                await session.flush()
            minimum = int(values.get("blackjack_min_bet", settings.blackjack_min_bet))
            maximum = int(values.get("blackjack_max_bet", settings.blackjack_max_bet))
            if minimum <= 0 or maximum < minimum:
                raise ValidationError(strings.ERR_BET_LIMITS)
            before = {key: getattr(settings, key) for key in values}
            for key, value in values.items():
                setattr(settings, key, value)
            session.add(
                AdminAudit(
                    guild_id=guild_id,
                    admin_user_id=admin_user_id,
                    action=action,
                    details={"before": before, "after": values},
                )
            )
            await session.flush()
            return settings

        return await self.db.run_transaction(operation)
