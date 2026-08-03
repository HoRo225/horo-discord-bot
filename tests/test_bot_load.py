from __future__ import annotations

from src.bot import COG_EXTENSIONS, CrystallineSwanBot
from src.config import Settings


async def test_all_cogs_load_and_only_documented_commands_are_registered(tmp_path):
    settings = Settings(
        discord_token="test-token",
        dev_guild_id=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'bot.db').as_posix()}",
        ai_base_url="http://127.0.0.1:1/v1",
        ai_api_key="",
        ai_default_model="test-model",
        ai_request_timeout=1,
        ai_max_retries=0,
        ai_max_context_messages=20,
        ai_max_context_chars=12_000,
        ai_max_response_chars=8_000,
        ai_rate_limit_seconds=5,
        log_level="INFO",
    )
    bot = CrystallineSwanBot(settings)
    try:
        for extension in COG_EXTENSIONS:
            await bot.load_extension(extension)
        assert set(bot.cogs) == {
            "AdminCog",
            "WelcomeCog",
            "EventLogCog",
            "EconomyCog",
            "GiveawayCog",
            "PollCog",
            "BlackjackCog",
            "AIChatCog",
        }
        assert {command.name for command in bot.tree.get_commands()} == {
            "setup",
            "settings",
            "help",
            "ping",
        }
    finally:
        for extension in reversed(COG_EXTENSIONS):
            if extension in bot.extensions:
                await bot.unload_extension(extension)
        await bot.ai_provider.close()
        await bot.database.dispose()
