#!/usr/bin/env python3
"""
shrimp_agent.py — 蝦米（Windows 筆電）專用 Agent 包裝

功能：
  - 自動處理 Windows 路徑與 Python sys.path
  - 簡化資料庫連接管理
  - 執行端（監聽主機任務）與發起端（向主機發起任務）兩種模式
  - 整合 ProgressTracker

使用示例：
  # 執行端（監聽）
  python shrimp_agent.py executor

  # 發起端（互動模式）
  python shrimp_agent.py initiator --interactive

  # 發起端（批次模式）
  python shrimp_agent.py initiator ^
    --task-type collection ^
    --description "蒐集數據" ^
    --threshold 300
"""

from __future__ import annotations

# ──────────────────────────────────────────────
# 自動路徑設置（Windows 兼容）
# ──────────────────────────────────────────────

import sys
from pathlib import Path

# 確保無論從哪個目錄執行，都能找到 src/ 下的模組
_REPO_ROOT = Path(__file__).resolve().parent
_SRC_DIR = _REPO_ROOT / "src"

for _p in (_REPO_ROOT, _SRC_DIR):
    _p_str = str(_p)
    if _p_str not in sys.path:
        sys.path.insert(0, _p_str)

# ──────────────────────────────────────────────
# 標準庫及核心模組導入
# ──────────────────────────────────────────────

import argparse
import json
import sqlite3
import time
import uuid
from typing import Any, Optional, Tuple

try:
    from watchdog.watchdog_db import (
        init_db,
        create_message,
        get_message,
        get_messages_by_status,
        update_message_status,
        arm_watchdog_job,
        heartbeat,
        get_active_watchdog_jobs,
        get_open_incidents,
        utc_now_iso,
        DEFAULT_THRESHOLDS,
    )
    from mesh.progress_tracker import ProgressTracker
except ImportError as exc:
    print(f"ERROR: 無法匯入核心模組: {exc}")
    print("請確認您在 hermes-audit-system 目錄中執行，且 src/ 目錄結構完整。")
    sys.exit(1)

# ──────────────────────────────────────────────
# 預設配置
# ──────────────────────────────────────────────

SHRIMP = "shrimp"
HOST = "host"

DEFAULT_DB_PATH: Path = Path("/srv/samba/hermes-audit/agent-mesh.db")
DEFAULT_POLL_INTERVAL: int = 5   # 秒
DEFAULT_WAIT_TIMEOUT: int = 660  # 秒（比最長 threshold 多 60s）


# ──────────────────────────────────────────────
# ShrimpAgent
# ──────────────────────────────────────────────

