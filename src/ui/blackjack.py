from __future__ import annotations

from typing import Any

import discord

from src import strings
from src.database.models import BlackjackGame
from src.services.blackjack import (
    BlackjackOperationResult,
    can_double,
    can_split,
    can_surrender,
    display_cards,
    hand_value,
    state_from_game,
)
from src.ui.common import (
    defer_ephemeral,
    handle_interaction_error,
    message_link,
    send_ephemeral,
)


def game_embed(game: BlackjackGame) -> discord.Embed:
    terminal = game.phase in {"settled", "refunded"}
    dealer_cards = display_cards(game.dealer_cards, hide_second=not terminal)
    if terminal:
        dealer_value = hand_value(game.dealer_cards)[0]
        dealer_line = f"{dealer_cards}（{dealer_value}）"
    else:
        dealer_line = dealer_cards
    lines = [strings.BLACKJACK_DEALER_LINE.format(cards=dealer_line)]
    result_hands = game.outcome.get("hands", []) if game.outcome else []
    result_names = {
        "win": strings.BLACKJACK_RESULT_WIN,
        "loss": strings.BLACKJACK_RESULT_LOSS,
        "push": strings.BLACKJACK_RESULT_PUSH,
        "blackjack": strings.BLACKJACK_RESULT_NATURAL,
        "surrender": strings.BLACKJACK_RESULT_SURRENDER,
    }
    for index, hand in enumerate(game.hands):
        value = hand_value(hand["cards"])[0]
        marker = "👉 " if index == game.active_hand and not terminal else ""
        result = ""
        if index < len(result_hands):
            result_key = result_hands[index]["result"]
            result = f"｜**{result_names.get(result_key, result_key)}**"
        lines.append(
            strings.BLACKJACK_HAND_LINE.format(
                marker=marker,
                number=index + 1,
                cards=display_cards(hand["cards"]),
                value=value,
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
    embed = discord.Embed(
        title=strings.BLACKJACK_EMBED_TITLE,
        description="\n".join(lines),
        colour=discord.Colour.dark_teal() if not terminal else discord.Colour.green(),
    )
    embed.set_footer(
        text=strings.BLACKJACK_FOOTER.format(user_id=game.user_id, game_id=game.id[:8])
    )
    return embed


class BlackjackPanel(discord.ui.LayoutView):
    def __init__(self, bot: Any) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        buttons: list[discord.ui.Button] = []
        for amount in (10, 100, 1_000):
            button = discord.ui.Button(
                label=strings.BLACKJACK_QUICK_BET.format(amount=amount),
                style=discord.ButtonStyle.primary,
                custom_id=f"cs:blackjack:bet:{amount}",
            )
            button.callback = self._quick_callback(amount)
            buttons.append(button)
        custom = discord.ui.Button(
            label=strings.BLACKJACK_CUSTOM_BET, custom_id="cs:blackjack:custom"
        )
        stats = discord.ui.Button(label=strings.BLACKJACK_STATS, custom_id="cs:blackjack:stats")
        custom.callback = self.custom
        stats.callback = self.stats
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(strings.BLACKJACK_TITLE),
                discord.ui.TextDisplay(strings.BLACKJACK_RULES),
                discord.ui.ActionRow(*buttons),
                discord.ui.ActionRow(custom, stats),
                accent_colour=discord.Colour.dark_teal(),
            )
        )

    def _quick_callback(self, amount: int):
        async def callback(interaction: discord.Interaction) -> None:
            await start_game(self.bot, interaction, amount)

        return callback

    async def custom(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CustomBetModal(self.bot))

    async def stats(self, interaction: discord.Interaction) -> None:
        try:
            await defer_ephemeral(interaction)
            stats = await self.bot.blackjack.stats(interaction.guild_id, interaction.user.id)
            if stats is None:
                text = strings.BLACKJACK_NO_STATS
            else:
                text = strings.BLACKJACK_STATS_TEXT.format(
                    wins=stats.wins,
                    losses=stats.losses,
                    pushes=stats.pushes,
                    blackjacks=stats.blackjacks,
                    wagered=stats.total_wagered,
                    won=stats.total_won,
                )
            await send_ephemeral(interaction, text)
        except Exception as exc:
            await handle_interaction_error(interaction, exc)


