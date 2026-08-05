"""settings 面板套件對外入口。

維持既有 import 路徑，呼叫端（src/cogs/admin.py）與測試
（tests/test_ui_settings.py、tests/test_ui_panels.py）皆從 `src.ui.settings` 匯入，
故在此重新匯出各子模組的公開名稱，呼叫端不需改動。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord

from src.ui.settings.ai import AIPage, AIQuotaModal, ModelPanel, ai_page, model_panel
from src.ui.settings.economy import EconomyPage, EconomySettingsModal, economy_page
from src.ui.settings.logging import LogPage, log_page
from src.ui.settings.nav import NAV_AI, NAV_ECONOMY, NAV_HOME, NAV_LOG, NAV_POLL, nav_row
from src.ui.settings.panel import SettingsPanel, settings_panel
from src.ui.settings.poll import PollPage, poll_page
from src.ui.settings.shared import SettingsModal, SettingsPage, module_statuses

# 導覽選單的頁面工廠表。放在套件入口而不是 nav.py，因為只有這裡同時看得到五個頁面模組；
# nav.py 反過來在 callback 內延遲匯入本模組，依賴方向才不會成環。
#
# model_panel 刻意不放進來：它是從 AI 頁點進去的一次性挑選器，不是導覽的一站
# （見 ai.ModelPanel 的說明），nav 的選項集合與 PANELS 的鍵必須一一對應。
PANELS: dict[str, Callable[..., Awaitable[discord.ui.LayoutView]]] = {
    NAV_HOME: settings_panel,
    NAV_LOG: log_page,
    NAV_ECONOMY: economy_page,
    NAV_POLL: poll_page,
    NAV_AI: ai_page,
}

__all__ = [
    "AIPage",
    "AIQuotaModal",
    "EconomyPage",
    "EconomySettingsModal",
    "LogPage",
    "ModelPanel",
    "PANELS",
    "PollPage",
    "SettingsModal",
    "SettingsPage",
    "SettingsPanel",
    "ai_page",
    "economy_page",
    "log_page",
    "model_panel",
    "module_statuses",
    "nav_row",
    "poll_page",
    "settings_panel",
]
