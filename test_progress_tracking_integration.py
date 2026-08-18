#!/usr/bin/env python3
"""
進度追蹤整合測試
驗證：watchdog_db API、ProgressTracker 類別、Initiator→Executor 流程
"""

import sys
import os
import sqlite3
from datetime import datetime

# 加入專案路徑
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from watchdog.watchdog_db import (
    DB_PATH,
    init_db,
    record_progress_event,
    get_task_progress,
    get_latest_progress_events,
    get_agent_status,
)
from mesh.progress_tracker import ProgressTracker

print("=" * 60)
print("進度追蹤整合測試")
print("=" * 60)

# 測試 1: 驗證資料庫路徑
print("\n[測試 1] 資料庫路徑驗證")
print(f"DB_PATH = {DB_PATH}")
expected_path = os.path.join(os.path.dirname(__file__), "agent-mesh.db")
assert DB_PATH == expected_path, f"路徑不符：{DB_PATH} != {expected_path}"
print("✅ 資料庫路徑正確")

# 測試 2: 初始化資料庫
print("\n[測試 2] 資料庫初始化")
init_db()
assert os.path.exists(DB_PATH), f"資料庫檔案不存在：{DB_PATH}"
print(f"✅ 資料庫已建立：{DB_PATH}")

# 測試 3: 直接使用 watchdog_db API 寫入與讀取
print("\n[測試 3] watchdog_db API 基礎驗證")
conn = sqlite3.connect(DB_PATH)

task_id = "test-task-001"
agent_name = "test-agent"

try:
    # 寫入進度事件
    record_progress_event(
        conn,
        task_id=task_id,
        event_type="started",
        agent_name=agent_name,
        status="running",
        message="任務已開始",
        progress_percent=0,
        metadata={"version": "1.0"}
    )
    print("✅ record_progress_event() 成功")

    # 寫入進度更新
    record_progress_event(
        conn,
        task_id=task_id,
        event_type="progress",
        agent_name=agent_name,
        status="running",
        message="正在處理中...",
        progress_percent=50,
        metadata={"step": 1}
    )
    print("✅ 進度更新事件寫入成功")

    # 寫入完成事件
    record_progress_event(
        conn,
        task_id=task_id,
        event_type="completed",
        agent_name=agent_name,
        status="completed",
        message="任務已完成",
        progress_percent=100,
        metadata={"result": "success"}
    )
    print("✅ 完成事件寫入成功")

    # 讀取任務進度
    task_events = get_task_progress(conn, task_id)
    assert len(task_events) == 3, f"預期 3 個事件，實際 {len(task_events)}"
    print(f"✅ get_task_progress() 成功，取得 {len(task_events)} 個事件")

    # 讀取最新進度事件
    latest_events = get_latest_progress_events(conn, limit=10)
    assert len(latest_events) >= 3, f"預期至少 3 個最新事件"
    print(f"✅ get_latest_progress_events() 成功，取得 {len(latest_events)} 個事件")

    # 讀取 agent 狀態
    agent_status = get_agent_status(conn, agent_name)
    assert agent_status is not None, "無法取得 agent 狀態"
    print(f"✅ get_agent_status() 成功")
    print(f"   Agent 狀態: {agent_status}")

except Exception as e:
    print(f"❌ watchdog_db API 測試失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    conn.close()

# 測試 4: ProgressTracker 類別隔離測試
print("\n[測試 4] ProgressTracker 類別隔離測試")
try:
    tracker = ProgressTracker(task_id="test-task-002", agent_name="progress-tracker-test")
    
    # 測試 record_started
    tracker.record_started(metadata={"initiator": "test"})
    print("✅ ProgressTracker.record_started() 成功")
    
    # 測試 record_progress
    tracker.record_progress(message="第一步", progress_percent=25)
    print("✅ ProgressTracker.record_progress() 成功")
    
    # 測試 record_heartbeat
    tracker.record_heartbeat()
    print("✅ ProgressTracker.record_heartbeat() 成功")
    
    # 測試 record_completed
    tracker.record_completed(metadata={"final_status": "ok"})
    print("✅ ProgressTracker.record_completed() 成功")
    
except Exception as e:
    print(f"❌ ProgressTracker 測試失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 測試 5: Initiator → Executor 模擬流程
print("\n[測試 5] Initiator → Executor 模擬流程")
try:
    # 模擬 Initiator 建立任務
    initiator_task_id = "end-to-end-task-001"
    initiator_tracker = ProgressTracker(
        task_id=initiator_task_id,
        agent_name="initiator"
    )
    initiator_tracker.record_started(metadata={"flow": "e2e-test"})
    print("✅ Initiator 已建立任務")
    
    # 模擬 Executor 接收並處理
    executor_tracker = ProgressTracker(
        task_id=initiator_task_id,
        agent_name="executor"
    )
    executor_tracker.record_started(metadata={"executor_pid": 12345})
    executor_tracker.record_progress(message="開始執行", progress_percent=25)
    executor_tracker.record_progress(message="處理中", progress_percent=75)
    executor_tracker.record_completed(metadata={"executor_result": "success"})
    print("✅ Executor 已完成任務處理")
    
    # 驗證整個流程的事件是否都寫入
    conn = sqlite3.connect(DB_PATH)
    try:
        e2e_events = get_task_progress(conn, initiator_task_id)
        # 預期事件：initiator started, executor started, executor progress (2x), executor completed
        assert len(e2e_events) >= 5, f"預期至少 5 個事件，實際 {len(e2e_events)}"
        print(f"✅ 端到端流程完整，共 {len(e2e_events)} 個事件")
        
        for i, event in enumerate(e2e_events, 1):
            print(f"   {i}. {event}")
    finally:
        conn.close()
    
except Exception as e:
    print(f"❌ 端到端流程測試失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 測試完成
print("\n" + "=" * 60)
print("✅ 整合測試通過")
print("=" * 60)
print("\n總結：")
print("- watchdog_db API 所有函式均可正常使用")
print("- ProgressTracker 類別可獨立運作")
print("- Initiator → Executor 端到端流程完整")
print("- 所有進度事件已正確寫入資料庫")
print("\n下一步：為 agent_executor.py 整合 ProgressTracker")
