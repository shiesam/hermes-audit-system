#!/usr/bin/env python3
"""
Progress Tracker 整合測試

測試 record_progress_event / get_task_progress / get_agent_status / get_latest_progress_events
使用專案根目錄 agent-mesh.db

注意：get_task_progress 回傳的 metadata 字段是 JSON 字串（而非 dict），需 json.loads 處理。
"""

import json
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from watchdog.watchdog_db import (
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
    """清除測試 agent 的所有進度事件，確保測試隔離。"""
    conn.execute(
        "DELETE FROM progress_events WHERE agent_name = ?",
        (TEST_AGENT,)
    )
    conn.commit()


def parse_metadata(raw) -> dict | None:
    """將原始 metadata 字段轉為 dict（若為 JSON 字串）。"""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}
    return {"_raw": str(raw)}


def test_record_progress_event():
    """寫入與讀取單一進度事件。"""
    print("=== test_record_progress_event ===")
    conn = init_db(DB_PATH)
    try:
        clear_test_data(conn)
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
        events = get_task_progress(conn, TEST_TASK_ID)
        assert len(events) == 1
        ev = events[0]
        assert ev["task_id"] == TEST_TASK_ID
        assert ev["event_type"] == "started"
        assert ev["agent_name"] == TEST_AGENT
        assert ev["progress_percent"] == 0
        print(f"  ✅ get_task_progress 讀取正確：{ev}")
        status = get_agent_status(conn, TEST_AGENT)
        assert status is not None
        assert status["agent_name"] == TEST_AGENT
        print(f"  ✅ get_agent_status 正確：{status}")
    finally:
        conn.close()
    print()


def test_progress_percent():
    """使用不同進度百分比。"""
    print("=== test_progress_percent ===")
    conn = init_db(DB_PATH)
    try:
        clear_test_data(conn)
        for pct, msg in [(25, "進行中 25%"), (50, "進行中 50%"), (75, "進行中 75%"), (100, "已完成")]:
            record_progress_event(
                conn,
                task_id=TEST_TASK_ID,
                event_type="progress",
                agent_name=TEST_AGENT,
                message=msg,
                progress_percent=pct,
            )
        events = get_task_progress(conn, TEST_TASK_ID)
        assert len(events) == 4
        pcts = [e["progress_percent"] for e in events]
        assert pcts == [25, 50, 75, 100]
        print(f"  ✅ 進度序列正確：{pcts}")
    finally:
        conn.close()
    print()


def test_heartbeat():
    """heartbeat 事件不帶 progress_percent。"""
    print("=== test_heartbeat ===")
    conn = init_db(DB_PATH)
    try:
        clear_test_data(conn)
        record_progress_event(
            conn,
            task_id=TEST_TASK_ID,
            event_type="heartbeat",
            agent_name=TEST_AGENT,
            message="心跳",
        )
        events = get_task_progress(conn, TEST_TASK_ID)
        assert len(events) == 1
        assert events[0]["event_type"] == "heartbeat"
        assert events[0]["progress_percent"] is None
        print("  ✅ heartbeat 事件無 progress_percent，正確")
    finally:
        conn.close()
    print()


def test_completed_and_failed():
    """completed 與 failed 事件（含 metadata 驗證）。"""
    print("=== test_completed_and_failed ===")
    conn = init_db(DB_PATH)
    try:
        clear_test_data(conn)

        # completed 事件：metadata 包含 {"result": {"status": "ok"}}
        eid1 = record_progress_event(
            conn,
            task_id=TEST_TASK_ID,
            event_type="completed",
            agent_name=TEST_AGENT,
            message="任務完成",
            progress_percent=100,
            metadata={"result": {"status": "ok"}},
        )
        print(f"  ✅ completed event_id: {eid1}")

        # failed 事件：metadata 包含 {"error": "測試錯誤"}
        FAILED_TASK = f"{TEST_TASK_ID}_failed"
        eid2 = record_progress_event(
            conn,
            task_id=FAILED_TASK,
            event_type="failed",
            agent_name=TEST_AGENT,
            message="任務失敗",
            metadata={"error": "測試錯誤"},
        )
        print(f"  ✅ failed event_id: {eid2}")

        # 讀取 completed
        done_events = get_task_progress(conn, TEST_TASK_ID)
        assert any(e["event_type"] == "completed" for e in done_events)
        print("  ✅ completed 事件已記錄")

        # 讀取 failed
        fail_events = get_task_progress(conn, FAILED_TASK)
        assert any(e["event_type"] == "failed" for e in fail_events)
        print("  ✅ failed 事件已記錄")

        # 驗證 metadata（需 json.loads，因 DB 儲存為 JSON 字串）
        for ev in done_events:
            if ev["event_type"] == "completed":
                meta = parse_metadata(ev["metadata"])
                assert meta is not None and meta.get("result", {}).get("status") == "ok"
                print(f"  ✅ completed metadata: {meta}")

        for ev in fail_events:
            if ev["event_type"] == "failed":
                meta = parse_metadata(ev["metadata"])
                assert meta is not None and meta.get("error") == "測試錯誤"
                print(f"  ✅ failed metadata: {meta}")

    finally:
        conn.close()
    print()


def test_get_latest_progress_events():
    """獲取最新進度事件（限源）。"""
    print("=== test_get_latest_progress_events ===")
    conn = init_db(DB_PATH)
    try:
        clear_test_data(conn)
        for i in range(3):
            record_progress_event(
                conn,
                task_id=TEST_TASK_ID,
                event_type=f"step_{i}",
                agent_name=TEST_AGENT,
                message=f"步驟 {i}",
                progress_percent=i * 33,
            )
        latest = get_latest_progress_events(conn, limit=2)
        assert len(latest) == 2, f"預期 2 個，實際 {len(latest)}"
        # get_latest_progress_events 按 created_at DESC 回傳（最新優先）
        assert latest[0]["event_type"] == "step_2", f"latest[0] 應為 step_2，實際 {latest[0]['event_type']}"
        assert latest[1]["event_type"] == "step_1", f"latest[1] 應為 step_1，實際 {latest[1]['event_type']}"
        print(f"  ✅ 最新 2 個事件（由新至舊）: {[e['event_type'] for e in latest]}")
        all_events = get_latest_progress_events(conn, limit=10)
        assert len(all_events) == 3
        print(f"  ✅ 全部事件數量：{len(all_events)}")
    finally:
        conn.close()
    print()


def main():
    print(f"📁 資料庫路徑: {DB_PATH}")
    print(f"🆔 測試任務 ID: {TEST_TASK_ID}")
    print(f"🤖 測試 Agent: {TEST_AGENT}")
    print()
    try:
        test_record_progress_event()
        test_progress_percent()
        test_heartbeat()
        test_completed_and_failed()
        test_get_latest_progress_events()
        print("=" * 50)
        print("  ✅ 所有 Progress Tracker 整合測試通過")
        print("=" * 50)
    except Exception as e:
        import traceback
        print("=" * 50)
        print(f"  ❌ 測試失敗：{e}")
        print("=" * 50)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
