#!/usr/bin/env python3
"""
進度追蹤系統整合測試
驗證：Initiator → Executor → progress_events 的完整流程

使用示例：
  python3 test_progress_tracking_integration.py
"""

import sys
import sqlite3
import json
import time
from pathlib import Path

# 設定路徑
sys.path.insert(0, str(Path(__file__).parent / "src"))

from watchdog.watchdog_db import (
    init_db, create_message, arm_watchdog_job, 
    get_message, update_message_status, get_task_progress,
    get_agent_status, get_latest_progress_events,
    utc_now_iso
)
from mesh.progress_tracker import ProgressTracker

# DB 路徑
DB_PATH = Path(__file__).resolve().parent / "agent-mesh.db"


def test_progress_events_table():
    """測試 1: progress_events 表存在且可操作"""
    print("\n" + "="*60)
    print("測試 1: progress_events 表存在性")
    print("="*60)
    
    conn = init_db(DB_PATH)
    cursor = conn.cursor()
    
    # 檢查表
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='progress_events'"
    )
    result = cursor.fetchone()
    
    if result:
        print("✅ progress_events 表存在")
        
        # 檢查欄位
        cursor.execute("PRAGMA table_info(progress_events)")
        columns = cursor.fetchall()
        col_names = [col[1] for col in columns]
        
        expected = ['id', 'task_id', 'agent_name', 'event_type', 'progress_percent', 'message', 'status', 'metadata', 'created_at']
        for col in expected:
            if col in col_names:
                print(f"  ✅ 欄位: {col}")
            else:
                print(f"  ❌ 缺少欄位: {col}")
    else:
        print("❌ progress_events 表不存在")
        conn.close()
        return False
    
    conn.close()
    return True


def test_progress_tracker_api():
    """測試 2: ProgressTracker API 正常工作"""
    print("\n" + "="*60)
    print("測試 2: ProgressTracker API")
    print("="*60)
    
    task_id = "test-task-001"
    agent_name = "test-agent"
    
    with ProgressTracker(DB_PATH, task_id, agent_name) as tracker:
        # 測試各個方法
        print(f"  📝 task_id: {task_id}")
        print(f"  🤖 agent_name: {agent_name}")
        
        # record_started
        tracker.record_started(message="Test started")
        print("  ✅ record_started()")
        
        # record_progress
        tracker.record_progress(percent=25, message="25% done")
        print("  ✅ record_progress(25%)")
        
        tracker.record_progress(percent=50, message="50% done")
        print("  ✅ record_progress(50%)")
        
        # record_heartbeat
        tracker.record_heartbeat(message="Still alive")
        print("  ✅ record_heartbeat()")
        
        # record_completed
        tracker.record_completed(result={"status": "success"}, message="All done")
        print("  ✅ record_completed()")
    
    # 驗證資料庫
    conn = init_db(DB_PATH)
    events = get_task_progress(conn, task_id)
    conn.close()
    
    print(f"\n  📊 記錄的事件數: {len(events)}")
    for i, evt in enumerate(events, 1):
        print(f"    {i}. {evt['event_type']:15} | {evt['progress_percent']:3}% | {evt['message']}")
    
    if len(events) >= 5:
        print("  ✅ 所有事件成功記錄")
        return True
    else:
        print("  ❌ 事件數不符")
        return False


