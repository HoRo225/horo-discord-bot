from __future__ import annotations

from typing import Any

import discord

from src import strings
from src.database.models import GuildSettings
from src.services.settings import parse_snowflake_list
from src.ui.common import (
    defer_ephemeral,
    handle_interaction_error,
    is_admin,
    send_ephemeral,
)


def _optional_snowflake(value: str) -> int | None:
    cleaned = value.strip().strip("<#>")
    if not cleaned:
        return None
    if not cleaned.isdigit() or int(cleaned) <= 0:
        raise ValueError(strings.CHANNEL_ID_INVALID)
    return int(cleaned)


class SettingsPanel(discord.ui.LayoutView):
    def __init__(self, bot: Any, settings: GuildSettings) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.settings = settings
        welcome = discord.ui.Button(label=strings.SETTINGS_WELCOME, custom_id="cs:settings:welcome")
        economy = discord.ui.Button(label=strings.SETTINGS_ECONOMY, custom_id="cs:settings:economy")
        poll = discord.ui.Button(label=strings.SETTINGS_POLL, custom_id="cs:settings:poll")
        ai = discord.ui.Button(label=strings.SETTINGS_AI, custom_id="cs:settings:ai")
        toggles = discord.ui.Button(
            label=strings.SETTINGS_LOG_TOGGLES, custom_id="cs:settings:log_toggles"
        )
        models = discord.ui.Button(
            label=strings.SETTINGS_MODEL,
            style=discord.ButtonStyle.primary,
            custom_id="cs:settings:model",
        )
        welcome.callback = self.welcome
        economy.callback = self.economy
        poll.callback = self.poll
        ai.callback = self.ai
        toggles.callback = self.log_toggles
        models.callback = self.models
        summary = strings.SETTINGS_SUMMARY.format(
            currency=settings.currency_name,
            daily=settings.daily_amount,
            minimum=settings.blackjack_min_bet,
            maximum=settings.blackjack_max_bet,
            model=(
                settings.ai_model or bot.settings.ai_default_model or strings.SETTING_NOT_CONFIGURED
            ),
        )
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(f"# ⚙️ {strings.SETTINGS_TITLE}"),
                discord.ui.TextDisplay(summary),
                discord.ui.ActionRow(welcome, economy, poll, ai),
                discord.ui.ActionRow(toggles, models),
                accent_colour=discord.Colour.from_rgb(180, 150, 255),
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not is_admin(interaction):
            await send_ephemeral(interaction, strings.ADMIN_ONLY)
            return False
        return True

    async def welcome(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(WelcomeLogModal(self.bot, self.settings))

    async def economy(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(EconomySettingsModal(self.bot, self.settings))

    async def poll(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(PollSettingsModal(self.bot, self.settings))

    async def ai(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(AISettingsModal(self.bot, self.settings))

    async def log_toggles(self, interaction: discord.Interaction) -> None:
        await send_ephemeral(interaction, view=LogToggleView(self.bot, self.settings))

    async def models(self, interaction: discord.Interaction) -> None:
        try:
            await defer_ephemeral(interaction)
            models = await self.bot.ai_provider.list_models()
            await send_ephemeral(interaction, view=ModelSelectView(self.bot, models))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)


class WelcomeLogModal(discord.ui.Modal):
    def __init__(self, bot: Any, settings: GuildSettings) -> None:
        super().__init__(title=strings.SETTINGS_WELCOME, custom_id="cs:settings:welcome:modal")
        self.bot = bot
        self.welcome_channel = discord.ui.TextInput(
            label=strings.WELCOME_CHANNEL_ID,
            default=str(settings.welcome_channel_id or ""),
            required=False,
            max_length=25,
        )
        self.goodbye_channel = discord.ui.TextInput(
            label=strings.GOODBYE_CHANNEL_ID,
            default=str(settings.goodbye_channel_id or ""),
            required=False,
            max_length=25,
        )
        self.log_channel = discord.ui.TextInput(
            label=strings.LOG_CHANNEL_ID,
            default=str(settings.log_channel_id or ""),
            required=False,
            max_length=25,
        )
        self.welcome_template = discord.ui.TextInput(
            label=strings.WELCOME_TEMPLATE,
            default=settings.welcome_template,
            style=discord.TextStyle.paragraph,
            max_length=1_500,
        )
        self.goodbye_template = discord.ui.TextInput(
            label=strings.GOODBYE_TEMPLATE,
            default=settings.goodbye_template,
            style=discord.TextStyle.paragraph,
            max_length=1_500,
        )
        for item in (
            self.welcome_channel,
            self.goodbye_channel,
            self.log_channel,
            self.welcome_template,
            self.goodbye_template,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await defer_ephemeral(interaction)
            await self.bot.settings_service.update(
                interaction.guild_id,
                interaction.user.id,
                action="settings_welcome_log",
                values={
                    "welcome_channel_id": _optional_snowflake(str(self.welcome_channel)),
                    "goodbye_channel_id": _optional_snowflake(str(self.goodbye_channel)),
                    "log_channel_id": _optional_snowflake(str(self.log_channel)),
                    "welcome_template": str(self.welcome_template),
                    "goodbye_template": str(self.goodbye_template),
                },
            )
            await send_ephemeral(interaction, strings.SUCCESS)
        except ValueError as exc:
            await send_ephemeral(interaction, strings.INVALID_INPUT.format(reason=str(exc)))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)


class EconomySettingsModal(discord.ui.Modal):
    def __init__(self, bot: Any, settings: GuildSettings) -> None:
        super().__init__(title=strings.SETTINGS_ECONOMY, custom_id="cs:settings:economy:modal")
        self.bot = bot
        self.currency = discord.ui.TextInput(
            label=strings.CURRENCY_NAME, default=settings.currency_name, max_length=50
        )
        self.daily = discord.ui.TextInput(
            label=strings.DAILY_AMOUNT, default=str(settings.daily_amount), max_length=18
        )
        self.minimum = discord.ui.TextInput(
            label=strings.BLACKJACK_MIN_BET,
            default=str(settings.blackjack_min_bet),
            max_length=18,
        )
        self.maximum = discord.ui.TextInput(
            label=strings.BLACKJACK_MAX_BET,
            default=str(settings.blackjack_max_bet),
            max_length=18,
        )
        for item in (self.currency, self.daily, self.minimum, self.maximum):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await defer_ephemeral(interaction)
            await self.bot.settings_service.update(
                interaction.guild_id,
                interaction.user.id,
                action="settings_economy_blackjack",
                values={
                    "currency_name": str(self.currency),
                    "daily_amount": int(str(self.daily)),
                    "blackjack_min_bet": int(str(self.minimum)),
                    "blackjack_max_bet": int(str(self.maximum)),
                },
            )
            await send_ephemeral(interaction, strings.SUCCESS)
        except ValueError as exc:
            await send_ephemeral(interaction, strings.INVALID_INPUT.format(reason=str(exc)))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)


class PollSettingsModal(discord.ui.Modal):
    def __init__(self, bot: Any, settings: GuildSettings) -> None:
        super().__init__(title=strings.SETTINGS_POLL, custom_id="cs:settings:poll:modal")
        self.bot = bot
        self.roles = discord.ui.TextInput(
            label=strings.POLL_ROLE_IDS,
            default=", ".join(map(str, settings.poll_creator_role_ids)),
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=1_000,
        )
        self.add_item(self.roles)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await defer_ephemeral(interaction)
            await self.bot.settings_service.update(
                interaction.guild_id,
                interaction.user.id,
                action="settings_poll_roles",
                values={"poll_creator_role_ids": parse_snowflake_list(str(self.roles))},
            )
            await send_ephemeral(interaction, strings.SUCCESS)
        except Exception as exc:
            await handle_interaction_error(interaction, exc)


class AISettingsModal(discord.ui.Modal):
    def __init__(self, bot: Any, settings: GuildSettings) -> None:
        super().__init__(title=strings.SETTINGS_AI, custom_id="cs:settings:ai:modal")
        self.bot = bot
        self.channels = discord.ui.TextInput(
            label=strings.AI_CHANNEL_IDS,
            default=", ".join(map(str, settings.ai_channel_ids)),
            required=False,
            max_length=1_000,
        )
        self.roles = discord.ui.TextInput(
            label=strings.AI_ROLE_IDS,
            default=", ".join(map(str, settings.ai_role_ids)),
            required=False,
            max_length=1_000,
        )
        self.model = discord.ui.TextInput(
            label=strings.AI_MODEL,
            default=settings.ai_model or "",
            required=False,
            max_length=200,
        )
        self.guild_quota = discord.ui.TextInput(
            label=strings.AI_GUILD_QUOTA,
            default=str(settings.ai_daily_guild_quota),
            max_length=9,
        )
        self.user_quota = discord.ui.TextInput(
            label=strings.AI_USER_QUOTA,
            default=str(settings.ai_daily_user_quota),
            max_length=9,
        )
        for item in (
            self.channels,
            self.roles,
            self.model,
            self.guild_quota,
            self.user_quota,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await defer_ephemeral(interaction)
            await self.bot.settings_service.update(
                interaction.guild_id,
                interaction.user.id,
                action="settings_ai",
                values={
                    "ai_channel_ids": parse_snowflake_list(str(self.channels)),
                    "ai_role_ids": parse_snowflake_list(str(self.roles)),
                    "ai_model": str(self.model).strip() or None,
                    "ai_daily_guild_quota": int(str(self.guild_quota)),
                    "ai_daily_user_quota": int(str(self.user_quota)),
                },
            )
            await send_ephemeral(interaction, strings.SUCCESS)
        except ValueError as exc:
            await send_ephemeral(interaction, strings.INVALID_INPUT.format(reason=str(exc)))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)


class LogToggleView(discord.ui.View):
    def __init__(self, bot: Any, settings: GuildSettings) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.settings = settings
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear_items()
        member_state = strings.TOGGLE_ON if self.settings.log_member_events else strings.TOGGLE_OFF
        members = discord.ui.Button(
            label=f"{strings.SETTINGS_LOG_MEMBERS}：{member_state}",
            style=(
                discord.ButtonStyle.success
                if self.settings.log_member_events
                else discord.ButtonStyle.secondary
            ),
        )
        message_state = (
            strings.TOGGLE_ON if self.settings.log_message_events else strings.TOGGLE_OFF
        )
        messages = discord.ui.Button(
            label=f"{strings.SETTINGS_LOG_MESSAGES}：{message_state}",
            style=(
                discord.ButtonStyle.success
                if self.settings.log_message_events
                else discord.ButtonStyle.secondary
            ),
        )
        members.callback = self.toggle_members
        messages.callback = self.toggle_messages
        self.add_item(members)
        self.add_item(messages)

    async def _toggle(self, interaction: discord.Interaction, field: str) -> None:
        if not is_admin(interaction):
            await send_ephemeral(interaction, strings.ADMIN_ONLY)
            return
        self.settings = await self.bot.settings_service.update(
            interaction.guild_id,
            interaction.user.id,
            action="settings_log_toggle",
            values={field: not getattr(self.settings, field)},
        )
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def toggle_members(self, interaction: discord.Interaction) -> None:
        try:
            await self._toggle(interaction, "log_member_events")
        except Exception as exc:
            await handle_interaction_error(interaction, exc)

    async def toggle_messages(self, interaction: discord.Interaction) -> None:
        try:
            await self._toggle(interaction, "log_message_events")
        except Exception as exc:
            await handle_interaction_error(interaction, exc)


class ModelSelect(discord.ui.Select):
    def __init__(self, bot: Any, models: list[str]) -> None:
        self.bot = bot
        self.models = models
        options = [
            discord.SelectOption(label=model[:100], value=str(index))
            for index, model in enumerate(models)
        ]
        super().__init__(placeholder=strings.SETTINGS_MODEL, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction):
            await send_ephemeral(interaction, strings.ADMIN_ONLY)
            return
        try:
            model = self.models[int(self.values[0])]
            await self.bot.settings_service.update(
                interaction.guild_id,
                interaction.user.id,
                action="settings_ai_model",
                values={"ai_model": model},
            )
            await send_ephemeral(interaction, strings.AI_MODEL_SAVED.format(model=model))
        except Exception as exc:
            await handle_interaction_error(interaction, exc)


class ModelSelectView(discord.ui.View):
    def __init__(self, bot: Any, models: list[str], *, page: int = 0) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.models = models
        self.page = page
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear_items()
        start = self.page * 25
        self.add_item(ModelSelect(self.bot, self.models[start : start + 25]))
        if len(self.models) <= 25:
            return
        previous = discord.ui.Button(
            label=strings.PREVIOUS_PAGE,
            disabled=self.page == 0,
            style=discord.ButtonStyle.secondary,
        )
        following = discord.ui.Button(
            label=strings.NEXT_PAGE,
            disabled=(self.page + 1) * 25 >= len(self.models),
            style=discord.ButtonStyle.secondary,
        )
        previous.callback = self.previous_page
        following.callback = self.next_page
        self.add_item(previous)
        self.add_item(following)

    async def previous_page(self, interaction: discord.Interaction) -> None:
        self.page = max(0, self.page - 1)
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction) -> None:
        self.page += 1
        self._rebuild()
        await interaction.response.edit_message(view=self)
