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
import gzip
import io
import json
import logging
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from watchdog.watchdog_db import init_db

ACTIVE_STATUSES = ("submitted", "acknowledged", "working", "input-required")
FINAL_STATUSES = ("completed", "failed", "cancelled")


DEFAULT_HTTP_PORT = 8888
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


@dataclass
class ServerMetrics:
    request_count: int = 0
    total_response_time_ms: float = 0.0
    start_time: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()

    def record(self, elapsed_ms: float) -> None:
        with self._lock:
            self.request_count += 1
            self.total_response_time_ms += elapsed_ms

    @property
    def avg_response_time_ms(self) -> float:
        with self._lock:
            if self.request_count == 0:
                return 0.0
            return self.total_response_time_ms / self.request_count

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self.start_time


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


# ---------------------------------------------------------------------------
# HTTP API server
# ---------------------------------------------------------------------------

class _TaskAPIState:
    """Thread-safe shared state between the task poller and HTTP handlers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: list[dict[str, Any]] = []
        self._finalized: list[dict[str, Any]] = []
        self._updated_at: str = datetime.now(timezone.utc).isoformat()
        self.metrics = ServerMetrics()

    def update(self, active: list[TaskRow], finalized: list[TaskRow]) -> None:
        now = datetime.now(timezone.utc).isoformat()

        def _row_to_dict(r: TaskRow) -> dict[str, Any]:
            return {
                "msg_id": r.msg_id,
                "task_type": r.task_type,
                "sender": r.sender,
                "receiver": r.receiver,
                "status": r.status,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
                "elapsed": _format_elapsed(r.created_at, r.updated_at),
            }

        with self._lock:
            self._active = [_row_to_dict(r) for r in active]
            self._finalized = [_row_to_dict(r) for r in finalized]
            self._updated_at = now

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "timestamp": self._updated_at,
                "active_tasks": list(self._active),
                "finalized_tasks": list(self._finalized),
            }

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": "ok",
                "uptime_seconds": round(self.metrics.uptime_seconds, 2),
                "active_task_count": len(self._active),
            }

    def metrics_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "request_count": self.metrics.request_count,
                "avg_response_time_ms": round(self.metrics.avg_response_time_ms, 3),
                "uptime_seconds": round(self.metrics.uptime_seconds, 2),
            }


def _make_handler(state: _TaskAPIState, use_gzip: bool) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            # Suppress default access log to avoid cluttering stdout
            pass

        def _send_json(self, body: dict[str, Any], status: int = 200) -> None:
            t0 = time.monotonic()
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            accept_enc = self.headers.get("Accept-Encoding", "")
            compress = use_gzip and "gzip" in accept_enc
            payload = gzip.compress(raw) if compress else raw
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            if compress:
                self.send_header("Content-Encoding", "gzip")
            for k, v in _CORS_HEADERS.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)
            elapsed_ms = (time.monotonic() - t0) * 1000
            state.metrics.record(elapsed_ms)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            for k, v in _CORS_HEADERS.items():
                self.send_header(k, v)
            self.end_headers()

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/api/tasks":
                self._send_json(state.snapshot())
            elif path == "/health":
                self._send_json(state.health())
            elif path == "/metrics":
                self._send_json(state.metrics_snapshot())
            else:
                self._send_json({"error": "not found"}, 404)

    return _Handler


class TaskMonitorServer:
    """Background HTTP server exposing task state via REST endpoints."""

    def __init__(
        self,
        port: int = DEFAULT_HTTP_PORT,
        use_gzip: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self.port = port
        self.use_gzip = use_gzip
        self._logger = logger or logging.getLogger("hermes-notify")
        self._state = _TaskAPIState()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def update_state(self, active: list[TaskRow], finalized: list[TaskRow]) -> None:
        self._state.update(active, finalized)

    def start(self) -> None:
        handler_cls = _make_handler(self._state, self.use_gzip)
        try:
            self._server = HTTPServer(("", self.port), handler_cls)
            self.port = self._server.server_address[1]  # update with actual bound port (handles port=0)
        except OSError as exc:
            self._logger.warning(f"[WARN] HTTP server 無法啟動（port {self.port}）: {exc}")
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="hermes-http"
        )
        self._thread.start()
        self._logger.info(f"[INFO] HTTP server 啟動：http://localhost:{self.port}")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None


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
    deliver_target: str,
    state_file: Path,
    logger: logging.Logger,
    http_server: TaskMonitorServer | None = None,
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

        if http_server is not None:
            http_server.update_state(active_rows, finalized_rows)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if changed_rows:
            logger.info(f"[{now}] 📬 檢測到新任務/任務進展（deliver={deliver_target}）")
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
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--loop", action="store_true", help="持續執行，每次間隔由 --interval 指定")
    parser.add_argument("--interval", type=float, default=2.0, help="輪詢秒數（--loop 模式使用）")
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT, help="HTTP server 埠號")
    parser.add_argument("--no-http", action="store_true", help="停用 HTTP server")
    parser.add_argument("--gzip", action="store_true", help="啟用 HTTP 回應 GZIP 壓縮")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logger = setup_logger(args.log_file)

    http_server: TaskMonitorServer | None = None
    if not args.no_http:
        http_server = TaskMonitorServer(
            port=args.http_port, use_gzip=args.gzip, logger=logger
        )
        http_server.start()

    try:
        if args.loop:
            while True:
                run_once(args.db, args.receiver, args.deliver, args.state_file, logger, http_server)
                time.sleep(max(args.interval, 0.1))
        else:
            run_once(args.db, args.receiver, args.deliver, args.state_file, logger, http_server)
    finally:
        if http_server:
            http_server.stop()


if __name__ == "__main__":
    main()
