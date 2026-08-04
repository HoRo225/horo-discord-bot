from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

log = logging.getLogger(__name__)
T = TypeVar("T")


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self._ensure_sqlite_directory()
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
            connect_args={"timeout": 30} if url.startswith("sqlite") else {},
        )
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )
        if url.startswith("sqlite"):
            self._configure_sqlite()

    def _ensure_sqlite_directory(self) -> None:
        prefix = "sqlite+aiosqlite:///"
        if not self.url.startswith(prefix):
            return
        raw_path = self.url.removeprefix(prefix)
        if raw_path == ":memory:" or raw_path.startswith("file:"):
            return
        Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    def _configure_sqlite(self) -> None:
        @event.listens_for(self.engine.sync_engine, "connect")
        def set_sqlite_pragmas(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def run_with_retry(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
        *,
        attempts: int = 4,
    ) -> T:
        """用新 session 重試 SQLite 暫時鎖定；operation 必須可安全重跑。"""
        delay = 0.05
        for attempt in range(attempts):
            try:
                async with self.session_factory() as session:
                    return await operation(session)
            except OperationalError as exc:
                locked = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if not locked or attempt == attempts - 1:
                    raise
                log.warning("SQLite busy，準備重試（%s/%s）", attempt + 1, attempts)
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")

    async def run_transaction(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
        *,
        attempts: int = 4,
    ) -> T:
        async def transactional(session: AsyncSession) -> T:
            try:
                if self.url.startswith("sqlite"):
                    await session.execute(text("BEGIN IMMEDIATE"))
                else:
                    await session.begin()
                result = await operation(session)
                await session.commit()
                return result
            except BaseException:
                await session.rollback()
                raise

        return await self.run_with_retry(transactional, attempts=attempts)
