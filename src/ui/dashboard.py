from __future__ import annotations

from typing import Any

import discord

from src import strings
from src.ui.common import handle_interaction_error, send_ephemeral


class DashboardView(discord.ui.LayoutView):
    """常駐 Components V2 主儀表板。"""

    def __init__(self, bot: Any) -> None:
        super().__init__(timeout=None)
        self.bot = bot

        economy = discord.ui.Button(
            label=strings.DASHBOARD_ECONOMY,
            emoji="💎",
            style=discord.ButtonStyle.primary,
            custom_id="cs:dashboard:economy",
        )
        game = discord.ui.Button(
            label=strings.DASHBOARD_GAME,
            emoji="🃏",
            style=discord.ButtonStyle.primary,
            custom_id="cs:dashboard:game",
        )
        giveaway = discord.ui.Button(
            label=strings.DASHBOARD_GIVEAWAY,
            emoji="🎁",
            style=discord.ButtonStyle.secondary,
            custom_id="cs:dashboard:giveaway",
        )
        poll = discord.ui.Button(
            label=strings.DASHBOARD_POLL,
            emoji="📊",
            style=discord.ButtonStyle.secondary,
            custom_id="cs:dashboard:poll",
        )
        economy.callback = self.open_economy
        game.callback = self.open_game
        giveaway.callback = self.open_giveaway
        poll.callback = self.open_poll
        container = discord.ui.Container(
            discord.ui.TextDisplay(strings.DASHBOARD_TITLE),
            discord.ui.TextDisplay(strings.DASHBOARD_BODY),
            discord.ui.ActionRow(economy, game, giveaway, poll),
            accent_colour=discord.Colour.from_rgb(121, 196, 255),
        )
        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            await send_ephemeral(interaction, strings.GUILD_ONLY)
            return False
        settings = await self.bot.settings_service.get(interaction.guild_id)
        if (
            interaction.message is not None
            and settings.dashboard_message_id != interaction.message.id
        ):
            await send_ephemeral(interaction, strings.DASHBOARD_STALE)
            return False
        return True

    async def open_economy(self, interaction: discord.Interaction) -> None:
        try:
            from src.ui.economy import EconomyPanel

            await send_ephemeral(interaction, view=EconomyPanel(self.bot))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def open_game(self, interaction: discord.Interaction) -> None:
        try:
            from src.ui.blackjack import BlackjackPanel

            await send_ephemeral(interaction, view=BlackjackPanel(self.bot))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def open_giveaway(self, interaction: discord.Interaction) -> None:
        try:
            from src.ui.giveaway import GiveawayPanel

            await send_ephemeral(interaction, view=GiveawayPanel(self.bot))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def open_poll(self, interaction: discord.Interaction) -> None:
        try:
            from src.ui.poll import PollPanel

            await send_ephemeral(interaction, view=PollPanel(self.bot))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)
