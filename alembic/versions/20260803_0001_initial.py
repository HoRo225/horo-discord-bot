"""建立 Crystalline Swan 完整初始資料表。

Revision ID: 20260803_0001
Revises:
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260803_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "guild_settings",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("welcome_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("goodbye_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("log_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("welcome_template", sa.Text(), nullable=False),
        sa.Column("goodbye_template", sa.Text(), nullable=False),
        sa.Column("log_member_events", sa.Boolean(), nullable=False),
        sa.Column("log_message_events", sa.Boolean(), nullable=False),
        sa.Column("dashboard_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("dashboard_message_id", sa.BigInteger(), nullable=True),
        sa.Column("currency_name", sa.String(length=50), nullable=False),
        sa.Column("daily_amount", sa.BigInteger(), nullable=False),
        sa.Column("blackjack_min_bet", sa.BigInteger(), nullable=False),
        sa.Column("blackjack_max_bet", sa.BigInteger(), nullable=False),
        sa.Column("poll_creator_role_ids", sa.JSON(), nullable=False),
        sa.Column("ai_channel_ids", sa.JSON(), nullable=False),
        sa.Column("ai_role_ids", sa.JSON(), nullable=False),
        sa.Column("ai_model", sa.String(length=200), nullable=True),
        sa.Column("ai_daily_guild_quota", sa.Integer(), nullable=False),
        sa.Column("ai_daily_user_quota", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("guild_id"),
    )
    op.create_table(
        "wallets",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("balance", sa.BigInteger(), nullable=False),
        sa.Column("last_daily", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("guild_id", "user_id"),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("transaction_type", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("counterparty_user_id", sa.BigInteger(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "idempotency_key", name="uq_transaction_idempotency"),
    )
    op.create_index(
        "ix_transactions_guild_user_time",
        "transactions",
        ["guild_id", "user_id", "created_at"],
    )
    op.create_table(
        "giveaways",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("prize", sa.String(length=300), nullable=False),
        sa.Column("winner_count", sa.Integer(), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ticket_price", sa.BigInteger(), nullable=False),
        sa.Column("per_user_limit", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("winners", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_giveaways_guild_status_ends",
        "giveaways",
        ["guild_id", "status", "ends_at"],
    )
    op.create_table(
        "giveaway_entries",
        sa.Column("giveaway_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("spent", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["giveaway_id"], ["giveaways.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("giveaway_id", "user_id"),
    )
    op.create_table(
        "polls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("question", sa.String(length=300), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("multiple", sa.Boolean(), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_polls_guild_status_ends", "polls", ["guild_id", "status", "ends_at"])
    op.create_table(
        "poll_votes",
        sa.Column("poll_id", sa.Integer(), nullable=False),
        sa.Column("answer_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["poll_id"], ["polls.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("poll_id", "answer_id", "user_id"),
    )
    op.create_table(
        "blackjack_games",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("shoe", sa.JSON(), nullable=False),
        sa.Column("dealer_cards", sa.JSON(), nullable=False),
        sa.Column("hands", sa.JSON(), nullable=False),
        sa.Column("active_hand", sa.Integer(), nullable=False),
        sa.Column("initial_bet", sa.BigInteger(), nullable=False),
        sa.Column("insurance_bet", sa.BigInteger(), nullable=False),
        sa.Column("phase", sa.String(length=30), nullable=False),
        sa.Column("outcome", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_blackjack_guild_user_phase",
        "blackjack_games",
        ["guild_id", "user_id", "phase"],
    )
    op.create_index("ix_blackjack_phase_expires", "blackjack_games", ["phase", "expires_at"])
    op.create_table(
        "blackjack_stats",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("losses", sa.Integer(), nullable=False),
        sa.Column("pushes", sa.Integer(), nullable=False),
        sa.Column("blackjacks", sa.Integer(), nullable=False),
        sa.Column("total_wagered", sa.BigInteger(), nullable=False),
        sa.Column("total_won", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("guild_id", "user_id"),
    )
    op.create_table(
        "admin_audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("admin_user_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("target_user_id", sa.BigInteger(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_audit_guild_time", "admin_audit", ["guild_id", "created_at"])
    op.create_table(
        "ai_usage",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("guild_id", "user_id", "usage_date"),
    )
    op.create_index("ix_ai_usage_guild_date", "ai_usage", ["guild_id", "usage_date"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_guild_date", table_name="ai_usage")
    op.drop_table("ai_usage")
    op.drop_index("ix_admin_audit_guild_time", table_name="admin_audit")
    op.drop_table("admin_audit")
    op.drop_table("blackjack_stats")
    op.drop_index("ix_blackjack_phase_expires", table_name="blackjack_games")
    op.drop_index("ix_blackjack_guild_user_phase", table_name="blackjack_games")
    op.drop_table("blackjack_games")
    op.drop_table("poll_votes")
    op.drop_index("ix_polls_guild_status_ends", table_name="polls")
    op.drop_table("polls")
    op.drop_table("giveaway_entries")
    op.drop_index("ix_giveaways_guild_status_ends", table_name="giveaways")
    op.drop_table("giveaways")
    op.drop_index("ix_transactions_guild_user_time", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("wallets")
    op.drop_table("guild_settings")
