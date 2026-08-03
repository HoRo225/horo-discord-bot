from __future__ import annotations

from src.services.blackjack import (
    can_split,
    deal_round,
    dealer_play,
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


def shoe_for(*draws: str) -> list[str]:
    return ["2C"] * 20 + list(reversed(draws))


def test_six_deck_shoe_and_ace_scoring():
    assert len(new_shoe()) == 312
    assert hand_value(["AS", "6H"]) == (17, True)
    assert hand_value(["AS", "6H", "10D"]) == (17, False)
    assert is_blackjack(["AS", "KH"])


def test_dealer_peek_and_natural_push():
    state = deal_round(10, shoe=shoe_for("AS", "KH", "QD", "AC"))
    assert state["phase"] == "dealer_blackjack"
    result = settle_round(state)
    assert result["hands"][0]["result"] == "push"
    assert result["credit"] == 10


def test_insurance_pays_two_to_one_when_dealer_has_blackjack():
    state = deal_round(10, shoe=shoe_for("9S", "AH", "7D", "KC"))
    assert state["phase"] == "insurance"
    resolve_insurance(state, 5)
    result = settle_round(state)
    assert result["insurance_credit"] == 15
    assert result["net"] == 0


def test_blackjack_pays_three_to_two():
    state = deal_round(10, shoe=shoe_for("AS", "9H", "KD", "7C"))
    assert state["phase"] == "player_done"
    result = settle_round(state)
    assert result["hands"][0]["result"] == "blackjack"
    assert result["credit"] == 25


def test_h17_dealer_hits_soft_seventeen():
    state = {
        "shoe": shoe_for("2D"),
        "dealer": ["AS", "6H"],
        "hands": [
            {
                "cards": ["10S", "8D"],
                "bet": 10,
                "status": "standing",
                "from_split": False,
                "split_aces": False,
                "actions": 1,
                "doubled": False,
            }
        ],
        "active_hand": 0,
        "phase": "dealer",
        "insurance_bet": 0,
    }
    dealer_play(state)
    assert state["dealer"][-1] == "2D"
    assert hand_value(state["dealer"])[0] == 19
    assert settle_round(state)["hands"][0]["result"] == "loss"


def test_late_surrender_returns_half_bet():
    state = deal_round(10, shoe=shoe_for("10S", "9H", "6D", "7C"))
    surrender(state)
    dealer_play(state)
    result = settle_round(state)
    assert result["hands"][0]["result"] == "surrender"
    assert result["credit"] == 5


def test_split_aces_receive_one_card_each_and_stop():
    state = deal_round(
        10,
        shoe=shoe_for("AS", "5H", "AD", "9C", "10S", "9D"),
    )
    assert can_split(state)
    split_hand(state)
    assert len(state["hands"]) == 2
    assert all(hand["status"] == "standing" for hand in state["hands"])
    assert state["phase"] == "dealer"
    assert not can_split(state)


def test_split_twenty_one_is_not_natural():
    state = deal_round(
        10,
        shoe=shoe_for("10S", "6H", "KD", "9C", "AS", "AH"),
    )
    split_hand(state)
    dealer_play(state)
    result = settle_round(state)
    assert [hand["result"] for hand in result["hands"]] == ["win", "win"]
    assert result["credit"] == 40


def test_hit_bust_advances_to_dealer():
    state = deal_round(10, shoe=shoe_for("10S", "6H", "9D", "9C", "5S"))
    hit(state)
    assert state["hands"][0]["status"] == "busted"
    assert state["phase"] == "dealer"


def test_double_after_split_is_allowed():
    state = deal_round(
        10,
        shoe=shoe_for(
            "8S",
            "5H",
            "8D",
            "9C",
            "3S",
            "2H",
            "10D",
            "9D",
        ),
    )
    split_hand(state)
    double_down(state)
    double_down(state)
    assert [hand["bet"] for hand in state["hands"]] == [20, 20]
    assert [hand_value(hand["cards"])[0] for hand in state["hands"]] == [21, 19]
    assert state["phase"] == "dealer"


def test_split_is_capped_at_four_hands():
    state = deal_round(
        10,
        shoe=shoe_for(
            "8S",
            "5H",
            "8H",
            "9C",
            "8D",
            "8C",
            "2S",
            "3S",
            "8S",
            "8H",
        ),
    )
    split_hand(state)
    split_hand(state)
    stand(state)
    stand(state)
    assert can_split(state)
    split_hand(state)
    assert len(state["hands"]) == 4
    assert not can_split(state)
