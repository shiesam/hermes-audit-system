#!/usr/bin/env python3
import socket
import tempfile
import time
import urllib.request
from pathlib import Path

from notify_tasks import (
    fetch_active_task_rows,
    fetch_finalized_rows,
    render_task_table,
    run_once,
    setup_logger,
    start_http_server,
    _active_tasks,
    _finalized_tasks,
    _active_index,
    _update_shared_state,
)
from src.watchdog.watchdog_db import create_message, init_db, update_message_status


def test_fetch_and_filter() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "mesh.db"
        conn = init_db(db_path)
        try:
            create_message(conn, "m-host-1", "shrimp", "host", {"task_type": "processing"})
            create_message(conn, "m-shrimp-1", "host", "shrimp", {"task_type": "collection"})
            rows = fetch_active_task_rows(conn, "host")
            assert len(rows) == 1
            assert rows[0].msg_id == "m-host-1"
            assert rows[0].task_type == "processing"
        finally:
            conn.close()


def test_finalized_detection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "mesh.db"
        conn = init_db(db_path)
        try:
            create_message(conn, "m-host-2", "shrimp", "host", {"task_type": "verification"})
            update_message_status(conn, "m-host-2", "acknowledged", expected_current="submitted")
            update_message_status(conn, "m-host-2", "working", expected_current="acknowledged")
            update_message_status(conn, "m-host-2", "completed", expected_current="working")
            rows = fetch_finalized_rows(conn, "host", {"m-host-2"})
            assert len(rows) == 1
            assert rows[0].status == "completed"
        finally:
            conn.close()


def test_run_once_state_tracking() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "mesh.db"
        state_path = Path(tmp) / "state.json"
        log_path = Path(tmp) / "notify.log"

        conn = init_db(db_path)
        try:
            create_message(conn, "m-host-3", "shrimp", "host", {"task_type": "collection"})
        finally:
            conn.close()

        logger = setup_logger(log_path)
        first_count = run_once(db_path, "host", "origin", state_path, logger)
        assert first_count == 1

        second_count = run_once(db_path, "host", "origin", state_path, logger)
        assert second_count == 0

        conn = init_db(db_path)
        try:
            update_message_status(conn, "m-host-3", "acknowledged", expected_current="submitted")
        finally:
            conn.close()

        third_count = run_once(db_path, "host", "origin", state_path, logger)
        assert third_count == 1

        conn = init_db(db_path)
        try:
            table = render_task_table(fetch_active_task_rows(conn, "host"))
            assert "msg_id" in table
            assert "task_type" in table
        finally:
            conn.close()


def _free_port() -> int:
    """Return an unused TCP port on localhost."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_http_server_responds() -> None:
    """HTTP server should start, serve /api/tasks, and return valid JSON."""
    import logging

    port = _free_port()
    logger = logging.getLogger("test-http")
    server = start_http_server(port, logger)
    try:
        # Give the daemon thread a moment to bind
        time.sleep(0.1)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tasks", timeout=3) as resp:
            assert resp.status == 200
            data = __import__("json").loads(resp.read())
            assert "timestamp" in data
            assert "active_tasks" in data
            assert "finalized_tasks" in data
    finally:
        server.shutdown()


def test_http_server_404_on_unknown_path() -> None:
    """HTTP server should return 404 for unknown paths."""
    import logging

    port = _free_port()
    logger = logging.getLogger("test-http-404")
    server = start_http_server(port, logger)
    try:
        time.sleep(0.1)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/unknown", timeout=3)
            assert False, "Expected HTTPError"
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()


def test_update_shared_state_active() -> None:
    """_update_shared_state should populate active tasks correctly."""
    # Reset shared state
    _active_tasks.clear()
    _finalized_tasks.clear()
    _active_index.clear()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "mesh.db"
        conn = init_db(db_path)
        try:
            create_message(conn, "m-http-1", "shrimp", "host", {"task_type": "processing"})
            rows = fetch_active_task_rows(conn, "host")
        finally:
            conn.close()

    _update_shared_state(rows, [])
    assert len(_active_tasks) == 1
    task = list(_active_tasks)[0]
    assert task["msg_id"] == "m-http-1"
    assert task["task_type"] == "processing"
    assert "elapsed" in task


def test_update_shared_state_finalized() -> None:
    """Finalized tasks should move out of active and into finalized list."""
    _active_tasks.clear()
    _finalized_tasks.clear()
    _active_index.clear()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "mesh.db"
        conn = init_db(db_path)
        try:
            create_message(conn, "m-http-2", "shrimp", "host", {"task_type": "verification"})
            update_message_status(conn, "m-http-2", "acknowledged", expected_current="submitted")
            update_message_status(conn, "m-http-2", "working", expected_current="acknowledged")
            update_message_status(conn, "m-http-2", "completed", expected_current="working")
            final_rows = fetch_finalized_rows(conn, "host", {"m-http-2"})
        finally:
            conn.close()

    _update_shared_state([], final_rows)
    assert len(_finalized_tasks) == 1
    assert list(_finalized_tasks)[0]["status"] == "completed"
    # Should not be in active
    assert "m-http-2" not in _active_index


def main() -> None:
    test_fetch_and_filter()
    test_finalized_detection()
    test_run_once_state_tracking()
    test_http_server_responds()
    test_http_server_404_on_unknown_path()
    test_update_shared_state_active()
    test_update_shared_state_finalized()
    print("✅ test_notify_tasks passed")


if __name__ == "__main__":
    main()
