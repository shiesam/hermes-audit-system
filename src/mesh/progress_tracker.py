#!/usr/bin/env python3
"""
ProgressTracker — 高階進度追蹤 API

目的：
- 為 Agent 提供簡單的進度記錄介面
- 無需直接呼叫 watchdog_db，降低耦合
- 支援進度百分比、訊息、元數據記錄
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from watchdog_db import (
    init_db,
    record_progress_event,
    get_task_progress,
    get_agent_status,
)


class ProgressTracker:
    """進度追蹤器 — 為任務記錄進度事件。"""

    def __init__(
        self,
        db_path: Path | str,
        task_id: str,
        agent_name: str,
    ):
        """
        初始化進度追蹤器。

        Args:
            db_path: SQLite 資料庫路徑
            task_id: 任務 ID（message.msg_id）
            agent_name: Agent 名稱（e.g., 'host', 'shrimp'）
        """
        self.db_path = Path(db_path) if isinstance(db_path, str) else db_path
        self.task_id = task_id
        self.agent_name = agent_name
        self.conn = init_db(self.db_path)

    def record_started(self, message: Optional[str] = None, metadata: Optional[dict] = None) -> str:
        """記錄任務開始事件。"""
        msg = message or f"Task {self.task_id} started on {self.agent_name}"
        return record_progress_event(
            self.conn,
            task_id=self.task_id,
            event_type="started",
            agent_name=self.agent_name,
            status="submitted",
            message=msg,
            metadata=metadata,
        )

    def record_acknowledged(self, message: Optional[str] = None, metadata: Optional[dict] = None) -> str:
        """記錄任務被 acknowledge。"""
        msg = message or f"Task {self.task_id} acknowledged by {self.agent_name}"
        return record_progress_event(
            self.conn,
            task_id=self.task_id,
            event_type="acknowledged",
            agent_name=self.agent_name,
            status="acknowledged",
            message=msg,
            metadata=metadata,
        )

    def record_progress(
        self,
        percent: int,
        message: str,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        記錄進度百分比。

        Args:
            percent: 進度百分比 (0-100)
            message: 進度訊息
            metadata: 額外元數據
        """
        if not 0 <= percent <= 100:
            raise ValueError(f"percent must be 0-100, got {percent}")
        
        return record_progress_event(
            self.conn,
            task_id=self.task_id,
            event_type="progress",
            agent_name=self.agent_name,
            status="working",
            progress_percent=percent,
            message=message,
            metadata=metadata,
        )

    def record_heartbeat(self, message: Optional[str] = None, metadata: Optional[dict] = None) -> str:
        """
        記錄心跳（表示 Agent 仍在活動）。

        Args:
            message: 心跳訊息
            metadata: 額外元數據
        """
        msg = message or f"Heartbeat from {self.agent_name}"
        return record_progress_event(
            self.conn,
            task_id=self.task_id,
            event_type="heartbeat",
            agent_name=self.agent_name,
            message=msg,
            metadata=metadata,
        )

    def record_completed(
        self,
        result: Any,
        message: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        記錄任務完成。

        Args:
            result: 任務結果
            message: 完成訊息
            metadata: 額外元數據
        """
        msg = message or f"Task {self.task_id} completed on {self.agent_name}"
        full_metadata = metadata or {}
        full_metadata["result"] = result
        
        return record_progress_event(
            self.conn,
            task_id=self.task_id,
            event_type="completed",
            agent_name=self.agent_name,
            status="completed",
            progress_percent=100,
            message=msg,
            metadata=full_metadata,
        )

    def record_failed(
        self,
        error: str,
        message: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        記錄任務失敗。

        Args:
            error: 錯誤訊息
            message: 失敗訊息
            metadata: 額外元數據
        """
        msg = message or f"Task {self.task_id} failed on {self.agent_name}: {error}"
        full_metadata = metadata or {}
        full_metadata["error"] = error
        
        return record_progress_event(
            self.conn,
            task_id=self.task_id,
            event_type="failed",
            agent_name=self.agent_name,
            status="failed",
            message=msg,
            metadata=full_metadata,
        )

    def get_history(self) -> list[dict]:
        """取得任務的完整進度歷史。"""
        return get_task_progress(self.conn, self.task_id)

    def get_latest(self) -> dict | None:
        """取得 Agent 最後一次的進度事件。"""
        return get_agent_status(self.conn, self.agent_name)

    def close(self) -> None:
        """關閉資料庫連線。"""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        """Context manager 進入。"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager 退出。"""
        self.close()


# 便利函數：快速記錄進度
def quick_record(
    db_path: Path | str,
    task_id: str,
    agent_name: str,
    event_type: str,
    message: str,
    progress_percent: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> str:
    """
    快速記錄進度事件（不需要建立 ProgressTracker）。

    Args:
        db_path: 資料庫路徑
        task_id: 任務 ID
        agent_name: Agent 名稱
        event_type: 事件類型
        message: 訊息
        progress_percent: 進度百分比
        metadata: 元數據

    Returns:
        event_id
    """
    conn = init_db(db_path)
    try:
        return record_progress_event(
            conn,
            task_id=task_id,
            event_type=event_type,
            agent_name=agent_name,
            message=message,
            progress_percent=progress_percent,
            metadata=metadata,
        )
    finally:
        conn.close()
