from __future__ import annotations

from discord.ext import commands


class EconomyCog(commands.Cog):
    """經濟功能由常駐儀表板 UI 呼叫；Cog 作為功能載入邊界。"""

    def __init__(self, bot) -> None:
        self.bot = bot


async def setup(bot) -> None:
    await bot.add_cog(EconomyCog(bot))
