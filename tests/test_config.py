from __future__ import annotations

import pytest

from src.config import Settings


def test_non_sqlite_database_url_is_rejected(monkeypatch):
    """錨定 SQLite：換成其他後端不會報錯只會靜默失去併發保證，所以要在入口擋掉。"""
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pw@localhost/horo")

    with pytest.raises(ValueError, match="SQLite"):
        Settings.from_env()


def test_sqlite_database_url_is_accepted(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./data/horo.db")

    settings = Settings.from_env()

    assert settings.database_url == "sqlite+aiosqlite:///./data/horo.db"
