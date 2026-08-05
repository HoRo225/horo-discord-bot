from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import strings
from src.database.engine import Database
from src.database.models import AdminAudit, Giveaway, GiveawayEntry
from src.services.common import ConflictError, NotFoundError, ValidationError, aware_utc
from src.services.economy import EconomyService


def weighted_sample_without_replacement(
    entries: list[tuple[int, int]],
    count: int,
    *,
    rng: random.Random | random.SystemRandom | None = None,
) -> list[int]:
    if count <= 0:
        return []
    pool = [(user_id, weight) for user_id, weight in entries if weight > 0]
    picker = rng or random.SystemRandom()
    winners: list[int] = []
    while pool and len(winners) < count:
        total = sum(weight for _, weight in pool)
        choice = picker.randrange(total)
        cursor = 0
        selected_index = 0
        for index, (_, weight) in enumerate(pool):
            cursor += weight
            if choice < cursor:
                selected_index = index
                break
        winners.append(pool.pop(selected_index)[0])
    return winners


@dataclass(frozen=True, slots=True)
class EntryResult:
    weight: int
    charged: int
    created: bool


class GiveawayService:
    def __init__(self, db: Database, economy: EconomyService) -> None:
        self.db = db
        self.economy = economy

    async def create(
        self,
        *,
        guild_id: int,
        channel_id: int,
        created_by: int,
        prize: str,
        winner_count: int,
        ends_at: datetime,
        ticket_price: int,
        per_user_limit: int,
    ) -> Giveaway:
        prize = prize.strip()
        if not 1 <= len(prize) <= 300:
            raise ValidationError(strings.ERR_PRIZE_LENGTH)
        if not 1 <= winner_count <= 20:
            raise ValidationError(strings.ERR_WINNER_COUNT)
        if aware_utc(ends_at) <= datetime.now(UTC):
            raise ValidationError(strings.ERR_END_FUTURE)
        if ticket_price < 0:
            raise ValidationError(strings.ERR_TICKET_PRICE)
        if not 1 <= per_user_limit <= 10_000:
            raise ValidationError(strings.ERR_ENTRY_LIMIT)

        async def operation(session: AsyncSession) -> Giveaway:
            giveaway = Giveaway(
                guild_id=guild_id,
                channel_id=channel_id,
                created_by=created_by,
                prize=prize,
                winner_count=winner_count,
                ends_at=aware_utc(ends_at),
                ticket_price=ticket_price,
                per_user_limit=per_user_limit,
            )
            session.add(giveaway)
            await session.flush()
            session.add(
                AdminAudit(
                    guild_id=guild_id,
                    admin_user_id=created_by,
                    action="giveaway_create",
                    details={"giveaway_id": giveaway.id, "prize": prize},
                )
            )
            return giveaway

        return await self.db.run_transaction(operation)

    async def attach_message(self, giveaway_id: int, message_id: int) -> None:
        async def operation(session: AsyncSession) -> None:
            giveaway = await session.get(Giveaway, giveaway_id)
            if giveaway is None:
                raise NotFoundError(strings.ERR_GIVEAWAY_NOT_FOUND)
            giveaway.message_id = message_id

        await self.db.run_transaction(operation)

    async def enter(
        self,
        *,
        giveaway_id: int,
        guild_id: int,
        user_id: int,
        quantity: int,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> EntryResult:
        current = aware_utc(now or datetime.now(UTC))
        if quantity <= 0:
            raise ValidationError(strings.ERR_QUANTITY_POSITIVE)

        async def operation(session: AsyncSession) -> EntryResult:
            giveaway = await session.get(Giveaway, giveaway_id)
            if giveaway is None or giveaway.guild_id != guild_id:
                raise NotFoundError(strings.ERR_GIVEAWAY_NOT_FOUND)
            if giveaway.status != "active" or aware_utc(giveaway.ends_at) <= current:
                raise ConflictError(strings.ERR_GIVEAWAY_ENDED)
            entry = await session.get(GiveawayEntry, (giveaway_id, user_id))
            if entry is None:
                entry = GiveawayEntry(giveaway_id=giveaway_id, user_id=user_id, weight=0)
                session.add(entry)
                await session.flush()

            if giveaway.ticket_price == 0:
                if entry.weight >= 1:
                    return EntryResult(entry.weight, 0, False)
                entry.weight = 1
                return EntryResult(1, 0, True)

            if entry.weight + quantity > giveaway.per_user_limit:
                raise ValidationError(strings.ERR_ENTRY_LIMIT_EXCEEDED)
            cost = giveaway.ticket_price * quantity
            payment = await self.economy.apply_in_session(
                session,
                guild_id=guild_id,
                user_id=user_id,
                amount=-cost,
                transaction_type="ticket",
                idempotency_key=f"giveaway:{giveaway_id}:{idempotency_key}",
                details={"giveaway_id": giveaway_id, "quantity": quantity},
            )
            if payment.created:
                entry.weight += quantity
                entry.spent += cost
            return EntryResult(entry.weight, cost if payment.created else 0, payment.created)

        return await self.db.run_transaction(operation)

    async def active(self, guild_id: int, *, paid_only: bool = False) -> list[Giveaway]:
        async with self.db.session_factory() as session:
            query = select(Giveaway).where(
                Giveaway.guild_id == guild_id, Giveaway.status == "active"
            )
            if paid_only:
                query = query.where(Giveaway.ticket_price > 0)
            result = await session.scalars(query.order_by(Giveaway.ends_at.asc()))
            return list(result)

    async def completed(self, guild_id: int, *, limit: int = 25) -> list[Giveaway]:
        """重抽只接受已結束的抽獎，所以選單必須從這裡取清單而不是 active()。"""
        async with self.db.session_factory() as session:
            result = await session.scalars(
                select(Giveaway)
                .where(Giveaway.guild_id == guild_id, Giveaway.status == "completed")
                .order_by(Giveaway.finalized_at.desc())
                .limit(limit)
            )
            return list(result)

    async def by_message(self, message_id: int) -> Giveaway | None:
        async with self.db.session_factory() as session:
            return await session.scalar(select(Giveaway).where(Giveaway.message_id == message_id))

    async def due(self, now: datetime | None = None) -> list[Giveaway]:
        current = aware_utc(now or datetime.now(UTC))
        async with self.db.session_factory() as session:
            result = await session.scalars(
                select(Giveaway).where(Giveaway.status == "active", Giveaway.ends_at <= current)
            )
            return list(result)

    async def finalize(
        self,
        giveaway_id: int,
        *,
        rng: random.Random | random.SystemRandom | None = None,
    ) -> Giveaway:
        async def operation(session: AsyncSession) -> Giveaway:
            giveaway = await session.get(Giveaway, giveaway_id)
            if giveaway is None:
                raise NotFoundError(strings.ERR_GIVEAWAY_NOT_FOUND)
            if giveaway.status == "completed":
                return giveaway
            if giveaway.status != "active":
                raise ConflictError(strings.ERR_GIVEAWAY_STATE)
            entries = list(
                await session.scalars(
                    select(GiveawayEntry).where(GiveawayEntry.giveaway_id == giveaway_id)
                )
            )
            giveaway.winners = weighted_sample_without_replacement(
                [(entry.user_id, entry.weight) for entry in entries],
                giveaway.winner_count,
                rng=rng,
            )
            giveaway.status = "completed"
            giveaway.finalized_at = datetime.now(UTC)
            await session.flush()
            return giveaway

        return await self.db.run_transaction(operation)

    async def reroll(
        self,
        giveaway_id: int,
        *,
        admin_user_id: int,
        rng: random.Random | random.SystemRandom | None = None,
    ) -> Giveaway:
        async def operation(session: AsyncSession) -> Giveaway:
            giveaway = await session.get(Giveaway, giveaway_id)
            if giveaway is None or giveaway.status != "completed":
                raise NotFoundError(strings.ERR_COMPLETED_GIVEAWAY_NOT_FOUND)
            old_winners = list(giveaway.winners)
            entries = list(
                await session.scalars(
                    select(GiveawayEntry).where(GiveawayEntry.giveaway_id == giveaway_id)
                )
            )
            eligible = [
                (entry.user_id, entry.weight)
                for entry in entries
                if entry.user_id not in old_winners
            ]
            giveaway.winners = weighted_sample_without_replacement(
                eligible, giveaway.winner_count, rng=rng
            )
            session.add(
                AdminAudit(
                    guild_id=giveaway.guild_id,
                    admin_user_id=admin_user_id,
                    action="giveaway_reroll",
                    details={
                        "giveaway_id": giveaway.id,
                        "old_winners": old_winners,
                        "new_winners": giveaway.winners,
                    },
                )
            )
            await session.flush()
            return giveaway

        return await self.db.run_transaction(operation)
