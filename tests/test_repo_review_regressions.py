from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.config import Settings
from src.database.engine import Database
from src.database.models import Giveaway, GuildSettings, Poll
from src.services.common import ValidationError
from src.services.economy import MAX_BALANCE
from src.services.giveaway import GiveawayService
from src.services.poll import PollService
from src.services.settings import SettingsService
from src.ui.blackjack import start_game
from src.ui.giveaway import CreateGiveawayModal
from src.ui.poll import CreatePollModal


async def test_debit_is_allowed_while_balance_is_above_the_credit_cap(db, economy):
    """內部賠付可超過上限後，扣款必須仍能把餘額往下帶。"""

    async def seed_above_cap(session):
        await economy.apply_in_session(
            session,
            guild_id=1,
            user_id=10,
            amount=MAX_BALANCE,
            transaction_type="admin",
            idempotency_key="fill-cap",
        )
        await economy.apply_in_session(
            session,
            guild_id=1,
            user_id=10,
            amount=500,
            transaction_type="blackjack",
            idempotency_key="settle-over-cap",
            enforce_balance_cap=False,
        )

    await db.run_transaction(seed_above_cap)
    result = await economy.apply(
        guild_id=1,
        user_id=10,
        amount=-100,
        transaction_type="admin",
        idempotency_key="debit-over-cap",
    )

    assert result.balance == MAX_BALANCE + 400


async def test_daily_setting_cannot_disable_daily_with_zero(db):
    service = SettingsService(db)

    with pytest.raises(ValidationError):
        await service.update(
            1,
            99,
            action="settings_economy",
            values={"daily_amount": 0},
        )


async def test_blackjack_setting_range_must_contain_an_even_bet(db):
    service = SettingsService(db)

    with pytest.raises(ValidationError):
        await service.update(
            1,
            99,
            action="settings_economy",
            values={"blackjack_min_bet": 11, "blackjack_max_bet": 11},
        )

    settings = await service.update(
        1,
        99,
        action="settings_economy",
        values={"blackjack_min_bet": 11, "blackjack_max_bet": 12},
    )
    assert settings.blackjack_max_bet == 12


async def test_legacy_odd_bet_range_does_not_lock_unrelated_settings(db):
    """偶數區間規則是後加的，不得讓先前合法存下的設定鎖死整個設定面板。"""
    service = SettingsService(db)
    # 繞過現行驗證，模擬規則加入前就已存在的奇數獨點區間。
    async with db.session_factory() as session:
        settings = GuildSettings(guild_id=1, blackjack_min_bet=11, blackjack_max_bet=11)
        session.add(settings)
        await session.commit()

    updated = await service.update(
        1, 99, action="settings_economy", values={"currency_name": "天鵝幣"}
    )

    assert updated.currency_name == "天鵝幣"
    # 但真的要動下注欄位時，規則仍然生效。
    with pytest.raises(ValidationError):
        await service.update(1, 99, action="settings_economy", values={"blackjack_max_bet": 11})


@pytest.mark.parametrize(
    "url",
    [
        "sqlite+aiosqlite:///:memory:",
        "sqlite+aiosqlite:///file:horo?mode=memory&cache=shared&uri=true",
    ],
)
def test_runtime_rejects_non_file_backed_sqlite(monkeypatch, url):
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", url)

    with pytest.raises(ValueError, match="檔案型 SQLite"):
        Settings.from_env()
    with pytest.raises(ValueError, match="檔案型 SQLite"):
        Database(url)


async def test_stale_pending_giveaway_is_cancelled(db, economy):
    service = GiveawayService(db, economy)
    now = datetime.now(UTC)
    giveaway = await service.create(
        guild_id=1,
        channel_id=10,
        created_by=99,
        prize="stale",
        winner_count=1,
        ends_at=now + timedelta(hours=1),
        ticket_price=0,
        per_user_limit=1,
    )

    async with db.session_factory() as session:
        row = await session.get(Giveaway, giveaway.id)
        row.created_at = now - timedelta(hours=25)
        await session.commit()

    assert await service.cancel_stale_pending(now=now) == 1
    async with db.session_factory() as session:
        assert (await session.get(Giveaway, giveaway.id)).status == "cancelled"


