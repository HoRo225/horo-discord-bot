from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from src.database.models import Transaction
from src.services.common import ConflictError, InsufficientFundsError


async def test_daily_uses_taipei_day_and_is_idempotent(economy):
    before_midnight_utc = datetime(2026, 8, 3, 15, 59, tzinfo=UTC)
    after_midnight_utc = datetime(2026, 8, 3, 16, 1, tzinfo=UTC)
    first = await economy.daily(1, 10, 100, now=before_midnight_utc)
    duplicate = await economy.daily(1, 10, 100, now=before_midnight_utc)
    next_day = await economy.daily(1, 10, 100, now=after_midnight_utc)
    assert (first.claimed, duplicate.claimed, next_day.claimed) == (True, False, True)
    assert next_day.balance == 200


async def test_transaction_idempotency_and_no_negative_balance(db, economy):
    first = await economy.apply(
        guild_id=1,
        user_id=10,
        amount=100,
        transaction_type="admin",
        idempotency_key="same",
    )
    duplicate = await economy.apply(
        guild_id=1,
        user_id=10,
        amount=100,
        transaction_type="admin",
        idempotency_key="same",
    )
    assert first.created is True
    assert duplicate.created is False
    assert await economy.balance(1, 10) == 100
    with pytest.raises(InsufficientFundsError):
        await economy.apply(
            guild_id=1,
            user_id=10,
            amount=-101,
            transaction_type="admin",
            idempotency_key="too-much",
        )
    assert await economy.balance(1, 10) == 100
    async with db.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Transaction))
    assert count == 1


async def test_concurrent_duplicate_transfer_only_moves_money_once(db, economy):
    await economy.apply(
        guild_id=1,
        user_id=10,
        amount=100,
        transaction_type="admin",
        idempotency_key="seed",
    )

    async def transfer_once():
        return await economy.transfer(
            guild_id=1,
            sender_id=10,
            recipient_id=20,
            amount=25,
            idempotency_key="interaction-123",
        )

    await asyncio.gather(*(transfer_once() for _ in range(8)))
    assert await economy.balance(1, 10) == 75
    assert await economy.balance(1, 20) == 25
    async with db.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Transaction))
    assert count == 3


async def test_self_transfer_is_rejected(economy):
    with pytest.raises(ConflictError):
        await economy.transfer(
            guild_id=1,
            sender_id=10,
            recipient_id=10,
            amount=1,
            idempotency_key="self",
        )


async def test_transaction_audit_rows_are_immutable(db, economy):
    await economy.apply(
        guild_id=1,
        user_id=10,
        amount=100,
        transaction_type="admin",
        idempotency_key="immutable",
    )
    async with db.session_factory() as session:
        transaction = await session.scalar(select(Transaction))
        transaction.amount = 999
        with pytest.raises(RuntimeError, match="不可變"):
            await session.commit()
        await session.rollback()

    async with db.session_factory() as session:
        transaction = await session.scalar(select(Transaction))
        await session.delete(transaction)
        with pytest.raises(RuntimeError, match="不可變"):
            await session.commit()
