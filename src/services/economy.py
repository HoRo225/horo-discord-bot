from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import strings
from src.database.engine import Database
from src.database.models import AdminAudit, Transaction, Wallet
from src.services.common import (
    ConflictError,
    InsufficientFundsError,
    ValidationError,
    taipei_today,
)


@dataclass(frozen=True, slots=True)
class TransactionResult:
    balance: int
    created: bool
    transaction_id: int


@dataclass(frozen=True, slots=True)
class DailyResult:
    claimed: bool
    amount: int
    balance: int


class EconomyService:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    async def _wallet(session: AsyncSession, guild_id: int, user_id: int) -> Wallet:
        wallet = await session.get(Wallet, (guild_id, user_id))
        if wallet is None:
            wallet = Wallet(guild_id=guild_id, user_id=user_id, balance=0)
            session.add(wallet)
            await session.flush()
        return wallet

    async def apply_in_session(
        self,
        session: AsyncSession,
        *,
        guild_id: int,
        user_id: int,
        amount: int,
        transaction_type: str,
        idempotency_key: str,
        counterparty_user_id: int | None = None,
        details: dict[str, object] | None = None,
    ) -> TransactionResult:
        if not idempotency_key or len(idempotency_key) > 160:
            raise ValidationError(strings.ERR_IDEMPOTENCY_KEY)
        existing = await session.scalar(
            select(Transaction).where(
                Transaction.guild_id == guild_id,
                Transaction.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return TransactionResult(existing.balance_after, False, existing.id)

        wallet = await self._wallet(session, guild_id, user_id)
        new_balance = wallet.balance + amount
        if new_balance < 0:
            raise InsufficientFundsError(strings.ERR_INSUFFICIENT_FUNDS)
        wallet.balance = new_balance
        transaction = Transaction(
            guild_id=guild_id,
            user_id=user_id,
            amount=amount,
            balance_after=new_balance,
            transaction_type=transaction_type,
            idempotency_key=idempotency_key,
            counterparty_user_id=counterparty_user_id,
            details=details or {},
        )
        session.add(transaction)
        await session.flush()
        return TransactionResult(new_balance, True, transaction.id)

    async def apply(
        self,
        *,
        guild_id: int,
        user_id: int,
        amount: int,
        transaction_type: str,
        idempotency_key: str,
        counterparty_user_id: int | None = None,
        details: dict[str, object] | None = None,
    ) -> TransactionResult:
        async def operation(session: AsyncSession) -> TransactionResult:
            return await self.apply_in_session(
                session,
                guild_id=guild_id,
                user_id=user_id,
                amount=amount,
                transaction_type=transaction_type,
                idempotency_key=idempotency_key,
                counterparty_user_id=counterparty_user_id,
                details=details,
            )

        return await self.db.run_transaction(operation)

    async def balance(self, guild_id: int, user_id: int) -> int:
        async with self.db.session_factory() as session:
            wallet = await session.get(Wallet, (guild_id, user_id))
            return wallet.balance if wallet else 0

    async def daily(
        self,
        guild_id: int,
        user_id: int,
        amount: int,
        *,
        now: datetime | None = None,
    ) -> DailyResult:
        if amount <= 0:
            raise ValidationError(strings.ERR_DAILY_POSITIVE)
        today = taipei_today(now)

        async def operation(session: AsyncSession) -> DailyResult:
            wallet = await self._wallet(session, guild_id, user_id)
            if wallet.last_daily == today:
                return DailyResult(False, 0, wallet.balance)
            result = await self.apply_in_session(
                session,
                guild_id=guild_id,
                user_id=user_id,
                amount=amount,
                transaction_type="daily",
                idempotency_key=f"daily:{user_id}:{today.isoformat()}",
            )
            wallet.last_daily = today
            return DailyResult(result.created, amount if result.created else 0, result.balance)

        return await self.db.run_transaction(operation)

    async def transfer(
        self,
        *,
        guild_id: int,
        sender_id: int,
        recipient_id: int,
        amount: int,
        idempotency_key: str,
    ) -> tuple[int, int, bool]:
        if sender_id == recipient_id:
            raise ConflictError(strings.ERR_SELF_TRANSFER)
        if amount <= 0:
            raise ValidationError(strings.ERR_TRANSFER_POSITIVE)

        async def operation(session: AsyncSession) -> tuple[int, int, bool]:
            debit = await self.apply_in_session(
                session,
                guild_id=guild_id,
                user_id=sender_id,
                amount=-amount,
                transaction_type="transfer",
                idempotency_key=f"{idempotency_key}:debit",
                counterparty_user_id=recipient_id,
            )
            credit = await self.apply_in_session(
                session,
                guild_id=guild_id,
                user_id=recipient_id,
                amount=amount,
                transaction_type="transfer",
                idempotency_key=f"{idempotency_key}:credit",
                counterparty_user_id=sender_id,
            )
            return debit.balance, credit.balance, debit.created and credit.created

        return await self.db.run_transaction(operation)

    async def admin_adjust(
        self,
        *,
        guild_id: int,
        admin_user_id: int,
        target_user_id: int,
        amount: int,
        idempotency_key: str,
        reason: str = "",
    ) -> TransactionResult:
        if amount == 0:
            raise ValidationError(strings.ERR_ADJUST_NONZERO)

        async def operation(session: AsyncSession) -> TransactionResult:
            result = await self.apply_in_session(
                session,
                guild_id=guild_id,
                user_id=target_user_id,
                amount=amount,
                transaction_type="admin",
                idempotency_key=idempotency_key,
                details={"reason": reason, "admin_user_id": admin_user_id},
            )
            if result.created:
                session.add(
                    AdminAudit(
                        guild_id=guild_id,
                        admin_user_id=admin_user_id,
                        action="economy_adjust",
                        target_user_id=target_user_id,
                        details={"amount": amount, "reason": reason},
                    )
                )
            return result

        return await self.db.run_transaction(operation)

    async def leaderboard(self, guild_id: int, *, limit: int = 10) -> list[Wallet]:
        if not 1 <= limit <= 100:
            raise ValidationError(strings.ERR_LEADERBOARD_LIMIT)
        async with self.db.session_factory() as session:
            result = await session.scalars(
                select(Wallet)
                .where(Wallet.guild_id == guild_id)
                .order_by(Wallet.balance.desc(), Wallet.user_id.asc())
                .limit(limit)
            )
            return list(result)