async def test_fresh_pending_giveaway_survives_the_sweep(db, economy):
    """核心保證：清理不得誤殺正在發布中的紀錄。

    create() 與 publish() 之間的窗口通常不到一秒，遠小於 24 小時的保留期；
    這則測試把該保證釘住，避免日後有人把閾值調小。
    """
    service = GiveawayService(db, economy)
    now = datetime.now(UTC)
    giveaway = await service.create(
        guild_id=1,
        channel_id=10,
        created_by=99,
        prize="剛建立",
        winner_count=1,
        ends_at=now + timedelta(hours=1),
        ticket_price=0,
        per_user_limit=1,
    )

    assert await service.cancel_stale_pending(now=now) == 0
    async with db.session_factory() as session:
        assert (await session.get(Giveaway, giveaway.id)).status == "pending"

    # 已 publish 的活動就算超過保留期也不該被碰。
    await service.publish(giveaway.id, message_id=777)
    async with db.session_factory() as session:
        row = await session.get(Giveaway, giveaway.id)
        row.created_at = now - timedelta(days=30)
        await session.commit()

    assert await service.cancel_stale_pending(now=now) == 0
    async with db.session_factory() as session:
        assert (await session.get(Giveaway, giveaway.id)).status == "active"


async def test_stale_pending_poll_is_cancelled(db):
    service = PollService(db)
    now = datetime.now(UTC)
    poll = await service.create(
        guild_id=1,
        channel_id=10,
        created_by=99,
        question="stale?",
        answers=["yes", "no"],
        duration=timedelta(hours=1),
        multiple=False,
        now=now,
    )

    async with db.session_factory() as session:
        row = await session.get(Poll, poll.id)
        row.created_at = now - timedelta(hours=25)
        await session.commit()

    assert await service.cancel_stale_pending(now=now) == 1
    async with db.session_factory() as session:
        assert (await session.get(Poll, poll.id)).status == "cancelled"


class FakeResponse:
    def __init__(self) -> None:
        self.done = False

    def is_done(self) -> bool:
        return self.done

    async def defer(self, **_kwargs) -> None:
        self.done = True


class FakeFollowup:
    async def send(self, *_args, **_kwargs) -> None:
        return None


class FakeInteraction(SimpleNamespace):
    def __init__(self, *, channel) -> None:
        super().__init__(
            guild_id=1,
            channel_id=10,
            channel=channel,
            id=1234,
            user=SimpleNamespace(
                id=99,
                guild_permissions=SimpleNamespace(manage_guild=True),
                roles=[],
            ),
            response=FakeResponse(),
            followup=FakeFollowup(),
        )

    async def edit_original_response(self, **_kwargs) -> None:
        return None


class RecordingMessage:
    def __init__(self) -> None:
        self.id = 555
        self.channel = SimpleNamespace(id=10)
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


class RecordingChannel:
    def __init__(self, message: RecordingMessage) -> None:
        self.message = message

    async def send(self, *_args, **_kwargs):
        return self.message


class CancellingGiveaways:
    async def create(self, **_kwargs):
        return SimpleNamespace(
            id=7,
            prize="gift",
            winner_count=1,
            ticket_price=0,
            per_user_limit=1,
            status="pending",
            ends_at=datetime.now(UTC) + timedelta(hours=1),
        )

    async def publish(self, _giveaway_id, _message_id):
        raise asyncio.CancelledError


async def test_giveaway_publish_cancellation_withdraws_message():
    message = RecordingMessage()
    modal = CreateGiveawayModal(SimpleNamespace(giveaways=CancellingGiveaways()))
    modal.prize, modal.winners, modal.duration = "gift", "1", "1h"
    modal.price, modal.limit = "0", "1"
    interaction = FakeInteraction(channel=RecordingChannel(message))

    with pytest.raises(asyncio.CancelledError):
        await modal.on_submit(interaction)

    assert message.deleted is True


