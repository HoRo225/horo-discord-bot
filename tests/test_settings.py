from __future__ import annotations

from src.services.settings import SettingsService


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
