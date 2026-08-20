#!/usr/bin/env python3
"""
hermes_monitor.py - Hermes 任務監控腳本（Copilot session 專用）

用途：
- 在 Copilot session 中持續執行
- 輪詢 localhost:8888/api/tasks
- 以漂亮的格式顯示任務狀態變化
- 偵測新任務、狀態變化、完成情況
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# ANSI color helpers (gracefully disabled when not a tty)
# ---------------------------------------------------------------------------

_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def _bold(t: str) -> str:
    return _c("1", t)


def _green(t: str) -> str:
    return _c("32", t)


def _yellow(t: str) -> str:
    return _c("33", t)


def _red(t: str) -> str:
    return _c("31", t)


def _cyan(t: str) -> str:
    return _c("36", t)


def _dim(t: str) -> str:
    return _c("2", t)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TaskInfo:
    msg_id: str
    task_type: str
    sender: str
    receiver: str
    status: str
    created_at: str
    updated_at: str
    elapsed: str = "n/a"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskInfo":
        return cls(
            msg_id=d.get("msg_id", ""),
            task_type=d.get("task_type", "unknown"),
            sender=d.get("sender", ""),
            receiver=d.get("receiver", ""),
            status=d.get("status", ""),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            elapsed=d.get("elapsed", "n/a"),
        )

    @property
    def fingerprint(self) -> str:
        return f"{self.status}|{self.updated_at}"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: float = 5.0) -> dict[str, Any] | None:
    """Perform a simple HTTP GET and return parsed JSON, or None on error."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_STATUS_ICON: dict[str, str] = {
    "submitted": "📤",
    "acknowledged": "👀",
    "working": "⏳",
    "input-required": "❓",
    "completed": "✅",
    "failed": "❌",
    "cancelled": "🚫",
}

_PROGRESS_ORDER = ["submitted", "acknowledged", "working", "input-required", "completed", "failed", "cancelled"]


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _box(lines: list[str], width: int = 32) -> str:
    border = "─" * width
    top = f"┌{border}┐"
    bottom = f"└{border}┘"
    body = "\n".join(f"│ {ln.ljust(width - 1)}│" for ln in lines)
    return f"{top}\n{body}\n{bottom}"


def _print_new_task(task: TaskInfo) -> None:
    ts = _now_str()
    print(f"\n[{ts}] {_bold(_green('📬 新任務檢測！'))}")
    lines = [
        _bold(task.msg_id),
        task.task_type,
        f"{task.sender} → {task.receiver}",
        _cyan(task.status),
    ]
    print(_box(lines))


def _print_status_change(task: TaskInfo, prev_status: str) -> None:
    ts = _now_str()
    icon = _STATUS_ICON.get(task.status, "⏳")
    is_final = task.status in ("completed", "failed", "cancelled")
    label = "任務完成" if is_final else "狀態變化"
    color_fn = _green if task.status == "completed" else (_red if task.status in ("failed", "cancelled") else _yellow)
    print(f"\n[{ts}] {icon} {_bold(color_fn(label))}")
    print(f"  {_bold(task.msg_id)}: {_dim(prev_status)} → {color_fn(task.status)} ({task.elapsed})")


def _print_finalized(task: TaskInfo) -> None:
    ts = _now_str()
    icon = _STATUS_ICON.get(task.status, "✅")
    color_fn = _green if task.status == "completed" else _red
    print(f"\n[{ts}] {icon} {_bold(color_fn('任務完成'))}")
    print(f"  {_bold(task.msg_id)}: {color_fn(task.status)} ({task.elapsed})")


def _print_connection_error(url: str, attempt: int) -> None:
    ts = _now_str()
    print(f"[{ts}] {_red('⚠ 無法連接')} {url} (重試 #{attempt})", flush=True)


def _print_reconnected(url: str) -> None:
    ts = _now_str()
    print(f"[{ts}] {_green('🔌 重新連線成功')} {url}", flush=True)


# ---------------------------------------------------------------------------
# Monitor core
# ---------------------------------------------------------------------------

@dataclass
class HermesMonitor:
    base_url: str = "http://localhost:8888"
    interval: float = 2.0
    reconnect_delay: float = 5.0
    max_finalized_memory: int = 100

    _known: dict[str, str] = field(default_factory=dict)  # msg_id → fingerprint
    _finalized_seen: set[str] = field(default_factory=set)
    _connected: bool = False
    _running: bool = False
    _error_count: int = 0

    @property
    def tasks_url(self) -> str:
        return f"{self.base_url}/api/tasks"

    def _process(self, data: dict[str, Any]) -> None:
        active: list[TaskInfo] = [TaskInfo.from_dict(d) for d in data.get("active_tasks", [])]
        finalized: list[TaskInfo] = [TaskInfo.from_dict(d) for d in data.get("finalized_tasks", [])]

        current_ids = {t.msg_id for t in active}

        for task in active:
            prev_fp = self._known.get(task.msg_id)
            if prev_fp is None:
                # Brand-new task
                _print_new_task(task)
            elif prev_fp != task.fingerprint:
                # Status changed
                prev_status = prev_fp.split("|", 1)[0]
                _print_status_change(task, prev_status)
            self._known[task.msg_id] = task.fingerprint

        # Detect tasks that left active and are now finalized
        removed_ids = set(self._known.keys()) - current_ids
        for task in finalized:
            if task.msg_id in removed_ids and task.msg_id not in self._finalized_seen:
                _print_finalized(task)
                self._finalized_seen.add(task.msg_id)

        # Prune known entries no longer active
        for mid in removed_ids:
            del self._known[mid]

        # Bound finalized memory
        if len(self._finalized_seen) > self.max_finalized_memory:
            excess = len(self._finalized_seen) - self.max_finalized_memory
            for mid in list(self._finalized_seen)[:excess]:
                self._finalized_seen.discard(mid)

    def run(self) -> None:
        self._running = True
        print(f"{_bold(_cyan('🔌 連接 Hermes 任務監控服務'))}")
        print(f"📡 監聽: {_bold(self.tasks_url)}")
        print(_dim("按 Ctrl+C 停止\n"))

        while self._running:
            data = _http_get(self.tasks_url, timeout=5.0)
            if data is None:
                self._error_count += 1
                if self._connected:
                    self._connected = False
                _print_connection_error(self.tasks_url, self._error_count)
                time.sleep(self.reconnect_delay)
                continue

            if not self._connected:
                if self._error_count > 0:
                    _print_reconnected(self.tasks_url)
                self._connected = True
                self._error_count = 0

            self._process(data)
            time.sleep(self.interval)

    def stop(self) -> None:
        self._running = False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes 任務監控（Copilot session）")
    parser.add_argument(
        "--url", default="http://localhost:8888", help="notify_tasks.py HTTP server URL"
    )
    parser.add_argument(
        "--interval", type=float, default=2.0, help="輪詢間隔（秒）"
    )
    parser.add_argument(
        "--reconnect-delay", type=float, default=5.0, help="重連等待時間（秒）"
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    monitor = HermesMonitor(
        base_url=args.url.rstrip("/"),
        interval=args.interval,
        reconnect_delay=args.reconnect_delay,
    )

    def _handle_sigint(sig: int, frame: Any) -> None:
        print(f"\n{_dim('[已停止]')}")
        monitor.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_sigint)
    monitor.run()


if __name__ == "__main__":
    main()
