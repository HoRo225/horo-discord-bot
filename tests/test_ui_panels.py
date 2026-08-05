from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import discord
from conftest import _button, _buttons, _container, _kinds, _texts, fake_bot

from src import strings
from src.services.economy import DailyResult
from src.ui.base import panel_action
from src.ui.blackjack import BlackjackGameView
from src.ui.economy import EconomyPanel, LeaderboardPanel
from src.ui.giveaway import GiveawayMessageView, GiveawayPanel, winners_line
from src.ui.settings import ModelPanel
from src.ui.status import ACCENTS, Notice, StatusKind, worst


def test_ai_model_picker_paginates_all_router_models():
    panel = ModelPanel(fake_bot(), [f"model-{index}" for index in range(30)])
    select = next(item for item in panel.walk_children() if isinstance(item, discord.ui.Select))
    assert len(select.options) == 25
    assert panel.page_count == 2


def test_pager_disables_edges_and_second_page_holds_remainder():
    models = [f"model-{index}" for index in range(30)]
    first = ModelPanel(fake_bot(), models)
    assert _button(first, "cs:nav:prev").disabled is True
    assert _button(first, "cs:nav:next").disabled is False

    second = ModelPanel(fake_bot(), models, page=1)
    select = next(item for item in second.walk_children() if isinstance(item, discord.ui.Select))
    assert len(select.options) == 5
    assert _button(second, "cs:nav:prev").disabled is False
    assert _button(second, "cs:nav:next").disabled is True


def test_pager_is_hidden_when_everything_fits_on_one_page():
    panel = ModelPanel(fake_bot(), ["only-one"])
    assert panel.page_count == 1
    assert _button(panel, "cs:nav:prev") is None
    assert _button(panel, "cs:nav:next") is None


def test_leaderboard_numbering_continues_across_pages():
    wallets = [SimpleNamespace(user_id=index, balance=index) for index in range(25)]
    second = LeaderboardPanel(fake_bot(), wallets, currency="水晶", page=1)
    body = [
        item.content for item in second.walk_children() if isinstance(item, discord.ui.TextDisplay)
    ]
    # 第 11 名是第二頁第一筆（page_size=10），不綁定 body 的索引位置或 "**N.**" 完整格式，
    # 只要求排名與對應項目（其 user_id）出現在同一段文字裡。
    eleventh = wallets[10]
    assert any("11" in text and str(eleventh.user_id) in text for text in body)


def test_notice_and_back_button_are_rendered():
    async def back(_interaction):
        return None

    plain = EconomyPanel(fake_bot(), balance=1, currency="水晶")
    annotated = EconomyPanel(fake_bot(), balance=1, currency="水晶", notice="測試通知", back=back)
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
    view = BlackjackGameView(fake_bot(), _finished_game())
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
        status="completed",
        ends_at=datetime.now(UTC),
    )
    view = GiveawayMessageView(fake_bot(), giveaway)
    kinds = _kinds(view)
    assert "Container" in kinds
    assert "TextDisplay" in kinds
    assert _buttons(view) == []


def test_winners_line_discloses_a_short_draw():
    """候選不足時抽樣只回傳較少人，靜默少發獎會被誤讀成漏抽。"""
    full = SimpleNamespace(winner_count=2, winners=[1, 2])
    short = SimpleNamespace(winner_count=3, winners=[1, 2])

    assert strings.GIVEAWAY_PARTIAL_WINNERS.format(actual=2, expected=2) not in winners_line(full)
    line = winners_line(short)
    assert "<@1>" in line and "<@2>" in line
    assert line.endswith(strings.GIVEAWAY_PARTIAL_WINNERS.format(actual=2, expected=3))


def test_pending_giveaway_still_renders_its_entry_button():
    """公告訊息是在 publish() 之前送出的，那時狀態還是 pending。"""
    giveaway = SimpleNamespace(
        id=8,
        prize="尚未公開的禮物",
        winner_count=1,
        ticket_price=0,
        per_user_limit=1,
        status="pending",
        ends_at=datetime.now(UTC),
    )
    view = GiveawayMessageView(fake_bot(), giveaway)
    assert _buttons(view) != []
    assert strings.GIVEAWAY_STATUS_ENDED not in "".join(_texts(view))


