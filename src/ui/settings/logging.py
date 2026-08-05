"""log 頻道與事件開關設定。

模組名雖與標準庫 logging 同名，但全專案一律用絕對 import（Python 3 預設），
且本檔完全不需要用到標準庫 logging，因此不會撞名。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

import discord

from src import strings
from src.ui.base import POSTABLE_CHANNEL_TYPES, button
from src.ui.settings.nav import NAV_LOG
from src.ui.settings.shared import SettingsPage, _defaults, _first, _mention, apply_setting
from src.ui.status import Notice, badge

if TYPE_CHECKING:
    from src.bot import HoRoBot


async def log_page(
    bot: HoRoBot, interaction: discord.Interaction, *, notice: str | Notice | None = None
) -> LogPage:
    settings = await bot.settings_service.get(interaction.guild_id)
    return LogPage(bot, settings, notice=notice)


class LogPage(SettingsPage):
    title = f"# 📜 {strings.SETTINGS_LOG}"
    body = strings.SETTINGS_LOG_BODY
    nav_key = NAV_LOG

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        current = self.settings
        # 現況一段獨立的 TextDisplay：badge 直接反映 shared.module_statuses() 對
        # log 的判定（有頻道即 OK），文字則用既有的 LOG_CHANNEL + _mention 組出，
        # 未設定時 _mention 自己會退回「未設定」。
        yield discord.ui.TextDisplay(
            badge(
                self.statuses["log"],
                f"{strings.LOG_CHANNEL}：{_mention(current.log_channel_id)}",
            )
        )
        yield discord.ui.ActionRow(self._channel_select())
        # 分隔線標記性質切換：上半是選頻道，下半是開關事件，避免糊成同一區。
        yield discord.ui.Separator()
        yield discord.ui.ActionRow(
            self._toggle(
                strings.SETTINGS_LOG_MEMBERS, "log_member_events", "cs:settings:log:members"
            ),
            self._toggle(
                strings.SETTINGS_LOG_MESSAGES, "log_message_events", "cs:settings:log:messages"
            ),
        )

    def _channel_select(self) -> discord.ui.ChannelSelect:
        current = self.settings
        select = discord.ui.ChannelSelect(
            custom_id="cs:settings:log:channel",
            channel_types=list(POSTABLE_CHANNEL_TYPES),
            # min_values=0 不可省：日誌頻道要能「清空即停用」，選單預設的
            # min_values=1 會讓使用者永遠無法把已選的頻道拿掉。
            min_values=0,
            max_values=1,
            placeholder=strings.LOG_CHANNEL_PLACEHOLDER,
            default_values=_defaults([current.log_channel_id] if current.log_channel_id else []),
        )

        async def callback(interaction: discord.Interaction) -> None:
            # 選完就存，選單重畫後 default_values 就是答案，不必再補通知。
            await apply_setting(
                self.bot,
                interaction,
                origin=NAV_LOG,
                action="settings_log_channel",
                values={"log_channel_id": _first(select)},
            )

        select.callback = callback
        return select

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
        # 新狀態已經寫在按鈕文字上，再補一句「設定已儲存」只是噪音，因此不傳 notice。
        await apply_setting(
            self.bot,
            interaction,
            origin=NAV_LOG,
            action="settings_log_toggle",
            values={field: not getattr(self.settings, field)},
        )
