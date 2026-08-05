from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from src.database.models import Transaction, Wallet
from src.services.common import ConflictError, InsufficientFundsError, ValidationError
from src.services.economy import MAX_BALANCE, MAX_TRANSFER


async def test_daily_uses_taipei_day_and_is_idempotent(economy):
    before_midnight_utc = datetime(2026, 8, 3, 15, 59, tzinfo=UTC)
    after_midnight_utc = datetime(2026, 8, 3, 16, 1, tzinfo=UTC)
    first = await economy.daily(1, 10, 100, now=before_midnight_utc)
    duplicate = await economy.daily(1, 10, 100, now=before_midnight_utc)
    next_day = await economy.daily(1, 10, 100, now=after_midnight_utc)
    assert (first.claimed, duplicate.claimed, next_day.claimed) == (True, False, True)
    assert next_day.balance == 200


async def test_repeated_daily_reports_current_balance_not_a_stale_snapshot(db, economy):
    """兩條「已簽到」的 early-return 必須回同一種餘額：當前餘額。"""
    day = datetime(2026, 8, 3, 15, 59, tzinfo=UTC)
    await economy.daily(1, 10, 100, now=day)
    # 簽到後另外進帳，讓「當前餘額」與「簽到當下的餘額」分岔。
    await economy.apply(
        guild_id=1,
        user_id=10,
        amount=50,
        transaction_type="admin",
        idempotency_key="later-topup",
    )

    # last_daily 那條 early-return。
    assert (await economy.daily(1, 10, 100, now=day)).balance == 150

    # 清掉 last_daily，改由冪等鍵攔截，兩條路徑要回報同一個數字。
    async with db.session_factory() as session:
        wallet = await session.get(Wallet, (1, 10))
        wallet.last_daily = None
        await session.commit()

    assert (await economy.daily(1, 10, 100, now=day)).balance == 150
    assert await economy.balance(1, 10) == 150


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


async def test_balance_and_transfer_have_business_ceilings(db, economy):
    await economy.apply(
        guild_id=1,
        user_id=10,
        amount=MAX_BALANCE,
        transaction_type="admin",
        idempotency_key="fill",
    )

    # 再多一塊就超過上限，且失敗的交易不得留下任何痕跡。
    with pytest.raises(ValidationError):
        await economy.apply(
            guild_id=1,
            user_id=10,
            amount=1,
            transaction_type="admin",
            idempotency_key="overflow",
        )
    assert await economy.balance(1, 10) == MAX_BALANCE
    async with db.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Transaction))
    assert count == 1

    with pytest.raises(ValidationError):
        await economy.transfer(
            guild_id=1,
            sender_id=10,
            recipient_id=20,
            amount=MAX_TRANSFER + 1,
            idempotency_key="too-big",
        )
    assert await economy.balance(1, 20) == 0


async def test_balance_cap_can_be_waived_for_internal_settlement(db, economy):
    """上限只管制外部資金流入；牌局結算與退款這類內部錢流必須能豁免。"""

    async def operation(session):
        await economy.apply_in_session(
            session,
            guild_id=1,
            user_id=10,
            amount=MAX_BALANCE,
            transaction_type="admin",
            idempotency_key="fill",
        )
        return await economy.apply_in_session(
            session,
            guild_id=1,
            user_id=10,
            amount=500,
            transaction_type="blackjack",
            idempotency_key="settle",
            enforce_balance_cap=False,
        )

    result = await db.run_transaction(operation)

    assert result.created is True
    assert await economy.balance(1, 10) == MAX_BALANCE + 500


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
