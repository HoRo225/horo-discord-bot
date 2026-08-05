from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import strings
from src.database.engine import Database
from src.database.models import BlackjackGame, BlackjackStats
from src.services.blackjack.rules import (
    TERMINAL_PHASES,
    _current_hand,
    can_double,
    can_split,
    deal_round,
    dealer_play,
    double_down,
    hit,
    resolve_insurance,
    settle_round,
    split_hand,
    stand,
    surrender,
)
from src.services.common import ConflictError, NotFoundError, ValidationError
from src.services.economy import EconomyService
from src.services.settings import SettingsService

ACTION_TIMEOUT = timedelta(seconds=120)


def state_from_game(game: BlackjackGame) -> dict[str, Any]:
    return {
        "shoe": list(game.shoe),
        "dealer": list(game.dealer_cards),
        "hands": [dict(hand) for hand in game.hands],
        "active_hand": game.active_hand,
        "phase": game.phase,
        "insurance_bet": game.insurance_bet,
    }


def save_state(game: BlackjackGame, state: dict[str, Any]) -> None:
    game.shoe = list(state["shoe"])
    game.dealer_cards = list(state["dealer"])
    game.hands = [dict(hand) for hand in state["hands"]]
    game.active_hand = int(state["active_hand"])
    game.insurance_bet = int(state.get("insurance_bet", 0))
    game.phase = str(state["phase"])
    game.expires_at = datetime.now(UTC) + ACTION_TIMEOUT


@dataclass(frozen=True, slots=True)
class BlackjackOperationResult:
    game: BlackjackGame
    settled_now: bool


