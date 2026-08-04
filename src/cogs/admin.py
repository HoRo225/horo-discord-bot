from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from src import strings
from src.ui.base import open_panel
from src.ui.common import defer_ephemeral, handle_interaction_error, is_admin, send_ephemeral
from src.ui.dashboard import DashboardView
from src.ui.settings import settings_panel


class AdminCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @app_commands.command(name="setup", description=strings.CMD_SETUP_DESC)
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction):
            await send_ephemeral(interaction, strings.ADMIN_ONLY)
            return
        try:
            await defer_ephemeral(interaction)
            if interaction.channel is None:
                raise RuntimeError(strings.CURRENT_CHANNEL_NOT_FOUND)
            settings = await self.bot.settings_service.get(interaction.guild_id)
            message: discord.Message | None = None
            if (
                settings.dashboard_channel_id == interaction.channel_id
                and settings.dashboard_message_id
            ):
                try:
                    message = await interaction.channel.fetch_message(settings.dashboard_message_id)
                    await message.edit(
                        content=None,
                        embeds=[],
                        attachments=[],
                        view=DashboardView(self.bot, interaction.guild),
                    )
                except discord.NotFound:
                    message = None
            if message is None:
                message = await interaction.channel.send(
                    view=DashboardView(self.bot, interaction.guild)
                )
            await self.bot.settings_service.update(
                interaction.guild_id,
                interaction.user.id,
                action="dashboard_setup",
                values={
                    "dashboard_channel_id": message.channel.id,
                    "dashboard_message_id": message.id,
                },
            )
            await send_ephemeral(interaction, strings.DASHBOARD_UPDATED)
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    @app_commands.command(name="settings", description=strings.CMD_SETTINGS_DESC)
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def settings(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction):
            await send_ephemeral(interaction, strings.ADMIN_ONLY)
            return
        try:
            await open_panel(interaction, await settings_panel(self.bot, interaction))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    @app_commands.command(name="help", description=strings.CMD_HELP_DESC)
    async def help(self, interaction: discord.Interaction) -> None:
        view = discord.ui.LayoutView(timeout=300)
        view.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(strings.HELP_TEXT),
                accent_colour=discord.Colour.from_rgb(121, 196, 255),
            )
        )
        await send_ephemeral(interaction, view=view)

    @app_commands.command(name="ping", description=strings.CMD_PING_DESC)
    async def ping(self, interaction: discord.Interaction) -> None:
        await send_ephemeral(
            interaction,
            strings.PING.format(latency_ms=round(self.bot.latency * 1_000)),
        )


async def setup(bot) -> None:
    await bot.add_cog(AdminCog(bot))
