#!/usr/bin/env python3
"""
test_host_executor.py — 主機端 End-to-End 測試腳本

用途：模擬主機執行端，監聽蝦米的訊息並執行任務。
      完全使用 watchdog_db.py 的 API，不直接寫 SQL。

運行方式：
  python3 test_host_executor.py --db /srv/samba/hermes-audit/agent-mesh.db

  若蝦米已有未處理的訊息，直接接單執行：
  python3 test_host_executor.py --db /path/to/agent-mesh.db --once

詳細說明：HOST_EXECUTOR_GUIDE.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

# ──────────────────────────────────────────────
# 路徑設定（支援從倉庫根目錄或 src/ 下的執行環境）
# ──────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent
SRC_PATH = REPO_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

try:
    from hermes_audit_system.dwg_conversion import run_dwg_to_dxf_task
    from watchdog.watchdog_db import (
        init_db,
        get_message,
        get_messages_by_status,
        update_message_status,
        get_active_watchdog_jobs,
        heartbeat,
        utc_now_iso,
    )
    from mesh.progress_tracker import ProgressTracker
except ImportError as e:
    print(f"❌ Import 失敗: {e}")
    print()
    print("請確認：")
    print("  1. 在 hermes-audit-system 目錄下運行")
    print("  2. Python 版本 >= 3.9")
    print("  3. src/ 目錄結構完整")
    sys.exit(1)

# ──────────────────────────────────────────────
# 常數
# ──────────────────────────────────────────────

SELF_AGENT = "host"
OTHER_AGENT = "shrimp"
DEFAULT_DB = Path("/srv/samba/hermes-audit/agent-mesh.db")
POLL_INTERVAL = 5  # 秒
SEPARATOR = "=" * 60


# ──────────────────────────────────────────────
# 模擬任務執行
# ──────────────────────────────────────────────

def do_work(payload: dict) -> dict:
    """
    模擬主機執行任務。
    真實部署時，替換此函數為實際業務邏輯。
    """
    task_type = payload.get("task_type", "unknown")
    description = payload.get("description", "")

    print(f"  │  📋 任務類型: {task_type}")
    print(f"  │  📝 描述:     {description}")
    print(f"  │  ⏳ 執行中...")

    if task_type == "dwg_to_dxf":
        return run_dwg_to_dxf_task(payload)

    # 模擬工作時間
    time.sleep(1)

    if task_type == "collection":
        return {
            "task_type": task_type,
            "status": "completed",
            "records": 42,
            "data": f"主機收集的數據：{description}",
            "processed_at": utc_now_iso(),
        }
    elif task_type == "processing":
        return {
            "task_type": task_type,
            "status": "completed",
            "result": f"主機處理完成：{description}",
            "processed_at": utc_now_iso(),
        }
    elif task_type == "verification":
        return {
            "task_type": task_type,
            "status": "completed",
            "verified": True,
            "result": f"主機驗證通過：{description}",
            "processed_at": utc_now_iso(),
        }
    else:
        return {
            "task_type": task_type,
            "status": "completed",
            "result": f"主機完成未知任務：{description}",
            "processed_at": utc_now_iso(),
        }


# ──────────────────────────────────────────────
# 處理單一訊息
# ──────────────────────────────────────────────

def process_message(conn, msg: dict, db_path: Path) -> bool:
    """
    處理單一訊息，執行完整狀態轉移：
      submitted → acknowledged → working → completed

    返回：True 表示處理成功，False 表示跳過或失敗。
    """
    msg_id = msg["msg_id"]
    sender = msg["sender"]
    payload = json.loads(msg["payload"]) if msg["payload"] else {}

    print(f"\n  ┌─ 訊息: {msg_id}")
    print(f"  │  來自: {sender}")
    print(f"  │  目前狀態: {msg['status']}")

    tracker = ProgressTracker(db_path, msg_id, SELF_AGENT)

    try:
        # ── Step 1: submitted → acknowledged ──
        ok = update_message_status(
            conn, msg_id, "acknowledged",
            expected_current="submitted",
        )
        if not ok:
            print(f"  │  ⚠️  狀態更新失敗（可能已被其他執行端搶先處理）")
            print(f"  └─")
            tracker.close()
            return False

        print(f"  │  ✅ 確認收到 (acknowledged)")

        # 尋找對應的 watchdog 並發送 heartbeat
        watchdog_jobs = get_active_watchdog_jobs(conn)
        wd_tag = next(
            (j["watchdog_tag"] for j in watchdog_jobs if j["msg_id"] == msg_id),
            None,
        )
        if wd_tag:
            heartbeat(conn, wd_tag)
            print(f"  │  💓 Heartbeat 已發送 (watchdog={wd_tag})")

        tracker.record_acknowledged(message=f"主機已確認來自 {sender} 的任務")

        # ── Step 2: acknowledged → working ──
        ok = update_message_status(
            conn, msg_id, "working",
            expected_current="acknowledged",
        )
        if not ok:
            print(f"  │  ⚠️  無法進入 working 狀態")
            print(f"  └─")
            tracker.close()
            return False

        print(f"  │  🔄 開始執行 (working)")
        tracker.record_progress(percent=25, message="主機開始執行任務")

        # ── Step 3: 執行任務 ──
        result = do_work(payload)
        if result is None:
            raise RuntimeError("任務執行返回空結果")

        tracker.record_progress(percent=75, message="任務執行完成，準備回報結果")

        # 再次 heartbeat（長任務時保持活躍）
        if wd_tag:
            heartbeat(conn, wd_tag)

        # ── Step 4: working → completed ──
        ok = update_message_status(
            conn, msg_id, "completed",
            expected_current="working",
            result=result,
        )

        if ok:
            print(f"  │  ✅ 任務完成 (completed)")
            print(f"  │  📊 結果: {json.dumps(result, ensure_ascii=False)}")
            if wd_tag:
                print(f"  │  🔓 Watchdog {wd_tag} 將自動 disarm")
            tracker.record_completed(result=result, message="主機任務完成")
        else:
            print(f"  │  ⚠️  標示 completed 失敗")

        print(f"  └─")
        tracker.close()
        return ok

    except Exception as exc:
        print(f"  │  ❌ 異常: {exc}")
        update_message_status(
            conn, msg_id, "failed",
            errors={"error": str(exc), "type": type(exc).__name__},
        )
        print(f"  │  ✅ 已標示失敗 (failed)")
        tracker.record_failed(error=str(exc), message=f"主機執行異常：{type(exc).__name__}")
        tracker.close()
        print(f"  └─")
        return False


# ──────────────────────────────────────────────
# 主監聽迴圈
# ──────────────────────────────────────────────

def run_executor(
    db_path: Path,
    once: bool = False,
    poll_interval: int = POLL_INTERVAL,
    max_iterations: Optional[int] = None,
):
    """
    主機執行端監聽迴圈。

    Args:
        db_path:        資料庫路徑
        once:           True=掃描一輪後退出；False=持續監聽
        poll_interval:  輪詢間隔（秒）
        max_iterations: 最大迭代次數（None=無限）
    """
    print(f"\n{SEPARATOR}")
    print(f"  🖥️  主機執行端 (Host Executor) — 端到端測試")
    print(f"  監聽對象: {OTHER_AGENT} 的訊息")
    print(f"  資料庫:   {db_path}")
    print(f"  輪詢間隔: {poll_interval}s")
    if once:
        print(f"  模式:     單次掃描（--once）")
    elif max_iterations is not None:
        print(f"  最大輪詢: {max_iterations} 次")
    else:
        print(f"  模式:     持續監聽（Ctrl+C 停止）")
    print(f"{SEPARATOR}\n")

    if not db_path.exists():
        print(f"❌ 資料庫不存在: {db_path}")
        print()
        print("請確認：")
        print("  1. 蝦米已經建立訊息（先在蝦米端執行 test_shrimp_initiator.py）")
        print("  2. 資料庫路徑正確（使用 --db 指定）")
        print("  3. Samba/NFS 共享已掛載")
        sys.exit(1)

    conn = init_db(db_path)
    print(f"✅ 資料庫連線成功\n")

    iteration = 0
    processed = 0

    try:
        while True:
            iteration += 1

            if max_iterations is not None and iteration > max_iterations:
                print(f"\n✅ 達到最大迭代次數 ({max_iterations})，停止")
                break

            try:
                messages = get_messages_by_status(conn, "submitted", limit=10)
                my_messages = [m for m in messages if m["receiver"] == SELF_AGENT]

                if my_messages:
                    print(f"📬 [{iteration}] 發現 {len(my_messages)} 個新訊息")
                    for msg in my_messages:
                        success = process_message(conn, msg, db_path)
                        if success:
                            processed += 1
                else:
                    print(f"⏳ [{iteration}] 沒有新訊息（已處理 {processed} 個任務）")

                if once:
                    print(f"\n✅ 單次掃描完成（--once 模式）")
                    break

                time.sleep(poll_interval)

            except KeyboardInterrupt:
                print(f"\n\n🛑 收到中止信號")
                break

            except Exception as exc:
                print(f"❌ 迴圈異常: {exc}")
                import traceback
                traceback.print_exc()
                time.sleep(poll_interval)

    finally:
        conn.close()
        print(f"\n{'─'*60}")
        print(f"  執行摘要：共處理 {processed} 個任務（共輪詢 {iteration} 次）")
        print(f"{'─'*60}")
        print(f"👋 主機執行端已停止")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="主機執行端端到端測試腳本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  # 持續監聽（正式使用）
  python3 test_host_executor.py --db /srv/samba/hermes-audit/agent-mesh.db

  # 單次掃描（快速測試）
  python3 test_host_executor.py --db /srv/samba/hermes-audit/agent-mesh.db --once

  # 自訂輪詢間隔
  python3 test_host_executor.py --interval 10

詳細說明：HOST_EXECUTOR_GUIDE.md
        """,
    )

    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite 資料庫路徑（預設: {DEFAULT_DB}）",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="掃描一輪後退出（用於快速測試）",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=POLL_INTERVAL,
        help=f"輪詢間隔（秒，預設: {POLL_INTERVAL}）",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="最大迭代次數（預設：無限）",
    )

    args = parser.parse_args()

    run_executor(
        db_path=args.db,
        once=args.once,
        poll_interval=args.interval,
        max_iterations=args.max_iterations,
    )


if __name__ == "__main__":
    main()
