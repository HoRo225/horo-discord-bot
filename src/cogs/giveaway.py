from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from src import strings
from src.ui.giveaway import giveaway_embed

log = logging.getLogger(__name__)


class GiveawayCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.finish_due.start()

    async def cog_unload(self) -> None:
        self.finish_due.cancel()

    @tasks.loop(seconds=30)
    async def finish_due(self) -> None:
        for pending in await self.bot.giveaways.due():
            try:
                giveaway = await self.bot.giveaways.finalize(pending.id)
                channel = self.bot.get_channel(giveaway.channel_id)
                if channel is None:
                    try:
                        channel = await self.bot.fetch_channel(giveaway.channel_id)
                    except discord.HTTPException:
                        channel = None
                if not isinstance(channel, discord.abc.Messageable):
                    continue
                if giveaway.message_id:
                    try:
                        message = await channel.fetch_message(giveaway.message_id)
                        await message.edit(embed=giveaway_embed(giveaway), view=None)
                    except discord.HTTPException:
                        pass
                if giveaway.winners:
                    winners = "、".join(f"<@{user_id}>" for user_id in giveaway.winners)
                    content = strings.GIVEAWAY_ENDED.format(prize=giveaway.prize, winners=winners)
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

    @finish_due.before_loop
    async def before_finish_due(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot) -> None:
    await bot.add_cog(GiveawayCog(bot))
