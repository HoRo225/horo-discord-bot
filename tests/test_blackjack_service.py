from __future__ import annotations

import pytest

from src.services.blackjack import BlackjackService
from src.services.common import ValidationError


def shoe_for(*draws: str) -> list[str]:
    return ["2C"] * 20 + list(reversed(draws))


async def test_start_settlement_and_refund_paths(db, economy):
    service = BlackjackService(db, economy)
    await economy.apply(
        guild_id=1,
        user_id=10,
        amount=100,
        transaction_type="admin",
        idempotency_key="seed",
    )
    natural = await service.start(
        guild_id=1,
        user_id=10,
        channel_id=20,
        bet=10,
        idempotency_key="natural",
        shoe=shoe_for("AS", "9H", "KD", "7C"),
    )
    assert natural.game.phase == "settled"
    assert await economy.balance(1, 10) == 115

    active = await service.start(
        guild_id=1,
        user_id=10,
        channel_id=20,
        bet=20,
        idempotency_key="active",
        shoe=shoe_for("10S", "6H", "7D", "9C"),
    )
    assert active.game.phase == "playing"
    refunded = await service.refund_missing_message(active.game.id)
    assert refunded == 20
    assert await economy.balance(1, 10) == 115


async def test_timeout_auto_stands_and_settles(db, economy):
    service = BlackjackService(db, economy)
    await economy.apply(
        guild_id=1,
        user_id=10,
        amount=100,
        transaction_type="admin",
        idempotency_key="seed",
    )
    started = await service.start(
        guild_id=1,
        user_id=10,
        channel_id=20,
        bet=10,
        idempotency_key="timeout",
        shoe=shoe_for("10S", "6H", "8D", "9C", "10H"),
    )
    result = await service.timeout(started.game.id)
    assert result.game.phase == "settled"
    assert result.game.outcome["hands"][0]["result"] == "win"
    assert await economy.balance(1, 10) == 110


async def test_odd_bet_is_rejected_to_keep_three_to_two_exact(db, economy):
    service = BlackjackService(db, economy)
    await economy.apply(
        guild_id=1,
        user_id=10,
        amount=100,
        transaction_type="admin",
        idempotency_key="seed",
    )
    with pytest.raises(ValidationError, match="偶數"):
        await service.start(
            guild_id=1,
            user_id=10,
            channel_id=20,
            bet=11,
            idempotency_key="odd",
        )
    assert await economy.balance(1, 10) == 100


async def test_parallel_users_have_isolated_games(db, economy):
    service = BlackjackService(db, economy)
    for user_id in (10, 20):
        await economy.apply(
            guild_id=1,
            user_id=user_id,
            amount=100,
            transaction_type="admin",
            idempotency_key=f"seed-{user_id}",
        )
    first = await service.start(
        guild_id=1,
        user_id=10,
        channel_id=20,
        bet=10,
        idempotency_key="first-user",
        shoe=shoe_for("10S", "6H", "7D", "9C"),
    )
    second = await service.start(
        guild_id=1,
        user_id=20,
        channel_id=20,
        bet=20,
        idempotency_key="second-user",
        shoe=shoe_for("9S", "6D", "8H", "9D"),
    )
    assert first.game.id != second.game.id
    assert (await service.get_active(1, 10)).id == first.game.id
    assert (await service.get_active(1, 20)).id == second.game.id
    assert await economy.balance(1, 10) == 90
    assert await economy.balance(1, 20) == 80
