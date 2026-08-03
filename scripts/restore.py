from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from scripts.backup import sqlite_path
from src.config import Settings


def restore(backup_path: Path) -> Path:
    source_path = backup_path.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"找不到備份：{source_path}")
    settings = Settings.from_env(require_token=False)
    destination = sqlite_path(settings.database_url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".restore.tmp")

    with closing(sqlite3.connect(source_path)) as source:
        integrity = source.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError("來源備份完整性檢查失敗")
        with closing(sqlite3.connect(temporary)) as target:
            source.backup(target)
            target_integrity = target.execute("PRAGMA integrity_check").fetchone()
            if not target_integrity or target_integrity[0] != "ok":
                raise RuntimeError("還原後完整性檢查失敗")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{destination}{suffix}")
        if sidecar.is_file():
            sidecar.unlink()
    os.replace(temporary, destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="還原 Crystalline Swan SQLite 備份")
    parser.add_argument("backup", type=Path)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="確認 Bot 已停止，並覆寫 DATABASE_URL 指向的資料庫",
    )
    args = parser.parse_args()
    if not args.confirm:
        parser.error("這會覆寫資料庫；停止 Bot 後加上 --confirm")
    print(restore(args.backup))
