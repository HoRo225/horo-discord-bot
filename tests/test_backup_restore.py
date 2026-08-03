from __future__ import annotations

import sqlite3
from contextlib import closing

from scripts.backup import backup
from scripts.restore import restore


def test_backup_and_restore_round_trip(tmp_path, monkeypatch):
    database = tmp_path / "production.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES ('original')")
        connection.commit()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database.as_posix()}")

    backup_path = backup(retention=2)
    assert backup_path.is_file()
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE sample SET value = 'changed'")
        connection.commit()
    wal = tmp_path / "production.db-wal"
    shm = tmp_path / "production.db-shm"
    wal.write_bytes(b"stale")
    shm.write_bytes(b"stale")

    restored = restore(backup_path)
    assert restored == database.resolve()
    assert not wal.exists()
    assert not shm.exists()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "original"