def test_end_to_end_flow():
    """測試 3: 端到端流程 (Initiator → Executor)"""
    print("\n" + "="*60)
    print("測試 3: 端到端流程")
    print("="*60)
    
    conn = init_db(DB_PATH)
    
    # 步驟 1: Initiator 建立任務
    msg_id = "m-e2e-test-001"
    print(f"\n  [Initiator] 建立任務: {msg_id}")
    
    create_message(
        conn,
        msg_id=msg_id,
        sender="host",
        receiver="shrimp",
        payload={"task_type": "collection", "description": "E2E Test"},
        msg_type="task"
    )
    print("  ✅ 訊息已建立")
    
    # Initiator 記錄進度
    tracker_init = ProgressTracker(DB_PATH, msg_id, "host")
    tracker_init.record_started(message="Initiator: task created")
    tracker_init.close()
    print("  ✅ Initiator: started 事件記錄")
    
    # 步驟 2: Executor 確認收到
    print(f"\n  [Executor] 處理任務: {msg_id}")
    
    ok = update_message_status(conn, msg_id, 'acknowledged', expected_current='submitted')
    if ok:
        print("  ✅ 確認收到")
        
        tracker_exec = ProgressTracker(DB_PATH, msg_id, "shrimp")
        tracker_exec.record_acknowledged(message="Executor: task acknowledged")
        tracker_exec.close()
        print("  ✅ Executor: acknowledged 事件記錄")
    else:
        print("  ❌ 確認失敗")
        conn.close()
        return False
    
    # 步驟 3: Executor 工作中
    print(f"\n  [Executor] 執行中...")
    
    ok = update_message_status(conn, msg_id, 'working', expected_current='acknowledged')
    if ok:
        tracker_exec = ProgressTracker(DB_PATH, msg_id, "shrimp")
        tracker_exec.record_progress(percent=50, message="Executor: processing")
        tracker_exec.close()
        print("  ✅ Executor: progress 事件記錄 (50%)")
    
    # 步驟 4: Executor 完成
    print(f"\n  [Executor] 任務完成")
    
    result = {"status": "completed", "records": 42}
    ok = update_message_status(
        conn, msg_id, 'completed', 
        expected_current='working',
        result=result
    )
    if ok:
        tracker_exec = ProgressTracker(DB_PATH, msg_id, "shrimp")
        tracker_exec.record_completed(result=result, message="Executor: task completed")
        tracker_exec.close()
        print("  ✅ Executor: completed 事件記錄")
    
    # 步驟 5: Initiator 收到結果
    print(f"\n  [Initiator] 等待結果...")
    
    msg = get_message(conn, msg_id)
    if msg['status'] == 'completed':
        tracker_init = ProgressTracker(DB_PATH, msg_id, "host")
        tracker_init.record_completed(
            result=json.loads(msg['result']),
            message="Initiator: result received"
        )
        tracker_init.close()
        print("  ✅ Initiator: completed 事件記錄")
        print(f"  ✅ 結果: {msg['result']}")
    
    # 驗證完整事件鏈
    print(f"\n  📊 完整事件鏈:")
    events = get_task_progress(conn, msg_id)
    
    for i, evt in enumerate(events, 1):
        agent = evt['agent_name']
        event_type = evt['event_type']
        progress = evt['progress_percent']
        msg_text = evt['message']
        print(f"    {i}. [{agent:6}] {event_type:15} {progress:3}% | {msg_text}")
    
    conn.close()
    
    if len(events) >= 6:
        print("\n  ✅ 端到端流程成功，所有事件記錄完整")
        return True
    else:
        print(f"\n  ❌ 事件數不符 (期望 ≥6，實際 {len(events)})")
        return False


def test_query_functions():
    """測試 4: 查詢函式"""
    print("\n" + "="*60)
    print("測試 4: 查詢函式 (get_task_progress, get_agent_status, get_latest_progress_events)")
    print("="*60)
    
    conn = init_db(DB_PATH)
    
    # 使用之前測試建立的資料
    task_id = "test-task-001"
    
    # get_task_progress
    print(f"\n  get_task_progress('{task_id}'):")
    events = get_task_progress(conn, task_id)
    print(f"    ✅ 傳回 {len(events)} 筆事件")
    
    # get_agent_status
    print(f"\n  get_agent_status('test-agent'):")
    status = get_agent_status(conn, "test-agent")
    if status:
        print(f"    ✅ latest_event: {status['latest_event']}")
        print(f"    ✅ latest_progress: {status['latest_progress']}%")
        print(f"    ✅ latest_message: {status['latest_message']}")
    
    # get_latest_progress_events
    print(f"\n  get_latest_progress_events(limit=5):")
    latest = get_latest_progress_events(conn, limit=5)
    print(f"    ✅ 傳回 {len(latest)} 筆最新事件")
    for evt in latest[:3]:
        print(f"      - [{evt['task_id']}] {evt['event_type']} @ {evt['created_at']}")
    
    conn.close()
    return True


def main():
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + " "*10 + "進度追蹤系統整合測試" + " "*24 + "║")
    print("╚" + "="*58 + "╝")
    
    results = {}
    
    # 執行所有測試
    results["進度表存在性"] = test_progress_events_table()
    results["ProgressTracker API"] = test_progress_tracker_api()
    results["端到端流程"] = test_end_to_end_flow()
    results["查詢函式"] = test_query_functions()
    
    # 總結
    print("\n" + "="*60)
    print("測試總結")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} | {test_name}")
    
    print(f"\n  總計: {passed}/{total} 通過")
    
    if passed == total:
        print("\n🎉 所有測試通過！進度追蹤系統正常運作。")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 個測試失敗。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
