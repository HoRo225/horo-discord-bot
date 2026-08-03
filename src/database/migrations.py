from __future__ import annotations

import asyncio
from pathlib import Path

from alembic.config import Config

from alembic import command
from src.config import PROJECT_ROOT


def _upgrade_sync(database_url: str) -> None:
    if database_url.startswith("sqlite+aiosqlite:///"):
        raw_path = database_url.removeprefix("sqlite+aiosqlite:///")
        if raw_path != ":memory:":
            Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


async def upgrade_database(database_url: str) -> None:
    await asyncio.to_thread(_upgrade_sync, database_url)
