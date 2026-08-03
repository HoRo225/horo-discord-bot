from __future__ import annotations

import asyncio

from sqlalchemy import text

from src.config import Settings
from src.database.engine import Database


async def check() -> None:
    settings = Settings.from_env(require_token=False)
    database = Database(settings.database_url)
    try:
        async with database.engine.connect() as connection:
            assert await connection.scalar(text("SELECT 1")) == 1
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(check())
