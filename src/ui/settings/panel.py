"""settings 總覽頁：唯讀狀態儀表板，彙總四個模組目前的設定完整度。

本頁不再是套件的匯聚點——四顆「編輯」鈕與兩顆捷徑鈕都已移除，要改設定一律靠
底部的 nav 切到對應子頁。因此本模組不 import 其他四個領域頁，只依賴
`shared`（共用骨架與狀態計算）、`nav`（取得 NAV_HOME）與 `strings`。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

import discord

from src import strings
from src.ui.settings.nav import NAV_HOME
from src.ui.settings.shared import SettingsPage, _mention, _model_name
from src.ui.status import Notice, StatusKind, badge, worst

if TYPE_CHECKING:
    from src.bot import HoRoBot


def _role_count(role_ids: Sequence[int]) -> str:
    """把身分組清單摺成數量，不展開 mention（25 個身分組的 mention 太佔字元）。

    poll 這一行只有這一個欄位，空清單顯示「未設定」比顯示「0」更好讀；
    AI 那一行要跟頻道數字對齊成一行兩個數字，兩者皆空時則直接顯示 0
    （見下方 rows() 內 SETTINGS_AI_LINE 的呼叫），因此這個轉換只給 poll 用。
    """
    return str(len(role_ids)) if role_ids else strings.SETTING_NOT_CONFIGURED


async def settings_panel(
    bot: HoRoBot, interaction: discord.Interaction, *, notice: str | Notice | None = None
) -> SettingsPanel:
    settings = await bot.settings_service.get(interaction.guild_id)
    return SettingsPanel(bot, settings, notice=notice)


class SettingsPanel(SettingsPage):
    title = f"# ⚙️ {strings.SETTINGS_TITLE}"
    body = strings.SETTINGS_HOME_BODY
    nav_key = NAV_HOME

    def status(self) -> StatusKind:
        # NAV_HOME 不是任何模組，不在 module_statuses() 的鍵裡，
        # 總覽頁的狀態色只能是「四個模組裡最壞的那個」。
        return worst(self.statuses.values())

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        current = self.settings
        status = self.statuses
        # 每個模組各自一段獨立的 TextDisplay，badge 一律壓在字串最前面
        # （不可包進粗體標題裡），四段才會對齊、也才能各自獨立判讀狀態符號。
        yield discord.ui.TextDisplay(
            badge(
                status["log"],
                strings.SETTINGS_LOG_LINE.format(
                    title=strings.SETTINGS_LOG,
                    channel=_mention(current.log_channel_id),
                    members=strings.TOGGLE_ON if current.log_member_events else strings.TOGGLE_OFF,
                    messages=strings.TOGGLE_ON
                    if current.log_message_events
                    else strings.TOGGLE_OFF,
                ),
            )
        )
        yield discord.ui.TextDisplay(
            badge(
                status["economy"],
                strings.SETTINGS_ECONOMY_LINE.format(
                    title=strings.SETTINGS_ECONOMY,
                    currency=current.currency_name,
                    daily=current.daily_amount,
                    minimum=current.blackjack_min_bet,
                    maximum=current.blackjack_max_bet,
                ),
            )
        )
        yield discord.ui.TextDisplay(
            badge(
                status["poll"],
                strings.SETTINGS_POLL_LINE.format(
                    title=strings.SETTINGS_POLL,
                    roles=_role_count(current.poll_creator_role_ids),
                ),
            )
        )
        yield discord.ui.TextDisplay(
            badge(
                status["ai"],
                strings.SETTINGS_AI_LINE.format(
                    title=strings.SETTINGS_AI,
                    model=_model_name(self.bot, current) or strings.SETTING_NOT_CONFIGURED,
                    channels=len(current.ai_channel_ids),
                    roles=len(current.ai_role_ids),
                ),
            )
        )
