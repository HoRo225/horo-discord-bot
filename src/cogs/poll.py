from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from src import strings
from src.services.poll import PollAnswerSnapshot

log = logging.getLogger(__name__)


class PollCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

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
        for pending in await self.bot.polls.due():
            try:
                channel = self.bot.get_channel(pending.channel_id)
                if channel is None:
                    try:
                        channel = await self.bot.fetch_channel(pending.channel_id)
                    except discord.HTTPException:
                        channel = None
                native: discord.Poll | None = None
                if isinstance(channel, discord.abc.Messageable) and pending.message_id:
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
                if isinstance(channel, discord.abc.Messageable):
                    await channel.send(
                        strings.POLL_ENDED.format(question=completed.question),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
            except Exception:
                log.exception(
                    "投票到期處理失敗",
                    extra={"guild_id": pending.guild_id, "poll_id": pending.id},
                )

    @finish_due.before_loop
    async def before_finish_due(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot) -> None:
    await bot.add_cog(PollCog(bot))
