from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from src.bot import HoRoBot


async def messageable_channel(bot: HoRoBot, channel_id: int) -> discord.abc.Messageable | None:
    """取得可發訊息的頻道：先查快取，沒有再打 API 補抓，兩者皆失敗回傳 None。

    三個背景 loop（21 點、抽獎、投票的到期處理）都需要這段邏輯，抽成共用函式避免各自維護。
    """
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.HTTPException:
            return None
    return channel if isinstance(channel, discord.abc.Messageable) else None
