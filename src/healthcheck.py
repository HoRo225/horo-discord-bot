from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from sqlalchemy import text

from src.config import HEARTBEAT_MAX_AGE_SECONDS, HEARTBEAT_PATH, Settings
from src.database.engine import Database


async def _database_failure(database_url: str) -> str | None:
    database = Database(database_url)
    try:
        async with database.engine.connect() as connection:
            if await connection.scalar(text("SELECT 1")) != 1:
                return "資料庫沒有回應預期結果"
    except Exception as exc:  # noqa: BLE001 - 健康檢查要把任何失敗都翻成訊息
        return f"資料庫連線失敗：{exc}"
    finally:
        await database.dispose()
    return None


def _heartbeat_failure(path: Path, max_age: float) -> str | None:
    """檢查 bot 主行程是否還在跳。

    健康檢查是 docker exec 出來的獨立行程，看不到主行程的狀態，只能讀它留下的
    時間戳。心跳只在 gateway 連著時才更新，所以這裡同時涵蓋「行程死了」與
    「行程還在但已經和 Discord 斷線」兩種情況——後者是舊版只查 SELECT 1 時
    完全看不出來的。
    """
    try:
        beat = float(path.read_text(encoding="utf-8").strip())
    except FileNotFoundError:
        return f"找不到心跳檔 {path}，bot 尚未就緒或已停止"
    except (OSError, ValueError) as exc:
        return f"心跳檔無法解讀：{exc}"
    age = time.time() - beat
    if age > max_age:
        return f"心跳已停止更新 {age:.0f} 秒（上限 {max_age:.0f} 秒）"
    return None


async def check() -> str | None:
    """回傳不健康的原因；一切正常則回傳 None。"""
    settings = Settings.from_env(require_token=False)
    return await _database_failure(settings.database_url) or _heartbeat_failure(
        HEARTBEAT_PATH, HEARTBEAT_MAX_AGE_SECONDS
    )


def main() -> int:
    try:
        reason = asyncio.run(check())
    except Exception as exc:  # noqa: BLE001 - 任何例外都算不健康，但要說得出原因
        reason = f"健康檢查本身失敗：{exc}"
    if reason is None:
        return 0
    # 明確的離開碼與原因，而不是讓例外冒泡；也不用 assert，python -O 會把它整條移除。
    print(reason, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
