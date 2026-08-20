#!/usr/bin/env python3
"""
Agent Executor 行為規範（適配版本）
在發起端生成任務後，執行端監聽並執行任務。

使用示例：
  作為「主機」執行：python agent_executor.py --agent host
  作為「蝦米」執行：python agent_executor.py --agent shrimp
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────

# 預設 DB 路徑 — 以 Windows 原生路徑為準，MSYS 環境下也可透過 /z 掛載讀寫
DEFAULT_DB_PATH = "C:/Users/shies/Z/agent-mesh.db"

AGENT_NAME_HOST = "host"
AGENT_NAME_SHRIMP = "shrimp"

LISTENERS = {
    AGENT_NAME_HOST: {
        "self": "host",
        "other": "shrimp",
        "description": "主機 (Linux VirtualBox) - 執行端",
    },
    AGENT_NAME_SHRIMP: {
        "self": "shrimp",
        "other": "host",
        "description": "蝦米 (Windows 筆電) - 執行端",
    },
}

# 預設 PDF 目錄（主機端讀檔案用；Z 盤已掛載可直接讀）
DEFAULT_PDF_DIR = "C:/Users/shies/Z/瓦斯燃氣法規"

PDF_FILES = [
    "北市都授建字第1100128922號.pdf",
    "燃氣熱水器及其配管安裝標準.pdf",
]

# 抽 PDF 文字的工具優先順序
PDF_EXTRACTORS = [
    ("pdftotext", ["pdftotext", "-layout", "%(in)s", "-"]),
    ("pymupdf", None),  # run-time 判斷
]


# ──────────────────────────────────────────────
# 工具函式
# ──────────────────────────────────────────────


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sqlite_now_iso(conn: sqlite3.Connection) -> str:
    """讓 SQLite 產生一致的 UTC 時間字串（回避 Python 與 DB 時區對不齊）"""
    cur = conn.cursor()
    cur.execute("SELECT datetime('now')")
    return cur.fetchone()[0]


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def mesh_task_get_pending(conn: sqlite3.Connection, role: str, limit: int = 10):
    """撈 role=role 且 status='submitted' 的任務，按建立時間排序"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, role, source, task_type, status, result, created_at, started_at, finished_at
        FROM mesh_tasks
        WHERE role = ? AND status = 'submitted'
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (role, limit),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return rows


def mesh_task_update(conn: sqlite3.Connection, task_id: int, status: str,
                     result: Optional[dict] = None,
                     expected_current: Optional[str] = None,
                     *, started_at: Optional[str] = None,
                     finished_at: Optional[str] = None):
    """
    更新 mesh_tasks 任務狀態（含樂觀鎖）。
    若 expected_current 指定，則僅當前狀態符合才更新。
    """
    if expected_current:
        sql = """
            UPDATE mesh_tasks
            SET status = ?, result = ?, started_at = ?, finished_at = ?
            WHERE id = ? AND status = ?
        """
        cur = conn.cursor()
        cur.execute(sql, (
            status,
            json.dumps(result) if result else None,
            started_at or sqlite_now_iso(conn),
            finished_at or sqlite_now_iso(conn),
            task_id,
            expected_current,
        ))
    else:
        sql = """
            UPDATE mesh_tasks
            SET status = ?, result = ?, finished_at = ?
            WHERE id = ?
        """
        cur = conn.cursor()
        cur.execute(sql, (
            status,
            json.dumps(result) if result else None,
            finished_at or sqlite_now_iso(conn),
            task_id,
        ))

    conn.commit()
    return cur.rowcount > 0


