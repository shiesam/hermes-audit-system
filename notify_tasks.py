#!/usr/bin/env python3
"""
notify_tasks.py - Hermes 主機任務通知腳本

用途：
- 查詢 agent-mesh.db 中 receiver='host' 且狀態為 active 的任務
- 偵測新任務/狀態變化，輸出簡潔表格通知
- 偵測剛結束的任務（completed/failed/cancelled）並輸出進展摘要
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from watchdog.watchdog_db import init_db, utc_now_iso

ACTIVE_STATUSES = ("submitted", "acknowledged", "working", "input-required")
FINAL_STATUSES = ("completed", "failed", "cancelled")


@dataclass(frozen=True)
class TaskRow:
    msg_id: str
    task_type: str
    sender: str
    receiver: str
    status: str
    created_at: str
    updated_at: str

    @property
    def fingerprint(self) -> str:
        return f"{self.status}|{self.updated_at}"


def _parse_task_type(payload_text: str | None) -> str:
    if not payload_text:
        return "unknown"
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return "unknown"
    return str(payload.get("task_type", "unknown"))


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_elapsed(created_at: str, updated_at: str) -> str:
    created_dt = _parse_iso(created_at)
    updated_dt = _parse_iso(updated_at)
    if not created_dt or not updated_dt:
        return "n/a"
    seconds = int((updated_dt - created_dt).total_seconds())
    if seconds < 0:
        return "n/a"
    return f"{seconds}s"


def fetch_active_task_rows(conn: sqlite3.Connection, receiver: str) -> list[TaskRow]:
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    rows = conn.execute(
        f"""
        SELECT msg_id, payload, sender, receiver, status, created_at, updated_at
        FROM messages
        WHERE receiver = ?
          AND status IN ({placeholders})
        ORDER BY created_at ASC
        """,
        (receiver, *ACTIVE_STATUSES),
    ).fetchall()
    return [
        TaskRow(
            msg_id=row["msg_id"],
            task_type=_parse_task_type(row["payload"]),
            sender=row["sender"],
            receiver=row["receiver"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def fetch_finalized_rows(
    conn: sqlite3.Connection, receiver: str, msg_ids: set[str]
) -> list[TaskRow]:
    if not msg_ids:
        return []

    placeholders = ",".join("?" for _ in msg_ids)
    final_placeholders = ",".join("?" for _ in FINAL_STATUSES)
    rows = conn.execute(
        f"""
        SELECT msg_id, payload, sender, receiver, status, created_at, updated_at
        FROM messages
        WHERE receiver = ?
          AND msg_id IN ({placeholders})
          AND status IN ({final_placeholders})
        ORDER BY updated_at ASC
        """,
        (receiver, *msg_ids, *FINAL_STATUSES),
    ).fetchall()
    return [
        TaskRow(
            msg_id=row["msg_id"],
            task_type=_parse_task_type(row["payload"]),
            sender=row["sender"],
            receiver=row["receiver"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def render_task_table(rows: list[TaskRow]) -> str:
    headers = ["msg_id", "task_type", "sender", "receiver", "status", "created_at"]
    table_rows = [
        [r.msg_id, r.task_type, r.sender, r.receiver, r.status, r.created_at]
        for r in rows
    ]
    widths = [len(h) for h in headers]
    for row in table_rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(str(value)))

    def _line(values: list[str]) -> str:
        return " | ".join(str(v).ljust(widths[i]) for i, v in enumerate(values))

    sep = "-+-".join("-" * w for w in widths)
    lines = [_line(headers), sep]
    lines.extend(_line(row) for row in table_rows)
    return "\n".join(lines)


def setup_logger(log_file: Path | None) -> logging.Logger:
    logger = logging.getLogger("hermes-notify")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(stream_handler)

    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(file_handler)
        except OSError:
            logger.warning(f"[WARN] 無法寫入日誌檔：{log_file}")

    return logger


def run_once(
    db_path: Path,
    receiver: str,
    deliver: str,
    state_file: Path,
    logger: logging.Logger,
) -> int:
    conn = init_db(db_path)
    try:
        previous_state = load_state(state_file)
        active_rows = fetch_active_task_rows(conn, receiver)
        current_state = {row.msg_id: row.fingerprint for row in active_rows}

        changed_rows = [
            row for row in active_rows if previous_state.get(row.msg_id) != row.fingerprint
        ]
        finalized_rows = fetch_finalized_rows(
            conn=conn,
            receiver=receiver,
            msg_ids=set(previous_state.keys()) - set(current_state.keys()),
        )

        now = datetime.now().strftime("%H:%M:%S")
        if changed_rows:
            logger.info(f"[{now}] 📬 檢測到新任務/任務進展（deliver={deliver}）")
            logger.info(render_task_table(changed_rows))

        for row in finalized_rows:
            elapsed = _format_elapsed(row.created_at, row.updated_at)
            logger.info(
                f"[{now}] ✅ 任務進展 msg_id={row.msg_id} status={row.status} elapsed={elapsed}"
            )

        if not changed_rows and not finalized_rows:
            logger.info(f"[{now}] idle: 無新任務")

        save_state(state_file, current_state)
        return len(changed_rows) + len(finalized_rows)
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes 任務通知腳本")
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "agent-mesh.db")
    parser.add_argument("--receiver", default="host")
    parser.add_argument("--deliver", default="origin")
    parser.add_argument("--state-file", type=Path, default=Path("/var/tmp/hermes-notify-state.json"))
    parser.add_argument("--log-file", type=Path, default=Path("/var/log/hermes-notify.log"))
    parser.add_argument("--loop", action="store_true", help="持續執行，每次間隔由 --interval 指定")
    parser.add_argument("--interval", type=float, default=2.0, help="輪詢秒數（--loop 模式使用）")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logger = setup_logger(args.log_file)

    if args.loop:
        while True:
            run_once(args.db, args.receiver, args.deliver, args.state_file, logger)
            time.sleep(max(args.interval, 0.1))
    else:
        run_once(args.db, args.receiver, args.deliver, args.state_file, logger)


if __name__ == "__main__":
    main()
