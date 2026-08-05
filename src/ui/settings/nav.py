"""settings 各頁共用的導覽選單。

設定拆成五頁（總覽／日誌／經濟／投票／AI），每頁底部掛同一個 StringSelect，
任兩頁之間都只要一次點選，使用者也不必再靠記憶推測自己在第幾層。

本模組維持一條不變量：**nav 的 callback 只做 swap_panel，永遠不 send_modal。**
需要 Modal 的操作（經濟數值、AI 配額）一律由該頁上的按鈕發起。兩個原因：

1. ``panel_action`` 一進來就 defer，而 ``send_modal`` 必須是該次互動的首個回應，
   兩者天生互斥。
2. select 開完 Modal 後選單會停在剛選的值，使用者得再選一次別的才回得去。

換頁後選單停在新頁的值則是正確的——那就是你現在所在的頁，
``_option()`` 的 ✓ 與 ``default=here`` 正是為此而設計。

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
#
# 後四個刻意與 shared.module_statuses() 回傳的鍵同字串，子頁才能用
# `self.statuses[self.nav_key]` 一行取到自己的狀態色，不必再維護一張頁面→模組的對照表。
# 改動任一邊都要同步另一邊。總覽頁沒有對應模組（它是全部模組的總和），故不在其中。
NAV_HOME = "home"
NAV_LOG = "log"
NAV_ECONOMY = "economy"
NAV_POLL = "poll"
NAV_AI = "ai"


@dataclass(frozen=True, slots=True)
class NavItem:
    """一個導覽選項。description 是必填欄位，因為選單的價值就在於進去前先知道能做什麼。"""

    key: str
    label: str
    description: str
    emoji: str


NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem(NAV_HOME, strings.NAV_SETTINGS_HOME, strings.NAV_SETTINGS_HOME_DESC, "⚙️"),
    NavItem(NAV_LOG, strings.SETTINGS_LOG, strings.NAV_LOG_DESC, "📜"),
    NavItem(NAV_ECONOMY, strings.SETTINGS_ECONOMY, strings.NAV_ECONOMY_DESC, "💎"),
    NavItem(NAV_POLL, strings.SETTINGS_POLL, strings.NAV_POLL_DESC, "📊"),
    NavItem(NAV_AI, strings.SETTINGS_AI, strings.NAV_AI_DESC, "🤖"),
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
