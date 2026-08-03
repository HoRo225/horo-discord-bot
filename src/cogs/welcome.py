from __future__ import annotations

import logging

import discord
from discord.ext import commands

log = logging.getLogger(__name__)


class WelcomeCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    async def _send(self, member: discord.Member, *, joined: bool) -> None:
        settings = await self.bot.settings_service.get(member.guild.id)
        channel_id = settings.welcome_channel_id if joined else settings.goodbye_channel_id
        if channel_id is None:
            return
        channel = member.guild.get_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return
        template = settings.welcome_template if joined else settings.goodbye_template
        content = self.bot.settings_service.render_template(
            template,
            user=member.mention,
            server=member.guild.name,
            count=member.guild.member_count or len(member.guild.members),
        )
        await channel.send(
            content,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        try:
            await self._send(member, joined=True)
        except Exception:
            log.exception("發送歡迎訊息失敗", extra={"guild_id": member.guild.id})

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        try:
            await self._send(member, joined=False)
        except Exception:
            log.exception("發送送別訊息失敗", extra={"guild_id": member.guild.id})


async def setup(bot) -> None:
    await bot.add_cog(WelcomeCog(bot))
