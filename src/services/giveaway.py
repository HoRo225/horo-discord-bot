from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import strings
from src.database.engine import Database
from src.database.models import AdminAudit, Giveaway, GiveawayEntry
from src.services.common import ConflictError, NotFoundError, ValidationError, aware_utc
from src.services.economy import EconomyService

# 累積排除歷史中獎者後，候選池單調遞減，三輪後實質等同重開一場抽獎。
MAX_REROLLS = 3
# 冷卻擋的是管理員連點造成的重複公告，時間足夠確認上一輪結果即可。
REROLL_COOLDOWN = timedelta(minutes=10)
# 發布失敗留下的 pending 不參與正常活動；保留一天供除錯，之後標成 cancelled，
# 避免永久累積成垃圾資料。
STALE_PENDING_AGE = timedelta(hours=24)


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
                # 先落在 pending，publish() 成功才轉 active。Discord 發訊息失敗時
                # 這筆就停在 pending，而 active()/due()/enter() 都只看 active。
                status="pending",
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

    async def publish(self, giveaway_id: int, message_id: int) -> None:
        """綁定公告訊息並讓抽獎正式生效；兩者必須在同一交易內完成。"""

        async def operation(session: AsyncSession) -> None:
            giveaway = await session.get(Giveaway, giveaway_id)
            if giveaway is None:
                raise NotFoundError(strings.ERR_GIVEAWAY_NOT_FOUND)
            giveaway.message_id = message_id
            if giveaway.status == "pending":
                giveaway.status = "active"

        await self.db.run_transaction(operation)

    async def cancel_stale_pending(self, now: datetime | None = None) -> int:
        """把超過保留期仍未 publish 的抽獎標記取消，避免 pending 永久累積。"""
        cutoff = aware_utc(now or datetime.now(UTC)) - STALE_PENDING_AGE

        async def operation(session: AsyncSession) -> int:
            pending = list(
                await session.scalars(
                    select(Giveaway).where(
                        Giveaway.status == "pending", Giveaway.created_at <= cutoff
                    )
                )
            )
            for giveaway in pending:
                giveaway.status = "cancelled"
            return len(pending)

        return await self.db.run_transaction(operation)

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

            payment_key = f"giveaway:{giveaway_id}:{idempotency_key}"
            # 上限檢查要排在重放判定之後：同一把鍵重送時這次根本不會扣款，
            # 卻會拿新的 quantity 去比上限而誤判成超過每人限額。
            if await self.economy.existing_transaction(session, guild_id, payment_key) is not None:
                return EntryResult(entry.weight, 0, False)
            if entry.weight + quantity > giveaway.per_user_limit:
                raise ValidationError(strings.ERR_ENTRY_LIMIT_EXCEEDED)
            cost = giveaway.ticket_price * quantity
            payment = await self.economy.apply_in_session(
                session,
                guild_id=guild_id,
                user_id=user_id,
                amount=-cost,
                transaction_type="ticket",
                idempotency_key=payment_key,
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
        now: datetime | None = None,
    ) -> Giveaway:
        current = aware_utc(now or datetime.now(UTC))

        async def operation(session: AsyncSession) -> Giveaway:
            giveaway = await session.get(Giveaway, giveaway_id)
            if giveaway is None or giveaway.status != "completed":
                raise NotFoundError(strings.ERR_COMPLETED_GIVEAWAY_NOT_FOUND)
            if giveaway.reroll_count >= MAX_REROLLS:
                raise ConflictError(strings.ERR_REROLL_LIMIT.format(limit=MAX_REROLLS))
            if giveaway.last_reroll_at is not None:
                elapsed = current - aware_utc(giveaway.last_reroll_at)
                if elapsed < REROLL_COOLDOWN:
                    # 向上取整而非「整除再加一」：後者在剛好剩整數分鐘時會多報一分鐘。
                    remaining = math.ceil((REROLL_COOLDOWN - elapsed).total_seconds() / 60)
                    raise ConflictError(strings.ERR_REROLL_COOLDOWN.format(minutes=remaining))

            old_winners = list(giveaway.winners)
            # 排除所有輪次的中獎者，而不只是上一輪，否則多輪重抽後同一個人
            # 會被放回候選池而重複中獎。
            excluded = set(giveaway.past_winners) | set(old_winners)
            entries = list(
                await session.scalars(
                    select(GiveawayEntry).where(GiveawayEntry.giveaway_id == giveaway_id)
                )
            )
            eligible = [
                (entry.user_id, entry.weight) for entry in entries if entry.user_id not in excluded
            ]
            winners = weighted_sample_without_replacement(eligible, giveaway.winner_count, rng=rng)
            if not winners:
                # 候選耗盡時不要把 winners 洗成空的——那會連原本的中獎者一起抹掉。
                # 這次不算一次重抽，也不寫入冷卻。
                raise ConflictError(strings.ERR_NO_REROLL_CANDIDATE)

            giveaway.winners = winners
            giveaway.past_winners = sorted(excluded)
            giveaway.reroll_count += 1
            giveaway.last_reroll_at = current
            session.add(
                AdminAudit(
                    guild_id=giveaway.guild_id,
                    admin_user_id=admin_user_id,
                    action="giveaway_reroll",
                    details={
                        "giveaway_id": giveaway.id,
                        "old_winners": old_winners,
                        "new_winners": giveaway.winners,
                        "reroll_count": giveaway.reroll_count,
                    },
                )
            )
            await session.flush()
            return giveaway

        return await self.db.run_transaction(operation)
