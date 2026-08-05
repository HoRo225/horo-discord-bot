from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from src.database.models import Giveaway
from src.services.common import ConflictError
from src.services.giveaway import (
    MAX_REROLLS,
    REROLL_COOLDOWN,
    GiveawayService,
    weighted_sample_without_replacement,
)


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


async def _giveaway_with_entrants(service, economy, *, entrants: int):
    """建一場已結束的免費抽獎，並讓指定人數參加。"""
    giveaway = await service.create(
        guild_id=1,
        channel_id=100,
        created_by=99,
        prize="重抽測試",
        winner_count=1,
        ends_at=datetime.now(UTC) + timedelta(hours=1),
        ticket_price=0,
        per_user_limit=1,
    )
    await service.publish(giveaway.id, message_id=3000 + giveaway.id)
    for index in range(entrants):
        await service.enter(
            giveaway_id=giveaway.id,
            guild_id=1,
            user_id=100 + index,
            quantity=1,
            idempotency_key=f"join-{index}",
        )
    return await service.finalize(giveaway.id)


async def test_reroll_never_picks_a_winner_from_an_earlier_round(db, economy):
    """只排除上一輪的話，第二次重抽會把第一次的中獎者放回候選池。"""
    service = GiveawayService(db, economy)
    giveaway = await _giveaway_with_entrants(service, economy, entrants=3)
    seen = set(giveaway.winners)
    long_ago = datetime.now(UTC) - REROLL_COOLDOWN * 10

    for round_index in range(2):
        result = await service.reroll(
            giveaway.id,
            admin_user_id=99,
            now=long_ago + timedelta(hours=round_index),
        )
        assert not (set(result.winners) & seen), "重抽選到了先前輪次的中獎者"
        seen |= set(result.winners)

    assert len(seen) == 3


async def test_reroll_stops_at_the_round_limit(db, economy):
    service = GiveawayService(db, economy)
    giveaway = await _giveaway_with_entrants(service, economy, entrants=MAX_REROLLS + 2)
    long_ago = datetime.now(UTC) - REROLL_COOLDOWN * 100

    for round_index in range(MAX_REROLLS):
        await service.reroll(
            giveaway.id, admin_user_id=99, now=long_ago + timedelta(hours=round_index)
        )

    with pytest.raises(ConflictError):
        await service.reroll(giveaway.id, admin_user_id=99, now=datetime.now(UTC))


async def test_giveaway_defaults_to_pending_so_a_missed_status_cannot_orphan(db):
    """ORM 預設若是 active，任何漏傳 status 的新建立路徑都會直接產生孤兒紀錄。"""
    async with db.session_factory() as session:
        giveaway = Giveaway(
            guild_id=1,
            channel_id=100,
            created_by=99,
            prize="沒傳 status",
            winner_count=1,
            ends_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(giveaway)
        await session.flush()

        assert giveaway.status == "pending"


async def test_reroll_cooldown_message_does_not_overstate_the_wait(db, economy):
    """整除邊界：剛好剩 60 秒時不該報成 2 分鐘。"""
    service = GiveawayService(db, economy)
    giveaway = await _giveaway_with_entrants(service, economy, entrants=3)
    first_at = datetime.now(UTC)
    await service.reroll(giveaway.id, admin_user_id=99, now=first_at)

    with pytest.raises(ConflictError, match="1 分鐘"):
        await service.reroll(
            giveaway.id, admin_user_id=99, now=first_at + REROLL_COOLDOWN - timedelta(seconds=60)
        )


async def test_reroll_is_rate_limited_by_a_cooldown(db, economy):
    service = GiveawayService(db, economy)
    giveaway = await _giveaway_with_entrants(service, economy, entrants=3)
    first_at = datetime.now(UTC)

    await service.reroll(giveaway.id, admin_user_id=99, now=first_at)

    with pytest.raises(ConflictError):
        await service.reroll(
            giveaway.id, admin_user_id=99, now=first_at + REROLL_COOLDOWN - timedelta(seconds=1)
        )
    # 冷卻過後就放行。
    await service.reroll(
        giveaway.id, admin_user_id=99, now=first_at + REROLL_COOLDOWN + timedelta(seconds=1)
    )


async def test_reroll_without_candidates_keeps_the_existing_winners(db, economy):
    """候選耗盡時不該把 winners 洗成空的，那會連原本的中獎者一起抹掉。"""
    service = GiveawayService(db, economy)
    giveaway = await _giveaway_with_entrants(service, economy, entrants=1)
    original = list(giveaway.winners)
    assert original

    with pytest.raises(ConflictError):
        await service.reroll(giveaway.id, admin_user_id=99)

    listed = await service.completed(1)
    assert listed[0].winners == original
    assert listed[0].reroll_count == 0
    assert listed[0].last_reroll_at is None


async def test_replayed_entry_with_a_bigger_quantity_is_not_judged_against_the_limit(db, economy):
    """重放不會再扣款，所以不該拿新的 quantity 去比每人上限而誤判超限。"""
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
        per_user_limit=2,
    )
    await service.publish(giveaway.id, message_id=1002)
    await service.enter(
        giveaway_id=giveaway.id, guild_id=1, user_id=10, quantity=2, idempotency_key="click"
    )

    # 同一把鍵、更大的 quantity：這次已經付過款了，應該原樣回報而不是拋超限。
    replay = await service.enter(
        giveaway_id=giveaway.id, guild_id=1, user_id=10, quantity=5, idempotency_key="click"
    )

    assert replay.created is False
    assert replay.weight == 2
    assert await economy.balance(1, 10) == 900


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
    # 每一項都必須通過 reroll() 的狀態檢查。這場沒有參加者，所以會因為沒有
    # 候選人而擋下，但關鍵是不能因為狀態不符而被判定成「找不到」。
    for item in listed:
        with pytest.raises(ConflictError):
            await service.reroll(item.id, admin_user_id=99)
