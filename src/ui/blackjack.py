from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

import discord

from src import strings
from src.database.models import BlackjackGame
from src.services.blackjack import (
    TERMINAL_PHASES,
    BlackjackOperationResult,
    can_double,
    can_split,
    can_surrender,
    display_cards,
    hand_value,
    state_from_game,
)
from src.ui.base import Panel, button, defer_update, panel_action, swap_panel
from src.ui.common import (
    COMPENSATION_TIMEOUT_SECONDS,
    discard_published_message,
    handle_interaction_error,
    message_link,
)
from src.ui.status import Notice

if TYPE_CHECKING:
    from src.bot import HoRoBot

log = logging.getLogger(__name__)


RESULT_NAMES = {
    "win": strings.BLACKJACK_RESULT_WIN,
    "loss": strings.BLACKJACK_RESULT_LOSS,
    "push": strings.BLACKJACK_RESULT_PUSH,
    "blackjack": strings.BLACKJACK_RESULT_NATURAL,
    "surrender": strings.BLACKJACK_RESULT_SURRENDER,
}


def game_text(game: BlackjackGame) -> str:
    """把牌局狀態組成一段可放進 TextDisplay 的文字。"""
    terminal = game.phase in TERMINAL_PHASES
    dealer_cards = display_cards(game.dealer_cards, hide_second=not terminal)
    if terminal:
        dealer_line = f"{dealer_cards}（{hand_value(game.dealer_cards)[0]}）"
    else:
        dealer_line = dealer_cards
    lines = [strings.BLACKJACK_DEALER_LINE.format(cards=dealer_line)]

    result_hands = game.outcome.get("hands", []) if game.outcome else []
    for index, hand in enumerate(game.hands):
        result = ""
        if index < len(result_hands):
            key = result_hands[index]["result"]
            result = f"｜**{RESULT_NAMES.get(key, key)}**"
        lines.append(
            strings.BLACKJACK_HAND_LINE.format(
                marker="👉 " if index == game.active_hand and not terminal else "",
                number=index + 1,
                cards=display_cards(hand["cards"]),
                value=hand_value(hand["cards"])[0],
                bet=hand["bet"],
                result=result,
            )
        )

    if game.phase == "insurance":
        lines.append(strings.BLACKJACK_INSURANCE_OFFER)
    if game.phase == "refunded":
        lines.append(strings.BLACKJACK_REFUND_LINE.format(amount=game.outcome.get("refund", 0)))
    elif terminal and game.outcome:
        lines.append(
            strings.BLACKJACK_SETTLEMENT_LINE.format(
                staked=game.outcome.get("staked", 0),
                credit=game.outcome.get("credit", 0),
                net=game.outcome.get("net", 0),
            )
        )
    # 原本 Embed 的 footer，在 V2 改用 Discord 的 subtext 語法呈現。
    lines.append("-# " + strings.BLACKJACK_FOOTER.format(user_id=game.user_id, game_id=game.id[:8]))
    return "\n".join(lines)


