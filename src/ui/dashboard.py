from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from src import strings
from src.ui.base import button, open_panel, section
from src.ui.blackjack import BlackjackPanel
from src.ui.common import handle_interaction_error, send_ephemeral
from src.ui.economy import economy_panel
from src.ui.giveaway import GiveawayPanel
from src.ui.poll import poll_panel

if TYPE_CHECKING:
    from src.bot import HoRoBot


class DashboardView(discord.ui.LayoutView):
    """常駐 Components V2 主儀表板。"""

    def __init__(self, bot: HoRoBot, guild: discord.Guild | None = None) -> None:
        super().__init__(timeout=None)
        self.bot = bot

        economy = button(
            strings.DASHBOARD_ECONOMY,
            "cs:dashboard:economy",
            self.open_economy,
            style=discord.ButtonStyle.primary,
            emoji="💎",
        )
        game = button(
            strings.DASHBOARD_GAME,
            "cs:dashboard:game",
            self.open_game,
            style=discord.ButtonStyle.primary,
            emoji="🃏",
        )
        giveaway = button(
            strings.DASHBOARD_GIVEAWAY,
            "cs:dashboard:giveaway",
            self.open_giveaway,
            emoji="🎁",
        )
        poll = button(
            strings.DASHBOARD_POLL,
            "cs:dashboard:poll",
            self.open_poll,
            emoji="📊",
        )

        items: list[discord.ui.Item[Any]] = [discord.ui.TextDisplay(strings.DASHBOARD_TITLE)]
        if guild is not None and guild.icon is not None:
            items.append(section(strings.DASHBOARD_BODY, discord.ui.Thumbnail(guild.icon.url)))
        else:
            items.append(discord.ui.TextDisplay(strings.DASHBOARD_BODY))
        items.append(discord.ui.Separator())
        items.append(discord.ui.ActionRow(economy))
        items.append(discord.ui.Separator())
        items.append(discord.ui.ActionRow(game))
        items.append(discord.ui.Separator())
        items.append(discord.ui.ActionRow(giveaway))
        items.append(discord.ui.Separator())
        items.append(discord.ui.ActionRow(poll))

        self.add_item(
            discord.ui.Container(*items, accent_colour=discord.Colour.from_rgb(121, 196, 255))
        )

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
            await open_panel(interaction, await economy_panel(self.bot, interaction))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def open_game(self, interaction: discord.Interaction) -> None:
        try:
            await open_panel(interaction, BlackjackPanel(self.bot))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def open_giveaway(self, interaction: discord.Interaction) -> None:
        try:
            await open_panel(interaction, GiveawayPanel(self.bot))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def open_poll(self, interaction: discord.Interaction) -> None:
        try:
            await open_panel(interaction, await poll_panel(self.bot, interaction))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)
