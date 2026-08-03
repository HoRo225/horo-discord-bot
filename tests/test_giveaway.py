from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from src.services.giveaway import GiveawayService, weighted_sample_without_replacement


def test_weighted_sample_is_unique_and_respects_zero_weight():
    winners = weighted_sample_without_replacement(
        [(1, 0), (2, 1), (3, 10)], 3, rng=random.Random(7)
    )
    assert len(winners) == len(set(winners)) == 2
    assert 1 not in winners


async def test_paid_entry_is_atomic_and_idempotent(db, economy):
    service = GiveawayService(db, economy)
    await economy.apply(
        guild_id=1,
        user_id=10,
        amount=1_000,
        transaction_type="admin",
        idempotency_key="seed",
    )
    giveaway = await service.create(
        guild_id=1,
        channel_id=100,
        created_by=99,
        prize="測試獎品",
        winner_count=1,
        ends_at=datetime.now(UTC) + timedelta(hours=1),
        ticket_price=50,
        per_user_limit=5,
    )
    first = await service.enter(
        giveaway_id=giveaway.id,
        guild_id=1,
        user_id=10,
        quantity=2,
        idempotency_key="click",
    )
    duplicate = await service.enter(
        giveaway_id=giveaway.id,
        guild_id=1,
        user_id=10,
        quantity=2,
        idempotency_key="click",
    )
    assert first.weight == duplicate.weight == 2
    assert first.created is True and duplicate.created is False
    assert await economy.balance(1, 10) == 900


async def test_finalize_without_entries_has_empty_winners(db, economy):
    service = GiveawayService(db, economy)
    giveaway = await service.create(
        guild_id=1,
        channel_id=100,
        created_by=99,
        prize="無人抽獎",
        winner_count=2,
        ends_at=datetime.now(UTC) + timedelta(seconds=1),
        ticket_price=0,
        per_user_limit=1,
    )
    result = await service.finalize(giveaway.id)
    assert result.status == "completed"
    assert result.winners == []
