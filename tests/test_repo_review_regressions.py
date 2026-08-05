from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.config import Settings
from src.database.engine import Database
from src.database.models import Giveaway, Poll
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
