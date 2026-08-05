from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import discord

from src import strings
from src.services.common import aware_utc
from src.ui.base import (
    PagedPanel,
    Panel,
    button,
    defer_update,
    panel_action,
    show_error,
    swap_panel,
)
from src.ui.common import discard_published_message, is_admin, message_link
from src.ui.status import Notice

if TYPE_CHECKING:
    from src.bot import HoRoBot


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"是", "true", "yes", "y", "1"}:
        return True
    if normalized in {"否", "false", "no", "n", "0"}:
        return False
    raise ValueError(strings.POLL_MULTIPLE_INVALID)


async def can_create_poll(bot: HoRoBot, interaction: discord.Interaction) -> bool:
    if is_admin(interaction):
        return True
    settings = await bot.settings_service.get(interaction.guild_id)
    role_ids = {role.id for role in getattr(interaction.user, "roles", [])}
    return bool(role_ids.intersection(settings.poll_creator_role_ids))


async def poll_panel(
    bot: HoRoBot, interaction: discord.Interaction, *, notice: str | Notice | None = None
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
        # 半 Modal 半面板：權限檢查與 send_modal 都可能拋錯，但 send_modal 必須是
        # 首個 response，不能整個包進 panel_action（它一進來就會 defer）。
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
        async with panel_action(
            interaction, lambda note: poll_panel(self.bot, interaction, notice=note)
        ):
            await swap_panel(interaction, await poll_list_panel(self.bot, interaction))


async def poll_list_panel(
    bot: HoRoBot,
    interaction: discord.Interaction,
    *,
    page: int = 0,
    notice: str | Notice | None = None,
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
    def __init__(self, bot: HoRoBot) -> None:
        super().__init__(title=strings.POLL_CREATE, timeout=300, custom_id="cs:poll:create:modal")
        self.bot = bot
        self.question = discord.ui.TextInput(max_length=300)
        self.options = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            min_length=3,
            max_length=600,
        )
        self.duration = discord.ui.TextInput(default="24", max_length=8)
        self.multiple = discord.ui.TextInput(
            default=strings.POLL_MULTIPLE_DEFAULT,
            max_length=5,
        )
        for text, component in (
            (strings.POLL_QUESTION, self.question),
            (strings.POLL_OPTIONS, self.options),
            (strings.POLL_DURATION_HOURS, self.duration),
            (strings.POLL_MULTIPLE, self.multiple),
        ):
            self.add_item(discord.ui.Label(text=text, component=component))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # 這裡是 Modal 送出後的處理，不是「開 Modal」本身，defer 不會擋到 send_modal。
        async with panel_action(
            interaction, lambda note: poll_panel(self.bot, interaction, notice=note)
        ):
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
            try:
                await self.bot.polls.publish(poll_record.id, message.id)
            except BaseException:
                # CancelledError 也要走補償；否則 DB rollback 後原生投票仍留在 Discord，
                # 使用者可繼續投票但背景結算永遠看不到它。
                await discard_published_message(message)
                raise
            link = message_link(interaction.guild_id, message.channel.id, message.id)
            notice = Notice(strings.POLL_CREATED + strings.POLL_LINK.format(link=link))
            await swap_panel(interaction, await poll_panel(self.bot, interaction, notice=notice))
