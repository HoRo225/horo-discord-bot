from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from src.config import PROJECT_ROOT
from src.database.migrations import upgrade_database


def _script_head() -> str:
    """從 migration 檔本身推出 head，這樣新增 migration 不必回頭改測試。"""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


async def test_sqlite_pragmas_are_enabled(db):
    async with db.engine.connect() as connection:
        journal_mode = await connection.scalar(text("PRAGMA journal_mode"))
        foreign_keys = await connection.scalar(text("PRAGMA foreign_keys"))
        busy_timeout = await connection.scalar(text("PRAGMA busy_timeout"))
    assert str(journal_mode).lower() == "wal"
    assert foreign_keys == 1
    assert busy_timeout == 30_000


async def test_alembic_upgrade_can_run_twice(tmp_path):
    path = (tmp_path / "migration.db").as_posix()
    url = f"sqlite+aiosqlite:///{path}"
    await upgrade_database(url)
    await upgrade_database(url)

    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    async with engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        tables = {
            row[0]
            for row in (
                await connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            )
        }
        guild_settings_columns = {
            row[1] for row in (await connection.execute(text("PRAGMA table_info(guild_settings)")))
        }
    await engine.dispose()
    assert revision == _script_head()
    assert {"wallets", "giveaways", "polls", "blackjack_games", "ai_usage"} <= tables
    # 歡迎功能已整檔移除，guild_settings 不應再殘留這些欄位。
    assert "welcome_channel_id" not in guild_settings_columns


async def test_migrations_produce_the_same_schema_as_the_orm_models(tmp_path):
    """conftest 的 db fixture 走 create_all，migration 壞掉測試不會紅。

    正式啟動走的是 alembic（bot.py 的 upgrade_database），所以兩條路徑
    產出的 schema 必須一致，否則「只改 model 忘了寫 migration」會一路
    通過測試直到部署才炸。
    """
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.database.models import Base

    path = (tmp_path / "drift.db").as_posix()
    url = f"sqlite+aiosqlite:///{path}"
    await upgrade_database(url)

    engine = create_async_engine(url)

    def _diff(sync_connection):
        context = MigrationContext.configure(sync_connection, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)

    async with engine.connect() as connection:
        diff = await connection.run_sync(_diff)
    await engine.dispose()

    # alembic 自己的版本表不在 ORM metadata 裡，是預期中的差異。
    drift = [entry for entry in diff if "alembic_version" not in str(entry)]
    assert drift == [], f"migration 與 ORM model 不一致：{drift}"
