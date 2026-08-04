from __future__ import annotations

from types import SimpleNamespace

from conftest import _container, _texts

from src import strings
from src.ui.settings import PANELS, SettingsPanel, module_statuses, nav_row
from src.ui.settings.nav import NAV_MODEL
from src.ui.status import ACCENTS, StatusKind


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
