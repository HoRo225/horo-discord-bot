from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import discord

from src import strings
from src.database.models import Giveaway
from src.services.common import aware_utc
from src.ui.base import PagedPanel, Panel, button, defer_update, panel_action, swap_panel
from src.ui.common import handle_interaction_error, is_admin, message_link
from src.ui.status import Notice, StatusKind

if TYPE_CHECKING:
    from src.bot import HoRoBot


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


def giveaway_text(giveaway: Giveaway) -> str:
    """把抽獎資訊組成一段可放進 TextDisplay 的文字。"""
    # 公告訊息是在 publish() 之前送出的，此時狀態還是 pending，
    # 所以判斷「已結束」要看是不是 completed，不能看是不是 active。
    status = (
        strings.GIVEAWAY_STATUS_ENDED
        if giveaway.status == "completed"
        else strings.GIVEAWAY_STATUS_ACTIVE
    )
    price = (
        strings.GIVEAWAY_FREE
        if giveaway.ticket_price == 0
        else strings.GIVEAWAY_PRICE.format(price=giveaway.ticket_price)
    )
    body = strings.GIVEAWAY_DESCRIPTION.format(
        id=giveaway.id,
        winner_count=giveaway.winner_count,
        price=price,
        limit=giveaway.per_user_limit,
        ending=discord.utils.format_dt(aware_utc(giveaway.ends_at), style="R"),
    )
    return f"## 🎁 {giveaway.prize}\n{body}\n-# {status}"


def _options(giveaways: Sequence[Giveaway]) -> list[discord.SelectOption]:
    return [
        discord.SelectOption(
            label=strings.GIVEAWAY_OPTION.format(id=item.id, prize=item.prize)[:100],
            value=str(item.id),
        )
        for item in giveaways[:25]
    ]


class GiveawayMessageView(discord.ui.LayoutView):
    """頻道內的抽獎公告訊息。

    公告內容與參加按鈕都在這個 view 裡，所以**結束時不能傳 view=None**，
    那會讓整則公告變空白。改由本類別在非 active 狀態自行收起參加按鈕。
    """

    def __init__(self, bot: HoRoBot, giveaway: Giveaway | None = None) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        items: list[discord.ui.Item[Any]] = []
        if giveaway is not None:
            items.append(discord.ui.TextDisplay(giveaway_text(giveaway)))
        if giveaway is None or giveaway.status != "completed":
            items.append(discord.ui.Separator())
            items.append(
                discord.ui.ActionRow(
                    button(
                        strings.GIVEAWAY_JOIN_OR_BUY,
                        "cs:giveaway:enter",
                        self.enter,
                        style=discord.ButtonStyle.success,
                        emoji="🎟️",
                    )
                )
            )
        self.add_item(discord.ui.Container(*items, accent_colour=discord.Colour.gold()))

    async def enter(self, interaction: discord.Interaction) -> None:
        # 公開訊息上的按鈕沒有可重建的私人面板，錯誤只能改用獨立訊息回報。
        try:
            await defer_update(interaction)
            if interaction.message is None:
                raise RuntimeError(strings.ACTIVITY_MESSAGE_NOT_FOUND)
            giveaway = await self.bot.giveaways.by_message(interaction.message.id)
            if giveaway is None:
                await interaction.followup.send(strings.NOT_FOUND, ephemeral=True)
                return
            result = await self.bot.giveaways.enter(
                giveaway_id=giveaway.id,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                quantity=1,
                idempotency_key=str(interaction.id),
            )
            # 公開公告是共享訊息，參加結果只回報給本人。
            await interaction.followup.send(
                strings.GIVEAWAY_ENTERED.format(weight=result.weight), ephemeral=True
            )
        except Exception as exc:
            await handle_interaction_error(interaction, exc)


async def giveaway_panel(
    bot: HoRoBot, interaction: discord.Interaction, *, notice: str | Notice | None = None
) -> GiveawayPanel:
    return GiveawayPanel(bot, notice=notice)


