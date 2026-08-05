from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} 必須是整數") from exc


def _positive_int(name: str, default: int) -> int:
    value = os.getenv(name, str(default)).strip()
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} 必須是整數") from exc
    if parsed <= 0:
        raise ValueError(f"{name} 必須大於 0")
    return parsed


def _positive_float(name: str, default: float) -> float:
    value = os.getenv(name, str(default)).strip()
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} 必須是數字") from exc
    if parsed <= 0:
        raise ValueError(f"{name} 必須大於 0")
    return parsed


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    dev_guild_id: int | None
    database_url: str
    ai_base_url: str
    ai_api_key: str
    ai_default_model: str
    ai_request_timeout: float
    ai_max_retries: int
    ai_max_context_messages: int
    ai_max_context_chars: int
    ai_max_response_chars: int
    ai_rate_limit_seconds: float
    log_level: str

    @classmethod
    def from_env(cls, *, require_token: bool = True) -> Settings:
        load_dotenv(PROJECT_ROOT / ".env")
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if require_token and not token:
            raise ValueError("缺少 DISCORD_TOKEN，請先建立 .env")

        database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/horo.db").strip()
        if not database_url:
            raise ValueError("DATABASE_URL 不可為空")
        if not database_url.startswith("sqlite"):
            raise ValueError(
                "DATABASE_URL 只接受 SQLite。本專案的冪等、配額與上限檢查都是"
                "先讀後寫，正確性依賴 SQLite BEGIN IMMEDIATE 的寫入序列化；"
                "換成其他後端會靜默失去這些保證，必須先補上 row-level locking。"
            )

        return cls(
            discord_token=token,
            dev_guild_id=_optional_int("DEV_GUILD_ID"),
            database_url=database_url,
            ai_base_url=os.getenv("AI_BASE_URL", "http://host.docker.internal:9000/v1")
            .strip()
            .rstrip("/"),
            ai_api_key=os.getenv("AI_API_KEY", "").strip(),
            ai_default_model=os.getenv("AI_DEFAULT_MODEL", "").strip(),
            ai_request_timeout=_positive_float("AI_REQUEST_TIMEOUT", 45),
            ai_max_retries=_positive_int("AI_MAX_RETRIES", 2),
            ai_max_context_messages=_positive_int("AI_MAX_CONTEXT_MESSAGES", 20),
            ai_max_context_chars=_positive_int("AI_MAX_CONTEXT_CHARS", 12_000),
            ai_max_response_chars=_positive_int("AI_MAX_RESPONSE_CHARS", 8_000),
            ai_rate_limit_seconds=_positive_float("AI_RATE_LIMIT_SECONDS", 5),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        )
