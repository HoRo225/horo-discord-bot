from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import discord

from src import strings
from src.cogs.admin import AdminCog
from src.services.economy import DailyResult
from src.ui.base import panel_action
from src.ui.blackjack import BlackjackGameView
from src.ui.dashboard import DashboardView
from src.ui.economy import EconomyPanel, LeaderboardPanel
from src.ui.giveaway import GiveawayMessageView
from src.ui.settings import PANELS, ModelPanel, SettingsPanel, module_statuses, nav_row
from src.ui.settings.nav import NAV_MODEL
from src.ui.status import ACCENTS, Notice, StatusKind, worst


def _buttons(view):
    return [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]


def _kinds(view):
    return [type(item).__name__ for item in view.walk_children()]


def _dispatch_custom_ids(view):
    return [item.custom_id for item in _buttons(view) if item.url is None]


def test_persistent_views_have_stable_custom_ids():
    bot = SimpleNamespace()
    views = [DashboardView(bot), GiveawayMessageView(bot), BlackjackGameView(bot)]
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
    panel = ModelPanel(SimpleNamespace(), [f"model-{index}" for index in range(30)])
    select = next(item for item in panel.walk_children() if isinstance(item, discord.ui.Select))
    assert len(select.options) == 25
    assert panel.page_count == 2


def test_pager_disables_edges_and_second_page_holds_remainder():
    models = [f"model-{index}" for index in range(30)]
    first = ModelPanel(SimpleNamespace(), models)
    previous, following = _buttons(first)
    assert previous.disabled is True
    assert following.disabled is False

    second = ModelPanel(SimpleNamespace(), models, page=1)
    select = next(item for item in second.walk_children() if isinstance(item, discord.ui.Select))
    assert len(select.options) == 5
    previous, following = _buttons(second)
    assert previous.disabled is False
    assert following.disabled is True


def test_pager_is_hidden_when_everything_fits_on_one_page():
    panel = ModelPanel(SimpleNamespace(), ["only-one"])
    assert panel.page_count == 1
    assert _buttons(panel) == []


def test_leaderboard_numbering_continues_across_pages():
    wallets = [SimpleNamespace(user_id=index, balance=index) for index in range(25)]
    second = LeaderboardPanel(SimpleNamespace(), wallets, currency="水晶", page=1)
    body = [
        item.content for item in second.walk_children() if isinstance(item, discord.ui.TextDisplay)
    ]
    assert "**11.**" in body[1]


def test_notice_and_back_button_are_rendered():
    async def back(_interaction):
        return None

    plain = EconomyPanel(SimpleNamespace(), balance=1, currency="水晶")
    annotated = EconomyPanel(
        SimpleNamespace(), balance=1, currency="水晶", notice="測試通知", back=back
    )
    texts = [
        item.content
        for item in annotated.walk_children()
        if isinstance(item, discord.ui.TextDisplay)
    ]
    assert "測試通知" in texts
    assert len(_buttons(annotated)) == len(_buttons(plain)) + 1


def _finished_game():
    return SimpleNamespace(
        phase="settled",
        dealer_cards=["AS", "KD"],
        hands=[{"cards": ["9H", "8C"], "bet": 50}],
        active_hand=0,
        outcome={"hands": [{"result": "loss"}], "staked": 50, "credit": 0, "net": -50},
        user_id=42,
        id="abcdef123456",
    )


def test_settled_blackjack_keeps_its_container_but_drops_actions():
    """牌面與按鈕同在 view 裡，結算時若傳 view=None 會讓整張牌桌消失。"""
    view = BlackjackGameView(SimpleNamespace(), _finished_game())
    kinds = _kinds(view)
    assert "Container" in kinds
    assert "TextDisplay" in kinds
    assert _buttons(view) == []


def test_ended_giveaway_keeps_its_container_but_drops_entry_button():
    giveaway = SimpleNamespace(
        id=7,
        prize="禮物",
        winner_count=1,
        ticket_price=0,
        per_user_limit=1,
        status="ended",
        ends_at=datetime.now(UTC),
    )
    view = GiveawayMessageView(SimpleNamespace(), giveaway)
    kinds = _kinds(view)
    assert "Container" in kinds
    assert "TextDisplay" in kinds
    assert _buttons(view) == []


class FakeResponse:
    def __init__(self):
        self.done = False
        self.deferred = False

    def is_done(self):
        return self.done

    async def defer(self, *, ephemeral=False, thinking=False):
        self.done = True
        self.deferred = True

    async def edit_message(self, **kwargs):
        self.done = True
        self.edits = kwargs


class FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, *, view=None, ephemeral=False):
        self.messages.append((content, view, ephemeral))


class FakeInteraction(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(
            guild_id=1,
            user=SimpleNamespace(id=2),
            response=FakeResponse(),
            followup=FakeFollowup(),
            **kwargs,
        )
        self.edits = []

    async def edit_original_response(self, **kwargs):
        self.edits.append(kwargs)


class FakeSettingsService:
    async def get(self, _guild_id):
        return SimpleNamespace(daily_amount=100, currency_name="水晶")


class FakeEconomy:
    async def daily(self, _guild_id, _user_id, _amount):
        return DailyResult(True, 100, 100)

    async def balance(self, _guild_id, _user_id):
        return 100


async def test_panel_action_edits_in_place_instead_of_sending_a_new_message():
    """單一訊息模型的核心契約：面板內的操作只改寫目前訊息，不另開訊息。"""
    bot = SimpleNamespace(settings_service=FakeSettingsService(), economy=FakeEconomy())
    interaction = FakeInteraction()
    panel = EconomyPanel(bot, balance=0, currency="水晶")

    await panel.daily(interaction)

    assert interaction.response.deferred is True
    assert interaction.followup.messages == []
    assert len(interaction.edits) == 1
    edit = interaction.edits[0]
    assert isinstance(edit["view"], EconomyPanel)
    # 切換到 LayoutView 時必須清掉 V1 欄位，否則舊內容會殘留。
    assert edit["content"] is None
    assert edit["embeds"] == []
    notices = [
        item.content
        for item in edit["view"].walk_children()
        if isinstance(item, discord.ui.TextDisplay)
    ]
    assert any("簽到成功" in text for text in notices)


def _texts(view):
    return [
        item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay)
    ]