class BlackjackService:
    def __init__(self, db: Database, economy: EconomyService, settings: SettingsService) -> None:
        self.db = db
        self.economy = economy
        self.settings = settings

    async def _active_for_user(
        self, session: AsyncSession, guild_id: int, user_id: int
    ) -> BlackjackGame | None:
        return await session.scalar(
            select(BlackjackGame).where(
                BlackjackGame.guild_id == guild_id,
                BlackjackGame.user_id == user_id,
                BlackjackGame.phase.not_in(TERMINAL_PHASES),
            )
        )

    @staticmethod
    async def _owned_game(
        session: AsyncSession, game_id: str, guild_id: int, user_id: int
    ) -> BlackjackGame:
        game = await session.get(BlackjackGame, game_id)
        if game is None or game.guild_id != guild_id or game.user_id != user_id:
            raise NotFoundError(strings.ERR_GAME_NOT_FOUND)
        return game

    async def _finish_in_session(
        self, session: AsyncSession, game: BlackjackGame, state: dict[str, Any]
    ) -> bool:
        if state["phase"] == "dealer":
            dealer_play(state)
        if state["phase"] not in {"dealer_blackjack", "player_done", "settling"}:
            save_state(game, state)
            return False
        outcome = settle_round(state)
        if outcome["credit"]:
            await self.economy.apply_in_session(
                session,
                guild_id=game.guild_id,
                user_id=game.user_id,
                amount=int(outcome["credit"]),
                transaction_type="blackjack",
                idempotency_key=f"blackjack:{game.id}:settle",
                details={"game_id": game.id, "outcome": outcome},
            )
        stats = await session.get(BlackjackStats, (game.guild_id, game.user_id))
        if stats is None:
            stats = BlackjackStats(
                guild_id=game.guild_id,
                user_id=game.user_id,
                wins=0,
                losses=0,
                pushes=0,
                blackjacks=0,
                total_wagered=0,
                total_won=0,
            )
            session.add(stats)
        for hand in outcome["hands"]:
            if hand["result"] in {"win", "blackjack"}:
                stats.wins += 1
            elif hand["result"] == "push":
                stats.pushes += 1
            else:
                stats.losses += 1
            if hand["result"] == "blackjack":
                stats.blackjacks += 1
        stats.total_wagered += int(outcome["staked"])
        stats.total_won += int(outcome["credit"])
        save_state(game, state)
        game.phase = "settled"
        game.outcome = outcome
        game.settled_at = datetime.now(UTC)
        await session.flush()
        return True

    async def start(
        self,
        *,
        guild_id: int,
        user_id: int,
        channel_id: int,
        bet: int,
        idempotency_key: str,
        shoe: list[str] | None = None,
    ) -> BlackjackOperationResult:
        async def operation(session: AsyncSession) -> BlackjackOperationResult:
            existing = await self._active_for_user(session, guild_id, user_id)
            if existing is not None:
                raise ConflictError(strings.ERR_ACTIVE_GAME)
            # 下注上下限屬於 SettingsService 管轄，這裡不直接查表，改共用同一交易取得
            # （get-or-create 保證非 None，不必再各自硬寫一份 fallback 預設值）。
            settings = await self.settings.get_in_session(session, guild_id)
            minimum = settings.blackjack_min_bet
            maximum = settings.blackjack_max_bet
            if not minimum <= bet <= maximum:
                raise ValidationError(
                    strings.ERR_BET_RANGE.format(minimum=minimum, maximum=maximum)
                )
            if bet % 2:
                raise ValidationError(strings.BLACKJACK_EVEN_BET)
            debit = await self.economy.apply_in_session(
                session,
                guild_id=guild_id,
                user_id=user_id,
                amount=-bet,
                transaction_type="blackjack",
                idempotency_key=f"blackjack:start:{idempotency_key}",
                details={"bet": bet},
            )
            if not debit.created:
                duplicate = await self._active_for_user(session, guild_id, user_id)
                if duplicate is not None:
                    return BlackjackOperationResult(duplicate, False)
                raise ConflictError(strings.ERR_BET_ALREADY_HANDLED)
            state = deal_round(bet, shoe=shoe)
            game = BlackjackGame(
                id=str(uuid.uuid4()),
                guild_id=guild_id,
                user_id=user_id,
                channel_id=channel_id,
                shoe=state["shoe"],
                dealer_cards=state["dealer"],
                hands=state["hands"],
                active_hand=state["active_hand"],
                initial_bet=bet,
                insurance_bet=0,
                phase=state["phase"],
                expires_at=datetime.now(UTC) + ACTION_TIMEOUT,
            )
            session.add(game)
            await session.flush()
            settled = await self._finish_in_session(session, game, state)
            return BlackjackOperationResult(game, settled)

        return await self.db.run_transaction(operation)

    async def attach_message(self, game_id: str, message_id: int) -> None:
        async def operation(session: AsyncSession) -> None:
            game = await session.get(BlackjackGame, game_id)
            if game is None:
                raise NotFoundError(strings.ERR_GAME_NOT_FOUND)
            game.message_id = message_id

        await self.db.run_transaction(operation)

    async def insurance(
        self,
        *,
        game_id: str,
        guild_id: int,
        user_id: int,
        take: bool,
        idempotency_key: str,
    ) -> BlackjackOperationResult:
        async def operation(session: AsyncSession) -> BlackjackOperationResult:
            game = await self._owned_game(session, game_id, guild_id, user_id)
            state = state_from_game(game)
            if state["phase"] != "insurance":
                raise ConflictError(strings.ERR_INSURANCE_PHASE)
            amount = game.initial_bet // 2 if take else 0
            if amount:
                payment = await self.economy.apply_in_session(
                    session,
                    guild_id=guild_id,
                    user_id=user_id,
                    amount=-amount,
                    transaction_type="blackjack",
                    idempotency_key=f"blackjack:{game.id}:insurance:{idempotency_key}",
                    details={"game_id": game.id},
                )
                if not payment.created:
                    return BlackjackOperationResult(game, False)
            resolve_insurance(state, amount)
            save_state(game, state)
            settled = await self._finish_in_session(session, game, state)
            return BlackjackOperationResult(game, settled)

        return await self.db.run_transaction(operation)

    async def action(
        self,
        *,
        game_id: str,
        guild_id: int,
        user_id: int,
        action: str,
        idempotency_key: str,
    ) -> BlackjackOperationResult:
        async def operation(session: AsyncSession) -> BlackjackOperationResult:
            game = await self._owned_game(session, game_id, guild_id, user_id)
            state = state_from_game(game)
            if state["phase"] != "playing":
                raise ConflictError(strings.ERR_GAME_ACTION_PHASE)
            hand = _current_hand(state)
            if action in {"double", "split"}:
                eligible = can_double(state) if action == "double" else can_split(state)
                if not eligible:
                    raise ConflictError(strings.ERR_GAME_ACTION)
                payment = await self.economy.apply_in_session(
                    session,
                    guild_id=guild_id,
                    user_id=user_id,
                    amount=-int(hand["bet"]),
                    transaction_type="blackjack",
                    idempotency_key=f"blackjack:{game.id}:{action}:{idempotency_key}",
                    details={"game_id": game.id, "action": action},
                )
                if not payment.created:
                    return BlackjackOperationResult(game, False)
            handlers = {
                "hit": hit,
                "stand": stand,
                "double": double_down,
                "split": split_hand,
                "surrender": surrender,
            }
            handler = handlers.get(action)
            if handler is None:
                raise ValidationError(strings.ERR_UNKNOWN_GAME_ACTION)
            handler(state)
            save_state(game, state)
            settled = await self._finish_in_session(session, game, state)
            return BlackjackOperationResult(game, settled)

        return await self.db.run_transaction(operation)

    async def by_message(self, message_id: int) -> BlackjackGame | None:
        async with self.db.session_factory() as session:
            return await session.scalar(
                select(BlackjackGame).where(BlackjackGame.message_id == message_id)
            )

    async def stats(self, guild_id: int, user_id: int) -> BlackjackStats | None:
        async with self.db.session_factory() as session:
            return await session.get(BlackjackStats, (guild_id, user_id))

    async def recoverable(self) -> list[BlackjackGame]:
        async with self.db.session_factory() as session:
            return list(
                await session.scalars(
                    select(BlackjackGame).where(BlackjackGame.phase.not_in(TERMINAL_PHASES))
                )
            )

    async def timeout(self, game_id: str) -> BlackjackOperationResult:
        async def operation(session: AsyncSession) -> BlackjackOperationResult:
            game = await session.get(BlackjackGame, game_id)
            if game is None:
                raise NotFoundError(strings.ERR_GAME_NOT_FOUND)
            if game.phase in TERMINAL_PHASES:
                return BlackjackOperationResult(game, False)
            state = state_from_game(game)
            if state["phase"] == "insurance":
                resolve_insurance(state, 0)
            if state["phase"] == "playing":
                for hand in state["hands"]:
                    if hand["status"] == "playing":
                        hand["status"] = "standing"
                state["phase"] = "dealer"
            save_state(game, state)
            settled = await self._finish_in_session(session, game, state)
            return BlackjackOperationResult(game, settled)

        return await self.db.run_transaction(operation)

    async def refund_missing_message(self, game_id: str) -> int:
        async def operation(session: AsyncSession) -> int:
            game = await session.get(BlackjackGame, game_id)
            if game is None:
                raise NotFoundError(strings.ERR_GAME_NOT_FOUND)
            if game.phase in TERMINAL_PHASES:
                return 0
            total = sum(int(hand["bet"]) for hand in game.hands) + game.insurance_bet
            result = await self.economy.apply_in_session(
                session,
                guild_id=game.guild_id,
                user_id=game.user_id,
                amount=total,
                transaction_type="blackjack",
                idempotency_key=f"blackjack:{game.id}:refund",
                details={"game_id": game.id, "reason": "missing_message"},
            )
            game.phase = "refunded"
            game.outcome = {"refund": total, "reason": "missing_message"}
            game.settled_at = datetime.now(UTC)
            return total if result.created else 0

        return await self.db.run_transaction(operation)
