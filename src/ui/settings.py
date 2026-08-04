from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import discord

from src import strings
from src.database.models import GuildSettings
from src.ui.base import (
    POSTABLE_CHANNEL_TYPES,
    PagedPanel,
    Panel,
    button,
    defer_update,
    section,
    show_error,
    swap_panel,
)
from src.ui.common import is_admin


def _mention(channel_id: int | None) -> str:
    return f"<#{channel_id}>" if channel_id else strings.SETTING_NOT_CONFIGURED


def _roles(role_ids: Sequence[int]) -> str:
    return "、".join(f"<@&{role_id}>" for role_id in role_ids) or strings.SETTING_NOT_CONFIGURED


def _channels(channel_ids: Sequence[int]) -> str:
    return "、".join(f"<#{cid}>" for cid in channel_ids) or strings.SETTING_NOT_CONFIGURED


def _defaults(ids: Sequence[int]) -> list[discord.Object]:
    """把已儲存的 ID 轉成選擇器的預設值，讓使用者一開啟就看到現況。"""
    return [discord.Object(id=item) for item in ids]


async def settings_panel(
    bot: Any, interaction: discord.Interaction, *, notice: str | None = None
) -> SettingsPanel:
    settings = await bot.settings_service.get(interaction.guild_id)
    return SettingsPanel(bot, settings, notice=notice)


