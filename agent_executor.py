#!/usr/bin/env python3
"""
Agent Executor 行為規範
在發起端生成任務後，執行端監聽並執行任務

使用示例：
  作為「主機」執行：python3 agent_executor.py --agent host
  作為「蝦米」執行：python3 agent_executor.py --agent shrimp
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 根據環境調整
try:
    from watchdog_db import (
        init_db, get_message, get_messages_by_status,
        update_message_status, heartbeat, get_active_watchdog_jobs,
        utc_now_iso
    )
except ImportError:
    print("ERROR: watchdog_db.py not found. Make sure you're in the hermes-audit-system directory.")
    sys.exit(1)

# 加入 src 讓進度追蹤可被 import
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
try:
    from watchdog.mesh.progress_tracker import ProgressTracker
except ImportError:
    print("WARNING: ProgressTracker not found. Progress tracking disabled.")
    ProgressTracker = None


# ──────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────

AGENT_NAME_HOST = "host"
AGENT_NAME_SHRIMP = "shrimp"

# 預設 DB 路徑（可覆寫）
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "agent-mesh.db"

# 主機和蝦米都應該監聽來自對方的訊息
LISTENERS = {
    AGENT_NAME_HOST: {
        "self": "host",
        "other": "shrimp",
        "description": "主機 (Linux VirtualBox) - 執行端"
    },
    AGENT_NAME_SHRIMP: {
        "self": "shrimp",
        "other": "host",
        "description": "蝦米 (Windows 筆電) - 執行端"
    }
}


# ──────────────────────────────────────────────
# 核心邏輯
# ──────────────────────────────────────────────

def do_work(payload: dict) -> dict:
    """
    執行任務的核心業務邏輯
    
    真實實現應該：
    - 根據 task_type 分派到不同的處理器
    - 處理 payload 中的資料
    - 回傳 result 或 errors
    """
    task_type = payload.get('task_type', 'unknown')
    description = payload.get('description', '')
    
    print(f"  📋 Task Type: {task_type}")
    print(f"  📝 Description: {description}")
    
    try:
        if task_type == 'collection':
            return {
                "task_type": task_type,
                "status": "collected",
                "records": 42,
                "result": f"Collected data: {description}",
                "processed_at": utc_now_iso()
            }
        
        elif task_type == 'processing':
            return {
                "task_type": task_type,
                "status": "processed",
                "result": f"Processed: {description}",
                "processed_at": utc_now_iso()
            }
        
        elif task_type == 'verification':
            return {
                "task_type": task_type,
                "status": "verified",
                "result": f"Verified: {description}",
                "processed_at": utc_now_iso()
            }
        
        else:
            return {
                "task_type": task_type,
                "status": "unknown",
                "result": f"Unknown task type: {task_type}",
                "processed_at": utc_now_iso()
            }
    
    except Exception as e:
        return None  # 由外層處理錯誤


def executor_listener_loop(
    agent_name: str,
    db_path: Path = DEFAULT_DB_PATH,
    poll_interval: int = 5,
    max_iterations: Optional[int] = None
):
    """
    持續監聽訊息，執行任務，回報進度
    
    Args:
        agent_name: "host" 或 "shrimp"
        db_path: SQLite 資料庫路徑
        poll_interval: 輪詢間隔（秒）
        max_iterations: 最大迭代次數（None 表示無限）
    """
    
    if agent_name not in LISTENERS:
        print(f"❌ 未知的 agent: {agent_name}")
        return
    
    config = LISTENERS[agent_name]
    self_name = config["self"]
    other_name = config["other"]
    
    print(f"\n{'='*60}")
    print(f"  {config['description']}")
    print(f"  監聽對象: {other_name} 的任務")
    print(f"  輪詢間隔: {poll_interval}s")
    print(f"{'='*60}\n")
    
    conn = init_db(db_path)
    iteration = 0
    
    try:
        while True:
            iteration += 1
            
            if max_iterations and iteration > max_iterations:
                print(f"\n✅ 達到最大迭代次數 ({max_iterations})，停止")
                break
            
            try:
                # 1. 掃描來自對方的新訊息 (status = submitted)
                messages = get_messages_by_status(conn, 'submitted', limit=10)
                
                if not messages:
                    # print(f"  ⏳ [{iteration}] 沒有新訊息")
                    time.sleep(poll_interval)
                    continue
                
                # 過濾：只處理發給我的訊息
                my_messages = [
                    m for m in messages if m['receiver'] == self_name
                ]
                
                if not my_messages:
                    time.sleep(poll_interval)
                    continue
                
                print(f"\n📬 [{iteration}] 發現 {len(my_messages)} 個新訊息")
                
                for msg in my_messages:
                    msg_id = msg['msg_id']
                    payload = json.loads(msg['payload']) if msg['payload'] else {}
                    sender = msg['sender']
                    
                    print(f"\n  ┌─ 訊息: {msg_id}")
                    print(f"  │  來自: {sender}")
                    print(f"  │  狀態: {msg['status']}")
                    
                    # 初始化進度追蹤（如果可用）
                    tracker = None
                    if ProgressTracker:
                        try:
                            tracker = ProgressTracker(
                                task_id=msg_id,
                                agent_name=self_name
                            )
                            tracker.record_started(
                                message=f"Executor {self_name} received task from {sender}"
                            )
                            print(f"  │  📊 進度追蹤已啟動")
                        except Exception as e:
                            print(f"  │  ⚠️  進度追蹤初始化失敗: {e}")
                            tracker = None
                    
                    try:
                        # 2. 確認收到 → state: acknowledged
                        ok = update_message_status(
                            conn, msg_id, 'acknowledged',
                            expected_current='submitted'
                        )
                        if not ok:
                            print(f"  │  ❌ 已被其他 agent 搶走")
                            if tracker:
                                tracker.record_failed(
                                    error="Message taken by another executor",
                                    message="已被其他執行端搶走"
                                )
                            print(f"  └─")
                            continue
                        
                        print(f"  │  ✅ 確認收到 (acknowledged)")
                        if tracker:
                            tracker.record_acknowledged(message="Task acknowledged")
                        
                        # 3. 尋找對應的 watchdog job
                        watchdog_jobs = get_active_watchdog_jobs(conn)
                        wd_tag = next(
                            (j['watchdog_tag'] for j in watchdog_jobs if j['msg_id'] == msg_id),
                            None
                        )
                        
                        if wd_tag:
                            # 4. 發送 heartbeat 確認
                            heartbeat(conn, wd_tag)
                            print(f"  │  💓 發送 heartbeat (wd={wd_tag})")
                        
                        # 5. 開始工作
                        ok = update_message_status(
                            conn, msg_id, 'working',
                            expected_current='acknowledged'
                        )
                        if not ok:
                            print(f"  │  ❌ 狀態更新失敗")
                            if tracker:
                                tracker.record_failed(
                                    error="Failed to update status to working",
                                    message="狀態更新失敗"
                                )
                            print(f"  └─")
                            continue
                        
                        print(f"  │  🔄 開始工作 (working)")
                        if tracker:
                            tracker.record_progress(percent=25, message="Started processing")
                        
                        # 6. 執行任務核心邏輯
                        result = do_work(payload)
                        
                        if result is None:
                            raise Exception("Work failed")
                        
                        print(f"  │  ✅ 工作完成")
                        if tracker:
                            tracker.record_progress(percent=75, message="Processing complete")
                        
                        # 7. 進度中：定期發送 heartbeat（可選）
                        if wd_tag:
                            heartbeat(conn, wd_tag)
                        
                        # 8. 任務完成
                        ok = update_message_status(
                            conn, msg_id, 'completed',
                            expected_current='working',
                            result=result
                        )
                        
                        if ok:
                            print(f"  │  ✅ 標示完成 (completed)")
                            if tracker:
                                tracker.record_completed(
                                    result=result,
                                    message="Task completed successfully"
                                )
                            if wd_tag:
                                print(f"  │  📍 watchdog 會自動 disarm")
                        else:
                            print(f"  │  ⚠️  標示完成失敗")
                            if tracker:
                                tracker.record_failed(
                                    error="Failed to mark as completed",
                                    message="標示完成失敗"
                                )
                        
                        print(f"  └─")
                    
                    except Exception as e:
                        # 9. 失敗處理
                        print(f"  │  ❌ 異常: {e}")
                        update_message_status(
                            conn, msg_id, 'failed',
                            errors={"error": str(e), "type": type(e).__name__}
                        )
                        if tracker:
                            tracker.record_failed(
                                error=str(e),
                                message=f"Exception: {type(e).__name__}"
                            )
                        print(f"  │  ✅ 標示失敗")
                        print(f"  └─")
                    
                    finally:
                        # 關閉進度追蹤
                        if tracker:
                            try:
                                tracker.close()
                            except Exception as e:
                                print(f"  ⚠️  進度追蹤關閉失敗: {e}")
                
                time.sleep(poll_interval)
            
            except KeyboardInterrupt:
                print(f"\n\n🛑 收到中止信號")
                break
            
            except Exception as e:
                print(f"  ❌ 迴圈異常: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(poll_interval)
    
    finally:
        conn.close()
        print(f"\n👋 監聽器已停止")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Hermes Executor - 監聽並執行任務"
    )
    
    parser.add_argument(
        "--agent",
        choices=["host", "shrimp"],
        required=True,
        help="Agent 身份 (host=主機/shrimp=蝦米)"
    )
    
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite 資料庫路徑 (預設: {DEFAULT_DB_PATH})"
    )
    
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="輪詢間隔 (秒，預設: 5)"
    )
    
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="最大迭代次數 (預設: 無限)"
    )
    
    args = parser.parse_args()
    
    executor_listener_loop(
        agent_name=args.agent,
        db_path=args.db,
        poll_interval=args.interval,
        max_iterations=args.max_iterations
    )


if __name__ == "__main__":
    main()
