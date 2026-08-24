#!/usr/bin/env python3
import tempfile
from pathlib import Path

from notify_tasks import (
    fetch_active_task_rows,
    fetch_finalized_rows,
    render_task_table,
    run_once,
    setup_logger,
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


def main() -> None:
    test_fetch_and_filter()
    test_finalized_detection()
    test_run_once_state_tracking()
    print("✅ test_notify_tasks passed")


if __name__ == "__main__":
    main()
