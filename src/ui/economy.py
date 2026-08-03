from __future__ import annotations

from typing import Any

import discord

from src import strings
from src.ui.common import (
    defer_ephemeral,
    ensure_guild_member,
    handle_interaction_error,
    is_admin,
    parse_user_id,
    send_ephemeral,
)


class EconomyPanel(discord.ui.LayoutView):
    def __init__(self, bot: Any) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        daily = discord.ui.Button(label=strings.DAILY, emoji="📅", custom_id="cs:economy:daily")
        balance = discord.ui.Button(
            label=strings.BALANCE, emoji="💰", custom_id="cs:economy:balance"
        )
        leaderboard = discord.ui.Button(
            label=strings.LEADERBOARD, emoji="🏆", custom_id="cs:economy:leaderboard"
        )
        transfer = discord.ui.Button(
            label=strings.TRANSFER,
            emoji="↔️",
            style=discord.ButtonStyle.primary,
            custom_id="cs:economy:transfer",
        )
        adjust = discord.ui.Button(
            label=strings.ADMIN_ADJUST,
            emoji="🛠️",
            style=discord.ButtonStyle.secondary,
            custom_id="cs:economy:admin",
        )
        daily.callback = self.daily
        balance.callback = self.balance
        leaderboard.callback = self.leaderboard
        transfer.callback = self.transfer
        adjust.callback = self.admin_adjust
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(strings.ECONOMY_TITLE),
                discord.ui.ActionRow(daily, balance, leaderboard),
                discord.ui.ActionRow(transfer, adjust),
                accent_colour=discord.Colour.from_rgb(94, 234, 212),
            )
        )

    async def daily(self, interaction: discord.Interaction) -> None:
        try:
            await defer_ephemeral(interaction)
            settings = await self.bot.settings_service.get(interaction.guild_id)
            result = await self.bot.economy.daily(
                interaction.guild_id, interaction.user.id, settings.daily_amount
            )
            if result.claimed:
                text = strings.DAILY_CLAIMED.format(
                    amount=result.amount,
                    balance=result.balance,
                    currency=settings.currency_name,
                )
            else:
                text = strings.DAILY_ALREADY
            await send_ephemeral(interaction, text)
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def balance(self, interaction: discord.Interaction) -> None:
        try:
            await defer_ephemeral(interaction)
            settings = await self.bot.settings_service.get(interaction.guild_id)
            balance = await self.bot.economy.balance(interaction.guild_id, interaction.user.id)
            await send_ephemeral(
                interaction,
                strings.BALANCE_TEXT.format(balance=balance, currency=settings.currency_name),
            )
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def leaderboard(self, interaction: discord.Interaction) -> None:
        try:
            await defer_ephemeral(interaction)
            settings = await self.bot.settings_service.get(interaction.guild_id)
            wallets = await self.bot.economy.leaderboard(interaction.guild_id)
            lines = [
                f"**{index}.** <@{wallet.user_id}> — {wallet.balance} {settings.currency_name}"
                for index, wallet in enumerate(wallets, 1)
            ]
            await send_ephemeral(
                interaction,
                strings.LEADERBOARD_HEADER
                + "\n"
                + ("\n".join(lines) if lines else strings.LEADERBOARD_EMPTY),
            )
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def transfer(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(TransferModal(self.bot))

    async def admin_adjust(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction):
            await send_ephemeral(interaction, strings.ADMIN_ONLY)
            return
        await interaction.response.send_modal(AdminAdjustModal(self.bot))


class TransferModal(discord.ui.Modal, title=strings.TRANSFER_MODAL_TITLE):
    recipient = discord.ui.TextInput(
        label=strings.RECIPIENT_ID, placeholder="123456789012345678", max_length=30
    )
    amount = discord.ui.TextInput(label=strings.AMOUNT, placeholder="100", max_length=18)

    def __init__(self, bot: Any) -> None:
        super().__init__(timeout=300, custom_id="cs:economy:transfer:modal")
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await defer_ephemeral(interaction)
            recipient_id = parse_user_id(str(self.recipient))
            await ensure_guild_member(interaction, recipient_id)
            amount = int(str(self.amount).strip())
            if amount <= 0:
                raise ValueError(strings.AMOUNT_POSITIVE)
            await self.bot.economy.transfer(
                guild_id=interaction.guild_id,
                sender_id=interaction.user.id,
                recipient_id=recipient_id,
                amount=amount,
                idempotency_key=str(interaction.id),
            )
            settings = await self.bot.settings_service.get(interaction.guild_id)
            await send_ephemeral(
                interaction,
                strings.TRANSFER_DONE.format(
                    amount=amount, currency=settings.currency_name, user_id=recipient_id
                ),
            )
        except ValueError as exc:
            await send_ephemeral(interaction, strings.INVALID_INPUT.format(reason=str(exc)))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)


class AdminAdjustModal(discord.ui.Modal, title=strings.ADMIN_ADJUST_MODAL_TITLE):
    target = discord.ui.TextInput(
        label=strings.USER_ID, placeholder="123456789012345678", max_length=30
    )
    amount = discord.ui.TextInput(
        label=strings.AMOUNT,
        placeholder=strings.ADMIN_ADJUST_PLACEHOLDER,
        max_length=18,
    )
    reason = discord.ui.TextInput(label=strings.REASON, required=False, max_length=300)

    def __init__(self, bot: Any) -> None:
        super().__init__(timeout=300, custom_id="cs:economy:admin:modal")
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction):
            await send_ephemeral(interaction, strings.ADMIN_ONLY)
            return
        try:
            await defer_ephemeral(interaction)
            target_id = parse_user_id(str(self.target))
            await ensure_guild_member(interaction, target_id)
            amount = int(str(self.amount).strip())
            result = await self.bot.economy.admin_adjust(
                guild_id=interaction.guild_id,
                admin_user_id=interaction.user.id,
                target_user_id=target_id,
                amount=amount,
                idempotency_key=f"admin:{interaction.id}",
                reason=str(self.reason).strip(),
            )
            await send_ephemeral(
                interaction,
                strings.ADMIN_ADJUST_DONE.format(user_id=target_id, balance=result.balance),
            )
        except ValueError as exc:
            await send_ephemeral(interaction, strings.INVALID_INPUT.format(reason=str(exc)))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)