class CancellingPolls:
    async def create(self, **_kwargs):
        return SimpleNamespace(id=8, question="question", answers=["yes", "no"])

    async def publish(self, _poll_id, _message_id):
        raise asyncio.CancelledError


async def test_poll_publish_cancellation_withdraws_message():
    message = RecordingMessage()
    modal = CreatePollModal(SimpleNamespace(polls=CancellingPolls()))
    modal.question = "question"
    modal.options = "yes\nno"
    modal.duration = "1"
    modal.multiple = "否"
    interaction = FakeInteraction(channel=RecordingChannel(message))

    with pytest.raises(asyncio.CancelledError):
        await modal.on_submit(interaction)

    assert message.deleted is True


def active_blackjack_game():
    return SimpleNamespace(
        id="game-1",
        phase="insurance",
        dealer_cards=["AS", "6H"],
        hands=[{"cards": ["10S", "7D"], "bet": 10, "status": "playing"}],
        active_hand=0,
        outcome={},
        user_id=99,
        shoe=[],
        insurance_bet=0,
    )


class CancellingBlackjack:
    def __init__(self) -> None:
        self.refunded = False

    async def start(self, **_kwargs):
        return SimpleNamespace(game=active_blackjack_game(), settled_now=False)

    async def attach_message(self, _game_id, _message_id):
        raise asyncio.CancelledError

    async def refund_missing_message(self, _game_id):
        self.refunded = True
        return 10


async def test_blackjack_attach_cancellation_refunds_and_withdraws_message():
    message = RecordingMessage()
    blackjack = CancellingBlackjack()
    bot = SimpleNamespace(blackjack=blackjack)
    interaction = FakeInteraction(channel=RecordingChannel(message))

    with pytest.raises(asyncio.CancelledError):
        await start_game(bot, interaction, 10)

    assert blackjack.refunded is True
    assert message.deleted is True


class FlakyCleanupGiveaways:
    """清理會炸、結算正常——用來釘住「維護工作不得擋掉結算」。"""

    def __init__(self) -> None:
        self.finalized: list[int] = []
        self.sweep_attempts = 0

    async def cancel_stale_pending(self, now=None):
        self.sweep_attempts += 1
        raise RuntimeError("database is locked")

    async def due(self, now=None):
        return [SimpleNamespace(id=1, guild_id=1, channel_id=10)]

    async def finalize(self, giveaway_id):
        self.finalized.append(giveaway_id)
        raise RuntimeError("停在這裡就好，本測試只在意 finalize 有沒有被呼叫")


async def test_cleanup_failure_cannot_block_giveaway_settlement():
    from src.cogs import giveaway as giveaway_cog

    service = FlakyCleanupGiveaways()
    cog = giveaway_cog.GiveawayCog(SimpleNamespace(giveaways=service))
    # 讓這一 tick 剛好輪到清理，確保它真的被呼叫到而不是被降頻跳過。
    cog._ticks = giveaway_cog.STALE_SWEEP_EVERY_TICKS - 1

    await cog.finish_due()

    assert service.finalized == [1], "清理失敗時結算被跳過了"
    assert service.sweep_attempts == 1


async def test_due_scan_failure_still_runs_cleanup_and_keeps_loop_alive():
    """掃描失敗不該讓例外逃出 tasks.loop，否則整個背景結算會靜默停擺。"""
    from src.cogs import poll as poll_cog

    swept = []

    class BrokenScanPolls:
        async def due(self, now=None):
            raise RuntimeError("scan boom")

        async def cancel_stale_pending(self, now=None):
            swept.append(True)
            return 0

    cog = poll_cog.PollCog(SimpleNamespace(polls=BrokenScanPolls()))
    cog._ticks = poll_cog.STALE_SWEEP_EVERY_TICKS - 1

    await cog.finish_due()

    assert swept == [True], "掃描失敗把後續的清理也一起跳過了"