class FakeResponse:
    def __init__(self):
        self.done = False
        self.deferred = False
        self.modals = []

    def is_done(self):
        return self.done

    async def defer(self, *, ephemeral=False, thinking=False):
        self.done = True
        self.deferred = True

    async def edit_message(self, **kwargs):
        self.done = True
        self.edits = kwargs

    async def send_modal(self, modal):
        self.done = True
        self.modals.append(modal)


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


class FakeGiveaways:
    def __init__(self, completed):
        self._completed = completed
        self.active_calls = 0

    async def completed(self, _guild_id, *, limit=25):
        return self._completed

    async def active(self, _guild_id, *, paid_only=False):
        self.active_calls += 1
        return []


def _admin_interaction():
    interaction = FakeInteraction()
    interaction.user = SimpleNamespace(id=2, guild_permissions=SimpleNamespace(manage_guild=True))
    return interaction


async def test_reroll_shows_neutral_notice_when_no_completed_giveaway():
    """沒有候選時不該開一張空 Select Modal。"""
    giveaways = FakeGiveaways(completed=[])
    panel = GiveawayPanel(SimpleNamespace(giveaways=giveaways))
    interaction = _admin_interaction()

    await panel.reroll(interaction)

    assert interaction.response.modals == []
    assert len(interaction.edits) == 1
    assert isinstance(interaction.edits[0]["view"], GiveawayPanel)


async def test_reroll_never_sources_its_options_from_active_giveaways():
    """reroll() 只接受 completed，選單抓 active 會讓每個選項都必然失敗。"""
    ended = SimpleNamespace(id=7, prize="已結束獎品")
    giveaways = FakeGiveaways(completed=[ended])
    panel = GiveawayPanel(SimpleNamespace(giveaways=giveaways))
    interaction = _admin_interaction()

    await panel.reroll(interaction)

    assert giveaways.active_calls == 0
    assert len(interaction.response.modals) == 1


class RecordingMessage:
    def __init__(self, *, delete_error: Exception | None = None) -> None:
        self.id = 555
        self.channel = SimpleNamespace(id=99)
        self.deleted = False
        self._delete_error = delete_error

    async def delete(self):
        if self._delete_error is not None:
            raise self._delete_error
        self.deleted = True


class RecordingChannel:
    def __init__(self, message) -> None:
        self.message = message

    async def send(self, *_args, **_kwargs):
        return self.message


class FailingPublishGiveaways:
    def __init__(self) -> None:
        self.published = False

    async def create(self, **_kwargs):
        return SimpleNamespace(
            id=7,
            prize="測試獎品",
            winner_count=1,
            ticket_price=0,
            per_user_limit=1,
            status="pending",
            ends_at=datetime.now(UTC),
        )

    async def publish(self, _giveaway_id, _message_id):
        raise RuntimeError("DB 掛了")


def _create_modal(bot, channel):
    from src.ui.giveaway import CreateGiveawayModal

    modal = CreateGiveawayModal(bot)
    # TextInput 的 str() 就是它的 value，直接塞字串即可驅動 on_submit。
    modal.prize, modal.winners, modal.duration = "測試獎品", "1", "1h"
    modal.price, modal.limit = "0", "1"
    interaction = _admin_interaction()
    interaction.channel = channel
    interaction.channel_id = 99
    interaction.id = 12345
    return modal, interaction


async def test_giveaway_publish_failure_withdraws_the_announcement():
    """訊息已公開卻沒綁上 DB 時，抽獎會顯示成進行中但參加按鈕永遠查不到活動。"""
    message = RecordingMessage()
    modal, interaction = _create_modal(
        SimpleNamespace(giveaways=FailingPublishGiveaways()), RecordingChannel(message)
    )

    await modal.on_submit(interaction)

    assert message.deleted is True
    # 使用者看到的必須是原始失敗原因，而不是補償動作的結果。
    assert strings.GENERIC_ERROR.split("{")[0] in "".join(_texts(interaction.edits[-1]["view"]))


async def test_publish_failure_surfaces_the_original_error_even_if_withdraw_fails():
    message = RecordingMessage(delete_error=RuntimeError("連刪除也失敗"))
    modal, interaction = _create_modal(
        SimpleNamespace(giveaways=FailingPublishGiveaways()), RecordingChannel(message)
    )

    await modal.on_submit(interaction)

    assert message.deleted is False
    assert strings.GENERIC_ERROR.split("{")[0] in "".join(_texts(interaction.edits[-1]["view"]))


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