def extract_pdf_text(pdf_path: str) -> str:
    """用可用的工具抽 PDF 文字，失敗則返回空字串"""
    for name, cmd in PDF_EXTRACTORS:
        if name == "pdftotext":
            try:
                proc = subprocess.run(
                    [a.replace("%(in)s", pdf_path) for a in cmd],
                    capture_output=True, text=True, timeout=60
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    return proc.stdout
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        elif name == "pymupdf":
            try:
                import fitz
                doc = fitz.open(pdf_path)
                txt = "\n".join(page.get_text() for page in doc)
                doc.close()
                return txt
            except Exception:
                continue
    return ""


# ──────────────────────────────────────────────
# 核心業務邏輯
# ──────────────────────────────────────────────


def do_work(payload: dict, task_type: str) -> dict:
    """
    執行任務的核心業務邏輯。
    目前支援 task_type：
      - regulation_read ：讀 Z 盤瓦斯燃氣法規 PDF 並回傳摘要
      - collection       ：（保留 stub）
      - processing       ：（保留 stub）
      - verification     ：（保留 stub）
      - unknown          ：回報不认识的型別
    """
    description = payload.get("description", "")

    if task_type == "regulation_read":
        pdf_dir = payload.get("pdf_dir", DEFAULT_PDF_DIR)
        pdf_files = payload.get("pdf_files", PDF_FILES)
        summaries = []
        for fname in pdf_files:
            fpath = os.path.join(pdf_dir, fname)
            if not os.path.exists(fpath):
                summaries.append({"file": fname, "error": f"檔案不存在：{fpath}"})
                continue
            text = extract_pdf_text(fpath)
            if not text:
                summaries.append({"file": fname, "error": "無法抽取文字"})
                continue
            # 截取前 2000 字當摘要（避免回傳過大）
            snippet = text[:2000]
            summaries.append({
                "file": fname,
                "chars": len(text),
                "snippet": snippet,
            })
        return {
            "task_type": task_type,
            "status": "completed",
            "pdf_dir": pdf_dir,
            "summaries": summaries,
            "processed_at": utc_now_iso(),
        }

    if task_type == "collection":
        return {
            "task_type": task_type,
            "status": "collected",
            "records": 42,
            "result": f"Collected data: {description}",
            "processed_at": utc_now_iso(),
        }

    if task_type == "processing":
        return {
            "task_type": task_type,
            "status": "processed",
            "result": f"Processed: {description}",
            "processed_at": utc_now_iso(),
        }

    if task_type == "verification":
        return {
            "task_type": task_type,
            "status": "verified",
            "result": f"Verified: {description}",
            "processed_at": utc_now_iso(),
        }

    return {
        "task_type": task_type,
        "status": "unknown",
        "result": f"Unknown task type: {task_type}",
        "processed_at": utc_now_iso(),
    }


# ──────────────────────────────────────────────
# 監聽循環
# ──────────────────────────────────────────────


def executor_listener_loop(
    agent_name: str,
    db_path: Path = DEFAULT_DB_PATH,
    poll_interval: int = 5,
    max_iterations: Optional[int] = None,
):
    """
    持續監聽 mesh_tasks，執行任務，回報進度。

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

    print("\n" + "=" * 60)
    print(f"  {config['description']}")
    print(f"  監聽對象: {other_name} 的任務")
    print(f"  輪詢間隔: {poll_interval}s")
    print(f"  DB 路徑: {db_path}")
    print("=" * 60 + "\n")

    conn = init_db(db_path)
    iteration = 0

    try:
        while True:
            iteration += 1

            if max_iterations and iteration > max_iterations:
                print(f"\n✅ 達到最大迭代次數 ({max_iterations})，停止")
                break

            try:
                # 1. 掃描發給我的新任務 (status = submitted)
                messages = mesh_task_get_pending(conn, self_name, limit=10)

                if not messages:
                    # print(f"  ⏳ [{iteration}] 沒有新訊息")
                    time.sleep(poll_interval)
                    continue

                print(f"\n📬 [{iteration}] 發現 {len(messages)} 個新任務")

                for msg in messages:
                    task_id = msg["id"]
                    payload = {}
                    #  legacy：若 result 欄位裡有 JSON payload 字串，解析出來
                    if msg["result"] and isinstance(msg["result"], str):
                        try:
                            payload = json.loads(msg["result"])
                        except (json.JSONDecodeError, TypeError):
                            payload = {}

                    sender = msg["source"]

                    print(f"\n  ┌─ 任務: {task_id}")
                    print(f"  │  來自: {sender}")
                    print(f"  │  類型: {msg['task_type']}")
                    print(f"  │  狀態: {msg['status']}")

                    # 2. 確認收到 → status: acknowledged（帶樂觀鎖）
                    ok = mesh_task_update(
                        conn, task_id, "acknowledged",
                        result=None,
                        expected_current="submitted",
                        started_at=utc_now_iso(),
                    )
                    if not ok:
                        print(f"  │  ❌ 已被其他 agent 搶走")
                        print(f"  └─")
                        continue

                    print(f"  │  ✅ 確認收到 (acknowledged)")

                    # 3. 開始工作
                    ok = mesh_task_update(
                        conn, task_id, "working",
                        result=None,
                        expected_current="acknowledged",
                        started_at=utc_now_iso(),
                    )
                    if not ok:
                        print(f"  │  ❌ 狀態更新失敗")
                        print(f"  └─")
                        continue

                    print(f"  │  🔄 開始工作 (working)")

                    # 4. 執行任務
                    try:
                        result = do_work(payload, msg["task_type"])
                    except Exception as exc:
                        print(f"  │  ❌ 執行異常: {exc}")
                        mesh_task_update(
                            conn, task_id, "failed",
                            result={"error": str(exc), "type": type(exc).__name__},
                            expected_current="working",
                            finished_at=utc_now_iso(),
                        )
                        print(f"  │  ✅ 標示失敗")
                        print(f"  └─")
                        continue

                    if not result:
                        print(f"  │  ❌ do_work 回傳 None")
                        mesh_task_update(
                            conn, task_id, "failed",
                            result={"error": "do_work 回傳 None"},
                            expected_current="working",
                            finished_at=utc_now_iso(),
                        )
                        print(f"  │  ✅ 標示失敗")
                        print(f"  └─")
                        continue

                    print(f"  │  ✅ 工作完成")

                    # 5. 標示完成
                    ok = mesh_task_update(
                        conn, task_id, "completed",
                        result=result,
                        expected_current="working",
                        finished_at=utc_now_iso(),
                    )
                    if ok:
                        print(f"  │  ✅ 標示完成 (completed)")
                    else:
                        print(f"  │  ⚠️  標示完成失敗")
                    print(f"  └─")

                time.sleep(poll_interval)

            except KeyboardInterrupt:
                print("\n🛑 收到中止信號")
                break

            except Exception as exc:
                print(f"  ❌ 迴圈異常: {exc}")
                import traceback
                traceback.print_exc()
                time.sleep(poll_interval)

    finally:
        conn.close()
        print("\n👋 監聽器已停止")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Hermes Executor - 監聽並執行任務（適配版本）"
    )

    parser.add_argument(
        "--agent",
        choices=["host", "shrimp"],
        required=True,
        help="Agent 身份 (host=主機/shrimp=蝦米)",
    )

    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite 資料庫路徑 (預設: {DEFAULT_DB_PATH})",
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="輪詢間隔 (秒，預設: 5)",
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="最大迭代次數 (預設: 無限)",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="執行一次迭代後結束（除錯用）",
    )

    args = parser.parse_args()

    if args.once:
        args.max_iterations = 1

    executor_listener_loop(
        agent_name=args.agent,
        db_path=args.db,
        poll_interval=args.interval,
        max_iterations=args.max_iterations,
    )


if __name__ == "__main__":
    main()
