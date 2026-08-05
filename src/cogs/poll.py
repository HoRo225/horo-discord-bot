from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from src import strings
from src.cogs.common import messageable_channel
from src.services.poll import PollAnswerSnapshot

if TYPE_CHECKING:
    from src.bot import HoRoBot

log = logging.getLogger(__name__)

# 同 cogs/giveaway.py：保留期 24 小時的清理不需要 30 秒跑一次。
STALE_SWEEP_EVERY_TICKS = 120


class PollCog(commands.Cog):
    def __init__(self, bot: HoRoBot) -> None:
        self.bot = bot
        self._ticks = 0

    async def cog_load(self) -> None:
        self.finish_due.start()

    async def cog_unload(self) -> None:
        self.finish_due.cancel()

    async def _snapshots(self, native: discord.Poll | None) -> list[PollAnswerSnapshot]:
        if native is None:
            return []
        snapshots: list[PollAnswerSnapshot] = []
        for answer in native.answers:
            voters: list[int] = []
            try:
                async for voter in answer.voters():
                    voters.append(voter.id)
            except discord.HTTPException:
                log.warning("無法取得原生投票 voters 明細", extra={"answer_id": answer.id})
            snapshots.append(
                PollAnswerSnapshot(
                    answer_id=answer.id,
                    text=answer.text,
                    vote_count=answer.vote_count,
                    voter_ids=voters,
                )
            )
        return snapshots

    @tasks.loop(seconds=30)
    async def finish_due(self) -> None:
        # 掃描失敗不該讓例外逃出 tasks.loop，否則整個背景結算會停止而 healthcheck
        # 看不出來（gateway heartbeat 仍正常）。
        try:
            pending_items = await self.bot.polls.due()
        except Exception:
            log.exception("投票到期掃描失敗")
            pending_items = []

        for pending in pending_items:
            try:
                channel = await messageable_channel(self.bot, pending.channel_id)
                native: discord.Poll | None = None
                if channel is not None and pending.message_id:
                    try:
                        message = await channel.fetch_message(pending.message_id)
                        native = message.poll
                        if native is not None and not native.is_finalized():
                            try:
                                message = await message.end_poll()
                                native = message.poll
                            except discord.HTTPException:
                                message = await channel.fetch_message(pending.message_id)
                                native = message.poll
                    except discord.HTTPException:
                        native = None
                completed = await self.bot.polls.complete(pending.id, await self._snapshots(native))
                if channel is not None:
                    await channel.send(
                        strings.POLL_ENDED.format(question=completed.question),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
            except Exception:
                log.exception(
                    "投票到期處理失敗",
                    extra={"guild_id": pending.guild_id, "poll_id": pending.id},
                )

        await self._sweep_stale_pending()

    async def _sweep_stale_pending(self) -> None:
        """清理過期 pending；理由與隔離方式同 cogs/giveaway.py。"""
        self._ticks += 1
        if self._ticks % STALE_SWEEP_EVERY_TICKS:
            return
        try:
            cancelled = await self.bot.polls.cancel_stale_pending()
            if cancelled:
                log.info("已取消 %s 筆過期 pending 投票", cancelled)
        except Exception:
            log.exception("清理過期 pending 投票失敗")

    @finish_due.before_loop
    async def before_finish_due(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: HoRoBot) -> None:
    await bot.add_cog(PollCog(bot))
