from __future__ import annotations

import pytest_asyncio

from src.database.engine import Database
from src.database.models import Base
from src.services.economy import EconomyService


@pytest_asyncio.fixture
async def db(tmp_path):
    path = (tmp_path / "test.db").as_posix()
    database = Database(f"sqlite+aiosqlite:///{path}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield database
    await database.dispose()


@pytest_asyncio.fixture
async def economy(db):
    return EconomyService(db)
