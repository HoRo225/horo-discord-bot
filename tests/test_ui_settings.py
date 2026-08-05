from __future__ import annotations

from types import SimpleNamespace

from conftest import _button, _container, _kinds, _select, _texts, fake_bot, guild_settings

from src import strings
from src.ui.settings import (
    PANELS,
    AIPage,
    AIQuotaModal,
    EconomyPage,
    EconomySettingsModal,
    LogPage,
    ModelPanel,
    PollPage,
    SettingsPanel,
    module_statuses,
    nav_row,
)
from src.ui.settings.nav import NAV_AI, NAV_CUSTOM_ID, NAV_ECONOMY, NAV_HOME, NAV_LOG, NAV_POLL
from src.ui.status import ACCENTS, Notice, StatusKind

_NAV_KEYS = (NAV_HOME, NAV_LOG, NAV_ECONOMY, NAV_POLL, NAV_AI)


def test_module_statuses_tell_untouched_modules_apart_from_half_configured_ai():
    bot = SimpleNamespace(settings=SimpleNamespace(ai_default_model="fallback-model"))

    assert module_statuses(bot, guild_settings()) == {
        "log": StatusKind.OFF,
        "economy": StatusKind.OK,
        "poll": StatusKind.OFF,
        "ai": StatusKind.OFF,
    }
    # 只設頻道沒設身分組是「設了也不會動」，必須跳警示而不是安靜地當成未啟用。
    assert module_statuses(bot, guild_settings(ai_channel_ids=[1]))["ai"] is StatusKind.WARN
    ready = guild_settings(
        log_channel_id=9, poll_creator_role_ids=[3], ai_channel_ids=[1], ai_role_ids=[2]
    )
    assert set(module_statuses(bot, ready).values()) == {StatusKind.OK}


def test_settings_panel_badges_every_module_and_takes_the_worst_status_colour():
    bot = SimpleNamespace(settings=SimpleNamespace(ai_default_model=""))
    panel = SettingsPanel(bot, guild_settings())
    assert sum(text.startswith(strings.STATUS_BADGE_OFF) for text in _texts(panel)) == 3
    assert _container(panel).accent_colour == ACCENTS[StatusKind.OFF]


def test_settings_nav_marks_the_current_page_and_reaches_every_panel():
    select = nav_row(SimpleNamespace(), NAV_AI).children[0]
    assert [option.label for option in select.options if option.default] == [
        f"{strings.NAV_CURRENT_MARK} {strings.SETTINGS_AI}"
    ]
    # 每個選項都得說明該頁能做什麼，否則選單只是把返回鈕換了個樣子。
    assert all(option.description for option in select.options)
    # 導覽鍵與面板工廠表必須對得上，否則選下去會直接 KeyError。
    assert {option.value for option in select.options} == set(PANELS)


def test_nav_row_reaches_every_panel_and_marks_exactly_the_current_page_from_any_page():
    """五個 nav key 各跑一次，選項集合恆等於 PANELS、且恰有一個 default 指向自己。"""
    for key in _NAV_KEYS:
        select = nav_row(SimpleNamespace(), key).children[0]
        assert {option.value for option in select.options} == set(PANELS)
        defaults = [option.value for option in select.options if option.default]
        assert defaults == [key]


def test_every_settings_page_carries_exactly_one_nav_row():
    """釘住 SettingsPage._assemble 的不變量：任何子類都不可能再多 yield 一次導覽列。"""
    bot = fake_bot()
    settings = guild_settings()
    pages = [
        SettingsPanel(bot, settings),
        LogPage(bot, settings),
        EconomyPage(bot, settings),
        PollPage(bot, settings),
        AIPage(bot, settings),
    ]
    for page in pages:
        navs = [
            item
            for item in page.walk_children()
            if getattr(item, "custom_id", None) == NAV_CUSTOM_ID
        ]
        assert len(navs) == 1


