"""settings 主面板：彙總各領域摘要與設定完整度，導向對應 Modal 或子面板。

本模組是整個 settings 套件唯一的匯聚點，import 方向只能是
`panel → {logging, economy, poll, ai} → shared → ui.base`；
反過來（各領域模組需要重建主面板）一律在 callback 內延遲 import，
避免模組層互相 import 在啟動時循環爆炸。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

import discord

from src import strings
from src.database.models import GuildSettings
from src.ui.base import (
    Panel,
    PanelFactory,
    button,
    defer_update,
    panel_action,
    section,
    swap_panel,
)
from src.ui.common import is_admin
from src.ui.settings.ai import AISettingsModal, model_panel
from src.ui.settings.economy import EconomySettingsModal
from src.ui.settings.logging import LogSettingsModal, log_toggle_panel
from src.ui.settings.nav import NAV_HOME, nav_row
from src.ui.settings.poll import PollSettingsModal
from src.ui.settings.shared import _channels, _mention, _roles
from src.ui.status import ACCENTS, Notice, StatusKind, badge, worst

if TYPE_CHECKING:
    from src.bot import HoRoBot


def _model_name(bot: HoRoBot, settings: GuildSettings) -> str:
    """伺服器沒指定就退回全域預設，順序與 cogs.ai_chat 實際送出請求時一致。"""
    return settings.ai_model or bot.settings.ai_default_model or ""


def module_statuses(bot: HoRoBot, settings: GuildSettings) -> dict[str, StatusKind]:
    """把各模組的設定完整度摺疊成單一狀態，讓主面板一眼看得出誰還沒設好。

    只有 AI 有中間態：它實際要「頻道 ∩ 身分組」都命中才會回應
    （見 cogs.ai_chat.ai_access_allowed），模型則允許退回全域預設。
    因此完全沒碰過視為未啟用（OFF，安靜）；碰了卻缺一角是「設了也不會動」，
    必須跳 WARN，否則管理員會以為 AI 已經開好了。

    log 與 poll 沒有中間態：欄位空著就是關閉（poll 空白代表僅管理員可建立），
    economy 四個欄位都有資料庫預設值，開箱即可用，因此恆為 OK。
    """
    scoped = bool(settings.ai_channel_ids or settings.ai_role_ids)
    complete = bool(settings.ai_channel_ids and settings.ai_role_ids and _model_name(bot, settings))
    return {
        "log": StatusKind.OK if settings.log_channel_id else StatusKind.OFF,
        "economy": StatusKind.OK,
        "poll": StatusKind.OK if settings.poll_creator_role_ids else StatusKind.OFF,
        "ai": (StatusKind.OK if complete else StatusKind.WARN) if scoped else StatusKind.OFF,
    }


async def settings_panel(
    bot: HoRoBot, interaction: discord.Interaction, *, notice: str | Notice | None = None
) -> SettingsPanel:
    settings = await bot.settings_service.get(interaction.guild_id)
    return SettingsPanel(bot, settings, notice=notice)


class SettingsPanel(Panel):
    title = f"# ⚙️ {strings.SETTINGS_TITLE}"
    accent = discord.Colour.from_rgb(180, 150, 255)

    def __init__(self, bot: HoRoBot, settings: GuildSettings, **kwargs: Any) -> None:
        self.settings = settings
        self.statuses = module_statuses(bot, settings)
        # accent 得在 super().__init__ 之前定案（Container 是建構當下取色，事後改沒用）。
        # 只在沒有通知時上狀態色：通知講的是「剛剛那個動作」，比靜態的模組狀態更該被看見，
        # 其顏色由 base.Panel 依 Notice 決定。
        if kwargs.get("notice") is None:
            self.accent = ACCENTS[worst(self.statuses.values())]
        super().__init__(bot, **kwargs)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not is_admin(interaction):
            await defer_update(interaction)
            await swap_panel(
                interaction,
                SettingsPanel(
                    self.bot, self.settings, notice=Notice(strings.ADMIN_ONLY, StatusKind.ERROR)
                ),
            )
            return False
        return True

    def _home(self, interaction: discord.Interaction) -> PanelFactory:
        """失敗時回主面板重畫用的工廠。"""
        return lambda notice: settings_panel(self.bot, interaction, notice=notice)

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        current = self.settings
        status = self.statuses
        # 徽章壓在整段摘要最前面（而不是包在粗體標題裡），四個區塊的符號才會對齊在同一欄，
        # 由上往下掃一眼就知道還有哪個模組沒設。
        yield section(
            badge(
                status["log"],
                strings.SETTINGS_LOG_SUMMARY.format(
                    title=strings.SETTINGS_LOG,
                    log=_mention(current.log_channel_id),
                ),
            ),
            button(strings.SETTINGS_EDIT, "cs:settings:log", self.log),
        )
        yield discord.ui.Separator()
        yield section(
            badge(
                status["economy"],
                strings.SETTINGS_ECONOMY_SUMMARY.format(
                    title=strings.SETTINGS_ECONOMY,
                    currency=current.currency_name,
                    daily=current.daily_amount,
                    minimum=current.blackjack_min_bet,
                    maximum=current.blackjack_max_bet,
                ),
            ),
            button(strings.SETTINGS_EDIT, "cs:settings:economy", self.economy),
        )
        yield discord.ui.Separator()
        yield section(
            badge(
                status["poll"],
                strings.SETTINGS_POLL_SUMMARY.format(
                    title=strings.SETTINGS_POLL, roles=_roles(current.poll_creator_role_ids)
                ),
            ),
            button(strings.SETTINGS_EDIT, "cs:settings:poll", self.poll),
        )
        yield discord.ui.Separator()
        yield section(
            badge(
                status["ai"],
                strings.SETTINGS_AI_SUMMARY.format(
                    title=strings.SETTINGS_AI,
                    model=_model_name(self.bot, current) or strings.SETTING_NOT_CONFIGURED,
                    channels=_channels(current.ai_channel_ids),
                    roles=_roles(current.ai_role_ids),
                ),
            ),
            button(strings.SETTINGS_EDIT, "cs:settings:ai", self.ai),
        )
        yield discord.ui.Separator()
        # 這兩顆按鈕與底下的導覽選單去處相同，但保留為一次點擊的捷徑：
        # 主面板是進入子頁最常見的起點，讓最常走的動線少一次展開清單。
        yield discord.ui.ActionRow(
            button(
                strings.SETTINGS_LOG_TOGGLES,
                "cs:settings:log_toggles",
                self.log_toggles,
                emoji="📜",
            ),
            button(
                strings.SETTINGS_MODEL,
                "cs:settings:model",
                self.models,
                style=discord.ButtonStyle.primary,
                emoji="🤖",
            ),
        )
        yield nav_row(self.bot, NAV_HOME)

    # 以下四顆「編輯」鈕都要開 Modal，send_modal 必須是該次互動的首個回應，
    # 因此刻意不套 panel_action（它一進來就 defer）；錯誤處理留給 Modal 的 on_submit。
    async def log(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(LogSettingsModal(self.bot, self.settings))

    async def economy(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(EconomySettingsModal(self.bot, self.settings))

    async def poll(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(PollSettingsModal(self.bot, self.settings))

    async def ai(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(AISettingsModal(self.bot, self.settings))

    async def log_toggles(self, interaction: discord.Interaction) -> None:
        async with panel_action(interaction, self._home(interaction)):
            await swap_panel(interaction, await log_toggle_panel(self.bot, interaction))

    async def models(self, interaction: discord.Interaction) -> None:
        async with panel_action(interaction, self._home(interaction)):
            await swap_panel(interaction, await model_panel(self.bot, interaction))
