from __future__ import annotations

import pytest
import pytest_asyncio

from src.services.blackjack import TERMINAL_PHASES, BlackjackService
from src.services.common import ValidationError
from src.services.settings import SettingsService

# 規則引擎會寫入 game.phase 的所有值（rules.py 各處 state["phase"] = ...）。
ALL_PHASES = frozenset(
    {
        "playing",
        "insurance",
        "dealer_blackjack",
        "player_done",
        "dealer",
        "settling",
        "settled",
        "refunded",
    }
)


def test_only_settled_and_refunded_count_as_terminal():
    """曾經有一份 ACTIVE_PHASES 只列了 3 個進行中狀態，漏掉另外 3 個。

    以終態列舉是為了讓「新增中間狀態」不必同步維護第二份清單，這裡釘住
    兩者互補，避免哪天多寫一個 phase 卻忘了它會被當成進行中。
    """
    assert set(TERMINAL_PHASES) == {"settled", "refunded"}
    assert set(TERMINAL_PHASES) <= ALL_PHASES
    active = ALL_PHASES - set(TERMINAL_PHASES)
    assert active == {
        "playing",
        "insurance",
        "dealer_blackjack",
        "player_done",
        "dealer",
        "settling",
    }


def shoe_for(*draws: str) -> list[str]:
    return ["2C"] * 20 + list(reversed(draws))


@pytest_asyncio.fixture
async def service(db, economy):
    # BlackjackService 需要 SettingsService 才能取得下注上下限（不再繞過直接查表），
    # 各測試共用同一套建構方式，避免每個案例各自組一次。
    return BlackjackService(db, economy, SettingsService(db))


async def test_start_settlement_and_refund_paths(db, economy, service):
    await economy.apply(
        guild_id=1,
        user_id=10,
        amount=100,
        transaction_type="admin",
        idempotency_key="seed",
    )
    natural = await service.start(
        guild_id=1,
        user_id=10,
        channel_id=20,
        bet=10,
        idempotency_key="natural",
        shoe=shoe_for("AS", "9H", "KD", "7C"),
    )
    assert natural.game.phase == "settled"
    assert await economy.balance(1, 10) == 115

    active = await service.start(
        guild_id=1,
        user_id=10,
        channel_id=20,
        bet=20,
        idempotency_key="active",
        shoe=shoe_for("10S", "6H", "7D", "9C"),
    )
    assert active.game.phase == "playing"
    refunded = await service.refund_missing_message(active.game.id)
    assert refunded == 20
    assert await economy.balance(1, 10) == 115


async def test_timeout_auto_stands_and_settles(db, economy, service):
    await economy.apply(
        guild_id=1,
        user_id=10,
        amount=100,
        transaction_type="admin",
        idempotency_key="seed",
    )
    started = await service.start(
        guild_id=1,
        user_id=10,
        channel_id=20,
        bet=10,
        idempotency_key="timeout",
        shoe=shoe_for("10S", "6H", "8D", "9C", "10H"),
    )
    result = await service.timeout(started.game.id)
    assert result.game.phase == "settled"
    assert result.game.outcome["hands"][0]["result"] == "win"
    assert await economy.balance(1, 10) == 110


async def test_odd_bet_is_rejected_to_keep_three_to_two_exact(db, economy, service):
    await economy.apply(
        guild_id=1,
        user_id=10,
        amount=100,
        transaction_type="admin",
        idempotency_key="seed",
    )
    with pytest.raises(ValidationError, match="偶數"):
        await service.start(
            guild_id=1,
            user_id=10,
            channel_id=20,
            bet=11,
            idempotency_key="odd",
        )
    assert await economy.balance(1, 10) == 100


async def test_parallel_users_have_isolated_games(db, economy, service):
    for user_id in (10, 20):
        await economy.apply(
            guild_id=1,
            user_id=user_id,
            amount=100,
            transaction_type="admin",
            idempotency_key=f"seed-{user_id}",
        )
    first = await service.start(
        guild_id=1,
        user_id=10,
        channel_id=20,
        bet=10,
        idempotency_key="first-user",
        shoe=shoe_for("10S", "6H", "7D", "9C"),
    )
    second = await service.start(
        guild_id=1,
        user_id=20,
        channel_id=20,
        bet=20,
        idempotency_key="second-user",
        shoe=shoe_for("9S", "6D", "8H", "9D"),
    )
    assert first.game.id != second.game.id
    # get_active() 已刪除（生產碼零呼叫），改用 recoverable() 過濾 user_id 驗證同等行為：
    # 兩位玩家的進行中牌局彼此獨立、不會互相覆蓋。
    recoverable = await service.recoverable()
    assert next(g for g in recoverable if g.user_id == 10).id == first.game.id
    assert next(g for g in recoverable if g.user_id == 20).id == second.game.id
    assert await economy.balance(1, 10) == 90
    assert await economy.balance(1, 20) == 80


async def test_start_for_brand_new_guild_uses_default_bet_limits(db, economy, service):
    """全新 guild（GuildSettings 列尚不存在）直接開局：
    get_in_session() 走 get-or-create，若少了 flush，剛建立物件的
    blackjack_min_bet/max_bet 會是 None，比較 minimum <= bet 會直接 TypeError。
    這裡驗證預設下限 10、上限 10_000（與 models.py 的欄位 default 一致）確實生效。
    """
    guild_id = 999  # 從未被任何 SettingsService 呼叫碰過的全新 guild
    await economy.apply(
        guild_id=guild_id,
        user_id=10,
        amount=100,
        transaction_type="admin",
        idempotency_key="seed",
    )
    with pytest.raises(ValidationError, match="介於 10 與 10000"):
        await service.start(
            guild_id=guild_id,
            user_id=10,
            channel_id=20,
            bet=8,
            idempotency_key="below-default-min",
        )
    started = await service.start(
        guild_id=guild_id,
        user_id=10,
        channel_id=20,
        bet=10,
        idempotency_key="at-default-min",
        shoe=shoe_for("10S", "6H", "7D", "9C"),
    )
    assert started.game.phase == "playing"
