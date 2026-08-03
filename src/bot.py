from __future__ import annotations

import logging
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from src import strings
from src.config import Settings
from src.database.engine import Database
from src.database.migrations import upgrade_database
from src.services.ai import (
    AIUsageService,
    ConversationMemory,
    InMemoryRateLimiter,
    OpenAICompatibleProvider,
)
from src.services.blackjack import BlackjackService
from src.services.economy import EconomyService
from src.services.giveaway import GiveawayService
from src.services.poll import PollService
from src.services.settings import SettingsService
from src.ui.blackjack import BlackjackActionView
from src.ui.dashboard import DashboardView
from src.ui.giveaway import GiveawayEntryView

log = logging.getLogger(__name__)

COG_EXTENSIONS = (
    "src.cogs.admin",
    "src.cogs.welcome",
    "src.cogs.event_log",
    "src.cogs.economy",
    "src.cogs.giveaway",
    "src.cogs.poll",
    "src.cogs.blackjack",
    "src.cogs.ai_chat",
)


class CrystallineSwanBot(commands.AutoShardedBot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.polls = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
            help_command=None,
        )
        self.tree.on_error = self.on_app_command_error
        self.settings = settings
        self.database = Database(settings.database_url)
        self.settings_service = SettingsService(self.database)
        self.economy = EconomyService(self.database)
        self.giveaways = GiveawayService(self.database, self.economy)
        self.polls = PollService(self.database)
        self.blackjack = BlackjackService(self.database, self.economy)
        self.ai_usage = AIUsageService(self.database)
        self.ai_provider = OpenAICompatibleProvider(
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            timeout=settings.ai_request_timeout,
            max_retries=settings.ai_max_retries,
        )
        self.ai_memory = ConversationMemory(
            max_messages=settings.ai_max_context_messages,
            max_characters=settings.ai_max_context_chars,
        )
        self.ai_rate_limiter = InMemoryRateLimiter(settings.ai_rate_limit_seconds)

    async def setup_hook(self) -> None:
        await upgrade_database(self.settings.database_url)
        self.add_view(DashboardView(self))
        self.add_view(GiveawayEntryView(self))
        self.add_view(BlackjackActionView(self))
        for extension in COG_EXTENSIONS:
            await self.load_extension(extension)

        if self.settings.dev_guild_id:
            guild = discord.Object(id=self.settings.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("已同步 %s 個開發伺服器指令", len(synced))
        else:
            synced = await self.tree.sync()
            log.info("已同步 %s 個全域指令", len(synced))

    async def on_ready(self) -> None:
        log.info(
            "Bot 已上線",
            extra={"user_id": self.user.id if self.user else None},
        )

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        from src.ui.common import send_ephemeral

        if isinstance(error, app_commands.MissingPermissions):
            await send_ephemeral(interaction, strings.ADMIN_ONLY)
            return
        correlation_id = uuid.uuid4().hex[:12]
        log.exception(
            "斜線指令失敗",
            exc_info=error,
            extra={
                "correlation_id": correlation_id,
                "guild_id": interaction.guild_id,
                "user_id": interaction.user.id,
                "interaction_id": interaction.id,
            },
        )
        await send_ephemeral(
            interaction, strings.GENERIC_ERROR.format(correlation_id=correlation_id)
        )

    async def close(self) -> None:
        try:
            await super().close()
        finally:
            await self.ai_provider.close()
            await self.database.dispose()
