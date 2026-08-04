"""settings 各領域模組共用的小工具與 Modal 基底類別。

抽成獨立模組是為了讓 logging/economy/poll/ai 都能匯入同一份共用邏輯，
同時維持單向依賴：這些領域模組只往這裡（與 ui.base）匯入，彼此互不相依。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import discord

from src import strings
from src.database.models import GuildSettings
from src.ui.base import panel_action, swap_panel
from src.ui.common import is_admin
from src.ui.status import Notice, StatusKind

if TYPE_CHECKING:
    from src.bot import HoRoBot


def _mention(channel_id: int | None) -> str:
    return f"<#{channel_id}>" if channel_id else strings.SETTING_NOT_CONFIGURED


def _roles(role_ids: Sequence[int]) -> str:
    return "、".join(f"<@&{role_id}>" for role_id in role_ids) or strings.SETTING_NOT_CONFIGURED


def _channels(channel_ids: Sequence[int]) -> str:
    return "、".join(f"<#{cid}>" for cid in channel_ids) or strings.SETTING_NOT_CONFIGURED


def _defaults(ids: Sequence[int]) -> list[discord.Object]:
    """把已儲存的 ID 轉成選擇器的預設值，讓使用者一開啟就看到現況。"""
    return [discord.Object(id=item) for item in ids]


def _first(select: discord.ui.ChannelSelect) -> int | None:
    """取單選頻道選擇器的結果；未選則視為停用（None）。"""
    return select.values[0].id if select.values else None


class SettingsModal(discord.ui.Modal):
    """設定類 Modal 的共同收尾：權限二次檢查、寫入、就地更新面板。"""

    def __init__(
        self, bot: HoRoBot, settings: GuildSettings, *, title: str, custom_id: str
    ) -> None:
        super().__init__(title=title, timeout=300, custom_id=custom_id)
        self.bot = bot
        self.settings = settings

    def values(self) -> dict[str, Any]:
        raise NotImplementedError

    action = "settings"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # 延遲匯入：settings_panel 在 panel.py，panel.py 反過來會 import 本模組
        # 底下的各領域 Modal，模組層互相 import 會在啟動時循環爆炸，故收在 callback 內。
        from src.ui.settings.panel import settings_panel

        async def rebuild(notice: str | Notice) -> discord.ui.LayoutView:
            return await settings_panel(self.bot, interaction, notice=notice)

        # 欄位格式錯誤丟出的 ValueError 由 panel_action 統一翻成 INVALID_INPUT，
        # 因此這裡不再自己接一次。
        async with panel_action(interaction, rebuild):
            # Modal 的 interaction 不會經過開啟它的面板檢查，這道防線必須留著。
            if not is_admin(interaction):
                await swap_panel(
                    interaction, await rebuild(Notice(strings.ADMIN_ONLY, StatusKind.ERROR))
                )
                return
            await self.bot.settings_service.update(
                interaction.guild_id,
                interaction.user.id,
                action=self.action,
                values=self.values(),
            )
            await swap_panel(interaction, await rebuild(Notice(strings.SUCCESS)))
