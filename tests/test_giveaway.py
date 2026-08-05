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
    await service.publish(giveaway.id, message_id=1000)
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
    await service.publish(giveaway.id, message_id=1001)
    result = await service.finalize(giveaway.id)
    assert result.status == "completed"
    assert result.winners == []


async def test_unpublished_giveaway_is_invisible_until_its_message_exists(db, economy):
    """Discord 發訊息失敗時抽獎停在 pending，背景結算不該對它發「已結束」公告。"""
    service = GiveawayService(db, economy)
    giveaway = await service.create(
        guild_id=1,
        channel_id=100,
        created_by=99,
        prize="尚未公開",
        winner_count=1,
        ends_at=datetime.now(UTC) + timedelta(hours=1),
        ticket_price=0,
        per_user_limit=1,
    )
    overdue = giveaway.ends_at + timedelta(seconds=1)

    assert giveaway.status == "pending"
    assert await service.active(1) == []
    assert await service.due(overdue) == []

    await service.publish(giveaway.id, message_id=777)

    assert [item.id for item in await service.active(1)] == [giveaway.id]
    assert [item.id for item in await service.due(overdue)] == [giveaway.id]


async def test_completed_lists_only_finalized_giveaways(db, economy):
    """重抽選單的資料來源；曾經誤用 active() 導致選任何項目都必然失敗。"""
    service = GiveawayService(db, economy)

    async def make(prize: str) -> int:
        giveaway = await service.create(
            guild_id=1,
            channel_id=100,
            created_by=99,
            prize=prize,
            winner_count=1,
            ends_at=datetime.now(UTC) + timedelta(hours=1),
            ticket_price=0,
            per_user_limit=1,
        )
        await service.publish(giveaway.id, message_id=2000 + giveaway.id)
        return giveaway.id

    still_running = await make("進行中")
    already_ended = await make("已結束")
    await service.finalize(already_ended)

    listed = await service.completed(1)

    assert [item.id for item in listed] == [already_ended]
    assert still_running not in [item.id for item in listed]
    # 每一個列出的項目都必須能通過 reroll() 的狀態檢查
    for item in listed:
        await service.reroll(item.id, admin_user_id=99)
