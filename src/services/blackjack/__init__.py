"""Blackjack 套件對外入口。

維持既有 import 路徑,呼叫端(src/bot.py、src/ui/blackjack.py、src/cogs/blackjack.py)
與測試(tests/test_blackjack.py、tests/test_blackjack_service.py)皆從
`src.services.blackjack` 匯入,故在此重新匯出 rules(純規則引擎)與
service(持久化轉接層)的所有公開名稱,呼叫端不需改動。
"""

from __future__ import annotations

from src.services.blackjack.rules import (
    RANKS,
    SUIT_DISPLAY,
    SUITS,
    TERMINAL_PHASES,
    can_double,
    can_split,
    can_surrender,
    card_rank,
    deal_round,
    dealer_play,
    display_card,
    display_cards,
    double_down,
    hand_value,
    hit,
    is_blackjack,
    new_shoe,
    resolve_insurance,
    settle_round,
    split_hand,
    stand,
    surrender,
)
from src.services.blackjack.service import (
    ACTION_TIMEOUT,
    BlackjackOperationResult,
    BlackjackService,
    save_state,
    state_from_game,
)

__all__ = [
    "ACTION_TIMEOUT",
    "RANKS",
    "SUIT_DISPLAY",
    "SUITS",
    "TERMINAL_PHASES",
    "BlackjackOperationResult",
    "BlackjackService",
    "can_double",
    "can_split",
    "can_surrender",
    "card_rank",
    "deal_round",
    "dealer_play",
    "display_card",
    "display_cards",
    "double_down",
    "hand_value",
    "hit",
    "is_blackjack",
    "new_shoe",
    "resolve_insurance",
    "save_state",
    "settle_round",
    "split_hand",
    "stand",
    "state_from_game",
    "surrender",
]
