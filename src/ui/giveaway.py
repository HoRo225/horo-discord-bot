from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import discord

from src import strings
from src.database.models import Giveaway
from src.services.common import aware_utc
from src.ui.common import (
    defer_ephemeral,
    handle_interaction_error,
    is_admin,
    message_link,
    send_ephemeral,
)


def parse_duration(value: str) -> timedelta:
    match = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", value.lower())
    if not match:
        raise ValueError(strings.GIVEAWAY_DURATION_FORMAT_ERROR)
    number = int(match.group(1))
    if number <= 0:
        raise ValueError(strings.GIVEAWAY_DURATION_POSITIVE)
    unit = match.group(2)
    return {
        "m": timedelta(minutes=number),
        "h": timedelta(hours=number),
        "d": timedelta(days=number),
    }[unit]


def giveaway_embed(giveaway: Giveaway) -> discord.Embed:
    status = (
        strings.GIVEAWAY_STATUS_ACTIVE
        if giveaway.status == "active"
        else strings.GIVEAWAY_STATUS_ENDED
    )
    price = (
        strings.GIVEAWAY_FREE
        if giveaway.ticket_price == 0
        else strings.GIVEAWAY_PRICE.format(price=giveaway.ticket_price)
    )
    ending = discord.utils.format_dt(aware_utc(giveaway.ends_at), style="R")
    embed = discord.Embed(
        title=f"🎁 {giveaway.prize}",
        description=strings.GIVEAWAY_DESCRIPTION.format(
            id=giveaway.id,
            winner_count=giveaway.winner_count,
            price=price,
            limit=giveaway.per_user_limit,
            ending=ending,
        ),
        colour=discord.Colour.gold(),
    )
    embed.set_footer(text=status)
    return embed


class GiveawayPanel(discord.ui.LayoutView):
    def __init__(self, bot: Any) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        create = discord.ui.Button(
            label=strings.GIVEAWAY_CREATE,
            style=discord.ButtonStyle.primary,
            custom_id="cs:giveaway:create",
        )
        listing = discord.ui.Button(label=strings.GIVEAWAY_LIST, custom_id="cs:giveaway:list")
        buy = discord.ui.Button(label=strings.GIVEAWAY_BUY, custom_id="cs:giveaway:buy")
        reroll = discord.ui.Button(label=strings.GIVEAWAY_REROLL, custom_id="cs:giveaway:reroll")
        create.callback = self.create
        listing.callback = self.listing
        buy.callback = self.buy
        reroll.callback = self.reroll
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(strings.GIVEAWAY_TITLE),
                discord.ui.ActionRow(create, listing, buy, reroll),
                accent_colour=discord.Colour.gold(),
            )
        )

    async def create(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction):
            await send_ephemeral(interaction, strings.ADMIN_ONLY)
            return
        await interaction.response.send_modal(CreateGiveawayModal(self.bot))

    async def listing(self, interaction: discord.Interaction) -> None:
        try:
            await defer_ephemeral(interaction)
            giveaways = await self.bot.giveaways.active(interaction.guild_id, paid_only=True)
            lines = []
            for item in giveaways:
                ending = discord.utils.format_dt(aware_utc(item.ends_at), style="R")
                lines.append(f"`#{item.id}` **{item.prize}** — {ending}")
            await send_ephemeral(
                interaction,
                strings.GIVEAWAY_PAID_HEADER
                + "\n"
                + ("\n".join(lines) if lines else strings.GIVEAWAY_PAID_EMPTY),
            )
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def buy(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(BuyTicketsModal(self.bot))

    async def reroll(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction):
            await send_ephemeral(interaction, strings.ADMIN_ONLY)
            return
        await interaction.response.send_modal(RerollModal(self.bot))


class CreateGiveawayModal(discord.ui.Modal):
    def __init__(self, bot: Any) -> None:
        super().__init__(title=strings.GIVEAWAY_CREATE, custom_id="cs:giveaway:create:modal")
        self.bot = bot
        self.prize = discord.ui.TextInput(label=strings.GIVEAWAY_PRIZE, max_length=300)
        self.winners = discord.ui.TextInput(
            label=strings.GIVEAWAY_WINNER_COUNT, default="1", max_length=2
        )
        self.duration = discord.ui.TextInput(
            label=strings.GIVEAWAY_DURATION, placeholder="2h", max_length=12
        )
        self.price = discord.ui.TextInput(
            label=strings.GIVEAWAY_TICKET_PRICE, default="0", max_length=18
        )
        self.limit = discord.ui.TextInput(
            label=strings.GIVEAWAY_PER_USER_LIMIT, default="1", max_length=6
        )
        for item in (self.prize, self.winners, self.duration, self.price, self.limit):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction):
            await send_ephemeral(interaction, strings.ADMIN_ONLY)
            return
        try:
            await defer_ephemeral(interaction)
            duration = parse_duration(str(self.duration))
            giveaway = await self.bot.giveaways.create(
                guild_id=interaction.guild_id,
                channel_id=interaction.channel_id,
                created_by=interaction.user.id,
                prize=str(self.prize),
                winner_count=int(str(self.winners)),
                ends_at=datetime.now(UTC) + duration,
                ticket_price=int(str(self.price)),
                per_user_limit=int(str(self.limit)),
            )
            if interaction.channel is None:
                raise RuntimeError(strings.CURRENT_CHANNEL_NOT_FOUND)
            message = await interaction.channel.send(
                embed=giveaway_embed(giveaway),
                view=GiveawayEntryView(self.bot),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await self.bot.giveaways.attach_message(giveaway.id, message.id)
            link = message_link(interaction.guild_id, message.channel.id, message.id)
            await send_ephemeral(
                interaction,
                strings.GIVEAWAY_CREATED.format(giveaway_id=giveaway.id)
                + strings.GIVEAWAY_LINK.format(link=link),
            )
        except ValueError as exc:
            await send_ephemeral(interaction, strings.INVALID_INPUT.format(reason=str(exc)))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)