class ShrimpAgent:
    """
    蝦米（Windows 筆電）Agent 包裝類。

    支援兩種操作模式：
      executor_mode  — 持續監聽來自主機的任務，自動確認並回報結果
      initiator_mode — 建立任務、設置 watchdog、等待主機回應

    範例::

        # 建立 Agent（使用預設 DB 路徑）
        agent = ShrimpAgent()

        # 執行端模式（阻塞，直到 KeyboardInterrupt）
        agent.executor_mode()

        # 發起端批次模式
        agent.initiator_mode(
            task_type="collection",
            description="蒐集系統日誌",
            threshold=300,
        )
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        初始化 ShrimpAgent。

        Args:
            db_path: SQLite 資料庫路徑。若為 None，使用專案預設路徑。
        """
        self.db_path: Path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    # ── 資料庫管理 ──────────────────────────────

    @property
    def conn(self) -> sqlite3.Connection:
        """惰性初始化並返回資料庫連接。"""
        if self._conn is None:
            self._conn = init_db(self.db_path)
        return self._conn

    def close(self) -> None:
        """關閉資料庫連接。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "ShrimpAgent":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── 執行端實現 ───────────────────────────────

    def executor_mode(
        self,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        max_iterations: Optional[int] = None,
    ) -> None:
        """
        執行端模式：持續監聽來自主機的訊息，執行任務並回報結果。

        Args:
            poll_interval:   輪詢間隔（秒）。
            max_iterations:  最大輪詢次數；None 表示無限循環。
        """
        print(f"\n{'='*60}")
        print(f"  蝦米 (Windows 筆電) — 執行端模式")
        print(f"  監聽對象: {HOST} 的任務")
        print(f"  資料庫:   {self.db_path}")
        print(f"  輪詢間隔: {poll_interval}s")
        print(f"{'='*60}\n")

        iteration = 0

        try:
            while True:
                iteration += 1

                if max_iterations is not None and iteration > max_iterations:
                    print(f"\n✅ 達到最大迭代次數 ({max_iterations})，停止")
                    break

                try:
                    self._executor_tick(iteration)
                    time.sleep(poll_interval)

                except KeyboardInterrupt:
                    print("\n\n🛑 收到中止信號，停止監聽")
                    break

                except Exception as exc:
                    print(f"  ❌ 迴圈異常: {exc}")
                    import traceback
                    traceback.print_exc()
                    time.sleep(poll_interval)

        finally:
            self.close()
            print("\n👋 執行端已停止")

    def _executor_tick(self, iteration: int) -> None:
        """單次輪詢：掃描並處理所有新訊息。"""
        messages = get_messages_by_status(self.conn, "submitted", limit=10)

        # 只處理發給蝦米的訊息
        my_messages = [m for m in messages if m["receiver"] == SHRIMP]

        if not my_messages:
            return

        print(f"\n📬 [{iteration}] 發現 {len(my_messages)} 個新訊息")

        for msg in my_messages:
            self._handle_message(msg)

    def _handle_message(self, msg: dict) -> None:
        """處理單則訊息：確認 → 執行 → 回報。"""
        msg_id = msg["msg_id"]
        payload = json.loads(msg["payload"]) if msg["payload"] else {}
        sender = msg["sender"]

        print(f"\n  ┌─ 訊息: {msg_id}")
        print(f"  │  來自: {sender}")

        tracker = ProgressTracker(self.db_path, msg_id, SHRIMP)

        try:
            # 1. 確認收到 (submitted → acknowledged)
            ok = update_message_status(
                self.conn, msg_id, "acknowledged", expected_current="submitted"
            )
            if not ok:
                print("  │  ❌ 已被其他 agent 搶走，略過")
                tracker.close()
                print("  └─")
                return

            print("  │  ✅ 確認收到 (acknowledged)")

            # 發送 watchdog heartbeat
            wd_tag = self._find_watchdog_tag(msg_id)
            if wd_tag:
                heartbeat(self.conn, wd_tag)
                print(f"  │  💓 heartbeat (wd={wd_tag})")

            tracker.record_acknowledged(message=f"已確認來自 {sender} 的任務")

            # 2. 開始工作 (acknowledged → working)
            ok = update_message_status(
                self.conn, msg_id, "working", expected_current="acknowledged"
            )
            if not ok:
                print("  │  ❌ 狀態更新失敗")
                tracker.close()
                print("  └─")
                return

            print("  │  🔄 開始工作 (working)")
            tracker.record_progress(percent=25, message="開始執行任務")

            # 3. 執行任務
            result = self._do_work(payload)
            if result is None:
                raise RuntimeError("任務回傳 None，視為失敗")

            print("  │  ✅ 工作完成")
            tracker.record_progress(percent=75, message="任務執行完成，準備回報結果")

            # 追加 heartbeat
            if wd_tag:
                heartbeat(self.conn, wd_tag)

            # 4. 標示完成 (working → completed)
            ok = update_message_status(
                self.conn, msg_id, "completed",
                expected_current="working", result=result
            )
            if ok:
                print("  │  ✅ 標示完成 (completed)")
                if wd_tag:
                    print("  │  📍 watchdog 將自動 disarm")
                tracker.record_completed(result=result, message="任務完成")
            else:
                print("  │  ⚠️  標示完成失敗")

        except Exception as exc:
            print(f"  │  ❌ 異常: {exc}")
            update_message_status(
                self.conn, msg_id, "failed",
                errors={"error": str(exc), "type": type(exc).__name__}
            )
            print("  │  ✅ 標示失敗")
            tracker.record_failed(
                error=str(exc), message=f"任務失敗：{type(exc).__name__}"
            )

        finally:
            tracker.close()
            print("  └─")

    def _do_work(self, payload: dict) -> Optional[dict]:
        """
        執行任務核心業務邏輯。

        可覆寫此方法以實作真實的任務處理。
        預設實作根據 task_type 返回模擬結果。

        Args:
            payload: 任務內容（含 task_type、description 等欄位）

        Returns:
            任務結果 dict，或 None（失敗）
        """
        task_type = payload.get("task_type", "unknown")
        description = payload.get("description", "")

        print(f"  │  📋 Task Type : {task_type}")
        print(f"  │  📝 Description: {description}")

        if task_type == "collection":
            return {
                "task_type": task_type,
                "status": "collected",
                "records": 42,
                "result": f"Collected: {description}",
                "processed_at": utc_now_iso(),
            }
        elif task_type == "processing":
            return {
                "task_type": task_type,
                "status": "processed",
                "result": f"Processed: {description}",
                "processed_at": utc_now_iso(),
            }
        elif task_type == "verification":
            return {
                "task_type": task_type,
                "status": "verified",
                "result": f"Verified: {description}",
                "processed_at": utc_now_iso(),
            }
        else:
            return {
                "task_type": task_type,
                "status": "unknown",
                "result": f"Unknown task type: {task_type}",
                "processed_at": utc_now_iso(),
            }

    def _find_watchdog_tag(self, msg_id: str) -> Optional[str]:
        """查找訊息對應的 watchdog tag。"""
        jobs = get_active_watchdog_jobs(self.conn)
        return next(
            (j["watchdog_tag"] for j in jobs if j["msg_id"] == msg_id), None
        )

    # ── 發起端實現 ───────────────────────────────

    def initiator_mode(
        self,
        task_type: Optional[str] = None,
        description: Optional[str] = None,
        threshold: Optional[int] = None,
        interactive: bool = False,
        wait: bool = True,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
    ) -> None:
        """
        發起端模式：建立任務、設置 watchdog、等待主機回應。

        Args:
            task_type:    任務類型 (collection/processing/verification)。
            description:  任務描述。
            threshold:    自訂超時時間（秒）；None 使用預設值。
            interactive:  True 時進入互動模式（忽略其他參數）。
            wait:         批次模式下是否等待結果。
            poll_interval: 等待結果的輪詢間隔（秒）。
        """
        if interactive:
            self._interactive_loop(poll_interval)
        elif task_type and description:
            self._batch_task(
                task_type=task_type,
                description=description,
                threshold=threshold,
                wait=wait,
                poll_interval=poll_interval,
            )
        else:
            # 預設進入互動模式
            self._interactive_loop(poll_interval)

    def _interactive_loop(self, poll_interval: int) -> None:
        """互動模式：逐個建立並監控任務。"""
        print(f"\n{'='*60}")
        print(f"  蝦米 (Windows 筆電) — 發起端互動模式")
        print(f"  目標: {HOST}")
        print(f"  資料庫: {self.db_path}")
        print(f"{'='*60}\n")

        try:
            while True:
                print("\n📋 建立新任務")
                print("-" * 40)

                task_type = (
                    input("任務類型 (collection/processing/verification) [collection]: ")
                    .strip() or "collection"
                )
                if task_type not in ("collection", "processing", "verification"):
                    print(f"❌ 未知的任務類型: {task_type}")
                    continue

                description = input("任務描述: ").strip()
                if not description:
                    print("❌ 描述不能為空")
                    continue

                threshold_input = input(
                    f"超時時間（秒，預設={DEFAULT_THRESHOLDS.get(task_type, 300)}）: "
                ).strip()
                threshold: Optional[int] = None
                if threshold_input:
                    try:
                        threshold = int(threshold_input)
                    except ValueError:
                        print(f"❌ 無效的數字: {threshold_input}")
                        continue

                try:
                    msg_id, wd_tag = self._create_task(
                        task_type=task_type,
                        description=description,
                        threshold=threshold,
                    )
                    timeout = (threshold or DEFAULT_THRESHOLDS.get(task_type, 300)) + 60
                    result = self._wait_for_result(
                        msg_id=msg_id,
                        timeout_seconds=timeout,
                        poll_interval=poll_interval,
                    )
                    if result:
                        print("\n✅ 任務成功")
                    else:
                        print("\n❌ 任務未完成")

                except Exception as exc:
                    print(f"❌ 異常: {exc}")
                    import traceback
                    traceback.print_exc()

                cont = input("\n繼續? (y/n) [y]: ").strip().lower() or "y"
                if cont != "y":
                    break

        finally:
            self.close()

    def _batch_task(
        self,
        task_type: str,
        description: str,
        threshold: Optional[int],
        wait: bool,
        poll_interval: int,
    ) -> None:
        """批次模式：建立單個任務並（可選地）等待結果。"""
        print(f"\n{'='*60}")
        print(f"  蝦米 (Windows 筆電) — 發起端批次模式")
        print(f"  目標: {HOST}")
        print(f"  資料庫: {self.db_path}")
        print(f"{'='*60}\n")

        try:
            msg_id, wd_tag = self._create_task(
                task_type=task_type,
                description=description,
                threshold=threshold,
            )
            print(f"\n訊息已建立: {msg_id}")
            print(f"Watchdog Tag: {wd_tag}")

            if wait:
                timeout = (threshold or DEFAULT_THRESHOLDS.get(task_type, 300)) + 60
                self._wait_for_result(
                    msg_id=msg_id,
                    timeout_seconds=timeout,
                    poll_interval=poll_interval,
                )

        finally:
            self.close()

    def _create_task(
        self,
        task_type: str,
        description: str,
        threshold: Optional[int] = None,
    ) -> Tuple[str, str]:
        """
        建立任務訊息、記錄進度起點並 arm watchdog。

        Returns:
            (msg_id, watchdog_tag)
        """
        msg_id = f"m-{uuid.uuid4().hex[:8]}"
        payload = {"task_type": task_type, "description": description}

        create_message(
            self.conn,
            msg_id=msg_id,
            sender=SHRIMP,
            receiver=HOST,
            payload=payload,
            msg_type="task",
        )
        print(f"✅ 建立訊息: {msg_id}")
        print(f"   發起端: {SHRIMP}")
        print(f"   執行端: {HOST}")

        # 記錄任務起點
        tracker = ProgressTracker(self.db_path, msg_id, SHRIMP)
        tracker.record_started(message=f"Task initiated by {SHRIMP}")
        tracker.close()
        print("✅ 記錄進度事件: started")

        # Arm watchdog
        wd_tag = arm_watchdog_job(
            self.conn,
            msg_id=msg_id,
            kind=task_type,
            threshold_override=threshold,
            label=f"task-{task_type}",
        )
        effective_threshold = threshold or DEFAULT_THRESHOLDS.get(task_type, 300)
        print(f"✅ Arm Watchdog: {wd_tag}")
        print(f"   超時時間: {effective_threshold}s")

        return msg_id, wd_tag

    def _wait_for_result(
        self,
        msg_id: str,
        timeout_seconds: int = DEFAULT_WAIT_TIMEOUT,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
    ) -> Optional[dict]:
        """
        輪詢等待任務完成。

        Args:
            msg_id:          目標訊息 ID。
            timeout_seconds: 最長等待時間（秒）。
            poll_interval:   輪詢間隔（秒）。

        Returns:
            完成時的 result dict，失敗 / 超時時返回 None。
        """
        start = time.time()
        iteration = 0

        tracker = ProgressTracker(self.db_path, msg_id, SHRIMP)
        print(f"\n⏳ 等待任務完成...")
        print(f"   訊息: {msg_id}")
        print(f"   超時: {timeout_seconds}s")
        print(f"   輪詢間隔: {poll_interval}s\n")

        try:
            while True:
                iteration += 1
                elapsed = time.time() - start

                if elapsed > timeout_seconds:
                    print(f"\n❌ 總超時 ({timeout_seconds}s)")
                    tracker.record_failed(
                        error=f"Timeout after {timeout_seconds}s",
                        message="等待結果超時",
                    )
                    return None

                msg = get_message(self.conn, msg_id)
                status = msg["status"]

                if status == "completed":
                    result = json.loads(msg["result"]) if msg["result"] else None
                    print(f"\n✅ 任務完成!")
                    print(f"   結果: {json.dumps(result, indent=2, ensure_ascii=False)}")
                    tracker.record_completed(
                        result=result,
                        message=f"Task completed after {elapsed:.1f}s",
                    )
                    return result

                elif status == "failed":
                    errors = json.loads(msg["errors"]) if msg["errors"] else {}
                    print(f"\n❌ 任務失敗")
                    print(f"   錯誤: {json.dumps(errors, indent=2, ensure_ascii=False)}")
                    tracker.record_failed(
                        error=json.dumps(errors, ensure_ascii=False),
                        message="任務失敗",
                    )
                    return None

                elif status == "cancelled":
                    print("\n🚫 任務已取消")
                    tracker.record_failed(error="Task cancelled", message="任務已取消")
                    return None

                else:
                    # 記錄心跳並印出輪詢狀態
                    tracker.record_heartbeat(message=f"Still waiting... elapsed={elapsed:.1f}s")

                    # 檢查是否有 incident
                    open_incs = get_open_incidents(self.conn, limit=50)
                    my_incs = [i for i in open_incs if i["msg_id"] == msg_id]
                    if my_incs:
                        for inc in my_incs:
                            evidence = json.loads(inc["evidence"]) if inc["evidence"] else {}
                            print(
                                f"  [{iteration}] ⚠️  {inc['severity'].upper()}: "
                                f"{evidence.get('reason', 'unknown')}"
                            )
                            idle = evidence.get("idle_seconds", 0)
                            if idle:
                                print(f"           已閒置 {idle:.1f}s")
                    else:
                        print(f"  [{iteration}] ⏳ 狀態: {status} (已等待 {elapsed:.0f}s)")

                time.sleep(poll_interval)

        finally:
            tracker.close()

    # ── 進度查詢便利方法 ──────────────────────────

    def get_task_history(self, msg_id: str) -> list[dict]:
        """查詢任務的完整進度歷史。"""
        with ProgressTracker(self.db_path, msg_id, SHRIMP) as tracker:
            return tracker.get_history()

    def get_open_incidents(self) -> list[dict]:
        """查詢目前所有未解決的 incident。"""
        return get_open_incidents(self.conn)


# ──────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="shrimp_agent — 蝦米（Windows 筆電）Agent 包裝",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 執行端（監聽主機任務）
  python shrimp_agent.py executor

  # 發起端（互動模式）
  python shrimp_agent.py initiator --interactive

  # 發起端（批次模式）
  python shrimp_agent.py initiator --task-type collection --description "蒐集數據"

  # 指定資料庫路徑（網路共享）
  python shrimp_agent.py executor --db //192.168.1.100/hermes/agent-mesh.db
        """,
    )

    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite 資料庫路徑 (預設: {DEFAULT_DB_PATH})",
    )

    subparsers = parser.add_subparsers(dest="mode", required=True)

    # ── executor 子命令 ──────────────────────────
    exec_parser = subparsers.add_parser(
        "executor",
        help="執行端：監聽並執行主機的任務",
    )
    exec_parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_POLL_INTERVAL,
        help=f"輪詢間隔（秒，預設: {DEFAULT_POLL_INTERVAL}）",
    )
    exec_parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="最大迭代次數（預設: 無限）",
    )

    # ── initiator 子命令 ─────────────────────────
    init_parser = subparsers.add_parser(
        "initiator",
        help="發起端：建立任務並等待主機回應",
    )
    init_parser.add_argument(
        "--interactive",
        action="store_true",
        help="互動模式（逐個建立任務）",
    )
    init_parser.add_argument(
        "--task-type",
        choices=["collection", "processing", "verification"],
        help="任務類型（批次模式必填）",
    )
    init_parser.add_argument(
        "--description",
        help="任務描述（批次模式必填）",
    )
    init_parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="自訂超時時間（秒）",
    )
    init_parser.add_argument(
        "--no-wait",
        action="store_true",
        help="建立後不等待結果",
    )
    init_parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_POLL_INTERVAL,
        help=f"輪詢間隔（秒，預設: {DEFAULT_POLL_INTERVAL}）",
    )

    args = parser.parse_args()

    agent = ShrimpAgent(db_path=args.db)

    if args.mode == "executor":
        agent.executor_mode(
            poll_interval=args.interval,
            max_iterations=args.max_iterations,
        )

    elif args.mode == "initiator":
        agent.initiator_mode(
            task_type=args.task_type,
            description=args.description,
            threshold=args.threshold,
            interactive=args.interactive,
            wait=not args.no_wait,
            poll_interval=args.interval,
        )


if __name__ == "__main__":
    main()
