from __future__ import annotations

from types import SimpleNamespace

import discord
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


# 以下是多個 tests/test_ui_*.py 共用的 LayoutView 內省小工具與假 bot，
# 集中在這裡是因為它們純粹描述「怎麼從 view 裡挖出按鈕/文字」，跟任何單一測試主題無關；
# 各檔要用就 `from conftest import ...`，避免同一段 walk_children() 邏輯在多檔案裡各抄一份。


def _buttons(view):
    return [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]


def _button(view, custom_id):
    """依 custom_id 定位單一按鈕，找不到回傳 None——不綁「面板剛好有幾顆按鈕」。"""
    return next((item for item in _buttons(view) if item.custom_id == custom_id), None)


def _kinds(view):
    return [type(item).__name__ for item in view.walk_children()]


def _dispatch_custom_ids(view):
    return [item.custom_id for item in _buttons(view) if item.url is None]


def _texts(view):
    return [
        item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay)
    ]


def _container(view):
    return next(item for item in view.walk_children() if isinstance(item, discord.ui.Container))


def fake_bot(**over):
    """最小可用的假 bot：預設帶 settings.ai_default_model，符合 panel._model_name 的期待。"""
    return SimpleNamespace(settings=SimpleNamespace(ai_default_model=""), **over)
