from __future__ import annotations

from datetime import timedelta
from typing import Any

import discord

from src import strings
from src.services.common import aware_utc
from src.ui.common import (
    defer_ephemeral,
    handle_interaction_error,
    is_admin,
    message_link,
    send_ephemeral,
)


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"是", "true", "yes", "y", "1"}:
        return True
    if normalized in {"否", "false", "no", "n", "0"}:
        return False
    raise ValueError(strings.POLL_MULTIPLE_INVALID)


async def can_create_poll(bot: Any, interaction: discord.Interaction) -> bool:
    if is_admin(interaction):
        return True
    settings = await bot.settings_service.get(interaction.guild_id)
    role_ids = {role.id for role in getattr(interaction.user, "roles", [])}
    return bool(role_ids.intersection(settings.poll_creator_role_ids))


class PollPanel(discord.ui.LayoutView):
    def __init__(self, bot: Any) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        create = discord.ui.Button(
            label=strings.POLL_CREATE,
            style=discord.ButtonStyle.primary,
            custom_id="cs:poll:create",
        )
        listing = discord.ui.Button(label=strings.POLL_LIST, custom_id="cs:poll:list")
        create.callback = self.create
        listing.callback = self.listing
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(strings.POLL_TITLE),
                discord.ui.ActionRow(create, listing),
                accent_colour=discord.Colour.blurple(),
            )
        )

    async def create(self, interaction: discord.Interaction) -> None:
        try:
            if not await can_create_poll(self.bot, interaction):
                await send_ephemeral(interaction, strings.POLL_FORBIDDEN)
                return
            await interaction.response.send_modal(CreatePollModal(self.bot))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def listing(self, interaction: discord.Interaction) -> None:
        try:
            await defer_ephemeral(interaction)
            polls = await self.bot.polls.active(interaction.guild_id)
            lines = []
            for poll in polls:
                ending = discord.utils.format_dt(aware_utc(poll.ends_at), style="R")
                lines.append(f"`#{poll.id}` **{poll.question}** — {ending}")
            await send_ephemeral(
                interaction,
                strings.POLL_ACTIVE_HEADER
                + "\n"
                + ("\n".join(lines) if lines else strings.POLL_ACTIVE_EMPTY),
            )
        except Exception as exc:
            await handle_interaction_error(interaction, exc)


class CreatePollModal(discord.ui.Modal):
    def __init__(self, bot: Any) -> None:
        super().__init__(title=strings.POLL_CREATE, custom_id="cs:poll:create:modal")
        self.bot = bot
        self.question = discord.ui.TextInput(label=strings.POLL_QUESTION, max_length=300)
        self.options = discord.ui.TextInput(
            label=strings.POLL_OPTIONS,
            style=discord.TextStyle.paragraph,
            min_length=3,
            max_length=600,
        )
        self.duration = discord.ui.TextInput(
            label=strings.POLL_DURATION_HOURS, default="24", max_length=8
        )
        self.multiple = discord.ui.TextInput(
            label=strings.POLL_MULTIPLE,
            default=strings.POLL_MULTIPLE_DEFAULT,
            max_length=5,
        )
        for item in (self.question, self.options, self.duration, self.multiple):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            if not await can_create_poll(self.bot, interaction):
                await send_ephemeral(interaction, strings.POLL_FORBIDDEN)
                return
            await defer_ephemeral(interaction)
            duration = timedelta(hours=float(str(self.duration).strip()))
            answers = [line.strip() for line in str(self.options).splitlines() if line.strip()]
            multiple = _parse_bool(str(self.multiple))
            poll_record = await self.bot.polls.create(
                guild_id=interaction.guild_id,
                channel_id=interaction.channel_id,
                created_by=interaction.user.id,
                question=str(self.question),
                answers=answers,
                duration=duration,
                multiple=multiple,
            )
            native_poll = discord.Poll(
                question=poll_record.question,
                duration=duration,
                multiple=multiple,
            )
            for answer in poll_record.answers:
                native_poll.add_answer(text=answer)
            if interaction.channel is None:
                raise RuntimeError(strings.CURRENT_CHANNEL_NOT_FOUND)
            message = await interaction.channel.send(
                poll=native_poll, allowed_mentions=discord.AllowedMentions.none()
            )
            await self.bot.polls.attach_message(poll_record.id, message.id)
            link = message_link(interaction.guild_id, message.channel.id, message.id)
            await send_ephemeral(
                interaction,
                strings.POLL_CREATED + strings.POLL_LINK.format(link=link),
            )
        except ValueError as exc:
            await send_ephemeral(interaction, strings.INVALID_INPUT.format(reason=str(exc)))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)
