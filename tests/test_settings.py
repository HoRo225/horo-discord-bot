from __future__ import annotations

import pytest

from src.services.common import ValidationError
from src.services.settings import (
    SettingsService,
    parse_snowflake_list,
    validate_message_template,
)


def test_template_allows_only_documented_fields():
    assert validate_message_template("歡迎 {user} 到 {server}，第 {count} 位")
    with pytest.raises(ValidationError, match="不支援"):
        validate_message_template("{user.__class__}")
    with pytest.raises(ValidationError, match="大括號"):
        validate_message_template("歡迎 {")


def test_parse_snowflake_list_accepts_mentions_and_deduplicates():
    assert parse_snowflake_list("<@&123>, 456，123") == [123, 456]
    with pytest.raises(ValidationError):
        parse_snowflake_list("abc")


async def test_settings_update_is_audited(db):
    service = SettingsService(db)
    settings = await service.update(
        1,
        99,
        action="settings_economy",
        values={"currency_name": "天鵝幣", "daily_amount": 250},
    )
    assert settings.currency_name == "天鵝幣"
    assert settings.daily_amount == 250

    from sqlalchemy import func, select

    from src.database.models import AdminAudit

    async with db.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(AdminAudit))
    assert count == 1
