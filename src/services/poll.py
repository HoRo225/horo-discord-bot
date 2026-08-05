from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src import strings
from src.database.engine import Database
from src.database.models import Poll, PollVote
from src.services.common import ConflictError, NotFoundError, ValidationError, aware_utc

MIN_DURATION = timedelta(hours=1)
MAX_DURATION = timedelta(days=32)


def validate_poll(
    question: str,
    answers: list[str],
    duration: timedelta,
) -> tuple[str, list[str]]:
    question = question.strip()
    cleaned = [answer.strip() for answer in answers if answer.strip()]
    if not 1 <= len(question) <= 300:
        raise ValidationError(strings.ERR_POLL_QUESTION)
    if not 2 <= len(cleaned) <= 10:
        raise ValidationError(strings.ERR_POLL_ANSWER_COUNT)
    if any(len(answer) > 55 for answer in cleaned):
        raise ValidationError(strings.ERR_POLL_ANSWER_LENGTH)
    if len(set(cleaned)) != len(cleaned):
        raise ValidationError(strings.ERR_POLL_DUPLICATE)
    if not MIN_DURATION <= duration <= MAX_DURATION:
        raise ValidationError(strings.ERR_POLL_DURATION)
    return question, cleaned


@dataclass(frozen=True, slots=True)
class PollAnswerSnapshot:
    answer_id: int
    text: str
    vote_count: int
    voter_ids: list[int]


class PollService:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(
        self,
        *,
        guild_id: int,
        channel_id: int,
        created_by: int,
        question: str,
        answers: list[str],
        duration: timedelta,
        multiple: bool,
        now: datetime | None = None,
    ) -> Poll:
        question, answers = validate_poll(question, answers, duration)
        current = aware_utc(now or datetime.now(UTC))

        async def operation(session: AsyncSession) -> Poll:
            poll = Poll(
                guild_id=guild_id,
                channel_id=channel_id,
                created_by=created_by,
                question=question,
                answers=answers,
                multiple=multiple,
                ends_at=current + duration,
                # 先落在 pending，publish() 成功才轉 active。Discord 發訊息失敗時
                # 這筆就停在 pending，而 active()/due() 都只看 active，因此不需要
                # 任何補償動作也不會被背景結算當成正常投票。
                status="pending",
            )
            session.add(poll)
            await session.flush()
            return poll

        return await self.db.run_transaction(operation)

    async def publish(self, poll_id: int, message_id: int) -> None:
        """綁定公告訊息並讓投票正式生效；兩者必須在同一交易內完成。"""

        async def operation(session: AsyncSession) -> None:
            poll = await session.get(Poll, poll_id)
            if poll is None:
                raise NotFoundError(strings.ERR_POLL_NOT_FOUND)
            poll.message_id = message_id
            if poll.status == "pending":
                poll.status = "active"

        await self.db.run_transaction(operation)

    async def active(self, guild_id: int) -> list[Poll]:
        async with self.db.session_factory() as session:
            return list(
                await session.scalars(
                    select(Poll)
                    .where(Poll.guild_id == guild_id, Poll.status == "active")
                    .order_by(Poll.ends_at.asc())
                )
            )

    async def due(self, now: datetime | None = None) -> list[Poll]:
        current = aware_utc(now or datetime.now(UTC))
        async with self.db.session_factory() as session:
            return list(
                await session.scalars(
                    select(Poll).where(Poll.status == "active", Poll.ends_at <= current)
                )
            )

    async def complete(self, poll_id: int, answers: list[PollAnswerSnapshot]) -> Poll:
        async def operation(session: AsyncSession) -> Poll:
            poll = await session.get(Poll, poll_id)
            if poll is None:
                raise NotFoundError(strings.ERR_POLL_NOT_FOUND)
            if poll.status == "completed":
                return poll
            if poll.status != "active":
                raise ConflictError(strings.ERR_POLL_STATE)
            await session.execute(delete(PollVote).where(PollVote.poll_id == poll_id))
            result_payload: dict[str, object] = {"answers": []}
            answer_results: list[dict[str, object]] = []
            for answer in answers:
                unique_voters = sorted(set(answer.voter_ids))
                answer_results.append(
                    {
                        "answer_id": answer.answer_id,
                        "text": answer.text,
                        "vote_count": answer.vote_count,
                        "voter_ids": unique_voters,
                    }
                )
                session.add_all(
                    PollVote(poll_id=poll_id, answer_id=answer.answer_id, user_id=user_id)
                    for user_id in unique_voters
                )
            result_payload["answers"] = answer_results
            poll.results = result_payload
            poll.status = "completed"
            poll.finalized_at = datetime.now(UTC)
            await session.flush()
            return poll

        return await self.db.run_transaction(operation)
