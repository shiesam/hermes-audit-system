#!/usr/bin/env python3
"""
test_shrimp_initiator.py — 蝦米端 End-to-End 測試腳本

用途：蝦米（Windows 筆電）發起任務，arm watchdog，等待主機回報結果。
      完全使用 watchdog_db.py 的 API，不直接寫 SQL。

運行方式（Windows PowerShell）：
  # 建立任務並等待結果（共享 DB 用網路路徑）
  python test_shrimp_initiator.py --db "\\\\192.168.1.100\\hermes\\hermes-audit-system\\agent-mesh.db"

  # 建立任務後不等待（讓主機去執行）
  python test_shrimp_initiator.py --no-wait

  # 自訂任務內容
  python test_shrimp_initiator.py --task-type processing --description "my task"

詳細說明：SHRIMP_EXECUTOR_TEST.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# ──────────────────────────────────────────────
# 路徑設定（Windows/Linux 通用）
# ──────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent
SRC_PATH = REPO_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

try:
    from watchdog.watchdog_db import (
        init_db,
        get_message,
        create_message,
        arm_watchdog_job,
        get_open_incidents,
        utc_now_iso,
        DEFAULT_THRESHOLDS,
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

SELF_AGENT = "shrimp"
OTHER_AGENT = "host"
DEFAULT_DB = REPO_ROOT / "agent-mesh.db"
POLL_INTERVAL = 5  # 秒
SEPARATOR = "=" * 60


# ──────────────────────────────────────────────
# 建立任務
# ──────────────────────────────────────────────

def create_task(
    conn,
    task_type: str,
    description: str,
    threshold_override: Optional[int],
    db_path: Path,
) -> tuple[str, str]:
    """
    建立訊息並 arm watchdog。
    返回 (msg_id, wd_tag)。
    """
    msg_id = f"m-{uuid.uuid4().hex[:8]}"
    payload = {
        "task_type": task_type,
        "description": description,
    }

    # 1. 建立訊息
    create_message(
        conn,
        msg_id=msg_id,
        sender=SELF_AGENT,
        receiver=OTHER_AGENT,
        payload=payload,
        msg_type="task",
    )
    print(f"✅ 建立訊息: {msg_id}")
    print(f"   發起端: {SELF_AGENT}（蝦米）")
    print(f"   執行端: {OTHER_AGENT}（主機）")

    # 2. 記錄進度事件
    tracker = ProgressTracker(db_path, msg_id, SELF_AGENT)
    tracker.record_started(message=f"Task initiated by {SELF_AGENT}")
    print(f"✅ 記錄進度事件: started")
    tracker.close()

    # 3. Arm watchdog
    threshold = threshold_override if threshold_override is not None else DEFAULT_THRESHOLDS.get(task_type, 300)
    wd_tag = arm_watchdog_job(
        conn,
        msg_id=msg_id,
        kind=task_type,
        threshold_override=threshold,
        label=f"task-{task_type}",
    )
    print(f"✅ Arm Watchdog: {wd_tag}")
    print(f"   超時時間: {threshold}s")

    return msg_id, wd_tag


# ──────────────────────────────────────────────
# 等待結果
# ──────────────────────────────────────────────

def wait_for_result(
    conn,
    msg_id: str,
    timeout_seconds: int,
    poll_interval: int,
    db_path: Path,
) -> Optional[dict]:
    """
    輪詢訊息狀態，直到 completed / failed / 超時。
    """
    start = time.time()
    iteration = 0
    tracker = ProgressTracker(db_path, msg_id, SELF_AGENT)

    print(f"\n⏳ 等待主機執行...")
    print(f"   訊息: {msg_id}")
    print(f"   超時: {timeout_seconds}s")
    print(f"   輪詢間隔: {poll_interval}s\n")

    try:
        while True:
            iteration += 1
            elapsed = time.time() - start

            if elapsed > timeout_seconds:
                print(f"\n❌ 總超時（{timeout_seconds}s）")
                tracker.record_failed(
                    error=f"Timeout after {timeout_seconds}s",
                    message="蝦米等待超時",
                )
                return None

            msg = get_message(conn, msg_id)
            status = msg["status"]

            if status == "completed":
                result = json.loads(msg["result"]) if msg["result"] else None
                print(f"\n✅ 任務完成！")
                print(f"   結果: {json.dumps(result, indent=2, ensure_ascii=False)}")
                tracker.record_completed(result=result, message=f"任務完成，耗時 {elapsed:.1f}s")
                return result

            elif status == "failed":
                errors = json.loads(msg["errors"]) if msg["errors"] else {}
                print(f"\n❌ 任務失敗")
                print(f"   錯誤: {json.dumps(errors, indent=2, ensure_ascii=False)}")
                tracker.record_failed(
                    error=json.dumps(errors, ensure_ascii=False),
                    message="主機回報任務失敗",
                )
                return None

            elif status == "cancelled":
                print(f"\n🚫 任務已取消")
                tracker.record_failed(error="cancelled", message="任務被取消")
                return None

            else:
                tracker.record_heartbeat(message=f"等待中... elapsed={elapsed:.1f}s")

                # 顯示 incident 警告
                open_incs = get_open_incidents(conn, limit=50)
                my_incs = [i for i in open_incs if i["msg_id"] == msg_id]
                if my_incs:
                    for inc in my_incs:
                        evidence = json.loads(inc["evidence"]) if inc["evidence"] else {}
                        reason = evidence.get("reason", "unknown")
                        idle = evidence.get("idle_seconds", 0)
                        print(
                            f"  [{iteration}] ⚠️  {inc['severity'].upper()}: {reason}"
                            + (f"（閒置 {idle:.0f}s）" if idle else "")
                        )
                else:
                    print(f"  [{iteration}] ⏳ 狀態: {status}（已等待 {elapsed:.0f}s）")

            time.sleep(poll_interval)

    finally:
        tracker.close()


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

def run_initiator(
    db_path: Path,
    task_type: str,
    description: str,
    threshold_override: Optional[int],
    no_wait: bool,
    poll_interval: int,
):
    print(f"\n{SEPARATOR}")
    print(f"  🦐 蝦米發起端（Shrimp Initiator）— 端到端測試")
    print(f"  目標執行端: {OTHER_AGENT}（主機）")
    print(f"  資料庫:     {db_path}")
    print(f"  任務類型:   {task_type}")
    print(f"  任務描述:   {description}")
    if no_wait:
        print(f"  模式:       建立後不等待（--no-wait）")
    print(f"{SEPARATOR}\n")

    if not db_path.exists() and not str(db_path).startswith("\\\\"):
        # 本地路徑不存在時給出提示
        # 網路路徑（UNC）跳過此檢查，讓 SQLite 自行嘗試連線
        print(f"⚠️  資料庫不存在: {db_path}")
        print(f"   將嘗試建立新資料庫。")
        print()

    conn = init_db(db_path)
    print(f"✅ 資料庫連線成功\n")

    try:
        # 建立任務
        msg_id, wd_tag = create_task(
            conn,
            task_type=task_type,
            description=description,
            threshold_override=threshold_override,
            db_path=db_path,
        )

        print(f"\n訊息 ID:      {msg_id}")
        print(f"Watchdog Tag: {wd_tag}")

        if no_wait:
            print(f"\n✅ 任務已提交（--no-wait，不等待主機結果）")
            print(f"   主機執行端會在下一輪輪詢時處理此訊息。")
            print()
            print(f"   驗證方式：")
            print(f"     python test_shrimp_initiator.py --check {msg_id} --db \"{db_path}\"")
            return

        # 等待結果
        timeout = (threshold_override or DEFAULT_THRESHOLDS.get(task_type, 300)) + 60
        result = wait_for_result(
            conn,
            msg_id=msg_id,
            timeout_seconds=timeout,
            poll_interval=poll_interval,
            db_path=db_path,
        )

        if result:
            print(f"\n🎉 端到端測試成功！蝦米 → 主機 → 蝦米")
        else:
            print(f"\n⚠️  端到端測試未完成，請檢查主機執行端是否在運行。")
            print(f"   提示：主機端執行 python3 test_host_executor.py --db <db路徑>")

    finally:
        conn.close()


def check_message_status(db_path: Path, msg_id: str):
    """單獨查詢指定訊息的狀態。"""
    conn = init_db(db_path)
    try:
        msg = get_message(conn, msg_id)
        if not msg:
            print(f"❌ 找不到訊息: {msg_id}")
            return
        print(f"\n訊息 {msg_id} 狀態：")
        print(f"  狀態:   {msg['status']}")
        print(f"  發起端: {msg['sender']}")
        print(f"  執行端: {msg['receiver']}")
        print(f"  建立時: {msg['created_at']}")
        print(f"  更新時: {msg['updated_at']}")
        if msg["result"]:
            result = json.loads(msg["result"])
            print(f"  結果:   {json.dumps(result, indent=2, ensure_ascii=False)}")
        if msg["errors"]:
            errors = json.loads(msg["errors"])
            print(f"  錯誤:   {json.dumps(errors, indent=2, ensure_ascii=False)}")
    finally:
        conn.close()


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="蝦米發起端端到端測試腳本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  # 建立任務並等待主機結果（使用共享 DB）
  python test_shrimp_initiator.py --db \\\\192.168.1.100\\hermes\\hermes-audit-system\\agent-mesh.db

  # 建立任務後不等待
  python test_shrimp_initiator.py --no-wait

  # 自訂任務類型與描述
  python test_shrimp_initiator.py --task-type processing --description "稽核資料處理"

  # 查詢某訊息狀態
  python test_shrimp_initiator.py --check m-xxxxxxxx

詳細說明：SHRIMP_EXECUTOR_TEST.md
        """,
    )

    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite 資料庫路徑（預設: {DEFAULT_DB}）",
    )
    parser.add_argument(
        "--task-type",
        choices=["collection", "processing", "verification"],
        default="collection",
        help="任務類型（預設: collection）",
    )
    parser.add_argument(
        "--description",
        default="test from shrimp laptop",
        help="任務描述（預設: test from shrimp laptop）",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="自訂超時時間（秒）",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="建立任務後不等待主機結果",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=POLL_INTERVAL,
        help=f"等待時的輪詢間隔（秒，預設: {POLL_INTERVAL}）",
    )
    parser.add_argument(
        "--check",
        metavar="MSG_ID",
        help="查詢指定訊息的狀態（不建立新任務）",
    )

    args = parser.parse_args()

    if args.check:
        check_message_status(args.db, args.check)
    else:
        run_initiator(
            db_path=args.db,
            task_type=args.task_type,
            description=args.description,
            threshold_override=args.threshold,
            no_wait=args.no_wait,
            poll_interval=args.interval,
        )


if __name__ == "__main__":
    main()
