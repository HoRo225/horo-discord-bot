from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 心跳檔。healthcheck 是 docker exec 出來的獨立行程，讀不到主行程的記憶體，
# 只能靠檔案時間戳判斷 bot 是否還活著。放 /tmp（compose 掛的是 tmpfs）而不是
# /app/data：心跳是執行期狀態不是資料，寫進 bind mount 會落到 host 磁碟，
# 也會被 scripts/backup.py 掃到；tmpfs 開機即空，容器重啟不會繼承上次的心跳。
HEARTBEAT_PATH = Path("/tmp/horo-heartbeat")  # noqa: S108
HEARTBEAT_INTERVAL_SECONDS = 15
# 容許漏掉三拍再判定為不健康，避免偶發的排程延遲造成誤殺。
HEARTBEAT_MAX_AGE_SECONDS = 60


def validate_database_url(database_url: str) -> None:
    """強制使用一般檔案型的 sqlite+aiosqlite URL。

    本專案的 Alembic migration、Bot runtime 與 healthcheck 都會各自建立 engine；
    `:memory:` 因此會變成彼此不同的資料庫，migration 成功後 runtime 仍是空 schema。
    `file:` URI 也刻意不開放，避免 shared-memory/URI mode 繞過這個 file-backed contract。
    """
    try:
        url = make_url(database_url)
    except Exception as exc:
        raise ValueError(f"DATABASE_URL 無法解析：{exc}") from exc
    if url.drivername != "sqlite+aiosqlite":
        raise ValueError(
            f"DATABASE_URL 只接受 sqlite+aiosqlite（目前是 {url.drivername}）。本專案的"
            "冪等、配額與上限檢查都是先讀後寫，正確性依賴 SQLite BEGIN IMMEDIATE "
            "的寫入序列化；換成其他後端會靜默失去這些保證，必須先補上 row-level locking。"
        )
    database = url.database or ""
    if database == ":memory:" or database.startswith("file:") or not database:
        raise ValueError("DATABASE_URL 必須指向一般檔案型 SQLite，不接受 :memory: 或 file: URI")


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
        validate_database_url(database_url)

        return cls(
            discord_token=token,
            dev_guild_id=_optional_int("DEV_GUILD_ID"),
            database_url=database_url,
            # 預設值必須與 .env.example 及 compose 的服務名稱／連接埠一致，
            # 否則沒設 AI_BASE_URL 的環境會連到一個不存在的位址。
            ai_base_url=os.getenv("AI_BASE_URL", "http://ninerouter:20128/v1").strip().rstrip("/"),
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
