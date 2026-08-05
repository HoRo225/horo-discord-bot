"""投票發起人身分組設定頁。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

import discord

from src import strings
from src.ui.settings.nav import NAV_POLL
from src.ui.settings.shared import SettingsPage, _defaults, _roles, apply_setting
from src.ui.status import Notice, badge

if TYPE_CHECKING:
    from src.bot import HoRoBot


async def poll_page(
    bot: HoRoBot, interaction: discord.Interaction, *, notice: str | Notice | None = None
) -> PollPage:
    settings = await bot.settings_service.get(interaction.guild_id)
    return PollPage(bot, settings, notice=notice)


class PollPage(SettingsPage):
    title = f"## 📊 {strings.SETTINGS_POLL}"
    body = strings.SETTINGS_POLL_BODY
    nav_key = NAV_POLL

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        current = self.settings
        yield discord.ui.TextDisplay(
            badge(self.status(), f"{strings.POLL_ROLES}：{_roles(current.poll_creator_role_ids)}")
        )
        select = discord.ui.RoleSelect(
            custom_id="cs:settings:poll:roles",
            placeholder=strings.POLL_ROLES_PLACEHOLDER,
            # min_values=0 不可省，否則永遠無法清空——清空正是「僅管理伺服器權限者可建投票」的意思。
            min_values=0,
            max_values=25,
            default_values=_defaults(current.poll_creator_role_ids),
        )

        async def choose(interaction: discord.Interaction) -> None:
            # 不傳 notice：選擇器重畫後 default_values 就是答案，再補一句「已儲存」是噪音。
            await apply_setting(
                self.bot,
                interaction,
                origin=NAV_POLL,
                action="settings_poll_roles",
                values={"poll_creator_role_ids": [role.id for role in select.values]},
            )

        select.callback = choose
        yield discord.ui.ActionRow(select)
