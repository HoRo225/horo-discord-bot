"""移除歡迎／送別功能相關欄位。

功能已整檔移除，guild_settings 不再需要 welcome/goodbye 頻道與模板欄位。

Revision ID: 20260804_0002
Revises: 20260803_0001
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260804_0002"
down_revision: str | None = "20260803_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# downgrade 需要重建 NOT NULL 的模板欄位，此處寫死原本的預設句字面值。
# 不 import src.strings：migration 是資料庫結構的歷史紀錄，不該依賴會持續變動的應用程式碼。
_WELCOME_DEFAULT = "歡迎 {user} 加入 {server}！你是第 {count} 位成員。"
_GOODBYE_DEFAULT = "{user} 離開了 {server}，目前共有 {count} 位成員。"


def upgrade() -> None:
    # SQLite（尤其舊版）不支援原生 DROP COLUMN，batch_alter_table 會自動改用
    # 「建立新表、搬移資料、換名」的方式達成；在 Postgres 上則會退化為原生 ALTER TABLE。
    with op.batch_alter_table("guild_settings") as batch:
        batch.drop_column("welcome_channel_id")
        batch.drop_column("goodbye_channel_id")
        batch.drop_column("welcome_template")
        batch.drop_column("goodbye_template")


def downgrade() -> None:
    with op.batch_alter_table("guild_settings") as batch:
        batch.add_column(sa.Column("welcome_channel_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("goodbye_channel_id", sa.BigInteger(), nullable=True))
        batch.add_column(
            sa.Column(
                "welcome_template",
                sa.Text(),
                nullable=False,
                server_default=_WELCOME_DEFAULT,
            )
        )
        batch.add_column(
            sa.Column(
                "goodbye_template",
                sa.Text(),
                nullable=False,
                server_default=_GOODBYE_DEFAULT,
            )
        )
