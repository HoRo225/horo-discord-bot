from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from src.config import Settings


def sqlite_path(database_url: str) -> Path:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        raise RuntimeError("備份工具目前只支援 SQLite DATABASE_URL")
    raw = database_url.removeprefix(prefix)
    if raw == ":memory:":
        raise RuntimeError("記憶體資料庫無法備份")
    return Path(raw).expanduser().resolve()


def backup(*, retention: int = 14) -> Path:
    settings = Settings.from_env(require_token=False)
    source_path = sqlite_path(settings.database_url)
    if not source_path.is_file():
        raise FileNotFoundError(f"找不到資料庫：{source_path}")
    backup_dir = source_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"crystalline-swan-{datetime.now(UTC):%Y%m%d-%H%M%S}.db"

    with (
        closing(sqlite3.connect(source_path)) as source,
        closing(sqlite3.connect(destination)) as target,
    ):
        source.backup(target)
        integrity = target.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError("備份完整性檢查失敗")

    backups = sorted(backup_dir.glob("crystalline-swan-*.db"), reverse=True)
    for expired in backups[max(1, retention) :]:
        expired.unlink()
    return destination


if __name__ == "__main__":
    keep = int(os.getenv("BACKUP_RETENTION", "14"))
    print(backup(retention=keep))
