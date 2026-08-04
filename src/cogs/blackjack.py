from __future__ import annotations

import logging
from datetime import UTC, datetime

import discord
from discord.ext import commands, tasks

from src import strings
from src.services.common import aware_utc
from src.ui.blackjack import BlackjackGameView

log = logging.getLogger(__name__)


class BlackjackCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.recover_and_timeout.start()

    async def cog_unload(self) -> None:
        self.recover_and_timeout.cancel()

    async def _channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return None
        return channel if isinstance(channel, discord.abc.Messageable) else None

    @tasks.loop(seconds=30)
    async def recover_and_timeout(self) -> None:
        now = datetime.now(UTC)
        for game in await self.bot.blackjack.recoverable():
            try:
                channel = await self._channel(game.channel_id)
                message: discord.Message | None = None
                if channel is not None and game.message_id is not None:
                    try:
                        message = await channel.fetch_message(game.message_id)
                    except discord.HTTPException:
                        message = None
                if message is None:
                    refunded = await self.bot.blackjack.refund_missing_message(game.id)
                    if refunded and channel is not None:
                        await channel.send(
                            f"<@{game.user_id}> "
                            + strings.BLACKJACK_REFUNDED.format(amount=refunded),
                            allowed_mentions=discord.AllowedMentions(users=True),
                        )
                    continue
                # 牌面與按鈕都在 view 裡，逾時結算時也不能傳 view=None，
                # 否則整張牌桌會消失；BlackjackGameView 自己會在終局收起操作按鈕。
                if aware_utc(game.expires_at) <= now:
                    result = await self.bot.blackjack.timeout(game.id)
                    target = result.game
                else:
                    target = game
                await message.edit(
                    content=None,
                    embeds=[],
                    attachments=[],
                    view=BlackjackGameView(self.bot, target),
                )
            except Exception:
                log.exception(
                    "21 點牌局恢復或逾時處理失敗",
                    extra={"guild_id": game.guild_id, "game_id": game.id},
                )

    @recover_and_timeout.before_loop
    async def before_recover(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot) -> None:
    await bot.add_cog(BlackjackCog(bot))
