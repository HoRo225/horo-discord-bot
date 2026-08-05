from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from src import strings
from src.cogs.common import messageable_channel
from src.ui.giveaway import GiveawayMessageView, winners_line

if TYPE_CHECKING:
    from src.bot import HoRoBot

log = logging.getLogger(__name__)

# 過期 pending 的保留期是 24 小時，用 30 秒的結算週期去掃等於每天多 2880 次
# 寫入交易，而且那是個吃不到索引的全表掃描。每 120 個 tick（約一小時）跑一次就夠。
STALE_SWEEP_EVERY_TICKS = 120


class GiveawayCog(commands.Cog):
    def __init__(self, bot: HoRoBot) -> None:
        self.bot = bot
        self._ticks = 0

    async def cog_load(self) -> None:
        self.finish_due.start()

    async def cog_unload(self) -> None:
        self.finish_due.cancel()

    @tasks.loop(seconds=30)
    async def finish_due(self) -> None:
        # 掃描本身也可能失敗；若例外逃出 tasks.loop，整個背景結算工作可能停止，
        # 但 gateway heartbeat 仍會繼續，healthcheck 看不出抽獎已不再結算。
        try:
            pending_items = await self.bot.giveaways.due()
        except Exception:
            log.exception("抽獎到期掃描失敗")
            pending_items = []

        for pending in pending_items:
            try:
                giveaway = await self.bot.giveaways.finalize(pending.id)
                channel = await messageable_channel(self.bot, giveaway.channel_id)
                if channel is None:
                    continue
                if giveaway.message_id:
                    try:
                        message = await channel.fetch_message(giveaway.message_id)
                        # 公告內容也在 view 裡，不能傳 view=None，否則整則公告會變空白；
                        # GiveawayMessageView 在非 active 狀態會自行收起參加按鈕。
                        await message.edit(
                            content=None,
                            embeds=[],
                            attachments=[],
                            view=GiveawayMessageView(self.bot, giveaway),
                        )
                    except discord.HTTPException:
                        pass
                if giveaway.winners:
                    content = strings.GIVEAWAY_ENDED.format(
                        prize=giveaway.prize, winners=winners_line(giveaway)
                    )
                    mentions = discord.AllowedMentions(users=True)
                else:
                    content = strings.GIVEAWAY_ENDED_NONE.format(prize=giveaway.prize)
                    mentions = discord.AllowedMentions.none()
                await channel.send(content, allowed_mentions=mentions)
            except Exception:
                log.exception(
                    "抽獎到期處理失敗",
                    extra={"guild_id": pending.guild_id, "giveaway_id": pending.id},
                )

        await self._sweep_stale_pending()

    async def _sweep_stale_pending(self) -> None:
        """清理過期 pending。

        刻意排在結算之後、用自己的 try 包起來：這是寫入交易，SQLite 只允許單一
        writer，遇到 database is locked 就會失敗。它是可有可無的維護工作，不該有
        能力擋掉真正重要的結算。
        """
        self._ticks += 1
        if self._ticks % STALE_SWEEP_EVERY_TICKS:
            return
        try:
            cancelled = await self.bot.giveaways.cancel_stale_pending()
            if cancelled:
                log.info("已取消 %s 筆過期 pending 抽獎", cancelled)
        except Exception:
            log.exception("清理過期 pending 抽獎失敗")

    @finish_due.before_loop
    async def before_finish_due(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: HoRoBot) -> None:
    await bot.add_cog(GiveawayCog(bot))
