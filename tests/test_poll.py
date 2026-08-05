from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from src.database.models import PollVote
from src.services.common import ValidationError
from src.services.poll import PollAnswerSnapshot, PollService, validate_poll


def test_poll_limits():
    assert validate_poll("題目", ["A", "B"], timedelta(hours=1))
    assert validate_poll("題目", ["A", "B"], timedelta(days=32))
    with pytest.raises(ValidationError):
        validate_poll("x" * 301, ["A", "B"], timedelta(hours=1))
    with pytest.raises(ValidationError):
        validate_poll("題目", [str(i) for i in range(11)], timedelta(hours=1))
    with pytest.raises(ValidationError):
        validate_poll("題目", ["A", "A"], timedelta(hours=1))


async def test_poll_completion_persists_results_and_voters(db):
    service = PollService(db)
    poll = await service.create(
        guild_id=1,
        channel_id=10,
        created_by=20,
        question="選哪個？",
        answers=["甲", "乙"],
        duration=timedelta(hours=1),
        multiple=True,
    )
    await service.publish(poll.id, message_id=999)
    completed = await service.complete(
        poll.id,
        [
            PollAnswerSnapshot(1, "甲", 2, [100, 101, 100]),
            PollAnswerSnapshot(2, "乙", 1, [101]),
        ],
    )
    assert completed.status == "completed"
    assert completed.results["answers"][0]["voter_ids"] == [100, 101]
    async with db.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(PollVote))
    assert count == 3


async def test_poll_defaults_to_pending_so_a_missed_status_cannot_orphan(db):
    """ORM 預設若是 active，任何漏傳 status 的新建立路徑都會直接產生孤兒紀錄。"""
    from datetime import UTC, datetime

    from src.database.models import Poll

    async with db.session_factory() as session:
        poll = Poll(
            guild_id=1,
            channel_id=10,
            created_by=20,
            question="沒傳 status",
            answers=["甲", "乙"],
            ends_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(poll)
        await session.flush()

        assert poll.status == "pending"


async def test_unpublished_poll_is_invisible_until_its_message_exists(db):
    """Discord 發訊息失敗時投票停在 pending，背景結算不該把它當成正常活動。"""
    service = PollService(db)
    poll = await service.create(
        guild_id=1,
        channel_id=10,
        created_by=20,
        question="還沒公開",
        answers=["甲", "乙"],
        duration=timedelta(hours=1),
        multiple=False,
    )

    assert poll.status == "pending"
    assert await service.active(1) == []
    assert await service.due(poll.ends_at + timedelta(seconds=1)) == []

    await service.publish(poll.id, message_id=555)

    assert [item.id for item in await service.active(1)] == [poll.id]
    assert [item.id for item in await service.due(poll.ends_at + timedelta(seconds=1))] == [poll.id]