class SettingsPanel(Panel):
    title = f"# ⚙️ {strings.SETTINGS_TITLE}"
    accent = discord.Colour.from_rgb(180, 150, 255)

    def __init__(self, bot: Any, settings: GuildSettings, **kwargs: Any) -> None:
        self.settings = settings
        super().__init__(bot, **kwargs)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not is_admin(interaction):
            await defer_update(interaction)
            await swap_panel(
                interaction,
                SettingsPanel(self.bot, self.settings, notice=strings.ADMIN_ONLY),
            )
            return False
        return True

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        current = self.settings
        model = (
            current.ai_model
            or getattr(getattr(self.bot, "settings", None), "ai_default_model", "")
            or strings.SETTING_NOT_CONFIGURED
        )
        yield section(
            strings.SETTINGS_WELCOME_SUMMARY.format(
                title=strings.SETTINGS_WELCOME,
                welcome=_mention(current.welcome_channel_id),
                goodbye=_mention(current.goodbye_channel_id),
                log=_mention(current.log_channel_id),
            ),
            button(strings.SETTINGS_EDIT, "cs:settings:welcome", self.welcome),
        )
        yield discord.ui.Separator()
        yield section(
            strings.SETTINGS_ECONOMY_SUMMARY.format(
                title=strings.SETTINGS_ECONOMY,
                currency=current.currency_name,
                daily=current.daily_amount,
                minimum=current.blackjack_min_bet,
                maximum=current.blackjack_max_bet,
            ),
            button(strings.SETTINGS_EDIT, "cs:settings:economy", self.economy),
        )
        yield discord.ui.Separator()
        yield section(
            strings.SETTINGS_POLL_SUMMARY.format(
                title=strings.SETTINGS_POLL, roles=_roles(current.poll_creator_role_ids)
            ),
            button(strings.SETTINGS_EDIT, "cs:settings:poll", self.poll),
        )
        yield discord.ui.Separator()
        yield section(
            strings.SETTINGS_AI_SUMMARY.format(
                title=strings.SETTINGS_AI,
                model=model,
                channels=_channels(current.ai_channel_ids),
                roles=_roles(current.ai_role_ids),
            ),
            button(strings.SETTINGS_EDIT, "cs:settings:ai", self.ai),
        )
        yield discord.ui.Separator()
        yield discord.ui.ActionRow(
            button(
                strings.SETTINGS_LOG_TOGGLES,
                "cs:settings:log_toggles",
                self.log_toggles,
                emoji="📜",
            ),
            button(
                strings.SETTINGS_MODEL,
                "cs:settings:model",
                self.models,
                style=discord.ButtonStyle.primary,
                emoji="🤖",
            ),
        )

    async def welcome(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(WelcomeLogModal(self.bot, self.settings))

    async def economy(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(EconomySettingsModal(self.bot, self.settings))

    async def poll(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(PollSettingsModal(self.bot, self.settings))

    async def ai(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(AISettingsModal(self.bot, self.settings))

    async def log_toggles(self, interaction: discord.Interaction) -> None:
        try:
            await defer_update(interaction)
            await swap_panel(interaction, await log_toggle_panel(self.bot, interaction))
        except Exception as exc:
            await show_error(
                interaction, exc, lambda note: settings_panel(self.bot, interaction, notice=note)
            )

    async def models(self, interaction: discord.Interaction) -> None:
        try:
            await defer_update(interaction)
            await swap_panel(interaction, await model_panel(self.bot, interaction))
        except Exception as exc:
            await show_error(
                interaction, exc, lambda note: settings_panel(self.bot, interaction, notice=note)
            )


class SettingsModal(discord.ui.Modal):
    """設定類 Modal 的共同收尾：權限二次檢查、寫入、就地更新面板。"""

    def __init__(self, bot: Any, settings: GuildSettings, *, title: str, custom_id: str) -> None:
        super().__init__(title=title, timeout=300, custom_id=custom_id)
        self.bot = bot
        self.settings = settings

    def values(self) -> dict[str, Any]:
        raise NotImplementedError

    action = "settings"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await defer_update(interaction)
            # Modal 的 interaction 不會經過開啟它的面板檢查，這道防線必須留著。
            if not is_admin(interaction):
                await swap_panel(
                    interaction,
                    await settings_panel(self.bot, interaction, notice=strings.ADMIN_ONLY),
                )
                return
            await self.bot.settings_service.update(
                interaction.guild_id,
                interaction.user.id,
                action=self.action,
                values=self.values(),
            )
            await swap_panel(
                interaction,
                await settings_panel(self.bot, interaction, notice=strings.SUCCESS),
            )
        except ValueError as exc:
            await swap_panel(
                interaction,
                await settings_panel(
                    self.bot,
                    interaction,
                    notice=strings.INVALID_INPUT.format(reason=str(exc)),
                ),
            )
        except Exception as exc:
            await show_error(
                interaction, exc, lambda note: settings_panel(self.bot, interaction, notice=note)
            )


class WelcomeLogModal(SettingsModal):
    action = "settings_welcome_log"

    def __init__(self, bot: Any, settings: GuildSettings) -> None:
        super().__init__(
            bot,
            settings,
            title=strings.SETTINGS_WELCOME,
            custom_id="cs:settings:welcome:modal",
        )
        self.welcome_channel = discord.ui.ChannelSelect(
            channel_types=list(POSTABLE_CHANNEL_TYPES),
            required=False,
            default_values=_defaults(
                [settings.welcome_channel_id] if settings.welcome_channel_id else []
            ),
        )
        self.goodbye_channel = discord.ui.ChannelSelect(
            channel_types=list(POSTABLE_CHANNEL_TYPES),
            required=False,
            default_values=_defaults(
                [settings.goodbye_channel_id] if settings.goodbye_channel_id else []
            ),
        )
        self.log_channel = discord.ui.ChannelSelect(
            channel_types=list(POSTABLE_CHANNEL_TYPES),
            required=False,
            default_values=_defaults([settings.log_channel_id] if settings.log_channel_id else []),
        )
        self.welcome_template = discord.ui.TextInput(
            default=settings.welcome_template, style=discord.TextStyle.paragraph, max_length=1_500
        )
        self.goodbye_template = discord.ui.TextInput(
            default=settings.goodbye_template, style=discord.TextStyle.paragraph, max_length=1_500
        )
        for text, component in (
            (strings.WELCOME_CHANNEL_ID, self.welcome_channel),
            (strings.GOODBYE_CHANNEL_ID, self.goodbye_channel),
            (strings.LOG_CHANNEL_ID, self.log_channel),
            (strings.WELCOME_TEMPLATE, self.welcome_template),
            (strings.GOODBYE_TEMPLATE, self.goodbye_template),
        ):
            self.add_item(discord.ui.Label(text=text, component=component))

    @staticmethod
    def _first(select: discord.ui.ChannelSelect) -> int | None:
        return select.values[0].id if select.values else None

    def values(self) -> dict[str, Any]:
        return {
            "welcome_channel_id": self._first(self.welcome_channel),
            "goodbye_channel_id": self._first(self.goodbye_channel),
            "log_channel_id": self._first(self.log_channel),
            "welcome_template": str(self.welcome_template),
            "goodbye_template": str(self.goodbye_template),
        }


class EconomySettingsModal(SettingsModal):
    action = "settings_economy_blackjack"

    def __init__(self, bot: Any, settings: GuildSettings) -> None:
        super().__init__(
            bot,
            settings,
            title=strings.SETTINGS_ECONOMY,
            custom_id="cs:settings:economy:modal",
        )
        self.currency = discord.ui.TextInput(default=settings.currency_name, max_length=50)
        self.daily = discord.ui.TextInput(default=str(settings.daily_amount), max_length=18)
        self.minimum = discord.ui.TextInput(default=str(settings.blackjack_min_bet), max_length=18)
        self.maximum = discord.ui.TextInput(default=str(settings.blackjack_max_bet), max_length=18)
        for text, component in (
            (strings.CURRENCY_NAME, self.currency),
            (strings.DAILY_AMOUNT, self.daily),
            (strings.BLACKJACK_MIN_BET, self.minimum),
            (strings.BLACKJACK_MAX_BET, self.maximum),
        ):
            self.add_item(discord.ui.Label(text=text, component=component))

    def values(self) -> dict[str, Any]:
        return {
            "currency_name": str(self.currency),
            "daily_amount": int(str(self.daily)),
            "blackjack_min_bet": int(str(self.minimum)),
            "blackjack_max_bet": int(str(self.maximum)),
        }


class PollSettingsModal(SettingsModal):
    action = "settings_poll_roles"

    def __init__(self, bot: Any, settings: GuildSettings) -> None:
        super().__init__(
            bot, settings, title=strings.SETTINGS_POLL, custom_id="cs:settings:poll:modal"
        )
        self.roles = discord.ui.RoleSelect(
            min_values=0,
            max_values=25,
            required=False,
            default_values=_defaults(settings.poll_creator_role_ids),
        )
        self.add_item(discord.ui.Label(text=strings.POLL_ROLE_IDS, component=self.roles))

    def values(self) -> dict[str, Any]:
        return {"poll_creator_role_ids": [role.id for role in self.roles.values]}


class AISettingsModal(SettingsModal):
    action = "settings_ai"

    def __init__(self, bot: Any, settings: GuildSettings) -> None:
        super().__init__(bot, settings, title=strings.SETTINGS_AI, custom_id="cs:settings:ai:modal")
        self.channels = discord.ui.ChannelSelect(
            channel_types=list(POSTABLE_CHANNEL_TYPES),
            min_values=0,
            max_values=25,
            required=False,
            default_values=_defaults(settings.ai_channel_ids),
        )
        self.roles = discord.ui.RoleSelect(
            min_values=0,
            max_values=25,
            required=False,
            default_values=_defaults(settings.ai_role_ids),
        )
        self.model = discord.ui.TextInput(
            default=settings.ai_model or "", required=False, max_length=200
        )
        self.guild_quota = discord.ui.TextInput(
            default=str(settings.ai_daily_guild_quota), max_length=9
        )
        self.user_quota = discord.ui.TextInput(
            default=str(settings.ai_daily_user_quota), max_length=9
        )
        for text, component in (
            (strings.AI_CHANNEL_IDS, self.channels),
            (strings.AI_ROLE_IDS, self.roles),
            (strings.AI_MODEL, self.model),
            (strings.AI_GUILD_QUOTA, self.guild_quota),
            (strings.AI_USER_QUOTA, self.user_quota),
        ):
            self.add_item(discord.ui.Label(text=text, component=component))

    def values(self) -> dict[str, Any]:
        return {
            "ai_channel_ids": [channel.id for channel in self.channels.values],
            "ai_role_ids": [role.id for role in self.roles.values],
            "ai_model": str(self.model).strip() or None,
            "ai_daily_guild_quota": int(str(self.guild_quota)),
            "ai_daily_user_quota": int(str(self.user_quota)),
        }


async def log_toggle_panel(
    bot: Any, interaction: discord.Interaction, *, notice: str | None = None
) -> LogTogglePanel:
    settings = await bot.settings_service.get(interaction.guild_id)

    async def back(target: discord.Interaction) -> None:
        await defer_update(target)
        await swap_panel(target, await settings_panel(bot, target))

    return LogTogglePanel(bot, settings, notice=notice, back=back)


class LogTogglePanel(Panel):
    title = f"# 📜 {strings.SETTINGS_LOG_TOGGLES}"
    accent = discord.Colour.from_rgb(180, 150, 255)

    def __init__(self, bot: Any, settings: GuildSettings, **kwargs: Any) -> None:
        self.settings = settings
        super().__init__(bot, **kwargs)

    def rows(self) -> Iterable[discord.ui.Item[Any]]:
        yield discord.ui.ActionRow(
            self._toggle(
                strings.SETTINGS_LOG_MEMBERS, "log_member_events", "cs:settings:log:members"
            ),
            self._toggle(
                strings.SETTINGS_LOG_MESSAGES, "log_message_events", "cs:settings:log:messages"
            ),
        )

    def _toggle(self, label: str, field: str, custom_id: str) -> discord.ui.Button:
        enabled = bool(getattr(self.settings, field))
        state = strings.TOGGLE_ON if enabled else strings.TOGGLE_OFF

        async def callback(interaction: discord.Interaction) -> None:
            await self._flip(interaction, field)

        return button(
            f"{label}：{state}",
            custom_id,
            callback,
            style=(discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary),
        )

    async def _flip(self, interaction: discord.Interaction, field: str) -> None:
        try:
            await defer_update(interaction)
            if not is_admin(interaction):
                await swap_panel(
                    interaction,
                    await log_toggle_panel(self.bot, interaction, notice=strings.ADMIN_ONLY),
                )
                return
            await self.bot.settings_service.update(
                interaction.guild_id,
                interaction.user.id,
                action="settings_log_toggle",
                values={field: not getattr(self.settings, field)},
            )
            await swap_panel(interaction, await log_toggle_panel(self.bot, interaction))
        except Exception as exc:
            await show_error(
                interaction, exc, lambda note: log_toggle_panel(self.bot, interaction, notice=note)
            )


async def model_panel(
    bot: Any, interaction: discord.Interaction, *, notice: str | None = None
) -> ModelPanel:
    models = await bot.ai_provider.list_models()

    async def back(target: discord.Interaction) -> None:
        await defer_update(target)
        await swap_panel(target, await settings_panel(bot, target))

    return ModelPanel(bot, models, notice=notice, back=back)


class ModelPanel(PagedPanel):
    title = f"# 🤖 {strings.SETTINGS_MODEL}"
    accent = discord.Colour.from_rgb(180, 150, 255)
    page_size = 25

    def page_rows(self, items: list[Any]) -> Iterable[discord.ui.Item[Any]]:
        select = discord.ui.Select(
            placeholder=strings.SETTINGS_MODEL,
            options=[discord.SelectOption(label=model[:100], value=model[:100]) for model in items],
        )
        select.callback = self._choose
        yield discord.ui.ActionRow(select)

    async def _choose(self, interaction: discord.Interaction) -> None:
        try:
            await defer_update(interaction)
            if not is_admin(interaction):
                await swap_panel(
                    interaction,
                    await settings_panel(self.bot, interaction, notice=strings.ADMIN_ONLY),
                )
                return
            model = interaction.data["values"][0]
            await self.bot.settings_service.update(
                interaction.guild_id,
                interaction.user.id,
                action="settings_ai_model",
                values={"ai_model": model},
            )
            await swap_panel(
                interaction,
                await settings_panel(
                    self.bot, interaction, notice=strings.AI_MODEL_SAVED.format(model=model)
                ),
            )
        except Exception as exc:
            await show_error(
                interaction, exc, lambda note: settings_panel(self.bot, interaction, notice=note)
            )
