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

# 業務上限。餘額欄位本身是 BigInteger，這裡擋的是「這個數字對玩法還有意義嗎」，
# 不是溢位。
#
# 語意：只管制**外部資金流入**（簽到、管理員調整、收到轉帳）。牌局結算與退款不受
# 管制；而扣款即使發生在餘額已超過上限時也必須允許，否則玩家贏到上限以上後反而
# 無法下注、買券、轉帳或被管理員扣款。
MAX_BALANCE = 1_000_000_000
MAX_TRANSFER = 1_000_000


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

    @staticmethod
    async def existing_transaction(
        session: AsyncSession, guild_id: int, idempotency_key: str
    ) -> Transaction | None:
        """查同一把冪等鍵是否已經記過帳；呼叫端據此判斷這次是不是重放。"""
        return await session.scalar(
            select(Transaction).where(
                Transaction.guild_id == guild_id,
                Transaction.idempotency_key == idempotency_key,
            )
        )

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
        enforce_balance_cap: bool = True,
    ) -> TransactionResult:
        """記一筆帳並更新錢包餘額。

        `enforce_balance_cap` 預設 True，新增的正向資金流入路徑會自動落在受管制的
        安全側；要豁免必須主動寫出來，在 diff 上看得見。目前只有牌局結算與退款
        豁免。負向扣款不套用上限，只受「餘額不得低於 0」約束。
        """
        if not idempotency_key or len(idempotency_key) > 160:
            raise ValidationError(strings.ERR_IDEMPOTENCY_KEY)
        existing = await self.existing_transaction(session, guild_id, idempotency_key)
        if existing is not None:
            return TransactionResult(existing.balance_after, False, existing.id)

        wallet = await self._wallet(session, guild_id, user_id)
        new_balance = wallet.balance + amount
        if new_balance < 0:
            raise InsufficientFundsError(strings.ERR_INSUFFICIENT_FUNDS)
        # 上限只限制正向進帳。若牌局賠付已讓餘額高於上限，後續扣款仍必須能把它降回來。
        if enforce_balance_cap and amount > 0 and new_balance > MAX_BALANCE:
            raise ValidationError(strings.ERR_BALANCE_LIMIT.format(limit=MAX_BALANCE))
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
            # 回傳當前餘額而不是 result.balance：重放時後者是當初那筆交易的
            # 歷史快照，會與 last_daily 那條 early-return 回報的餘額不一致。
            return DailyResult(result.created, amount if result.created else 0, wallet.balance)

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
        if amount > MAX_TRANSFER:
            raise ValidationError(strings.ERR_TRANSFER_LIMIT.format(limit=MAX_TRANSFER))

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
