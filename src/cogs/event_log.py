from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src import strings

if TYPE_CHECKING:
    from src.bot import HoRoBot

log = logging.getLogger(__name__)


class EventLogCog(commands.Cog):
    def __init__(self, bot: HoRoBot) -> None:
        self.bot = bot

    async def _log(self, guild: discord.Guild, content: str) -> None:
        settings = await self.bot.settings_service.get(guild.id)
        if settings.log_channel_id is None:
            return
        channel = guild.get_channel(settings.log_channel_id)
        if isinstance(channel, discord.abc.Messageable):
            await channel.send(content[:2_000], allowed_mentions=discord.AllowedMentions.none())

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        try:
            settings = await self.bot.settings_service.get(member.guild.id)
            if settings.log_member_events:
                await self._log(
                    member.guild,
                    strings.EVENT_MEMBER_JOINED.format(member=str(member)),
                )
        except Exception:
            log.exception("記錄成員加入失敗", extra={"guild_id": member.guild.id})

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        try:
            settings = await self.bot.settings_service.get(member.guild.id)
            if settings.log_member_events:
                await self._log(
                    member.guild,
                    strings.EVENT_MEMBER_LEFT.format(member=str(member)),
                )
        except Exception:
            log.exception("記錄成員離開失敗", extra={"guild_id": member.guild.id})

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        try:
            settings = await self.bot.settings_service.get(message.guild.id)
            if settings.log_message_events:
                content = message.content or strings.EVENT_CONTENT_UNCACHED
                await self._log(
                    message.guild,
                    strings.EVENT_MESSAGE_DELETED.format(
                        author=str(message.author), channel=message.channel.mention, content=content
                    ),
                )
        except Exception:
            log.exception("記錄訊息刪除失敗", extra={"guild_id": message.guild.id})

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.guild is None or before.author.bot or before.content == after.content:
            return
        try:
            settings = await self.bot.settings_service.get(before.guild.id)
            if settings.log_message_events:
                await self._log(
                    before.guild,
                    strings.EVENT_MESSAGE_EDITED.format(
                        author=str(before.author),
                        channel=before.channel.mention,
                        before=before.content or strings.EVENT_NO_TEXT,
                        after=after.content or strings.EVENT_NO_TEXT,
                    ),
                )
        except Exception:
            log.exception("記錄訊息編輯失敗", extra={"guild_id": before.guild.id})


async def setup(bot: HoRoBot) -> None:
    await bot.add_cog(EventLogCog(bot))