class GiveawayPanel(Panel):
    title = strings.GIVEAWAY_TITLE
    accent = discord.Colour.gold()

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        yield discord.ui.Separator()
        yield discord.ui.ActionRow(
            button(
                strings.GIVEAWAY_CREATE,
                "cs:giveaway:create",
                self.create,
                style=discord.ButtonStyle.primary,
                emoji="✨",
            ),
            button(strings.GIVEAWAY_LIST, "cs:giveaway:list", self.listing, emoji="📋"),
            button(strings.GIVEAWAY_BUY, "cs:giveaway:buy", self.buy, emoji="🎟️"),
            button(strings.GIVEAWAY_REROLL, "cs:giveaway:reroll", self.reroll, emoji="🔁"),
        )

    async def _deny(self, interaction: discord.Interaction) -> None:
        # 拒絕分支沒有 Modal，套 panel_action 換得「重建面板也失敗」時的保底。
        async with panel_action(
            interaction, lambda note: giveaway_panel(self.bot, interaction, notice=note)
        ):
            await swap_panel(
                interaction, await giveaway_panel(self.bot, interaction, notice=strings.ADMIN_ONLY)
            )

    async def create(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction):
            await self._deny(interaction)
            return
        await interaction.response.send_modal(CreateGiveawayModal(self.bot))

    async def listing(self, interaction: discord.Interaction) -> None:
        async with panel_action(
            interaction, lambda note: giveaway_panel(self.bot, interaction, notice=note)
        ):
            await swap_panel(interaction, await giveaway_list_panel(self.bot, interaction))

    async def buy(self, interaction: discord.Interaction) -> None:
        giveaways = await self.bot.giveaways.active(interaction.guild_id)
        if not giveaways:
            # 半 Modal 半面板：沒有可買的抽獎才走面板分支，通過則送出 Modal，
            # 所以只把這個分支縮進 panel_action，不能整個 callback 包起來。
            async with panel_action(
                interaction, lambda note: giveaway_panel(self.bot, interaction, notice=note)
            ):
                await swap_panel(
                    interaction,
                    await giveaway_panel(
                        self.bot,
                        interaction,
                        # 目前沒有活動可買，不是錯誤也不是成功，用 OFF 表達中性語意。
                        notice=Notice(strings.GIVEAWAY_NONE_ACTIVE, StatusKind.OFF),
                    ),
                )
            return
        await interaction.response.send_modal(BuyTicketsModal(self.bot, giveaways))

    async def reroll(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction):
            await self._deny(interaction)
            return
        giveaways = await self.bot.giveaways.completed(interaction.guild_id)
        if not giveaways:
            # 同 buy()：沒有候選才走面板分支，有候選則送 Modal，所以只縮排這一段。
            async with panel_action(
                interaction, lambda note: giveaway_panel(self.bot, interaction, notice=note)
            ):
                await swap_panel(
                    interaction,
                    await giveaway_panel(
                        self.bot,
                        interaction,
                        notice=Notice(strings.GIVEAWAY_NONE_COMPLETED, StatusKind.OFF),
                    ),
                )
            return
        await interaction.response.send_modal(RerollModal(self.bot, giveaways))


async def giveaway_list_panel(
    bot: HoRoBot, interaction: discord.Interaction, *, notice: str | Notice | None = None
) -> GiveawayListPanel:
    giveaways = await bot.giveaways.active(interaction.guild_id, paid_only=True)

    async def back(target: discord.Interaction) -> None:
        await defer_update(target)
        await swap_panel(target, await giveaway_panel(bot, target))

    return GiveawayListPanel(bot, giveaways, notice=notice, back=back)


class GiveawayListPanel(PagedPanel):
    title = strings.GIVEAWAY_PAID_HEADER
    accent = discord.Colour.gold()
    page_size = 10

    def page_rows(self, items: list[Any]) -> Iterable[discord.ui.Item[Any]]:
        if not self.items:
            yield discord.ui.TextDisplay(strings.GIVEAWAY_PAID_EMPTY)
            return
        yield discord.ui.TextDisplay(
            "\n".join(
                f"`#{item.id}` **{item.prize}** — "
                f"{discord.utils.format_dt(aware_utc(item.ends_at), style='R')}"
                for item in items
            )
        )


