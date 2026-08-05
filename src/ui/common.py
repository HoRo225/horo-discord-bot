from __future__ import annotations

import logging
import uuid

import discord

from src import strings
from src.services.common import (
    ConflictError,
    DomainError,
    InsufficientFundsError,
    NotFoundError,
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


def error_notice(interaction: discord.Interaction, error: BaseException) -> str:
    """把例外翻成使用者看得懂的訊息，必要時記錄並產生追蹤碼。

    只負責產生文字，不負責送出；呼叫端決定要畫進面板還是另送訊息。
    """
    if isinstance(error, NotFoundError):
        return strings.NOT_FOUND
    if isinstance(error, InsufficientFundsError):
        return strings.INSUFFICIENT_BALANCE
    if isinstance(error, ValidationError):
        return strings.INVALID_INPUT.format(reason=str(error))
    if isinstance(error, (ConflictError, DomainError)):
        return str(error)
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
    return strings.GENERIC_ERROR.format(correlation_id=correlation_id)


async def handle_interaction_error(interaction: discord.Interaction, error: BaseException) -> None:
    """以獨立訊息回報錯誤。用於沒有面板可回寫的情境（例如公開訊息上的按鈕）。"""
    await send_ephemeral(interaction, error_notice(interaction, error))


async def discard_published_message(message: discord.Message) -> None:
    """撤回剛送出但沒能完成綁定的公告訊息。

    公告是先送 Discord 再寫回 DB 的，中間失敗會留下一則「看起來正常、實際上
    bot 完全不認得」的訊息。這裡盡力撤回，但吞掉自己的例外——補償失敗不該蓋掉
    原始錯誤，那才是使用者需要看到的原因。
    """
    try:
        await message.delete()
    except Exception:
        log.exception("撤回未完成發布的公告訊息失敗", extra={"message_id": message.id})


def is_admin(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions and permissions.manage_guild)


def message_link(guild_id: int, channel_id: int, message_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
