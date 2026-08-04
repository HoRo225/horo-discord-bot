"""settings 各頁共用的導覽選單。

子面板原本只有一顆「返回」鈕，從日誌開關跳到模型清單得先退回主面板再點進去；
把同一個 StringSelect 掛在每一頁底部之後，任兩頁之間都只要一次點選，
使用者也不必再靠記憶推測自己在第幾層。

領域設定（日誌頻道、經濟、投票權限、AI 觸發條件）刻意留在主面板的「編輯」鈕，
不併進這個選單：select 的 callback 雖然也開得起 Modal，但 Modal 關閉後選單會停在
剛才選中的值，使用者得再選一次別的選項才回得去，比按鈕更難用。

本模組只往下依賴 ui.base、ui.status 與 strings；面板工廠表（PANELS）在 callback 內
延遲匯入，維持 settings 套件既有的單向依賴。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from src import strings
from src.ui.base import panel_action, swap_panel

if TYPE_CHECKING:
    from src.bot import HoRoBot
    from src.ui.status import Notice

NAV_CUSTOM_ID = "cs:settings:nav"

# 頁面代號：同時是 PANELS 的鍵，兩邊不同步會直接 KeyError，不會默默導到錯的頁。
NAV_HOME = "home"
NAV_LOG_TOGGLES = "log_toggles"
NAV_MODEL = "model"


@dataclass(frozen=True, slots=True)
class NavItem:
    """一個導覽選項。description 是必填欄位，因為選單的價值就在於進去前先知道能做什麼。"""

    key: str
    label: str
    description: str
    emoji: str


NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem(NAV_HOME, strings.NAV_SETTINGS_HOME, strings.NAV_SETTINGS_HOME_DESC, "⚙️"),
    NavItem(NAV_LOG_TOGGLES, strings.SETTINGS_LOG_TOGGLES, strings.NAV_LOG_TOGGLES_DESC, "📜"),
    NavItem(NAV_MODEL, strings.SETTINGS_MODEL, strings.NAV_MODEL_DESC, "🤖"),
)


def _option(item: NavItem, current: str) -> discord.SelectOption:
    here = item.key == current
    return discord.SelectOption(
        # 勾記寫進 label，而不是只靠 default：收合時 Discord 只顯示選中值，
        # 展開清單的當下仍要一眼看得出自己站在哪一頁。
        label=f"{strings.NAV_CURRENT_MARK} {item.label}" if here else item.label,
        value=item.key,
        description=item.description,
        emoji=item.emoji,
        default=here,
    )


def nav_row(bot: HoRoBot, current: str) -> discord.ui.ActionRow:
    """產生設定頁共用的導覽列；current 是目前所在頁的代號，會被標記為已選。"""
    select = discord.ui.Select(
        custom_id=NAV_CUSTOM_ID,
        placeholder=strings.NAV_SETTINGS_PLACEHOLDER,
        options=[_option(item, current) for item in NAV_ITEMS],
    )

    async def choose(interaction: discord.Interaction) -> None:
        # 延遲匯入：PANELS 在套件 __init__，而 __init__ 又要匯入各面板模組（含本模組），
        # 放在模組層會在啟動時循環爆炸，故收在 callback 內（同 shared.SettingsModal 作法）。
        from src.ui.settings import PANELS

        async def rebuild(notice: str | Notice) -> discord.ui.LayoutView:
            # 出錯時留在原頁重畫，而不是把使用者丟到一個根本沒去成的頁面。
            return await PANELS[current](bot, interaction, notice=notice)

        async with panel_action(interaction, rebuild):
            await swap_panel(interaction, await PANELS[select.values[0]](bot, interaction))

    select.callback = choose
    return discord.ui.ActionRow(select)