def test_settings_pages_stay_within_the_component_and_character_budget():
    """把「元件超限」這個最大風險釘死在 CI：LayoutView 硬限制是 40 個元件、4000 字元。"""
    bot = fake_bot()
    settings = guild_settings()
    notice = Notice(strings.SUCCESS)

    async def back(_interaction):
        return None

    pages = [
        SettingsPanel(bot, settings),
        SettingsPanel(bot, settings, notice=notice),
        LogPage(bot, settings),
        LogPage(bot, settings, notice=notice),
        EconomyPage(bot, settings),
        EconomyPage(bot, settings, notice=notice),
        PollPage(bot, settings),
        PollPage(bot, settings, notice=notice),
        AIPage(bot, settings),
        AIPage(bot, settings, notice=notice),
        ModelPanel(bot, [f"model-{index}" for index in range(30)], back=back),
    ]
    for page in pages:
        assert page.total_children_count <= 40
        assert page.content_length() <= 4000
        assert _kinds(page).count("ActionRow") <= 5


class FakeResponse:
    def __init__(self):
        self.done = False

    def is_done(self):
        return self.done

    async def defer(self, *, ephemeral=False, thinking=False):
        self.done = True


class FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, *, view=None, ephemeral=False):
        self.messages.append((content, view, ephemeral))


class FakeInteraction(SimpleNamespace):
    """比照 test_ui_panels.py 的寫法，額外預設管理員權限——設定頁的操作都要過 is_admin。"""

    def __init__(self, **kwargs):
        super().__init__(
            guild_id=1,
            user=SimpleNamespace(id=2, guild_permissions=SimpleNamespace(manage_guild=True)),
            response=FakeResponse(),
            followup=FakeFollowup(),
            **kwargs,
        )
        self.edits = []

    async def edit_original_response(self, **kwargs):
        self.edits.append(kwargs)


class RecordingSettingsService:
    """假 settings_service：get 回傳固定 settings，update 只記錄呼叫參數不真的寫入。"""

    def __init__(self, settings):
        self._settings = settings
        self.updates = []

    async def get(self, _guild_id):
        return self._settings

    async def update(self, guild_id, user_id, *, action, values):
        self.updates.append(SimpleNamespace(guild_id=guild_id, user_id=user_id, values=values))


async def test_choosing_a_channel_saves_immediately_and_stays_on_the_same_page():
    service = RecordingSettingsService(guild_settings())
    bot = fake_bot(settings_service=service)
    page = LogPage(bot, guild_settings())
    select = _select(page, "cs:settings:log:channel")
    select._values = [SimpleNamespace(id=123)]
    interaction = FakeInteraction()

    await select.callback(interaction)

    assert len(service.updates) == 1
    assert service.updates[0].values == {"log_channel_id": 123}
    assert len(interaction.edits) == 1
    view = interaction.edits[0]["view"]
    assert isinstance(view, LogPage)
    # 反噪音契約：選擇器重畫後 default_values 就是答案，不該再貼「已儲存」。
    assert not any(strings.SUCCESS in text for text in _texts(view))


async def test_clearing_the_channel_selection_disables_logging():
    select_source = LogPage(fake_bot(), guild_settings(log_channel_id=123))
    select = _select(select_source, "cs:settings:log:channel")
    # 這個容易漏設的參數：沒有它，使用者永遠無法把已選的頻道清空。
    assert select.min_values == 0

    service = RecordingSettingsService(guild_settings(log_channel_id=123))
    bot = fake_bot(settings_service=service)
    page = LogPage(bot, guild_settings(log_channel_id=123))
    select = _select(page, "cs:settings:log:channel")
    select._values = []
    interaction = FakeInteraction()

    await select.callback(interaction)

    assert service.updates[0].values == {"log_channel_id": None}


async def test_modal_submission_returns_to_the_page_it_was_opened_from():
    service = RecordingSettingsService(guild_settings())
    bot = fake_bot(settings_service=service)
    modal = EconomySettingsModal(bot, guild_settings())
    interaction = FakeInteraction()

    await modal.on_submit(interaction)

    assert len(interaction.edits) == 1
    view = interaction.edits[0]["view"]
    assert isinstance(view, EconomyPage)
    assert not isinstance(view, SettingsPanel)
    assert AIQuotaModal.origin == NAV_AI


def test_model_panel_has_a_back_button_instead_of_the_shared_nav_row():
    async def back(_interaction):
        return None

    panel = ModelPanel(fake_bot(), ["only-one"], back=back)
    assert _button(panel, "cs:nav:back") is not None
