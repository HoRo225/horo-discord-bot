"""log 頻道與事件開關設定。

模組名雖與標準庫 logging 同名，但全專案一律用絕對 import（Python 3 預設），
且本檔完全不需要用到標準庫 logging，因此不會撞名。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

import discord

from src import strings
from src.database.models import GuildSettings
from src.ui.base import POSTABLE_CHANNEL_TYPES, Panel, button, panel_action, swap_panel
from src.ui.common import is_admin
from src.ui.settings.nav import NAV_LOG_TOGGLES, nav_row
from src.ui.settings.shared import SettingsModal, _defaults, _first
from src.ui.status import Notice, StatusKind

if TYPE_CHECKING:
    from src.bot import HoRoBot


class LogSettingsModal(SettingsModal):
    action = "settings_log"

    def __init__(self, bot: HoRoBot, settings: GuildSettings) -> None:
        super().__init__(
            bot,
            settings,
            title=strings.SETTINGS_LOG,
            custom_id="cs:settings:log:modal",
        )
        self.log_channel = discord.ui.ChannelSelect(
            channel_types=list(POSTABLE_CHANNEL_TYPES),
            required=False,
            default_values=_defaults([settings.log_channel_id] if settings.log_channel_id else []),
        )
        self.add_item(discord.ui.Label(text=strings.LOG_CHANNEL_ID, component=self.log_channel))

    def values(self) -> dict[str, Any]:
        return {"log_channel_id": _first(self.log_channel)}


async def log_toggle_panel(
    bot: HoRoBot, interaction: discord.Interaction, *, notice: str | Notice | None = None
) -> LogTogglePanel:
    settings = await bot.settings_service.get(interaction.guild_id)
    return LogTogglePanel(bot, settings, notice=notice)


class LogTogglePanel(Panel):
    title = f"# 📜 {strings.SETTINGS_LOG_TOGGLES}"
    accent = discord.Colour.from_rgb(180, 150, 255)

    def __init__(self, bot: HoRoBot, settings: GuildSettings, **kwargs: Any) -> None:
        self.settings = settings
        super().__init__(bot, **kwargs)

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        yield discord.ui.ActionRow(
            self._toggle(
                strings.SETTINGS_LOG_MEMBERS, "log_member_events", "cs:settings:log:members"
            ),
            self._toggle(
                strings.SETTINGS_LOG_MESSAGES, "log_message_events", "cs:settings:log:messages"
            ),
        )
        # 導覽取代了原本的返回鈕：回主面板與跳去模型清單現在都是同一次點選。
        yield nav_row(self.bot, NAV_LOG_TOGGLES)

    def _toggle(self, label: str, field: str, custom_id: str) -> discord.ui.Button:
        enabled = bool(getattr(self.settings, field))
        state = strings.TOGGLE_ON if enabled else strings.TOGGLE_OFF

        async def callback(interaction: discord.Interaction) -> None:
            await self._flip(interaction, field)

        return button(
            f"{label}：{state}",
            custom_id,
            callback,
            style=(discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary),
        )

    async def _flip(self, interaction: discord.Interaction, field: str) -> None:
        async with panel_action(
            interaction, lambda notice: log_toggle_panel(self.bot, interaction, notice=notice)
        ):
            if not is_admin(interaction):
                await swap_panel(
                    interaction,
                    await log_toggle_panel(
                        self.bot,
                        interaction,
                        notice=Notice(strings.ADMIN_ONLY, StatusKind.ERROR),
                    ),
                )
                return
            await self.bot.settings_service.update(
                interaction.guild_id,
                interaction.user.id,
                action="settings_log_toggle",
                values={field: not getattr(self.settings, field)},
            )
            # 開關的新狀態已經寫在按鈕文字上，再補一句「設定已儲存」只是噪音。
            await swap_panel(interaction, await log_toggle_panel(self.bot, interaction))