class BuyTicketsModal(discord.ui.Modal):
    def __init__(self, bot: Any) -> None:
        super().__init__(title=strings.GIVEAWAY_BUY, custom_id="cs:giveaway:buy:modal")
        self.bot = bot
        self.giveaway_id = discord.ui.TextInput(label=strings.GIVEAWAY_ID, max_length=12)
        self.quantity = discord.ui.TextInput(
            label=strings.GIVEAWAY_QUANTITY, default="1", max_length=6
        )
        self.add_item(self.giveaway_id)
        self.add_item(self.quantity)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await defer_ephemeral(interaction)
            result = await self.bot.giveaways.enter(
                giveaway_id=int(str(self.giveaway_id)),
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                quantity=int(str(self.quantity)),
                idempotency_key=str(interaction.id),
            )
            await send_ephemeral(interaction, strings.GIVEAWAY_ENTERED.format(weight=result.weight))
        except ValueError as exc:
            await send_ephemeral(interaction, strings.INVALID_INPUT.format(reason=str(exc)))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)


class RerollModal(discord.ui.Modal):
    def __init__(self, bot: Any) -> None:
        super().__init__(title=strings.GIVEAWAY_REROLL, custom_id="cs:giveaway:reroll:modal")
        self.bot = bot
        self.giveaway_id = discord.ui.TextInput(label=strings.GIVEAWAY_ID, max_length=12)
        self.add_item(self.giveaway_id)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction):
            await send_ephemeral(interaction, strings.ADMIN_ONLY)
            return
        try:
            await defer_ephemeral(interaction)
            giveaway = await self.bot.giveaways.reroll(
                int(str(self.giveaway_id)), admin_user_id=interaction.user.id
            )
            winners = "、".join(f"<@{user_id}>" for user_id in giveaway.winners)
            winners = winners or strings.GIVEAWAY_NO_REROLL_CANDIDATE
            if interaction.channel is not None:
                await interaction.channel.send(
                    strings.GIVEAWAY_REROLL_RESULT.format(id=giveaway.id, winners=winners),
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            await send_ephemeral(interaction, strings.SUCCESS)
        except ValueError as exc:
            await send_ephemeral(interaction, strings.INVALID_INPUT.format(reason=str(exc)))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)


class GiveawayEntryView(discord.ui.View):
    def __init__(self, bot: Any) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        button = discord.ui.Button(
            label=strings.GIVEAWAY_JOIN_OR_BUY,
            emoji="🎟️",
            style=discord.ButtonStyle.success,
            custom_id="cs:giveaway:enter",
        )
        button.callback = self.enter
        self.add_item(button)

    async def enter(self, interaction: discord.Interaction) -> None:
        try:
            await defer_ephemeral(interaction)
            if interaction.message is None:
                raise RuntimeError(strings.ACTIVITY_MESSAGE_NOT_FOUND)
            giveaway = await self.bot.giveaways.by_message(interaction.message.id)
            if giveaway is None:
                await send_ephemeral(interaction, strings.NOT_FOUND)
                return
            result = await self.bot.giveaways.enter(
                giveaway_id=giveaway.id,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                quantity=1,
                idempotency_key=str(interaction.id),
            )
            await send_ephemeral(interaction, strings.GIVEAWAY_ENTERED.format(weight=result.weight))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)
