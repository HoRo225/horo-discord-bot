"""經濟系統（貨幣名稱、每日津貼、21 點賭注上下限）設定頁。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, ClassVar

import discord

from src import strings
from src.database.models import GuildSettings
from src.ui.base import button
from src.ui.settings.nav import NAV_ECONOMY
from src.ui.settings.shared import SettingsModal, SettingsPage
from src.ui.status import Notice, badge

if TYPE_CHECKING:
    from src.bot import HoRoBot


async def economy_page(
    bot: HoRoBot, interaction: discord.Interaction, *, notice: str | Notice | None = None
) -> EconomyPage:
    settings = await bot.settings_service.get(interaction.guild_id)
    return EconomyPage(bot, settings, notice=notice)


class EconomyPage(SettingsPage):
    title = f"## 💎 {strings.SETTINGS_ECONOMY}"
    body = strings.SETTINGS_ECONOMY_BODY
    nav_key = NAV_ECONOMY

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        current = self.settings
        # 四個欄位都有資料庫預設值，開箱即可用，狀態恆為 OK（見 shared.module_statuses）。
        yield discord.ui.TextDisplay(
            badge(
                self.status(),
                f"{strings.CURRENCY_NAME}：**{current.currency_name}**｜"
                f"{strings.DAILY_AMOUNT}：**{current.daily_amount}**\n"
                f"　　{strings.BLACKJACK_MIN_BET}：**{current.blackjack_min_bet}**｜"
                f"{strings.BLACKJACK_MAX_BET}：**{current.blackjack_max_bet}**",
            )
        )
        yield discord.ui.ActionRow(
            button(strings.SETTINGS_EDIT, "cs:settings:economy:edit", self.edit, emoji="✏️")
        )

    async def edit(self, interaction: discord.Interaction) -> None:
        # send_modal 必須是該次互動的首個回應；panel_action 一進來就 defer，兩者互斥，
        # 因此這顆鈕刻意不套 panel_action，錯誤處理留給 Modal 的 on_submit。
        await interaction.response.send_modal(EconomySettingsModal(self.bot, self.settings))


class EconomySettingsModal(SettingsModal):
    action = "settings_economy_blackjack"
    # 送出後回經濟頁而非總覽：在這頁點編輯，結果也該留在這頁。
    origin: ClassVar[str] = NAV_ECONOMY

    def __init__(self, bot: HoRoBot, settings: GuildSettings) -> None:
        super().__init__(
            bot,
            settings,
            title=strings.SETTINGS_ECONOMY,
            custom_id="cs:settings:economy:modal",
        )
        self.currency = discord.ui.TextInput(default=settings.currency_name, max_length=50)
        self.daily = discord.ui.TextInput(default=str(settings.daily_amount), max_length=7)
        self.minimum = discord.ui.TextInput(default=str(settings.blackjack_min_bet), max_length=7)
        self.maximum = discord.ui.TextInput(default=str(settings.blackjack_max_bet), max_length=7)
        for text, component in (
            (strings.CURRENCY_NAME, self.currency),
            (strings.DAILY_AMOUNT, self.daily),
            (strings.BLACKJACK_MIN_BET, self.minimum),
            (strings.BLACKJACK_MAX_BET, self.maximum),
        ):
            self.add_item(discord.ui.Label(text=text, component=component))

    def values(self) -> dict[str, Any]:
        # 四欄必須一次送出：src.services.settings 的跨欄位驗證會拿 DB 既有值補另一半，
        # 只送半組（例如只改 max）會被「min > 0 and max >= min」擋下，
        # 使用者就卡在「得先改 min 才能改 max、但 min 又不能大於 max」的死結。
        # 這也是保留 Modal（而不是把四欄拆成面板上分開存檔的元件）的第二個理由，
        # 第一個理由是 TextInput 本來就上不了面板，只有 Modal 能用。
        return {
            "currency_name": str(self.currency),
            "daily_amount": int(str(self.daily)),
            "blackjack_min_bet": int(str(self.minimum)),
            "blackjack_max_bet": int(str(self.maximum)),
        }
