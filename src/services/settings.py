from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src import strings
from src.database.engine import Database
from src.database.models import AdminAudit, GuildSettings
from src.services.common import ValidationError

ALLOWED_TEMPLATE_FIELDS = {"user", "server", "count"}


def validate_message_template(template: str) -> str:
    template = template.strip()
    if not template:
        raise ValidationError(strings.ERR_TEMPLATE_EMPTY)
    if len(template) > 1_500:
        raise ValidationError(strings.ERR_TEMPLATE_TOO_LONG)
    try:
        fields = {
            field_name for _, field_name, _, _ in string.Formatter().parse(template) if field_name
        }
    except ValueError as exc:
        raise ValidationError(strings.ERR_TEMPLATE_BRACES) from exc
    unknown = fields - ALLOWED_TEMPLATE_FIELDS
    if unknown:
        raise ValidationError(
            strings.ERR_TEMPLATE_UNKNOWN.format(fields=", ".join(sorted(unknown)))
        )
    return template


def parse_snowflake_list(value: str) -> list[int]:
    if not value.strip():
        return []
    items: list[int] = []
    for raw in value.replace("，", ",").split(","):
        cleaned = raw.strip().strip("<@#&!>")
        if not cleaned:
            continue
        if not cleaned.isdigit():
            raise ValidationError(strings.ERR_INVALID_ID.format(value=raw.strip()))
        number = int(cleaned)
        if number <= 0:
            raise ValidationError(strings.ERR_ID_POSITIVE)
        if number not in items:
            items.append(number)
    return items


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
            "welcome_channel_id",
            "goodbye_channel_id",
            "log_channel_id",
            "welcome_template",
            "goodbye_template",
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
        if "welcome_template" in values:
            values["welcome_template"] = validate_message_template(values["welcome_template"])
        if "goodbye_template" in values:
            values["goodbye_template"] = validate_message_template(values["goodbye_template"])
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

    @staticmethod
    def render_template(template: str, *, user: str, server: str, count: int) -> str:
        validated = validate_message_template(template)
        return validated.format(user=user, server=server, count=count)


def default_settings_preview() -> dict[str, str]:
    return {
        "welcome_template": strings.WELCOME_DEFAULT,
        "goodbye_template": strings.GOODBYE_DEFAULT,
    }
