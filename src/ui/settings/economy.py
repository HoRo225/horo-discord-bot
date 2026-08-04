"""經濟系統（貨幣名稱、每日津貼、21 點賭注上下限）設定。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from src import strings
from src.database.models import GuildSettings
from src.ui.settings.shared import SettingsModal

if TYPE_CHECKING:
    from src.bot import HoRoBot


class EconomySettingsModal(SettingsModal):
    action = "settings_economy_blackjack"

    def __init__(self, bot: HoRoBot, settings: GuildSettings) -> None:
        super().__init__(
            bot,
            settings,
            title=strings.SETTINGS_ECONOMY,
            custom_id="cs:settings:economy:modal",
        )
        self.currency = discord.ui.TextInput(default=settings.currency_name, max_length=50)
        self.daily = discord.ui.TextInput(default=str(settings.daily_amount), max_length=18)
        self.minimum = discord.ui.TextInput(default=str(settings.blackjack_min_bet), max_length=18)
        self.maximum = discord.ui.TextInput(default=str(settings.blackjack_max_bet), max_length=18)
        for text, component in (
            (strings.CURRENCY_NAME, self.currency),
            (strings.DAILY_AMOUNT, self.daily),
            (strings.BLACKJACK_MIN_BET, self.minimum),
            (strings.BLACKJACK_MAX_BET, self.maximum),
        ):
            self.add_item(discord.ui.Label(text=text, component=component))

    def values(self) -> dict[str, Any]:
        return {
            "currency_name": str(self.currency),
            "daily_amount": int(str(self.daily)),
            "blackjack_min_bet": int(str(self.minimum)),
            "blackjack_max_bet": int(str(self.maximum)),
        }
