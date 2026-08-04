"""投票發起人身分組設定。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from src import strings
from src.database.models import GuildSettings
from src.ui.settings.shared import SettingsModal, _defaults

if TYPE_CHECKING:
    from src.bot import HoRoBot


class PollSettingsModal(SettingsModal):
    action = "settings_poll_roles"

    def __init__(self, bot: HoRoBot, settings: GuildSettings) -> None:
        super().__init__(
            bot, settings, title=strings.SETTINGS_POLL, custom_id="cs:settings:poll:modal"
        )
        self.roles = discord.ui.RoleSelect(
            min_values=0,
            max_values=25,
            required=False,
            default_values=_defaults(settings.poll_creator_role_ids),
        )
        self.add_item(discord.ui.Label(text=strings.POLL_ROLE_IDS, component=self.roles))

    def values(self) -> dict[str, Any]:
        return {"poll_creator_role_ids": [role.id for role in self.roles.values]}