class CustomBetModal(discord.ui.Modal):
    def __init__(self, bot: Any) -> None:
        super().__init__(title=strings.BLACKJACK_CUSTOM_BET, custom_id="cs:blackjack:bet:modal")
        self.bot = bot
        self.amount = discord.ui.TextInput(
            label=strings.BLACKJACK_BET_AMOUNT, placeholder="100", max_length=18
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            amount = int(str(self.amount).strip())
        except ValueError as exc:
            await send_ephemeral(interaction, strings.INVALID_INPUT.format(reason=str(exc)))
            return
        await start_game(self.bot, interaction, amount)


async def start_game(bot: Any, interaction: discord.Interaction, amount: int) -> None:
    try:
        await defer_ephemeral(interaction)
        result = await bot.blackjack.start(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            channel_id=interaction.channel_id,
            bet=amount,
            idempotency_key=str(interaction.id),
        )
        if interaction.channel is None:
            raise RuntimeError(strings.CURRENT_CHANNEL_NOT_FOUND)
        view = None if result.game.phase == "settled" else BlackjackActionView(bot, result.game)
        try:
            message = await interaction.channel.send(
                embed=game_embed(result.game),
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await bot.blackjack.attach_message(result.game.id, message.id)
        except Exception:
            await bot.blackjack.refund_missing_message(result.game.id)
            raise
        link = message_link(interaction.guild_id, message.channel.id, message.id)
        await send_ephemeral(interaction, strings.BLACKJACK_GAME_CREATED.format(link=link))
    except Exception as exc:
        await handle_interaction_error(interaction, exc)


class BlackjackActionView(discord.ui.View):
    def __init__(self, bot: Any, game: BlackjackGame | None = None) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        state = state_from_game(game) if game is not None else None
        phase = game.phase if game is not None else "unknown"
        definitions = [
            (strings.BLACKJACK_HIT, "cs:blackjack:hit", discord.ButtonStyle.primary, self.hit),
            (
                strings.BLACKJACK_STAND,
                "cs:blackjack:stand",
                discord.ButtonStyle.secondary,
                self.stand,
            ),
            (
                strings.BLACKJACK_DOUBLE,
                "cs:blackjack:double",
                discord.ButtonStyle.success,
                self.double,
            ),
            (
                strings.BLACKJACK_SPLIT,
                "cs:blackjack:split",
                discord.ButtonStyle.success,
                self.split,
            ),
            (
                strings.BLACKJACK_SURRENDER,
                "cs:blackjack:surrender",
                discord.ButtonStyle.danger,
                self.surrender,
            ),
            (
                strings.BLACKJACK_INSURANCE,
                "cs:blackjack:insurance",
                discord.ButtonStyle.success,
                self.insurance,
            ),
            (
                strings.BLACKJACK_NO_INSURANCE,
                "cs:blackjack:no_insurance",
                discord.ButtonStyle.secondary,
                self.no_insurance,
            ),
        ]
        for label, custom_id, style, callback in definitions:
            disabled = False
            if game is not None:
                if (
                    custom_id.endswith("insurance")
                    and not custom_id.endswith("no_insurance")
                    or custom_id.endswith("no_insurance")
                ):
                    disabled = phase != "insurance"
                elif phase != "playing":
                    disabled = True
                elif custom_id.endswith("double"):
                    disabled = not can_double(state)
                elif custom_id.endswith("split"):
                    disabled = not can_split(state)
                elif custom_id.endswith("surrender"):
                    disabled = not can_surrender(state)
            button = discord.ui.Button(
                label=label, style=style, custom_id=custom_id, disabled=disabled
            )
            button.callback = callback
            self.add_item(button)

    async def _game(self, interaction: discord.Interaction) -> BlackjackGame | None:
        if interaction.message is None:
            return None
        return await self.bot.blackjack.by_message(interaction.message.id)

    async def _act(self, interaction: discord.Interaction, action: str) -> None:
        try:
            await defer_ephemeral(interaction)
            game = await self._game(interaction)
            if game is None:
                await send_ephemeral(interaction, strings.BLACKJACK_NO_GAME)
                return
            result: BlackjackOperationResult = await self.bot.blackjack.action(
                game_id=game.id,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                action=action,
                idempotency_key=str(interaction.id),
            )
            await interaction.message.edit(
                embed=game_embed(result.game),
                view=(
                    None
                    if result.game.phase == "settled"
                    else BlackjackActionView(self.bot, result.game)
                ),
            )
            await send_ephemeral(interaction, strings.BLACKJACK_ACTION_DONE)
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def _insurance(self, interaction: discord.Interaction, take: bool) -> None:
        try:
            await defer_ephemeral(interaction)
            game = await self._game(interaction)
            if game is None:
                await send_ephemeral(interaction, strings.BLACKJACK_NO_GAME)
                return
            result = await self.bot.blackjack.insurance(
                game_id=game.id,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                take=take,
                idempotency_key=str(interaction.id),
            )
            await interaction.message.edit(
                embed=game_embed(result.game),
                view=(
                    None
                    if result.game.phase == "settled"
                    else BlackjackActionView(self.bot, result.game)
                ),
            )
            await send_ephemeral(interaction, strings.BLACKJACK_ACTION_DONE)
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
