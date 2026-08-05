from __future__ import annotations

import re

import pytest

from src.config import PROJECT_ROOT, Settings


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://user:pw@localhost/horo",
        # 同步 driver：startswith("sqlite") 會放行，但 create_async_engine 與
        # scripts/backup.py 都只吃 aiosqlite。
        "sqlite:///./data/horo.db",
        "sqlite+pysqlite:///./data/horo.db",
    ],
)
def test_database_urls_other_than_aiosqlite_are_rejected(monkeypatch, url):
    """錨定 SQLite：換成其他後端不會報錯只會靜默失去併發保證，所以要在入口擋掉。"""
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", url)

    with pytest.raises(ValueError, match="sqlite"):
        Settings.from_env()


def test_sqlite_database_url_is_accepted(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./data/horo.db")

    settings = Settings.from_env()

    assert settings.database_url == "sqlite+aiosqlite:///./data/horo.db"


def test_default_ai_endpoint_matches_env_example_and_compose(monkeypatch):
    """三處曾經各說各話，沒設 AI_BASE_URL 的環境會連到不存在的位址。"""
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.delenv("AI_BASE_URL", raising=False)

    default = Settings.from_env().ai_base_url

    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert f"AI_BASE_URL={default}" in env_example

    # compose 的服務名稱與容器內連接埠必須真的對得上這個位址。
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    host, port = re.fullmatch(r"http://([^:/]+):(\d+)/v1", default).groups()
    assert re.search(rf"^  {re.escape(host)}:$", compose, re.MULTILINE)
    assert f":{port}:{port}" in compose


def test_ninerouter_image_is_pinned(monkeypatch):
    """latest 會隨上游改版漂移，讓同一個 commit 重新部署拿到不同的 build。"""
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    image = re.search(r"^\s*image:\s*(decolua/9router\S*)", compose, re.MULTILINE).group(1)
    assert not image.endswith(":latest")
    assert "@sha256:" in image
