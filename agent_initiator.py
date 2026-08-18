#!/usr/bin/env python3
"""
Agent Initiator 行為規範
發起端生成任務、arm watchdog、等待結果

使用示例：
  作為「主機」發起：python3 agent_initiator.py --agent host --task-type collection
  作為「蝦米」發起：python3 agent_initiator.py --agent shrimp --task-type verification
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
from typing import Optional, Tuple

# 根據環境調整
try:
    from watchdog_db import (
        init_db, get_message, create_message, arm_watchdog_job,
        update_message_status, get_open_incidents, get_active_watchdog_jobs,
        utc_now_iso, DEFAULT_THRESHOLDS
    )
    from progress_tracker import ProgressTracker
except ImportError as e:
    print(f"ERROR: Import failed: {e}")
    print("Make sure you're in the hermes-audit-system directory.")
    sys.exit(1)


# ──────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────

AGENT_NAME_HOST = "host"
AGENT_NAME_SHRIMP = "shrimp"

# 預設 DB 路徑（可覆寫）
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "agent-mesh.db"

# 主機和蝦米都可以是發起端
INITIATORS = {
    AGENT_NAME_HOST: {
        "self": "host",
        "other": "shrimp",
        "description": "主機 (Linux VirtualBox) - 發起端"
    },
    AGENT_NAME_SHRIMP: {
        "self": "shrimp",
        "other": "host",
        "description": "蝦米 (Windows 筆電) - 發起端"
    }
}


# ──────────────────────────────────────────────
# 核心邏輯
# ──────────────────────────────────────────────

def initiator_create_task(
    conn: sqlite3.Connection,
    agent_name: str,
    payload: dict,
    kind: str = "collection",
    threshold_override: Optional[int] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> Tuple[str, str]:
    """
    發起端建立任務並 arm watchdog
    
    Args:
        conn: 資料庫連接
        agent_name: "host" 或 "shrimp"
        payload: 任務內容
        kind: 任務類型 (collection/processing/verification)
        threshold_override: 覆寫超時時間（秒）
        db_path: 資料庫路徑
    
    Returns:
        (msg_id, watchdog_tag)
    """
    
    if agent_name not in INITIATORS:
        raise ValueError(f"未知的 agent: {agent_name}")
    
    config = INITIATORS[agent_name]
    self_name = config["self"]
    other_name = config["other"]
    
    # 1. 建立訊息（=task_id）
    msg_id = f"m-{uuid.uuid4().hex[:8]}"
    create_message(
        conn,
        msg_id=msg_id,
        sender=self_name,
        receiver=other_name,
        payload=payload,
        msg_type="task"
    )
    print(f"✅ 建立訊息: {msg_id}")
    print(f"   發起端: {self_name}")
    print(f"   執行端: {other_name}")
    
    # 2. 初始化進度追蹤
    tracker = ProgressTracker(db_path, msg_id, self_name)
    tracker.record_started(message=f"Task initiated by {self_name}")
    print(f"✅ 記錄進度事件: started")
    
    # 3. Arm watchdog
    threshold = threshold_override or DEFAULT_THRESHOLDS.get(kind, 300)
    wd_tag = arm_watchdog_job(
        conn,
        msg_id=msg_id,
        kind=kind,
        threshold_override=threshold_override,
        label=f"task-{kind}"
    )
    print(f"✅ Arm Watchdog: {wd_tag}")
    print(f"   超時時間: {threshold}s")
    
    tracker.close()
    return msg_id, wd_tag


def initiator_wait_for_result(
    conn: sqlite3.Connection,
    msg_id: str,
    agent_name: str,
    timeout_seconds: int = 600,
    poll_interval: int = 5,
    verbose: bool = True,
    db_path: Path = DEFAULT_DB_PATH,
) -> Optional[dict]:
    """
    發起端等待任務結果

    Args:
        conn: 資料庫連接
        msg_id: 訊息 ID
        agent_name: Agent 名稱（用於進度追蹤）
        timeout_seconds: 總超時時間（秒）
        poll_interval: 輪詢間隔（秒）
        verbose: 是否詳細輸出
        db_path: 資料庫路徑
    
    Returns:
        result dict 或 None
    """
    
    start_time = time.time()
    iteration = 0
    
    # 初始化進度追蹤
    tracker = ProgressTracker(db_path, msg_id, agent_name)
    
    print(f"\n⏳ 等待任務完成...")
    print(f"   訊息: {msg_id}")
    print(f"   超時: {timeout_seconds}s")
    print(f"   輪詢間隔: {poll_interval}s\n")
    
    while True:
        iteration += 1
        elapsed = time.time() - start_time
        
        if elapsed > timeout_seconds:
            print(f"\n❌ 總超時 ({timeout_seconds}s)")
            tracker.record_failed(
                error=f"Timeout after {timeout_seconds}s",
                message=f"Task timed out waiting for result"
            )
            tracker.close()
            return None
        
        msg = get_message(conn, msg_id)
        
        if msg['status'] == 'completed':
            result = json.loads(msg['result']) if msg['result'] else None
            print(f"\n✅ 任務完成!")
            print(f"   結果: {json.dumps(result, indent=2, ensure_ascii=False)}")
            
            # 記錄完成事件
            tracker.record_completed(
                result=result,
                message=f"Task completed after {elapsed:.1f}s"
            )
            tracker.close()
            return result
        
        elif msg['status'] == 'failed':
            errors = json.loads(msg['errors']) if msg['errors'] else {}
            print(f"\n❌ 任務失敗")
            print(f"   錯誤: {json.dumps(errors, indent=2, ensure_ascii=False)}")
            
            # 記錄失敗事件
            error_msg = json.dumps(errors, ensure_ascii=False)
            tracker.record_failed(
                error=error_msg,
                message=f"Task failed"
            )
            tracker.close()
            return None
        
        elif msg['status'] == 'input-required':
            next_hop = json.loads(msg['next_hop']) if msg['next_hop'] else {}
            print(f"\n⏸️  需要輸入")
            print(f"   提示: {next_hop}")
            
            tracker.record_progress(
                percent=50,
                message=f"Waiting for input",
                metadata={"next_hop": next_hop}
            )
            tracker.close()
            return None
        
        elif msg['status'] == 'cancelled':
            print(f"\n🚫 任務已取消")
            
            tracker.record_failed(
                error="Task cancelled",
                message="Task was cancelled by user or system"
            )
            tracker.close()
            return None
        
        else:
            # 記錄心跳和進度
            tracker.record_heartbeat(message=f"Still waiting... elapsed={elapsed:.1f}s")
            
            # 檢查 incident
            open_incs = get_open_incidents(conn, limit=50)
            my_incidents = [i for i in open_incs if i['msg_id'] == msg_id]
            
            if my_incidents:
                for inc in my_incidents:
                    evidence = json.loads(inc['evidence']) if inc['evidence'] else {}
                    print(f"  [{iteration}] ⚠️  {inc['severity'].upper()}: {evidence.get('reason', 'unknown')}")
                    idle = evidence.get('idle_seconds', 0)
                    if idle:
                        print(f"           已閒置 {idle:.1f}s")
            else:
                if verbose:
                    print(f"  [{iteration}] ⏳ 狀態: {msg['status']} (已等待 {elapsed:.0f}s)")
        
        time.sleep(poll_interval)


def initiator_interactive_mode(
    agent_name: str,
    db_path: Path = DEFAULT_DB_PATH
):
    """
    互動模式：逐個建立和監控任務
    """
    
    if agent_name not in INITIATORS:
        print(f"❌ 未知的 agent: {agent_name}")
        return
    
    config = INITIATORS[agent_name]
    print(f"\n{'='*60}")
    print(f"  {config['description']}")
    print(f"{'='*60}\n")
    
    conn = init_db(db_path)
    
    try:
        while True:
            print("\n📋 建立新任務")
            print("-" * 40)
            
            # 輸入任務類型
            task_type = input("任務類型 (collection/processing/verification) [collection]: ").strip() or "collection"
            if task_type not in ["collection", "processing", "verification"]:
                print(f"❌ 未知的任務類型: {task_type}")
                continue
            
            # 輸入描述
            description = input("任務描述: ").strip()
            if not description:
                print("❌ 描述不能為空")
                continue
            
            # 輸入自訂 threshold
            threshold_input = input(f"超時時間 (秒，預設={DEFAULT_THRESHOLDS.get(task_type, 300)}): ").strip()
            threshold_override = None
            if threshold_input:
                try:
                    threshold_override = int(threshold_input)
                except ValueError:
                    print(f"❌ 無效的數字: {threshold_input}")
                    continue
            
            # 建立任務
            payload = {
                "task_type": task_type,
                "description": description,
            }
            
            try:
                msg_id, wd_tag = initiator_create_task(
                    conn,
                    agent_name,
                    payload,
                    kind=task_type,
                    threshold_override=threshold_override,
                    db_path=db_path,
                )
                
                # 等待結果
                timeout = threshold_override or DEFAULT_THRESHOLDS.get(task_type, 300)
                timeout = timeout + 60  # 加上 60s 的 margin
                
                result = initiator_wait_for_result(
                    conn,
                    msg_id,
                    agent_name=agent_name,
                    timeout_seconds=timeout,
                    poll_interval=5,
                    verbose=True,
                    db_path=db_path,
                )
                
                if result:
                    print(f"\n✅ 任務成功")
                else:
                    print(f"\n❌ 任務未完成")
                
            except Exception as e:
                print(f"❌ 異常: {e}")
                import traceback
                traceback.print_exc()
            
            # 詢問是否繼續
            continue_input = input("\n繼續? (y/n) [y]: ").strip().lower() or "y"
            if continue_input != "y":
                break
    
    finally:
        conn.close()


def initiator_batch_mode(
    agent_name: str,
    task_type: str,
    description: str,
    threshold_override: Optional[int] = None,
    wait_for_result: bool = True,
    db_path: Path = DEFAULT_DB_PATH
):
    """
    批次模式：建立單個任務並等待結果
    """
    
    if agent_name not in INITIATORS:
        print(f"❌ 未知的 agent: {agent_name}")
        return
    
    config = INITIATORS[agent_name]
    print(f"\n{'='*60}")
    print(f"  {config['description']}")
    print(f"{'='*60}\n")
    
    conn = init_db(db_path)
    
    try:
        # 建立任務
        payload = {
            "task_type": task_type,
            "description": description,
        }
        
        msg_id, wd_tag = initiator_create_task(
            conn,
            agent_name,
            payload,
            kind=task_type,
            threshold_override=threshold_override,
            db_path=db_path,
        )
        
        print(f"\n訊息已建立: {msg_id}")
        print(f"Watchdog Tag: {wd_tag}")
        
        if wait_for_result:
            timeout = threshold_override or DEFAULT_THRESHOLDS.get(task_type, 300)
            timeout = timeout + 60  # 加上 60s 的 margin
            
            result = initiator_wait_for_result(
                conn,
                msg_id,
                agent_name=agent_name,
                timeout_seconds=timeout,
                poll_interval=5,
                verbose=True,
                db_path=db_path,
            )
    
    finally:
        conn.close()


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Hermes Initiator - 發起任務並等待結果"
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
        "--interactive",
        action="store_true",
        help="互動模式（逐個建立任務）"
    )
    
    # 批次模式參數
    parser.add_argument(
        "--task-type",
        choices=["collection", "processing", "verification"],
        help="任務類型"
    )
    
    parser.add_argument(
        "--description",
        help="任務描述"
    )
    
    parser.add_argument(
        "--threshold",
        type=int,
        help="超時時間（秒）"
    )
    
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="建立後不等待結果"
    )
    
    args = parser.parse_args()
    
    if args.interactive:
        # 互動模式
        initiator_interactive_mode(args.agent, args.db)
    
    elif args.task_type and args.description:
        # 批次模式
        initiator_batch_mode(
            args.agent,
            args.task_type,
            args.description,
            threshold_override=args.threshold,
            wait_for_result=not args.no_wait,
            db_path=args.db
        )
    
    else:
        # 預設互動模式
        initiator_interactive_mode(args.agent, args.db)


if __name__ == "__main__":
    main()
