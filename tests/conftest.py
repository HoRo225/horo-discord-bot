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


def _select(view, custom_id):
    """依 custom_id 定位單一選擇器（Select/ChannelSelect/RoleSelect 皆可），找不到回傳 None。

    三種選擇器共同的基底類別（BaseSelect）未對外公開，因此改用 custom_id 這個
    所有元件都有的屬性來過濾，不必分別 isinstance 三次。
    """
    return next(
        (item for item in view.walk_children() if getattr(item, "custom_id", None) == custom_id),
        None,
    )


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


def guild_settings(**overrides):
    """組出 settings 五個頁面讀得到的那些 GuildSettings 欄位，其餘留給資料庫。

    原本是 test_ui_settings.py 自帶的 `_guild_settings()`，搬來這裡讓五個頁面的
    測試共用；AI 頁另外會讀 ai_daily_guild_quota / ai_daily_user_quota，一併補上。
    """
    base = {
        "log_channel_id": None,
        "log_member_events": True,
        "log_message_events": True,
        "currency_name": "水晶",
        "daily_amount": 100,
        "blackjack_min_bet": 10,
        "blackjack_max_bet": 10_000,
        "poll_creator_role_ids": [],
        "ai_channel_ids": [],
        "ai_role_ids": [],
        "ai_model": None,
        "ai_daily_guild_quota": 500,
        "ai_daily_user_quota": 50,
    }
    return SimpleNamespace(**{**base, **overrides})
