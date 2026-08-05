from __future__ import annotations

import time

from src.healthcheck import _heartbeat_failure


def test_fresh_heartbeat_is_healthy(tmp_path):
    beat = tmp_path / "horo-heartbeat"
    beat.write_text(str(time.time()), encoding="utf-8")

    assert _heartbeat_failure(beat, 60) is None


def test_stale_heartbeat_is_unhealthy(tmp_path):
    """行程還在但已經和 Discord 斷線時，心跳會停更——舊版只查 SELECT 1 看不出來。"""
    beat = tmp_path / "horo-heartbeat"
    beat.write_text(str(time.time() - 120), encoding="utf-8")

    reason = _heartbeat_failure(beat, 60)

    assert reason is not None
    assert "心跳" in reason


def test_missing_heartbeat_is_unhealthy(tmp_path):
    reason = _heartbeat_failure(tmp_path / "does-not-exist", 60)

    assert reason is not None
    assert "找不到心跳檔" in reason


def test_unreadable_heartbeat_is_unhealthy(tmp_path):
    beat = tmp_path / "horo-heartbeat"
    beat.write_text("這不是時間戳", encoding="utf-8")

    reason = _heartbeat_failure(beat, 60)

    assert reason is not None
    assert "無法解讀" in reason
