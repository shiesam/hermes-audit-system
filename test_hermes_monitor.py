#!/usr/bin/env python3
"""
test_hermes_monitor.py - HermesMonitor の単体テスト
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from hermes_monitor import HermesMonitor, TaskInfo, _http_get


# ---------------------------------------------------------------------------
# Tiny mock HTTP server
# ---------------------------------------------------------------------------

class _MockHandler(BaseHTTPRequestHandler):
    """Serves JSON from the shared _responses dict keyed by path."""

    _responses: dict[str, dict] = {}

    def log_message(self, format, *args):  # noqa: A002
        pass

    def do_GET(self):
        body = json.dumps(self._responses.get(self.path, {"error": "not found"})).encode()
        status = 200 if self.path in self._responses else 404
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_mock_server(responses: dict[str, dict]) -> tuple[HTTPServer, int]:
    _MockHandler._responses = responses
    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_http_get_success():
    payload = {"timestamp": "2026-08-20T00:00:00Z", "active_tasks": [], "finalized_tasks": []}
    server, port = _start_mock_server({"/api/tasks": payload})
    try:
        result = _http_get(f"http://127.0.0.1:{port}/api/tasks")
        assert result == payload
    finally:
        server.shutdown()


def test_http_get_failure():
    # Port that nothing is listening on — should return None
    result = _http_get("http://127.0.0.1:19999/api/tasks", timeout=0.5)
    assert result is None


def test_task_info_from_dict():
    d = {
        "msg_id": "m-abc",
        "task_type": "processing",
        "sender": "shrimp",
        "receiver": "host",
        "status": "submitted",
        "created_at": "2026-08-20T10:00:00Z",
        "updated_at": "2026-08-20T10:00:01Z",
        "elapsed": "1s",
    }
    t = TaskInfo.from_dict(d)
    assert t.msg_id == "m-abc"
    assert t.status == "submitted"
    assert t.fingerprint == "submitted|2026-08-20T10:00:01Z"


def test_new_task_detection(capsys):
    monitor = HermesMonitor()
    data = {
        "timestamp": "T",
        "active_tasks": [
            {
                "msg_id": "m-1",
                "task_type": "processing",
                "sender": "shrimp",
                "receiver": "host",
                "status": "submitted",
                "created_at": "2026-08-20T10:00:00Z",
                "updated_at": "2026-08-20T10:00:00Z",
                "elapsed": "0s",
            }
        ],
        "finalized_tasks": [],
    }
    monitor._process(data)
    captured = capsys.readouterr()
    assert "m-1" in captured.out
    assert "m-1" in monitor._known


def test_status_change_detection(capsys):
    monitor = HermesMonitor()
    # Seed known state
    monitor._known["m-2"] = "submitted|2026-08-20T10:00:00Z"

    data = {
        "timestamp": "T",
        "active_tasks": [
            {
                "msg_id": "m-2",
                "task_type": "processing",
                "sender": "shrimp",
                "receiver": "host",
                "status": "working",
                "created_at": "2026-08-20T10:00:00Z",
                "updated_at": "2026-08-20T10:00:05Z",
                "elapsed": "5s",
            }
        ],
        "finalized_tasks": [],
    }
    monitor._process(data)
    captured = capsys.readouterr()
    assert "m-2" in captured.out
    assert monitor._known["m-2"] == "working|2026-08-20T10:00:05Z"


def test_finalized_detection(capsys):
    monitor = HermesMonitor()
    # Task was active before, now gone from active_tasks
    monitor._known["m-3"] = "working|2026-08-20T10:00:05Z"

    data = {
        "timestamp": "T",
        "active_tasks": [],  # m-3 is gone
        "finalized_tasks": [
            {
                "msg_id": "m-3",
                "task_type": "processing",
                "sender": "shrimp",
                "receiver": "host",
                "status": "completed",
                "created_at": "2026-08-20T10:00:00Z",
                "updated_at": "2026-08-20T10:00:30Z",
                "elapsed": "30s",
            }
        ],
    }
    monitor._process(data)
    captured = capsys.readouterr()
    assert "m-3" in captured.out
    assert "m-3" in monitor._finalized_seen
    assert "m-3" not in monitor._known


def test_no_duplicate_finalized_notification(capsys):
    monitor = HermesMonitor()
    monitor._known["m-4"] = "working|2026-08-20T10:00:05Z"
    data = {
        "timestamp": "T",
        "active_tasks": [],
        "finalized_tasks": [
            {
                "msg_id": "m-4",
                "task_type": "processing",
                "sender": "shrimp",
                "receiver": "host",
                "status": "completed",
                "created_at": "2026-08-20T10:00:00Z",
                "updated_at": "2026-08-20T10:00:30Z",
                "elapsed": "30s",
            }
        ],
    }
    monitor._process(data)
    # Second call — should not print again
    monitor._process(data)
    captured = capsys.readouterr()
    count = captured.out.count("m-4")
    assert count == 1  # Only one notification


def test_reconnect_logic():
    """Monitor stops cleanly after stop() is called."""
    responses = {
        "/api/tasks": {
            "timestamp": "T",
            "active_tasks": [],
            "finalized_tasks": [],
        }
    }
    server, port = _start_mock_server(responses)
    try:
        monitor = HermesMonitor(
            base_url=f"http://127.0.0.1:{port}",
            interval=0.05,
        )
        # Run in a thread and stop after a short time
        errors = []

        def _run():
            try:
                monitor.run()
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(0.2)
        monitor.stop()
        t.join(timeout=2.0)
        assert not t.is_alive()
        assert not errors
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# Notify tasks HTTP server integration
# ---------------------------------------------------------------------------

def test_notify_tasks_http_server():
    """TaskMonitorServer exposes /api/tasks, /health, /metrics."""
    from notify_tasks import TaskMonitorServer

    server = TaskMonitorServer(port=0)  # OS assigns a free port
    server.start()
    port = server.port
    time.sleep(0.1)  # let the thread start
    try:
        data = _http_get(f"http://127.0.0.1:{port}/api/tasks")
        assert data is not None
        assert "active_tasks" in data
        assert "finalized_tasks" in data

        health = _http_get(f"http://127.0.0.1:{port}/health")
        assert health is not None
        assert health.get("status") == "ok"

        metrics = _http_get(f"http://127.0.0.1:{port}/metrics")
        assert metrics is not None
        assert "request_count" in metrics
    finally:
        server.stop()


def main() -> None:
    import traceback
    tests = [
        test_http_get_success,
        test_http_get_failure,
        test_task_info_from_dict,
        test_notify_tasks_http_server,
        test_reconnect_logic,
    ]
    failures = 0
    for fn in tests:
        try:
            fn()
            print(f"  ✅ {fn.__name__}")
        except Exception:
            failures += 1
            print(f"  ❌ {fn.__name__}")
            traceback.print_exc()

    # Run pytest-style tests manually (no capsys)
    class _CapSys:
        """Minimal capsys substitute that captures stdout."""
        def __init__(self):
            import io
            self._buf = io.StringIO()

        def __enter__(self):
            import sys
            self._old = sys.stdout
            sys.stdout = self._buf
            return self

        def __exit__(self, *a):
            import sys
            sys.stdout = self._old

        def readouterr(self):
            v = self._buf.getvalue()
            self._buf.truncate(0); self._buf.seek(0)
            return type("R", (), {"out": v, "err": ""})()

    cap_tests = [
        test_new_task_detection,
        test_status_change_detection,
        test_finalized_detection,
        test_no_duplicate_finalized_notification,
    ]
    for fn in cap_tests:
        try:
            with _CapSys() as cap:
                fn(cap)
            print(f"  ✅ {fn.__name__}")
        except Exception:
            failures += 1
            print(f"  ❌ {fn.__name__}")
            traceback.print_exc()

    if failures:
        print(f"\n❌ {failures} test(s) failed")
        raise SystemExit(1)
    print("\n✅ test_hermes_monitor passed")


if __name__ == "__main__":
    main()
