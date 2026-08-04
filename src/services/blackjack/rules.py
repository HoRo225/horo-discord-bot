from __future__ import annotations

import random
from typing import Any

from src import strings
from src.services.common import ConflictError, ValidationError

RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
SUITS = ("S", "H", "D", "C")
SUIT_DISPLAY = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
ACTIVE_PHASES = ("insurance", "playing", "dealer")


def card_rank(card: str) -> str:
    return card[:-1]


def display_card(card: str) -> str:
    return f"{card_rank(card)}{SUIT_DISPLAY.get(card[-1], card[-1])}"


def display_cards(cards: list[str], *, hide_second: bool = False) -> str:
    shown = [display_card(card) for card in cards]
    if hide_second and len(shown) > 1:
        shown[1] = "🂠"
    return " ".join(shown)


def new_shoe(
    *, rng: random.Random | random.SystemRandom | None = None, decks: int = 6
) -> list[str]:
    if decks <= 0:
        raise ValidationError(strings.ERR_DECKS_POSITIVE)
    cards = [f"{rank}{suit}" for _ in range(decks) for suit in SUITS for rank in RANKS]
    (rng or random.SystemRandom()).shuffle(cards)
    return cards


def hand_value(cards: list[str]) -> tuple[int, bool]:
    total = 0
    aces = 0
    for card in cards:
        rank = card_rank(card)
        if rank == "A":
            aces += 1
            total += 11
        elif rank in {"J", "Q", "K"}:
            total += 10
        else:
            total += int(rank)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total, aces > 0


def is_blackjack(cards: list[str]) -> bool:
    return len(cards) == 2 and hand_value(cards)[0] == 21


def _draw(state: dict[str, Any]) -> str:
    shoe: list[str] = state["shoe"]
    if not shoe:
        raise RuntimeError(strings.ERR_SHOE_EMPTY)
    return shoe.pop()


def _new_hand(cards: list[str], bet: int, *, from_split: bool = False) -> dict[str, Any]:
    return {
        "cards": cards,
        "bet": bet,
        "status": "playing",
        "from_split": from_split,
        "split_aces": False,
        "actions": 0,
        "doubled": False,
    }


def deal_round(bet: int, *, shoe: list[str] | None = None) -> dict[str, Any]:
    if bet <= 0:
        raise ValidationError(strings.ERR_BET_POSITIVE)
    state: dict[str, Any] = {
        "shoe": list(shoe) if shoe is not None else new_shoe(),
        "dealer": [],
        "hands": [_new_hand([], bet)],
        "active_hand": 0,
        "phase": "playing",
        "insurance_bet": 0,
    }
    if len(state["shoe"]) < 4:
        raise ValidationError(strings.ERR_SHOE_TOO_SMALL)
    state["hands"][0]["cards"].append(_draw(state))
    state["dealer"].append(_draw(state))
    state["hands"][0]["cards"].append(_draw(state))
    state["dealer"].append(_draw(state))

    dealer_up = card_rank(state["dealer"][0])
    player_natural = is_blackjack(state["hands"][0]["cards"])
    if dealer_up == "A":
        state["phase"] = "insurance"
    elif dealer_up in {"10", "J", "Q", "K"} and is_blackjack(state["dealer"]):
        state["phase"] = "dealer_blackjack"
    elif player_natural:
        state["hands"][0]["status"] = "blackjack"
        state["phase"] = "player_done"
    return state


def resolve_insurance(state: dict[str, Any], insurance_bet: int = 0) -> None:
    if state["phase"] != "insurance":
        raise ConflictError(strings.ERR_INSURANCE_PHASE)
    maximum = state["hands"][0]["bet"] // 2
    if insurance_bet not in (0, maximum):
        raise ValidationError(strings.ERR_INSURANCE_AMOUNT)
    state["insurance_bet"] = insurance_bet
    if is_blackjack(state["dealer"]):
        state["phase"] = "dealer_blackjack"
    elif is_blackjack(state["hands"][0]["cards"]):
        state["hands"][0]["status"] = "blackjack"
        state["phase"] = "player_done"
    else:
        state["phase"] = "playing"


def _current_hand(state: dict[str, Any]) -> dict[str, Any]:
    if state["phase"] != "playing":
        raise ConflictError(strings.ERR_PLAYER_PHASE)
    index = state["active_hand"]
    try:
        hand = state["hands"][index]
    except IndexError as exc:
        raise ConflictError(strings.ERR_CURRENT_HAND) from exc
    if hand["status"] != "playing":
        raise ConflictError(strings.ERR_HAND_FINISHED)
    return hand


def can_double(state: dict[str, Any]) -> bool:
    try:
        hand = _current_hand(state)
    except ConflictError:
        return False
    return len(hand["cards"]) == 2 and hand["actions"] == 0


def _split_value(card: str) -> int:
    rank = card_rank(card)
    if rank == "A":
        return 11
    if rank in {"10", "J", "Q", "K"}:
        return 10
    return int(rank)


def can_split(state: dict[str, Any]) -> bool:
    try:
        hand = _current_hand(state)
    except ConflictError:
        return False
    cards = hand["cards"]
    return (
        len(state["hands"]) < 4
        and len(cards) == 2
        and hand["actions"] == 0
        and not hand.get("split_aces", False)
        and _split_value(cards[0]) == _split_value(cards[1])
    )


