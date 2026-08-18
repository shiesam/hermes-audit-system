#!/usr/bin/env python3
"""
Progress Tracker 整合測試
直接操作 watchdog_db 的 progress_events 表，驗證：
- record_progress_event() 寫入
- get_task_progress() 讀取
- get_agent_status() 讀取
- get_latest_progress_events() 讀取
使用專案根目錄的 agent-mesh.db（與生產環境相同路徑）。
"""
import sys
import sqlite3
from pathlib import Path

# 讓 Python 能 import src/watchdog/watchdog_db.py
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from watchdog_db import (
    init_db,
    record_progress_event,
    get_task_progress,
    get_agent_status,
    get_latest_progress_events,
)

DB_PATH = Path(__file__).resolve().parent / "agent-mesh.db"
TEST_TASK_ID = "test_integration_001"
TEST_AGENT = "test-agent"


def clear_test_data(conn: sqlite3.Connection) -> None:
    """清除測試任務的進度事件，避免污染。"""
    conn.execute(
        "DELETE FROM progress_events WHERE task_id = ?",
        (TEST_TASK_ID,)
    )
    conn.commit()


def test_record_progress_event():
    """測試寫入與讀取單一進度事件。"""
    print("=== test_record_progress_event ===")
    conn = init_db(DB_PATH)
    try:
        clear_test_data(conn)

        # 寫入
        event_id = record_progress_event(
            conn,
            task_id=TEST_TASK_ID,
            event_type="started",
            agent_name=TEST_AGENT,
            message="測試任務已開始",
            progress_percent=0,
        )
        assert event_id is not None
        print(f"  ✅ record_progress_event 返回 event_id: {event_id}")

        # 讀取該任務所有事件
        events = get_task_progress(conn, TEST_TASK_ID)
        assert len(events) == 1, f"預期 1 個事件，實際 {len(events)}"
        ev = events[0]
        assert ev["task_id"] == TEST_TASK_ID
        assert ev["event_type"] == "started"
        assert ev["agent_name"] == TEST_AGENT
        assert ev["progress_percent"] == 0
        print(f"  ✅ get_task_progress 讀取正確：{ev}")

        # 讀取 agent status
        status = get_agent_status(conn, TEST_AGENT)
        assert status is not None
        assert status["agent_name"] == TEST_AGENT
        print(f"  ✅ get_agent_status 正確：{status}")

    finally:
        conn.close()

    print()


def test_multiple_events():
    """測試寫入與讀取多個進度事件。"""
    print("=== test_multiple_events ===")
    conn = init_db(DB_PATH)
    try:
        clear_test_data(conn)

        # 寫入多個事件
        messages = [
            ("started", 0, "任務開始"),
            ("progress", 25, "進度 25%"),
            ("progress", 50, "進度 50%"),
            ("progress", 75, "進度 75%"),
            ("completed", 100, "任務完成"),
        ]

        event_ids = []
        for event_type, progress, message in messages:
            eid = record_progress_event(
                conn,
                task_id=TEST_TASK_ID,
                event_type=event_type,
                agent_name=TEST_AGENT,
                message=message,
                progress_percent=progress,
            )
            event_ids.append(eid)
            print(f"  ✅ 寫入 {event_type:12} ({progress:3}%) → event_id: {eid}")

        # 讀取所有事件
        events = get_task_progress(conn, TEST_TASK_ID)
        assert len(events) == 5, f"預期 5 個事件，實際 {len(events)}"
        print(f"  ✅ 讀取所有事件：共 {len(events)} 筆")

        # 驗證事件順序
        for i, (expected_type, expected_progress, _) in enumerate(messages):
            assert events[i]["event_type"] == expected_type
            assert events[i]["progress_percent"] == expected_progress
        print(f"  ✅ 事件順序正確")

    finally:
        conn.close()

    print()


def test_get_latest_progress_events():
    """測試讀取最新進度事件。"""
    print("=== test_get_latest_progress_events ===")
    conn = init_db(DB_PATH)
    try:
        # 讀取最新 10 筆
        latest = get_latest_progress_events(conn, limit=10)
        assert isinstance(latest, list)
        print(f"  ✅ get_latest_progress_events 返回 {len(latest)} 筆事件")

        # 驗證排序（應該是最新的在前）
        if len(latest) > 1:
            for i in range(len(latest) - 1):
                # created_at 應該遞減（越往後越早）
                assert latest[i]["created_at"] >= latest[i + 1]["created_at"]
            print(f"  ✅ 事件順序正確（newest first）")

    finally:
        conn.close()

    print()


def test_agent_status_multiple_agents():
    """測試多個 agent 的狀態查詢。"""
    print("=== test_agent_status_multiple_agents ===")
    conn = init_db(DB_PATH)
    try:
        # 為不同 agent 寫入事件
        agents = [
            ("agent-001", "started", 0),
            ("agent-002", "progress", 50),
            ("agent-003", "completed", 100),
        ]

        for agent_name, event_type, progress in agents:
            record_progress_event(
                conn,
                task_id=f"test_multi_{agent_name}",
                event_type=event_type,
                agent_name=agent_name,
                message=f"{agent_name} 事件",
                progress_percent=progress,
            )

        # 讀取各 agent 狀態
        for agent_name, _, expected_progress in agents:
            status = get_agent_status(conn, agent_name)
            assert status is not None
            assert status["agent_name"] == agent_name
            print(f"  ✅ {agent_name}: {status}")

    finally:
        conn.close()

    print()


def main():
    print("\n" + "=" * 60)
    print("Progress Tracker 整合測試")
    print("=" * 60)
    print(f"DB_PATH: {DB_PATH}")
    print(f"TEST_TASK_ID: {TEST_TASK_ID}")
    print(f"TEST_AGENT: {TEST_AGENT}")
    print()

    try:
        test_record_progress_event()
        test_multiple_events()
        test_get_latest_progress_events()
        test_agent_status_multiple_agents()

        print("=" * 60)
        print("✅ 整合測試全部通過")
        print("=" * 60)
        return 0

    except AssertionError as e:
        print(f"\n❌ 測試失敗: {e}")
        import traceback
        traceback.print_exc()
        return 1

    except Exception as e:
        print(f"\n❌ 執行出錯: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
