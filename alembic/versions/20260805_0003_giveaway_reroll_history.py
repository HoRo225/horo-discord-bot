"""記錄抽獎重抽歷史。

重抽原本只排除當前 winners，所以第二次重抽會把第一次的中獎者放回候選池。
新增三個欄位以累積排除歷史中獎者，並支撐次數與冷卻限制。

Revision ID: 20260805_0003
Revises: 20260804_0002
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260805_0003"
down_revision: str | None = "20260804_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default 讓既有列補上值；欄位在 ORM 端由 default 供值，
    # 所以 server_default 只是為了這一次回填，不需要留在 model 上。
    with op.batch_alter_table("giveaways") as batch:
        batch.add_column(sa.Column("past_winners", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(
            sa.Column("reroll_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("last_reroll_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("giveaways") as batch:
        batch.drop_column("last_reroll_at")
        batch.drop_column("reroll_count")
        batch.drop_column("past_winners")