class BlackjackGameView(discord.ui.LayoutView):
    """頻道內的牌桌訊息。

    牌面與操作按鈕都在這個 view 裡，所以**結算後不能傳 view=None**，
    那會讓整張牌桌畫面消失。改由本類別自行決定終局時不放操作按鈕。
    """

    def __init__(self, bot: HoRoBot, game: BlackjackGame | None = None) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        items: list[discord.ui.Item[Any]] = [discord.ui.TextDisplay(strings.BLACKJACK_EMBED_TITLE)]
        if game is not None:
            items.append(discord.ui.TextDisplay(game_text(game)))
        terminal = game is not None and game.phase in TERMINAL_PHASES
        if not terminal:
            items.append(discord.ui.Separator())
            items.extend(self._action_rows(game))
        self.add_item(
            discord.ui.Container(
                *items,
                accent_colour=(discord.Colour.green() if terminal else discord.Colour.dark_teal()),
            )
        )

    def _action_rows(self, game: BlackjackGame | None) -> Iterable[discord.ui.ActionRow]:
        state = state_from_game(game) if game is not None else None
        phase = game.phase if game is not None else "unknown"

        def blocked(kind: str) -> bool:
            if game is None:
                return False
            if kind in {"insurance", "no_insurance"}:
                return phase != "insurance"
            if phase != "playing":
                return True
            if kind == "double":
                return not can_double(state)
            if kind == "split":
                return not can_split(state)
            if kind == "surrender":
                return not can_surrender(state)
            return False

        yield discord.ui.ActionRow(
            button(
                strings.BLACKJACK_HIT,
                "cs:blackjack:hit",
                self.hit,
                style=discord.ButtonStyle.primary,
                disabled=blocked("hit"),
            ),
            button(
                strings.BLACKJACK_STAND,
                "cs:blackjack:stand",
                self.stand,
                disabled=blocked("stand"),
            ),
            button(
                strings.BLACKJACK_DOUBLE,
                "cs:blackjack:double",
                self.double,
                style=discord.ButtonStyle.success,
                disabled=blocked("double"),
            ),
            button(
                strings.BLACKJACK_SPLIT,
                "cs:blackjack:split",
                self.split,
                style=discord.ButtonStyle.success,
                disabled=blocked("split"),
            ),
            button(
                strings.BLACKJACK_SURRENDER,
                "cs:blackjack:surrender",
                self.surrender,
                style=discord.ButtonStyle.danger,
                disabled=blocked("surrender"),
            ),
        )
        yield discord.ui.ActionRow(
            button(
                strings.BLACKJACK_INSURANCE,
                "cs:blackjack:insurance",
                self.insurance,
                style=discord.ButtonStyle.success,
                disabled=blocked("insurance"),
            ),
            button(
                strings.BLACKJACK_NO_INSURANCE,
                "cs:blackjack:no_insurance",
                self.no_insurance,
                disabled=blocked("no_insurance"),
            ),
        )

    async def _game(self, interaction: discord.Interaction) -> BlackjackGame | None:
        if interaction.message is None:
            return None
        return await self.bot.blackjack.by_message(interaction.message.id)

    async def _apply(self, interaction: discord.Interaction, result: BlackjackOperationResult):
        await interaction.message.edit(
            content=None,
            embeds=[],
            attachments=[],
            view=BlackjackGameView(self.bot, result.game),
        )

    async def _act(self, interaction: discord.Interaction, action: str) -> None:
        # 公開牌桌訊息上的按鈕沒有可重建的私人面板，錯誤只能改用獨立訊息回報。
        try:
            await defer_update(interaction)
            game = await self._game(interaction)
            if game is None:
                await interaction.followup.send(strings.BLACKJACK_NO_GAME, ephemeral=True)
                return
            result = await self.bot.blackjack.action(
                game_id=game.id,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                action=action,
                idempotency_key=str(interaction.id),
            )
            await self._apply(interaction, result)
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def _insurance(self, interaction: discord.Interaction, take: bool) -> None:
        try:
            await defer_update(interaction)
            game = await self._game(interaction)
            if game is None:
                await interaction.followup.send(strings.BLACKJACK_NO_GAME, ephemeral=True)
                return
            result = await self.bot.blackjack.insurance(
                game_id=game.id,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                take=take,
                idempotency_key=str(interaction.id),
            )
            await self._apply(interaction, result)
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def hit(self, interaction: discord.Interaction) -> None:
        await self._act(interaction, "hit")

    async def stand(self, interaction: discord.Interaction) -> None:
        await self._act(interaction, "stand")

    async def double(self, interaction: discord.Interaction) -> None:
        await self._act(interaction, "double")

    async def split(self, interaction: discord.Interaction) -> None:
        await self._act(interaction, "split")

    async def surrender(self, interaction: discord.Interaction) -> None:
        await self._act(interaction, "surrender")

    async def insurance(self, interaction: discord.Interaction) -> None:
        await self._insurance(interaction, True)

    async def no_insurance(self, interaction: discord.Interaction) -> None:
        await self._insurance(interaction, False)


async def blackjack_panel(
    bot: HoRoBot, interaction: discord.Interaction, *, notice: str | Notice | None = None
) -> BlackjackPanel:
    return BlackjackPanel(bot, notice=notice)


