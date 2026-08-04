from __future__ import annotations

from src.bot import HoRoBot
from src.config import Settings
from src.logging_config import configure_logging


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    bot = HoRoBot(settings)
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
