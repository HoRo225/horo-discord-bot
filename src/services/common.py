from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


class DomainError(Exception):
    """可安全顯示給使用者的業務錯誤。"""


class ValidationError(DomainError):
    pass


class NotFoundError(DomainError):
    pass


class InsufficientFundsError(DomainError):
    pass


class ConflictError(DomainError):
    pass


def taipei_today(now: datetime | None = None) -> date:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(TAIPEI).date()


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