class BlackjackPanel(Panel):
    title = strings.BLACKJACK_TITLE
    body = strings.BLACKJACK_RULES
    accent = discord.Colour.dark_teal()

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        yield discord.ui.Separator()
        yield discord.ui.ActionRow(
            *(
                button(
                    strings.BLACKJACK_QUICK_BET.format(amount=amount),
                    f"cs:blackjack:bet:{amount}",
                    self._quick(amount),
                    style=discord.ButtonStyle.primary,
                )
                for amount in (10, 100, 1_000)
            )
        )
        yield discord.ui.ActionRow(
            button(strings.BLACKJACK_CUSTOM_BET, "cs:blackjack:custom", self.custom),
            button(strings.BLACKJACK_STATS, "cs:blackjack:stats", self.stats, emoji="📈"),
        )

    def _quick(self, amount: int):
        async def callback(interaction: discord.Interaction) -> None:
            await start_game(self.bot, interaction, amount)

        return callback

    async def custom(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CustomBetModal(self.bot))

    async def stats(self, interaction: discord.Interaction) -> None:
        async with panel_action(
            interaction, lambda note: blackjack_panel(self.bot, interaction, notice=note)
        ):
            stats = await self.bot.blackjack.stats(interaction.guild_id, interaction.user.id)
            # 純戰績展示，不是操作成功/失敗的回饋，維持原樣文字、不套 Notice 徽章。
            notice = (
                strings.BLACKJACK_NO_STATS
                if stats is None
                else strings.BLACKJACK_STATS_TEXT.format(
                    wins=stats.wins,
                    losses=stats.losses,
                    pushes=stats.pushes,
                    blackjacks=stats.blackjacks,
                    wagered=stats.total_wagered,
                    won=stats.total_won,
                )
            )
            await swap_panel(
                interaction, await blackjack_panel(self.bot, interaction, notice=notice)
            )


class CustomBetModal(discord.ui.Modal):
    def __init__(self, bot: HoRoBot) -> None:
        super().__init__(
            title=strings.BLACKJACK_CUSTOM_BET, timeout=300, custom_id="cs:blackjack:bet:modal"
        )
        self.bot = bot
        self.amount = discord.ui.TextInput(placeholder="100", max_length=18)
        self.add_item(discord.ui.Label(text=strings.BLACKJACK_BET_AMOUNT, component=self.amount))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # 這裡是 Modal 送出後的處理，不是「開 Modal」本身，defer 不會擋到 send_modal；
        # 金額解析失敗會被 panel_action 的 ValueError 分支接住，行為與原本一致。
        async with panel_action(
            interaction, lambda note: blackjack_panel(self.bot, interaction, notice=note)
        ):
            amount = int(str(self.amount).strip())
            await start_game(self.bot, interaction, amount)


async def _refund_unpublished_game(bot: HoRoBot, game_id: str) -> None:
    """盡力退款，但補償失敗不可蓋掉原始 send/attach/cancellation 例外。

    與 discard_published_message 同理用 shield 包住：進入補償時工作常常已被取消
    一次，裸 await 會被第二次 cancellation 打斷，錢就卡在已扣未退。退款失敗時
    phase 仍非終局，30 秒後背景 recovery loop 會補上。
    """
    try:
        await asyncio.wait_for(
            asyncio.shield(bot.blackjack.refund_missing_message(game_id)),
            timeout=COMPENSATION_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        log.warning("回退未發布的 21 點牌局被取消", extra={"game_id": game_id})
    except Exception:
        log.exception("回退未發布的 21 點牌局失敗", extra={"game_id": game_id})


async def start_game(bot: HoRoBot, interaction: discord.Interaction, amount: int) -> None:
    async with panel_action(
        interaction, lambda note: blackjack_panel(bot, interaction, notice=note)
    ):
        result = await bot.blackjack.start(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            channel_id=interaction.channel_id,
            bet=amount,
            idempotency_key=str(interaction.id),
        )
        message: discord.Message | None = None
        try:
            if interaction.channel is None:
                raise RuntimeError(strings.CURRENT_CHANNEL_NOT_FOUND)
            message = await interaction.channel.send(
                view=BlackjackGameView(bot, result.game),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await bot.blackjack.attach_message(result.game.id, message.id)
        except BaseException:
            # start() 已經扣款並建立 game。任何後續失敗（包含 CancelledError）都要
            # 退款，若訊息已送出也要撤回 ghost table。
            #
            # 順序很重要：先撤訊息再退款。退款會把 phase 設成 refunded，那一刻起
            # 這局就脫離 recoverable()，背景 recovery loop 再也不會碰它——此時若
            # 撤訊息才失敗，帶按鈕的 ghost table 就永久留在頻道上沒人清。反過來
            # 先撤訊息、退款才失敗的話，phase 仍非終局且 message_id 為 NULL，
            # 30 秒後 recovery loop 會補上退款。
            if message is not None:
                await discard_published_message(message)
            await _refund_unpublished_game(bot, result.game.id)
            raise
        link = message_link(interaction.guild_id, message.channel.id, message.id)
        notice = Notice(strings.BLACKJACK_GAME_CREATED.format(link=link))
        await swap_panel(interaction, await blackjack_panel(bot, interaction, notice=notice))