class CreateGiveawayModal(discord.ui.Modal):
    def __init__(self, bot: HoRoBot) -> None:
        super().__init__(
            title=strings.GIVEAWAY_CREATE, timeout=300, custom_id="cs:giveaway:create:modal"
        )
        self.bot = bot
        self.prize = discord.ui.TextInput(max_length=300)
        self.winners = discord.ui.TextInput(default="1", max_length=2)
        self.duration = discord.ui.TextInput(placeholder="2h", max_length=12)
        self.price = discord.ui.TextInput(default="0", max_length=18)
        self.limit = discord.ui.TextInput(default="1", max_length=6)
        for text, component in (
            (strings.GIVEAWAY_PRIZE, self.prize),
            (strings.GIVEAWAY_WINNER_COUNT, self.winners),
            (strings.GIVEAWAY_DURATION, self.duration),
            (strings.GIVEAWAY_TICKET_PRICE, self.price),
            (strings.GIVEAWAY_PER_USER_LIMIT, self.limit),
        ):
            self.add_item(discord.ui.Label(text=text, component=component))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # 這裡是 Modal 送出後的處理，不是「開 Modal」本身，defer 不會擋到 send_modal。
        async with panel_action(
            interaction, lambda note: giveaway_panel(self.bot, interaction, notice=note)
        ):
            # Modal 的 interaction 不會經過開啟它的面板檢查，這道防線必須留著。
            if not is_admin(interaction):
                await swap_panel(
                    interaction,
                    await giveaway_panel(self.bot, interaction, notice=strings.ADMIN_ONLY),
                )
                return
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
                view=GiveawayMessageView(self.bot, giveaway),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await self.bot.giveaways.publish(giveaway.id, message.id)
            link = message_link(interaction.guild_id, message.channel.id, message.id)
            notice = Notice(
                strings.GIVEAWAY_CREATED.format(giveaway_id=giveaway.id)
                + strings.GIVEAWAY_LINK.format(link=link)
            )
            await swap_panel(
                interaction, await giveaway_panel(self.bot, interaction, notice=notice)
            )


class BuyTicketsModal(discord.ui.Modal):
    def __init__(self, bot: HoRoBot, giveaways: Sequence[Giveaway]) -> None:
        super().__init__(title=strings.GIVEAWAY_BUY, timeout=300, custom_id="cs:giveaway:buy:modal")
        self.bot = bot
        self.target = discord.ui.Select(
            placeholder=strings.GIVEAWAY_PICK_PLACEHOLDER, options=_options(giveaways)
        )
        self.quantity = discord.ui.TextInput(default="1", max_length=6)
        self.add_item(discord.ui.Label(text=strings.GIVEAWAY_ID, component=self.target))
        self.add_item(discord.ui.Label(text=strings.GIVEAWAY_QUANTITY, component=self.quantity))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        async with panel_action(
            interaction, lambda note: giveaway_panel(self.bot, interaction, notice=note)
        ):
            result = await self.bot.giveaways.enter(
                giveaway_id=int(self.target.values[0]),
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                quantity=int(str(self.quantity)),
                idempotency_key=str(interaction.id),
            )
            notice = Notice(strings.GIVEAWAY_ENTERED.format(weight=result.weight))
            await swap_panel(
                interaction, await giveaway_panel(self.bot, interaction, notice=notice)
            )


class RerollModal(discord.ui.Modal):
    def __init__(self, bot: HoRoBot, giveaways: Sequence[Giveaway]) -> None:
        super().__init__(
            title=strings.GIVEAWAY_REROLL, timeout=300, custom_id="cs:giveaway:reroll:modal"
        )
        self.bot = bot
        self.target = discord.ui.Select(
            placeholder=strings.GIVEAWAY_PICK_PLACEHOLDER, options=_options(giveaways)
        )
        self.add_item(discord.ui.Label(text=strings.GIVEAWAY_ID, component=self.target))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        async with panel_action(
            interaction, lambda note: giveaway_panel(self.bot, interaction, notice=note)
        ):
            if not is_admin(interaction):
                await swap_panel(
                    interaction,
                    await giveaway_panel(self.bot, interaction, notice=strings.ADMIN_ONLY),
                )
                return
            giveaway = await self.bot.giveaways.reroll(
                int(self.target.values[0]), admin_user_id=interaction.user.id
            )
            winners = "、".join(f"<@{user_id}>" for user_id in giveaway.winners)
            winners = winners or strings.GIVEAWAY_NO_REROLL_CANDIDATE
            if interaction.channel is not None:
                await interaction.channel.send(
                    strings.GIVEAWAY_REROLL_RESULT.format(id=giveaway.id, winners=winners),
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            notice = Notice(strings.SUCCESS)
            await swap_panel(
                interaction, await giveaway_panel(self.bot, interaction, notice=notice)
            )
