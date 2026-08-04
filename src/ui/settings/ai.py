"""AI 觸發條件（頻道／身分組／模型／配額）與模型選擇面板。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

import discord

from src import strings
from src.database.models import GuildSettings
from src.ui.base import POSTABLE_CHANNEL_TYPES, PagedPanel, panel_action, swap_panel
from src.ui.common import is_admin
from src.ui.settings.nav import NAV_MODEL, nav_row
from src.ui.settings.shared import SettingsModal, _defaults
from src.ui.status import Notice, StatusKind

if TYPE_CHECKING:
    from src.bot import HoRoBot


class AISettingsModal(SettingsModal):
    action = "settings_ai"

    def __init__(self, bot: HoRoBot, settings: GuildSettings) -> None:
        super().__init__(bot, settings, title=strings.SETTINGS_AI, custom_id="cs:settings:ai:modal")
        self.channels = discord.ui.ChannelSelect(
            channel_types=list(POSTABLE_CHANNEL_TYPES),
            min_values=0,
            max_values=25,
            required=False,
            default_values=_defaults(settings.ai_channel_ids),
        )
        self.roles = discord.ui.RoleSelect(
            min_values=0,
            max_values=25,
            required=False,
            default_values=_defaults(settings.ai_role_ids),
        )
        self.model = discord.ui.TextInput(
            default=settings.ai_model or "", required=False, max_length=200
        )
        self.guild_quota = discord.ui.TextInput(
            default=str(settings.ai_daily_guild_quota), max_length=9
        )
        self.user_quota = discord.ui.TextInput(
            default=str(settings.ai_daily_user_quota), max_length=9
        )
        for text, component in (
            (strings.AI_CHANNEL_IDS, self.channels),
            (strings.AI_ROLE_IDS, self.roles),
            (strings.AI_MODEL, self.model),
            (strings.AI_GUILD_QUOTA, self.guild_quota),
            (strings.AI_USER_QUOTA, self.user_quota),
        ):
            self.add_item(discord.ui.Label(text=text, component=component))

    def values(self) -> dict[str, Any]:
        return {
            "ai_channel_ids": [channel.id for channel in self.channels.values],
            "ai_role_ids": [role.id for role in self.roles.values],
            "ai_model": str(self.model).strip() or None,
            "ai_daily_guild_quota": int(str(self.guild_quota)),
            "ai_daily_user_quota": int(str(self.user_quota)),
        }


async def model_panel(
    bot: HoRoBot, interaction: discord.Interaction, *, notice: str | Notice | None = None
) -> ModelPanel:
    models = await bot.ai_provider.list_models()
    return ModelPanel(bot, models, notice=notice)


class ModelPanel(PagedPanel):
    title = f"# 🤖 {strings.SETTINGS_MODEL}"
    accent = discord.Colour.from_rgb(180, 150, 255)
    page_size = 25

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        yield from super().rows()
        # 導覽固定壓在分頁列之後，「換頁」與「換頁面」才不會混在同一層。
        yield nav_row(self.bot, NAV_MODEL)

    def page_rows(self, items: list[Any]) -> Iterable[discord.ui.Item[Any]]:
        # 存成實例屬性，_choose 才能像 shared._first() 一樣讀元件本身的 values，
        # 而不必伸手去掏 interaction.data 這種原始 payload。
        self.model_select = discord.ui.Select(
            placeholder=strings.SETTINGS_MODEL,
            options=[discord.SelectOption(label=model[:100], value=model[:100]) for model in items],
        )
        self.model_select.callback = self._choose
        yield discord.ui.ActionRow(self.model_select)

    async def _choose(self, interaction: discord.Interaction) -> None:
        # 延遲匯入：settings_panel 在 panel.py，panel.py 反過來會 import 本模組，
        # 模組層互相 import 會在啟動時循環爆炸，故收在 callback 內。
        from src.ui.settings.panel import settings_panel

        async with panel_action(
            interaction, lambda notice: settings_panel(self.bot, interaction, notice=notice)
        ):
            if not is_admin(interaction):
                await swap_panel(
                    interaction,
                    await settings_panel(
                        self.bot,
                        interaction,
                        notice=Notice(strings.ADMIN_ONLY, StatusKind.ERROR),
                    ),
                )
                return
            model = self.model_select.values[0]
            await self.bot.settings_service.update(
                interaction.guild_id,
                interaction.user.id,
                action="settings_ai_model",
                values={"ai_model": model},
            )
            await swap_panel(
                interaction,
                await settings_panel(
                    self.bot,
                    interaction,
                    notice=Notice(strings.AI_MODEL_SAVED.format(model=model)),
                ),
            )
