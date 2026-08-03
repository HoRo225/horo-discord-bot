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
