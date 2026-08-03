from __future__ import annotations

from sqlalchemy import text

from src.database.migrations import upgrade_database


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
    await engine.dispose()
    assert revision == "20260803_0001"
    assert {"wallets", "giveaways", "polls", "blackjack_games", "ai_usage"} <= tables
