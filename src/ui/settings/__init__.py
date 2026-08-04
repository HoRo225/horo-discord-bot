"""settings 面板套件對外入口。

維持既有 import 路徑，呼叫端（src/cogs/admin.py）與測試
（tests/test_ui_and_cogs.py）皆從 `src.ui.settings` 匯入，
故在此重新匯出各子模組的公開名稱，呼叫端不需改動。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord

from src.ui.settings.ai import AISettingsModal, ModelPanel, model_panel
from src.ui.settings.economy import EconomySettingsModal
from src.ui.settings.logging import LogSettingsModal, LogTogglePanel, log_toggle_panel
from src.ui.settings.nav import NAV_HOME, NAV_LOG_TOGGLES, NAV_MODEL, nav_row
from src.ui.settings.panel import SettingsPanel, module_statuses, settings_panel
from src.ui.settings.poll import PollSettingsModal
from src.ui.settings.shared import SettingsModal

# 導覽選單的頁面工廠表。放在套件入口而不是 nav.py，因為只有這裡同時看得到三個面板模組；
# nav.py 反過來在 callback 內延遲匯入本模組，依賴方向才不會成環。
PANELS: dict[str, Callable[..., Awaitable[discord.ui.LayoutView]]] = {
    NAV_HOME: settings_panel,
    NAV_LOG_TOGGLES: log_toggle_panel,
    NAV_MODEL: model_panel,
}

__all__ = [
    "AISettingsModal",
    "EconomySettingsModal",
    "LogSettingsModal",
    "LogTogglePanel",
    "ModelPanel",
    "PANELS",
    "PollSettingsModal",
    "SettingsModal",
    "SettingsPanel",
    "log_toggle_panel",
    "model_panel",
    "module_statuses",
    "nav_row",
    "settings_panel",
]
