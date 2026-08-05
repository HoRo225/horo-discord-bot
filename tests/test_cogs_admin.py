from __future__ import annotations

from conftest import _dispatch_custom_ids, fake_bot

from src.cogs.admin import AdminCog
from src.ui.blackjack import BlackjackGameView
from src.ui.dashboard import DashboardView
from src.ui.giveaway import GiveawayMessageView


def test_persistent_views_have_stable_custom_ids():
    bot = fake_bot()
    views = [DashboardView(bot), GiveawayMessageView(bot), BlackjackGameView(bot)]
    assert all(view.is_persistent() for view in views)
    for view in views:
        custom_ids = _dispatch_custom_ids(view)
        assert custom_ids
        assert all(custom_id and custom_id.startswith("cs:") for custom_id in custom_ids)
        assert len(custom_ids) == len(set(custom_ids))


def test_only_two_documented_slash_commands_exist():
    names = {command.name for command in AdminCog.__cog_app_commands__}
    assert names == {"setup", "settings"}