def can_surrender(state: dict[str, Any]) -> bool:
    try:
        hand = _current_hand(state)
    except ConflictError:
        return False
    return (
        len(state["hands"]) == 1
        and len(hand["cards"]) == 2
        and hand["actions"] == 0
        and not hand["from_split"]
    )


def _advance(state: dict[str, Any]) -> None:
    for index in range(state["active_hand"] + 1, len(state["hands"])):
        if state["hands"][index]["status"] == "playing":
            state["active_hand"] = index
            return
    state["phase"] = "dealer"


def hit(state: dict[str, Any]) -> None:
    hand = _current_hand(state)
    hand["cards"].append(_draw(state))
    hand["actions"] += 1
    value, _ = hand_value(hand["cards"])
    if value > 21:
        hand["status"] = "busted"
        _advance(state)
    elif value == 21:
        hand["status"] = "standing"
        _advance(state)


def stand(state: dict[str, Any]) -> None:
    hand = _current_hand(state)
    hand["status"] = "standing"
    hand["actions"] += 1
    _advance(state)


def double_down(state: dict[str, Any]) -> None:
    if not can_double(state):
        raise ConflictError(strings.ERR_DOUBLE)
    hand = _current_hand(state)
    hand["bet"] *= 2
    hand["doubled"] = True
    hand["actions"] += 1
    hand["cards"].append(_draw(state))
    hand["status"] = "busted" if hand_value(hand["cards"])[0] > 21 else "standing"
    _advance(state)


def split_hand(state: dict[str, Any]) -> None:
    if not can_split(state):
        raise ConflictError(strings.ERR_SPLIT)
    index = state["active_hand"]
    original = state["hands"][index]
    left_card, right_card = original["cards"]
    splitting_aces = card_rank(left_card) == "A"
    left = _new_hand([left_card], original["bet"], from_split=True)
    right = _new_hand([right_card], original["bet"], from_split=True)
    left["split_aces"] = splitting_aces
    right["split_aces"] = splitting_aces
    left["cards"].append(_draw(state))
    right["cards"].append(_draw(state))
    state["hands"][index : index + 1] = [left, right]
    state["active_hand"] = index
    for hand in (left, right):
        value = hand_value(hand["cards"])[0]
        if splitting_aces or value == 21:
            hand["status"] = "standing"
    if left["status"] != "playing":
        if right["status"] == "playing":
            state["active_hand"] = index + 1
        else:
            _advance(state)


def surrender(state: dict[str, Any]) -> None:
    if not can_surrender(state):
        raise ConflictError(strings.ERR_SURRENDER)
    hand = _current_hand(state)
    hand["status"] = "surrendered"
    hand["actions"] += 1
    _advance(state)


def dealer_play(state: dict[str, Any]) -> None:
    if state["phase"] != "dealer":
        raise ConflictError(strings.ERR_DEALER_PHASE)
    live_hands = [
        hand for hand in state["hands"] if hand["status"] not in {"busted", "surrendered"}
    ]
    if live_hands:
        while True:
            total, soft = hand_value(state["dealer"])
            if total < 17 or (total == 17 and soft):
                state["dealer"].append(_draw(state))
                continue
            break
    state["phase"] = "settling"


def settle_round(state: dict[str, Any]) -> dict[str, Any]:
    if state["phase"] not in {
        "dealer_blackjack",
        "player_done",
        "settling",
    }:
        raise ConflictError(strings.ERR_SETTLEMENT_PHASE)
    dealer_total, _ = hand_value(state["dealer"])
    dealer_natural = is_blackjack(state["dealer"])
    hand_results: list[dict[str, Any]] = []
    total_credit = 0
    total_staked = int(state.get("insurance_bet", 0))

    for hand in state["hands"]:
        bet = int(hand["bet"])
        total_staked += bet
        player_total, _ = hand_value(hand["cards"])
        natural = not hand["from_split"] and is_blackjack(hand["cards"])
        if hand["status"] == "surrendered":
            result, credit = "surrender", bet // 2
        elif player_total > 21:
            result, credit = "loss", 0
        elif dealer_natural:
            if natural:
                result, credit = "push", bet
            else:
                result, credit = "loss", 0
        elif natural:
            result, credit = "blackjack", (bet * 5) // 2
        elif dealer_total > 21 or player_total > dealer_total:
            result, credit = "win", bet * 2
        elif player_total == dealer_total:
            result, credit = "push", bet
        else:
            result, credit = "loss", 0
        total_credit += credit
        hand_results.append(
            {
                "result": result,
                "credit": credit,
                "bet": bet,
                "value": player_total,
                "cards": list(hand["cards"]),
            }
        )

    insurance_bet = int(state.get("insurance_bet", 0))
    insurance_credit = insurance_bet * 3 if dealer_natural else 0
    total_credit += insurance_credit
    return {
        "hands": hand_results,
        "dealer_cards": list(state["dealer"]),
        "dealer_value": dealer_total,
        "dealer_blackjack": dealer_natural,
        "insurance_credit": insurance_credit,
        "staked": total_staked,
        "credit": total_credit,
        "net": total_credit - total_staked,
    }
