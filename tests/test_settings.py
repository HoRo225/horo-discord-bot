from __future__ import annotations

import pytest

from src.services.common import ValidationError
from src.services.settings import MAX_AMOUNT, SettingsService


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


@pytest.mark.parametrize("key", ["daily_amount", "blackjack_min_bet", "blackjack_max_bet"])
async def test_amount_settings_have_an_upper_bound(db, key):
    """原本只擋負數，管理員可以把下注上限設到 10^17 之類毫無意義的量級。"""
    service = SettingsService(db)

    with pytest.raises(ValidationError):
        await service.update(1, 99, action="settings_economy", values={key: MAX_AMOUNT + 1})

    with pytest.raises(ValidationError):
        await service.update(1, 99, action="settings_economy", values={key: -1})


async def test_amount_settings_accept_the_boundary_value(db):
    service = SettingsService(db)

    settings = await service.update(
        1,
        99,
        action="settings_economy",
        values={"blackjack_min_bet": 1, "blackjack_max_bet": MAX_AMOUNT},
    )

    assert settings.blackjack_max_bet == MAX_AMOUNT
