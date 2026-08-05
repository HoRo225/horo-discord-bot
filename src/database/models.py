from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class GuildSettings(Base):
    __tablename__ = "guild_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    log_member_events: Mapped[bool] = mapped_column(Boolean, default=True)
    log_message_events: Mapped[bool] = mapped_column(Boolean, default=True)
    dashboard_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    dashboard_message_id: Mapped[int | None] = mapped_column(BigInteger)
    currency_name: Mapped[str] = mapped_column(String(50), default="水晶")
    daily_amount: Mapped[int] = mapped_column(BigInteger, default=100)
    blackjack_min_bet: Mapped[int] = mapped_column(BigInteger, default=10)
    blackjack_max_bet: Mapped[int] = mapped_column(BigInteger, default=10_000)
    poll_creator_role_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    ai_channel_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    ai_role_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    ai_model: Mapped[str | None] = mapped_column(String(200))
    ai_daily_guild_quota: Mapped[int] = mapped_column(Integer, default=500)
    ai_daily_user_quota: Mapped[int] = mapped_column(Integer, default=50)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Wallet(Base):
    __tablename__ = "wallets"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    last_daily: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("guild_id", "idempotency_key", name="uq_transaction_idempotency"),
        Index("ix_transactions_guild_user_time", "guild_id", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    counterparty_user_id: Mapped[int | None] = mapped_column(BigInteger)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Giveaway(Base):
    __tablename__ = "giveaways"
    __table_args__ = (Index("ix_giveaways_guild_status_ends", "guild_id", "status", "ends_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    prize: Mapped[str] = mapped_column(String(300), nullable=False)
    winner_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ticket_price: Mapped[int] = mapped_column(BigInteger, default=0)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    # 預設 pending 而非 active：活動要等 publish() 綁上 Discord 訊息才生效。
    # 若預設是 active，任何漏傳 status 的新建立路徑都會直接產生孤兒紀錄。
    status: Mapped[str] = mapped_column(String(20), default="pending")
    winners: Mapped[list[int]] = mapped_column(JSON, default=list)
    # 累積的歷史中獎者。只看 winners 的話，重抽第二次就會把第一次的中獎者
    # 放回候選池，同一個人可能在不同輪次重複中獎。
    past_winners: Mapped[list[int]] = mapped_column(JSON, default=list)
    reroll_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reroll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GiveawayEntry(Base):
    __tablename__ = "giveaway_entries"

    giveaway_id: Mapped[int] = mapped_column(
        ForeignKey("giveaways.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    weight: Mapped[int] = mapped_column(Integer, default=0)
    spent: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Poll(Base):
    __tablename__ = "polls"
    __table_args__ = (Index("ix_polls_guild_status_ends", "guild_id", "status", "ends_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    question: Mapped[str] = mapped_column(String(300), nullable=False)
    answers: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    multiple: Mapped[bool] = mapped_column(Boolean, default=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 同 Giveaway.status：預設 pending，publish() 成功才轉 active。
    status: Mapped[str] = mapped_column(String(20), default="pending")
    results: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PollVote(Base):
    __tablename__ = "poll_votes"

    poll_id: Mapped[int] = mapped_column(
        ForeignKey("polls.id", ondelete="CASCADE"), primary_key=True
    )
    answer_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BlackjackGame(Base):
    __tablename__ = "blackjack_games"
    __table_args__ = (
        Index("ix_blackjack_guild_user_phase", "guild_id", "user_id", "phase"),
        Index("ix_blackjack_phase_expires", "phase", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    shoe: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    dealer_cards: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    hands: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    active_hand: Mapped[int] = mapped_column(Integer, default=0)
    initial_bet: Mapped[int] = mapped_column(BigInteger, nullable=False)
    insurance_bet: Mapped[int] = mapped_column(BigInteger, default=0)
    phase: Mapped[str] = mapped_column(String(30), nullable=False)
    outcome: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BlackjackStats(Base):
    __tablename__ = "blackjack_stats"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    pushes: Mapped[int] = mapped_column(Integer, default=0)
    blackjacks: Mapped[int] = mapped_column(Integer, default=0)
    total_wagered: Mapped[int] = mapped_column(BigInteger, default=0)
    total_won: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AdminAudit(Base):
    __tablename__ = "admin_audit"
    __table_args__ = (Index("ix_admin_audit_guild_time", "guild_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    admin_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_user_id: Mapped[int | None] = mapped_column(BigInteger)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIUsage(Base):
    __tablename__ = "ai_usage"
    __table_args__ = (Index("ix_ai_usage_guild_date", "guild_id", "usage_date"),)

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    character_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


@event.listens_for(Transaction, "before_update", propagate=True)
@event.listens_for(Transaction, "before_delete", propagate=True)
def _prevent_transaction_mutation(*_: object) -> None:
    raise RuntimeError("transactions 是不可變金流審計，不允許更新或刪除")