def _container(view):
    return next(item for item in view.walk_children() if isinstance(item, discord.ui.Container))


def test_semantic_notice_adds_a_badge_and_repaints_the_accent():
    panel = EconomyPanel(
        SimpleNamespace(), balance=1, currency="水晶", notice=Notice("出事了", StatusKind.ERROR)
    )
    assert f"{strings.STATUS_BADGE_ERROR} 出事了" in _texts(panel)
    assert _container(panel).accent_colour == ACCENTS[StatusKind.ERROR]


def test_plain_string_notice_is_never_decorated():
    """語意化是 opt-in：純 str 不加徽章也不換色，否則既有呼叫端的文字會被偷改。"""
    plain = EconomyPanel(SimpleNamespace(), balance=1, currency="水晶")
    panel = EconomyPanel(SimpleNamespace(), balance=1, currency="水晶", notice="測試通知")
    assert "測試通知" in _texts(panel)
    assert _container(panel).accent_colour == _container(plain).accent_colour


def test_worst_status_wins_and_nothing_means_ok():
    assert worst([StatusKind.OK, StatusKind.ERROR, StatusKind.WARN]) is StatusKind.ERROR
    assert worst([]) is StatusKind.OK


async def _economy_rebuild(notice):
    return EconomyPanel(SimpleNamespace(), balance=0, currency="水晶", notice=notice)


async def test_panel_action_keeps_the_single_message_contract_when_the_body_raises():
    """例外經過 panel_action 後仍只能改寫同一則訊息，不可退化成另送一則。"""
    interaction = FakeInteraction()

    async with panel_action(interaction, _economy_rebuild):
        raise ValueError("金額必須是正整數")

    assert interaction.response.deferred is True
    assert interaction.followup.messages == []
    assert len(interaction.edits) == 1
    view = interaction.edits[0]["view"]
    assert any(
        text.startswith(strings.STATUS_BADGE_ERROR) and "金額必須是正整數" in text
        for text in _texts(view)
    )
    assert _container(view).accent_colour == ACCENTS[StatusKind.ERROR]


async def test_panel_action_hides_unexpected_error_details_from_the_panel():
    interaction = FakeInteraction(id=99)

    async with panel_action(interaction, _economy_rebuild):
        raise RuntimeError("資料庫連線字串 postgres://secret")

    assert len(interaction.edits) == 1
    texts = _texts(interaction.edits[0]["view"])
    assert all("postgres://secret" not in text for text in texts)
    assert any(text.startswith(strings.STATUS_BADGE_ERROR) for text in texts)


def _guild_settings(**overrides):
    """組出 settings 面板讀得到的那些 GuildSettings 欄位，其餘留給資料庫。"""
    base = {
        "log_channel_id": None,
        "log_member_events": True,
        "log_message_events": True,
        "currency_name": "水晶",
        "daily_amount": 100,
        "blackjack_min_bet": 10,
        "blackjack_max_bet": 10_000,
        "poll_creator_role_ids": [],
        "ai_channel_ids": [],
        "ai_role_ids": [],
        "ai_model": None,
    }
    return SimpleNamespace(**{**base, **overrides})


def test_module_statuses_tell_untouched_modules_apart_from_half_configured_ai():
    bot = SimpleNamespace(settings=SimpleNamespace(ai_default_model="fallback-model"))

    assert module_statuses(bot, _guild_settings()) == {
        "log": StatusKind.OFF,
        "economy": StatusKind.OK,
        "poll": StatusKind.OFF,
        "ai": StatusKind.OFF,
    }
    # 只設頻道沒設身分組是「設了也不會動」，必須跳警示而不是安靜地當成未啟用。
    assert module_statuses(bot, _guild_settings(ai_channel_ids=[1]))["ai"] is StatusKind.WARN
    ready = _guild_settings(
        log_channel_id=9, poll_creator_role_ids=[3], ai_channel_ids=[1], ai_role_ids=[2]
    )
    assert set(module_statuses(bot, ready).values()) == {StatusKind.OK}


def test_settings_panel_badges_every_module_and_takes_the_worst_status_colour():
    bot = SimpleNamespace(settings=SimpleNamespace(ai_default_model=""))
    panel = SettingsPanel(bot, _guild_settings())
    assert sum(text.startswith(strings.STATUS_BADGE_OFF) for text in _texts(panel)) == 3
    assert _container(panel).accent_colour == ACCENTS[StatusKind.OFF]


def test_settings_nav_marks_the_current_page_and_reaches_every_panel():
    select = nav_row(SimpleNamespace(), NAV_MODEL).children[0]
    assert [option.label for option in select.options if option.default] == [
        f"{strings.NAV_CURRENT_MARK} {strings.SETTINGS_MODEL}"
    ]
    # 每個選項都得說明該頁能做什麼，否則選單只是把返回鈕換了個樣子。
    assert all(option.description for option in select.options)
    # 導覽鍵與面板工廠表必須對得上，否則選下去會直接 KeyError。
    assert {option.value for option in select.options} == set(PANELS)
