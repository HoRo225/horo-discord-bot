from __future__ import annotations

import logging
import re
from contextlib import suppress

import discord
from discord.ext import commands

from src import strings
from src.services.ai import AIUpstreamError, ChatMessage, QuotaExceededError, redact_sensitive

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


def ai_access_allowed(settings, channel_id: int, role_ids: set[int]) -> bool:
    return channel_id in settings.ai_channel_ids and bool(
        role_ids.intersection(settings.ai_role_ids)
    )


def truncate_ai_response(content: str, max_characters: int) -> str:
    if len(content) <= max_characters:
        return content
    return content[:max_characters] + strings.AI_RESPONSE_TRUNCATED


class AIChatCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

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
        mentioned = self.bot.user in message.mentions
        if not mentioned and not await self._is_reply_to_bot(message):
            return

        settings = await self.bot.settings_service.get(message.guild.id)
        member_roles = {role.id for role in getattr(message.author, "roles", [])}
        if not ai_access_allowed(settings, message.channel.id, member_roles):
            await message.reply(
                strings.AI_FORBIDDEN,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        model = settings.ai_model or self.bot.settings.ai_default_model
        if not model:
            await message.reply(
                strings.AI_DISABLED,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        if not self.bot.ai_rate_limiter.allow(message.guild.id, message.author.id):
            await message.reply(
                strings.AI_RATE_LIMIT,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        reserved = False
        upstream_succeeded = False
        response_sent = False
        try:
            await self.bot.ai_usage.reserve(
                guild_id=message.guild.id,
                user_id=message.author.id,
                guild_quota=settings.ai_daily_guild_quota,
                user_quota=settings.ai_daily_user_quota,
            )
            reserved = True
            mention_pattern = re.compile(rf"<@!?{self.bot.user.id}>")
            prompt = mention_pattern.sub("", message.content).strip()
            prompt = redact_sensitive(
                prompt or strings.AI_EMPTY_PROMPT,
                known_secrets=(self.bot.settings.ai_api_key,),
            )
            history = self.bot.ai_memory.get(message.guild.id, message.channel.id)
            request_messages = [
                ChatMessage("system", strings.AI_SYSTEM_PROMPT),
                *history,
                ChatMessage("user", prompt),
            ]
            async with message.channel.typing():
                response = await self.bot.ai_provider.chat(model=model, messages=request_messages)
            upstream_succeeded = True
            response = redact_sensitive(response, known_secrets=(self.bot.settings.ai_api_key,))
            response = truncate_ai_response(response, self.bot.settings.ai_max_response_chars)
            self.bot.ai_memory.add(
                message.guild.id, message.channel.id, ChatMessage("user", prompt)
            )
            self.bot.ai_memory.add(
                message.guild.id,
                message.channel.id,
                ChatMessage("assistant", response),
            )
            chunks = split_discord_message(response)
            for index, chunk in enumerate(chunks):
                if index == 0:
                    await message.reply(
                        chunk,
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    response_sent = True
                else:
                    await message.channel.send(
                        chunk, allowed_mentions=discord.AllowedMentions.none()
                    )
            try:
                await self.bot.ai_usage.record_characters(
                    guild_id=message.guild.id,
                    user_id=message.author.id,
                    character_count=len(response),
                )
            except Exception:
                log.exception("記錄 AI 回應字數失敗", extra={"guild_id": message.guild.id})
        except QuotaExceededError:
            await message.reply(
                strings.AI_QUOTA,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except AIUpstreamError as exc:
            if reserved and not upstream_succeeded:
                await self.bot.ai_usage.release(
                    guild_id=message.guild.id, user_id=message.author.id
                )
            log.warning(
                "AI 上游請求失敗：%s",
                exc,
                extra={"guild_id": message.guild.id, "user_id": message.author.id},
            )
            await message.reply(
                strings.AI_UPSTREAM_ERROR,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception:
            if reserved and not upstream_succeeded:
                try:
                    await self.bot.ai_usage.release(
                        guild_id=message.guild.id, user_id=message.author.id
                    )
                except Exception:
                    log.exception("回退 AI 配額失敗", extra={"guild_id": message.guild.id})
            log.exception(
                "AI 聊天處理失敗",
                extra={"guild_id": message.guild.id, "user_id": message.author.id},
            )
            if not response_sent:
                with suppress(discord.HTTPException):
                    await message.reply(
                        strings.AI_UPSTREAM_ERROR,
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )


async def setup(bot) -> None:
    await bot.add_cog(AIChatCog(bot))
