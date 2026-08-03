from __future__ import annotations

import logging
import uuid
from typing import Any

import discord

from src import strings
from src.services.common import (
    ConflictError,
    DomainError,
    InsufficientFundsError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)

log = logging.getLogger(__name__)


async def send_ephemeral(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    view: discord.ui.View | discord.ui.LayoutView | None = None,
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, view=view, ephemeral=True)
    else:
        await interaction.response.send_message(content, view=view, ephemeral=True)


async def defer_ephemeral(interaction: discord.Interaction) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)


async def handle_interaction_error(interaction: discord.Interaction, error: BaseException) -> None:
    if isinstance(error, NotFoundError):
        await send_ephemeral(interaction, strings.NOT_FOUND)
        return
    if isinstance(error, InsufficientFundsError):
        await send_ephemeral(interaction, strings.INSUFFICIENT_BALANCE)
        return
    if isinstance(error, PermissionDeniedError):
        await send_ephemeral(interaction, strings.ADMIN_ONLY)
        return
    if isinstance(error, ValidationError):
        await send_ephemeral(interaction, strings.INVALID_INPUT.format(reason=str(error)))
        return
    if isinstance(error, (ConflictError, DomainError)):
        await send_ephemeral(interaction, str(error))
        return
    correlation_id = uuid.uuid4().hex[:12]
    log.exception(
        "互動處理失敗",
        exc_info=error,
        extra={
            "correlation_id": correlation_id,
            "guild_id": interaction.guild_id,
            "user_id": interaction.user.id,
            "interaction_id": interaction.id,
        },
    )
    await send_ephemeral(interaction, strings.GENERIC_ERROR.format(correlation_id=correlation_id))


def is_admin(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions and permissions.manage_guild)


async def require_admin(interaction: discord.Interaction) -> bool:
    if interaction.guild_id is None:
        await send_ephemeral(interaction, strings.GUILD_ONLY)
        return False
    if not is_admin(interaction):
        await send_ephemeral(interaction, strings.ADMIN_ONLY)
        return False
    return True


def parse_user_id(value: str) -> int:
    cleaned = value.strip().strip("<@!>")
    if not cleaned.isdigit() or int(cleaned) <= 0:
        raise ValueError(strings.USER_ID_INVALID)
    return int(cleaned)


async def ensure_guild_member(interaction: discord.Interaction, user_id: int) -> discord.Member:
    if interaction.guild is None:
        raise ValueError(strings.GUILD_ONLY)
    member = interaction.guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await interaction.guild.fetch_member(user_id)
    except discord.NotFound as exc:
        raise ValueError(strings.MEMBER_NOT_FOUND) from exc


def message_link(guild_id: int, channel_id: int, message_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def bot_from_interaction(interaction: discord.Interaction) -> Any:
    return interaction.client
