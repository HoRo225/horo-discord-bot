from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from typing import Any

import discord

from src import strings
from src.services.common import aware_utc
from src.ui.base import (
    PagedPanel,
    Panel,
    button,
    defer_update,
    show_error,
    swap_panel,
)
from src.ui.common import is_admin, message_link


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


async def poll_panel(
    bot: Any, interaction: discord.Interaction, *, notice: str | None = None
) -> PollPanel:
    """組出投票主面板。目前不需要查資料庫，但維持 async 工廠以配合返回鈕的呼叫慣例。"""
    return PollPanel(bot, notice=notice)


class PollPanel(Panel):
    title = strings.POLL_TITLE
    accent = discord.Colour.blurple()

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        yield discord.ui.ActionRow(
            button(
                strings.POLL_CREATE,
                "cs:poll:create",
                self.create,
                style=discord.ButtonStyle.primary,
            ),
            button(strings.POLL_LIST, "cs:poll:list", self.listing),
        )

    async def create(self, interaction: discord.Interaction) -> None:
        try:
            if not await can_create_poll(self.bot, interaction):
                await defer_update(interaction)
                await swap_panel(
                    interaction,
                    await poll_panel(self.bot, interaction, notice=strings.POLL_FORBIDDEN),
                )
                return
            await interaction.response.send_modal(CreatePollModal(self.bot))
        except Exception as exc:
            await show_error(
                interaction, exc, lambda note: poll_panel(self.bot, interaction, notice=note)
            )

    async def listing(self, interaction: discord.Interaction) -> None:
        try:
            await defer_update(interaction)
            await swap_panel(interaction, await poll_list_panel(self.bot, interaction))
        except Exception as exc:
            await show_error(
                interaction, exc, lambda note: poll_panel(self.bot, interaction, notice=note)
            )


async def poll_list_panel(
    bot: Any,
    interaction: discord.Interaction,
    *,
    page: int = 0,
    notice: str | None = None,
) -> PollListPanel:
    polls = await bot.polls.active(interaction.guild_id)

    async def back(target: discord.Interaction) -> None:
        await defer_update(target)
        await swap_panel(target, await poll_panel(bot, target))

    return PollListPanel(bot, polls, page=page, notice=notice, back=back)


class PollListPanel(PagedPanel):
    title = strings.POLL_ACTIVE_HEADER
    accent = discord.Colour.blurple()
    page_size = 10

    def page_rows(self, items: list[Any]) -> Iterable[discord.ui.Item[Any]]:
        if not self.items:
            yield discord.ui.TextDisplay(strings.POLL_ACTIVE_EMPTY)
            return
        lines = []
        for poll in items:
            ending = discord.utils.format_dt(aware_utc(poll.ends_at), style="R")
            lines.append(f"`#{poll.id}` **{poll.question}** — {ending}")
        yield discord.ui.TextDisplay("\n".join(lines))


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
            await defer_update(interaction)
            if not await can_create_poll(self.bot, interaction):
                await swap_panel(
                    interaction,
                    await poll_panel(self.bot, interaction, notice=strings.POLL_FORBIDDEN),
                )
                return
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
            notice = strings.POLL_CREATED + strings.POLL_LINK.format(link=link)
            await swap_panel(interaction, await poll_panel(self.bot, interaction, notice=notice))
        except ValueError as exc:
            await swap_panel(
                interaction,
                await poll_panel(
                    self.bot,
                    interaction,
                    notice=strings.INVALID_INPUT.format(reason=str(exc)),
                ),
            )
        except Exception as exc:
            await show_error(
                interaction, exc, lambda note: poll_panel(self.bot, interaction, notice=note)
            )
