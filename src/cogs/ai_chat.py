from __future__ import annotations

import logging
import re
from contextlib import suppress
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src import strings
from src.database.models import GuildSettings
from src.services.ai import AIUpstreamError
from src.services.common import DomainError

if TYPE_CHECKING:
    from src.bot import HoRoBot

log = logging.getLogger(__name__)


def split_discord_message(content: str, limit: int = 1_900) -> list[str]:
    if len(content) <= limit:
        return [content]
    chunks: list[str] = []
    remaining = content
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    return [chunk for chunk in chunks if chunk]


def ai_access_allowed(settings: GuildSettings, channel_id: int, role_ids: set[int]) -> bool:
    return channel_id in settings.ai_channel_ids and bool(
        role_ids.intersection(settings.ai_role_ids)
    )


class AIChatCog(commands.Cog):
    def __init__(self, bot: HoRoBot) -> None:
        self.bot = bot

    async def _reply(self, message: discord.Message, content: str) -> None:
        await message.reply(
            content,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _is_reply_to_bot(self, message: discord.Message) -> bool:
        if message.reference is None or message.reference.message_id is None:
            return False
        resolved = message.reference.resolved
        if isinstance(resolved, discord.Message):
            referenced = resolved
        else:
            try:
                referenced = await message.channel.fetch_message(message.reference.message_id)
            except discord.HTTPException:
                return False
        return self.bot.user is not None and referenced.author.id == self.bot.user.id

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or self.bot.user is None:
            return
        if self.bot.user not in message.mentions and not await self._is_reply_to_bot(message):
            return

        settings = await self.bot.settings_service.get(message.guild.id)
        member_roles = {role.id for role in getattr(message.author, "roles", [])}
        if not ai_access_allowed(settings, message.channel.id, member_roles):
            await self._reply(message, strings.AI_FORBIDDEN)
            return

        log_context = {"guild_id": message.guild.id, "user_id": message.author.id}
        prompt = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()
        try:
            async with message.channel.typing():
                response = await self.bot.ai_conversation.respond(
                    guild_id=message.guild.id,
                    channel_id=message.channel.id,
                    user_id=message.author.id,
                    prompt=prompt,
                    guild_model=settings.ai_model,
                    guild_quota=settings.ai_daily_guild_quota,
                    user_quota=settings.ai_daily_user_quota,
                )
        except DomainError as exc:
            await self._reply(message, str(exc))
            return
        except AIUpstreamError as exc:
            log.warning("AI 上游請求失敗：%s", exc, extra=log_context)
            await self._reply(message, strings.AI_UPSTREAM_ERROR)
            return
        except Exception:
            log.exception("AI 聊天處理失敗", extra=log_context)
            with suppress(discord.HTTPException):
                await self._reply(message, strings.AI_UPSTREAM_ERROR)
            return

        # 走到這裡代表上游成本已經發生，送出失敗一律不退配額，因此只記錄不補償。
        try:
            for index, chunk in enumerate(split_discord_message(response)):
                if index == 0:
                    await self._reply(message, chunk)
                else:
                    await message.channel.send(
                        chunk, allowed_mentions=discord.AllowedMentions.none()
                    )
        except discord.HTTPException:
            log.warning("AI 回覆送出失敗", extra=log_context)


async def setup(bot: HoRoBot) -> None:
    await bot.add_cog(AIChatCog(bot))
