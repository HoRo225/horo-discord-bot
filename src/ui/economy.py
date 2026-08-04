from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import discord

from src import strings
from src.ui.base import (
    PagedPanel,
    Panel,
    button,
    defer_update,
    section,
    show_error,
    swap_panel,
)
from src.ui.common import is_admin


async def economy_panel(
    bot: Any, interaction: discord.Interaction, *, notice: str | None = None
) -> EconomyPanel:
    """組出帶有目前餘額的經濟面板。餘額要查資料庫，所以建構走 async 工廠。"""
    settings = await bot.settings_service.get(interaction.guild_id)
    balance = await bot.economy.balance(interaction.guild_id, interaction.user.id)
    return EconomyPanel(bot, balance=balance, currency=settings.currency_name, notice=notice)


class EconomyPanel(Panel):
    title = strings.ECONOMY_TITLE
    accent = discord.Colour.from_rgb(94, 234, 212)

    def __init__(self, bot: Any, *, balance: int = 0, currency: str = "", **kwargs: Any) -> None:
        self.balance = balance
        self.currency = currency
        super().__init__(bot, **kwargs)

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        # 餘額常駐顯示，因此不再需要獨立的「查詢餘額」按鈕。
        yield section(
            strings.BALANCE_TEXT.format(balance=self.balance, currency=self.currency),
            button(
                strings.DAILY,
                "cs:economy:daily",
                self.daily,
                style=discord.ButtonStyle.primary,
                emoji="📅",
            ),
        )
        yield discord.ui.Separator()
        yield discord.ui.ActionRow(
            button(strings.LEADERBOARD, "cs:economy:leaderboard", self.leaderboard, emoji="🏆"),
            button(
                strings.TRANSFER,
                "cs:economy:transfer",
                self.transfer,
                style=discord.ButtonStyle.primary,
                emoji="↔️",
            ),
            button(strings.ADMIN_ADJUST, "cs:economy:admin", self.admin_adjust, emoji="🛠️"),
        )

    async def daily(self, interaction: discord.Interaction) -> None:
        try:
            await defer_update(interaction)
            settings = await self.bot.settings_service.get(interaction.guild_id)
            result = await self.bot.economy.daily(
                interaction.guild_id, interaction.user.id, settings.daily_amount
            )
            notice = (
                strings.DAILY_CLAIMED.format(
                    amount=result.amount,
                    balance=result.balance,
                    currency=settings.currency_name,
                )
                if result.claimed
                else strings.DAILY_ALREADY
            )
            await swap_panel(interaction, await economy_panel(self.bot, interaction, notice=notice))
        except Exception as exc:
            await show_error(
                interaction, exc, lambda note: economy_panel(self.bot, interaction, notice=note)
            )

    async def leaderboard(self, interaction: discord.Interaction) -> None:
        try:
            await defer_update(interaction)
            await swap_panel(interaction, await leaderboard_panel(self.bot, interaction))
        except Exception as exc:
            await show_error(
                interaction, exc, lambda note: economy_panel(self.bot, interaction, notice=note)
            )

    async def transfer(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(TransferModal(self.bot))

    async def admin_adjust(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction):
            await defer_update(interaction)
            await swap_panel(
                interaction,
                await economy_panel(self.bot, interaction, notice=strings.ADMIN_ONLY),
            )
            return
        await interaction.response.send_modal(AdminAdjustModal(self.bot))


async def leaderboard_panel(
    bot: Any, interaction: discord.Interaction, *, notice: str | None = None
) -> LeaderboardPanel:
    settings = await bot.settings_service.get(interaction.guild_id)
    wallets = await bot.economy.leaderboard(interaction.guild_id, limit=100)

    async def back(target: discord.Interaction) -> None:
        await defer_update(target)
        await swap_panel(target, await economy_panel(bot, target))

    return LeaderboardPanel(bot, wallets, currency=settings.currency_name, notice=notice, back=back)


class LeaderboardPanel(PagedPanel):
    title = strings.LEADERBOARD_HEADER
    accent = discord.Colour.from_rgb(94, 234, 212)
    page_size = 10

    def __init__(self, bot: Any, wallets: Any, *, currency: str = "", **kwargs: Any) -> None:
        self.currency = currency
        super().__init__(bot, wallets, **kwargs)

    def _respawn(self, page: int) -> LeaderboardPanel:
        return LeaderboardPanel(
            self.bot,
            self.items,
            currency=self.currency,
            page=page,
            notice=self.notice,
            back=self.back,
        )

    def page_rows(self, items: list[Any]) -> Iterable[discord.ui.Item[Any]]:
        if not self.items:
            yield discord.ui.TextDisplay(strings.LEADERBOARD_EMPTY)
            return
        offset = self.page * self.page_size
        yield discord.ui.TextDisplay(
            "\n".join(
                f"**{offset + index}.** <@{wallet.user_id}> — {wallet.balance} {self.currency}"
                for index, wallet in enumerate(items, 1)
            )
        )


class TransferModal(discord.ui.Modal):
    def __init__(self, bot: Any) -> None:
        super().__init__(
            title=strings.TRANSFER_MODAL_TITLE, timeout=300, custom_id="cs:economy:transfer:modal"
        )
        self.bot = bot
        self.recipient = discord.ui.UserSelect(
            placeholder=strings.RECIPIENT_PLACEHOLDER, min_values=1, max_values=1
        )
        self.amount = discord.ui.TextInput(placeholder="100", max_length=18)
        self.add_item(discord.ui.Label(text=strings.RECIPIENT, component=self.recipient))
        self.add_item(discord.ui.Label(text=strings.AMOUNT, component=self.amount))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await defer_update(interaction)
            recipient = self.recipient.values[0]
            amount = int(str(self.amount).strip())
            if amount <= 0:
                raise ValueError(strings.AMOUNT_POSITIVE)
            await self.bot.economy.transfer(
                guild_id=interaction.guild_id,
                sender_id=interaction.user.id,
                recipient_id=recipient.id,
                amount=amount,
                idempotency_key=str(interaction.id),
            )
            settings = await self.bot.settings_service.get(interaction.guild_id)
            notice = strings.TRANSFER_DONE.format(
                amount=amount, currency=settings.currency_name, user_id=recipient.id
            )
            await swap_panel(interaction, await economy_panel(self.bot, interaction, notice=notice))
        except ValueError as exc:
            await swap_panel(
                interaction,
                await economy_panel(
                    self.bot,
                    interaction,
                    notice=strings.INVALID_INPUT.format(reason=str(exc)),
                ),
            )
        except Exception as exc:
            await show_error(
                interaction, exc, lambda note: economy_panel(self.bot, interaction, notice=note)
            )


class AdminAdjustModal(discord.ui.Modal):
    def __init__(self, bot: Any) -> None:
        super().__init__(
            title=strings.ADMIN_ADJUST_MODAL_TITLE,
            timeout=300,
            custom_id="cs:economy:admin:modal",
        )
        self.bot = bot
        self.target = discord.ui.UserSelect(
            placeholder=strings.TARGET_USER_PLACEHOLDER, min_values=1, max_values=1
        )
        self.amount = discord.ui.TextInput(
            placeholder=strings.ADMIN_ADJUST_PLACEHOLDER, max_length=18
        )
        self.reason = discord.ui.TextInput(required=False, max_length=300)
        self.add_item(discord.ui.Label(text=strings.TARGET_USER, component=self.target))
        self.add_item(discord.ui.Label(text=strings.AMOUNT, component=self.amount))
        self.add_item(discord.ui.Label(text=strings.REASON, component=self.reason))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await defer_update(interaction)
            # Modal 的 interaction 不會經過開啟它的面板檢查，這道防線必須留著。
            if not is_admin(interaction):
                await swap_panel(
                    interaction,
                    await economy_panel(self.bot, interaction, notice=strings.ADMIN_ONLY),
                )
                return
            target = self.target.values[0]
            amount = int(str(self.amount).strip())
            result = await self.bot.economy.admin_adjust(
                guild_id=interaction.guild_id,
                admin_user_id=interaction.user.id,
                target_user_id=target.id,
                amount=amount,
                idempotency_key=f"admin:{interaction.id}",
                reason=str(self.reason).strip(),
            )
            notice = strings.ADMIN_ADJUST_DONE.format(user_id=target.id, balance=result.balance)
            await swap_panel(interaction, await economy_panel(self.bot, interaction, notice=notice))
        except ValueError as exc:
            await swap_panel(
                interaction,
                await economy_panel(
                    self.bot,
                    interaction,
                    notice=strings.INVALID_INPUT.format(reason=str(exc)),
                ),
            )
        except Exception as exc:
            await show_error(
                interaction, exc, lambda note: economy_panel(self.bot, interaction, notice=note)
            )
