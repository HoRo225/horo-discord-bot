from __future__ import annotations

from types import SimpleNamespace

import discord

from src.cogs.admin import AdminCog
from src.services.economy import DailyResult
from src.ui.blackjack import BlackjackActionView
from src.ui.dashboard import DashboardView
from src.ui.economy import EconomyPanel
from src.ui.giveaway import GiveawayEntryView
from src.ui.settings import ModelSelectView


def _dispatch_custom_ids(view):
    return [
        item.custom_id
        for item in view.walk_children()
        if isinstance(item, discord.ui.Button) and item.url is None
    ]


def test_persistent_views_have_stable_custom_ids():
    bot = SimpleNamespace()
    views = [DashboardView(bot), GiveawayEntryView(bot), BlackjackActionView(bot)]
    assert all(view.is_persistent() for view in views)
    for view in views:
        custom_ids = _dispatch_custom_ids(view)
        assert custom_ids
        assert all(custom_id and custom_id.startswith("cs:") for custom_id in custom_ids)
        assert len(custom_ids) == len(set(custom_ids))


def test_only_four_documented_slash_commands_exist():
    names = {command.name for command in AdminCog.__cog_app_commands__}
    assert names == {"setup", "settings", "help", "ping"}


def test_ai_model_picker_paginates_all_router_models():
    view = ModelSelectView(SimpleNamespace(), [f"model-{index}" for index in range(30)])
    select = next(item for item in view.children if isinstance(item, discord.ui.Select))
    assert len(select.options) == 25
    assert len(view.children) == 3


class FakeResponse:
    def __init__(self):
        self.done = False
        self.deferred_ephemeral = None

    def is_done(self):
        return self.done

    async def defer(self, *, ephemeral, thinking):
        self.done = True
        self.deferred_ephemeral = ephemeral


class FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, content, *, view=None, ephemeral=False):
        self.messages.append((content, view, ephemeral))


class FakeSettingsService:
    async def get(self, _guild_id):
        return SimpleNamespace(daily_amount=100, currency_name="水晶")


class FakeEconomy:
    async def daily(self, _guild_id, _user_id, _amount):
        return DailyResult(True, 100, 100)


async def test_dashboard_economy_interaction_defers_and_replies_ephemerally():
    bot = SimpleNamespace(settings_service=FakeSettingsService(), economy=FakeEconomy())
    interaction = SimpleNamespace(
        guild_id=1,
        user=SimpleNamespace(id=2),
        response=FakeResponse(),
        followup=FakeFollowup(),
    )
    panel = EconomyPanel(bot)
    await panel.daily(interaction)
    assert interaction.response.deferred_ephemeral is True
    assert interaction.followup.messages[0][2] is True
