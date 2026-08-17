#!/usr/bin/env python3
"""
Agent Mesh Watchdog (SQLite 版)

設計來源：
- codex-task-watchdog 的 job state machine 與 absence-only 政策
- A2A 協定的 Task 狀態模型（ submitted / acknowledged / working / input-required / completed / failed ）
- Claude-Code-Agent-Monitor 的共享狀態庫概念

兩種使用方式：
1. CLI 模式：給 Hermes cronjob 跑（ python watchdog_db.py run ）
2. Library 模式：Agent 行為規範呼叫（ from watchdog_db import ... ）
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ──────────────────────────────────────────────
# 常數
# ──────────────────────────────────────────────

DB_PATH = Path(__file__).resolve().parent / "agent-mesh.db"

DEFAULT_THRESHOLDS = {
    "collection":       600,   # 蒐集類任務
    "processing":       900,   # 處理類任務
    "verification":     600,   # 驗證類任務
    "unknown":          300,   # 未知任務類型的預設
}

WATCHDOG_SENDER = "watchdog"
HEARTBEAT_CHECK_INTERVAL = 30   # 秒（ codex-task-watchdog 的觀察週期概念）
REVIEW_COOLDOWN_SECONDS = 600   # 同一訊息再次回報的冷卻時間

# ──────────────────────────────────────────────
# 時間工具
# ──────────────────────────────────────────────

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def utc_now_ts() -> float:
    return time.time()

def parse_iso_to_ts(iso: Optional[str]) -> float:
    if not iso:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.timestamp()
    except (TypeError, ValueError):
        return 0.0


# ──────────────────────────────────────────────
# 資料庫初始化
# ──────────────────────────────────────────────

def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """建立所有表格（ idempotent ）。"""
    conn = get_connection(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            msg_id         TEXT PRIMARY KEY,
            type           TEXT NOT NULL DEFAULT 'task',
            status         TEXT NOT NULL DEFAULT 'submitted',
            sender         TEXT NOT NULL,
            receiver       TEXT NOT NULL,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL,
            payload        TEXT,          -- JSON
            result         TEXT,          -- JSON，完成時填入
            errors         TEXT,          -- JSON，失敗時填入
            next_hop       TEXT           -- JSON，下一步提示
        );

        CREATE TABLE IF NOT EXISTS watchdog_jobs (
            watchdog_tag     TEXT PRIMARY KEY,
            msg_id           TEXT NOT NULL REFERENCES messages(msg_id),
            state            TEXT NOT NULL DEFAULT 'armed',  -- armed | stalled | review_due | disarmed
            armed_at         TEXT NOT NULL,
            last_heartbeat_at TEXT,
            no_progress_threshold INTEGER NOT NULL,          -- 秒
            next_review_at   TEXT,
            kind             TEXT,                            -- 任務類型，用於查預設 threshold
            label            TEXT
        );

        CREATE TABLE IF NOT EXISTS incidents (
            incident_id      TEXT PRIMARY KEY,
            watchdog_tag     TEXT NOT NULL,
            msg_id           TEXT NOT NULL,
            severity         TEXT NOT NULL,                   -- warning | review | critical
            evidence         TEXT,                             -- JSON 或文字
            created_at       TEXT NOT NULL,
            resolved_at      TEXT,
            status           TEXT NOT NULL DEFAULT 'open',    -- open | resolved
            creator          TEXT NOT NULL DEFAULT 'watchdog'
        );

        CREATE TABLE IF NOT EXISTS config (
            config_key       TEXT PRIMARY KEY,
            config_value     TEXT NOT NULL
        );

        -- 預設 threshold 設定
        INSERT OR IGNORE INTO config (config_key, config_value) VALUES
            ('threshold.collection',        '600'),
            ('threshold.processing',        '900'),
            ('threshold.verification',      '600'),
            ('threshold.unknown',           '300'),
            ('review_cooldown',             '600');
    """)
    conn.commit()
    return conn


# ──────────────────────────────────────────────
# 訊息 CRUD（帶原子更新）
# ──────────────────────────────────────────────

def create_message(
    conn: sqlite3.Connection,
    msg_id: str,
    sender: str,
    receiver: str,
    payload: dict,
    msg_type: str = "task",
    result: Optional[dict] = None,
    errors: Optional[dict] = None,
    next_hop: Optional[dict] = None,
) -> None:
    """建立新訊息。 msg_id 若已存在則不建立（ 保護重複寫入 ）。"""
    now = utc_now_iso()
    conn.execute("""
        INSERT OR IGNORE INTO messages
            (msg_id, type, status, sender, receiver, created_at, updated_at, payload, result, errors, next_hop)
        VALUES (?, 'task', 'submitted', ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        msg_id, sender, receiver, now, now,
        json.dumps(payload), 
        json.dumps(result) if result else None,
        json.dumps(errors) if errors else None,
        json.dumps(next_hop) if next_hop else None,
    ))
    conn.commit()


def update_message_status(
    conn: sqlite3.Connection,
    msg_id: str,
    new_status: str,
    expected_current: Optional[str] = None,
    result: Optional[dict] = None,
    errors: Optional[dict] = None,
    next_hop: Optional[dict] = None,
) -> bool:
    """
    原子更新訊息狀態。

    - 若 expected_current 指定，則僅當目前狀態吻合才更新（ 防止覆蓋 ）。
    - 回傳 True 表示有成功更新一列， False 表示條件不吻合或 msg_id 不存在。
    """
    now = utc_now_iso()
    sql = """
        UPDATE messages
        SET status = ?,
            updated_at = ?,
            result = COALESCE(?, result),
            errors = COALESCE(?, errors),
            next_hop = COALESCE(?, next_hop)
        WHERE msg_id = ?
    """
    params: list[Any] = [new_status, now, 
                         json.dumps(result) if result else None,
                         json.dumps(errors) if errors else None,
                         json.dumps(next_hop) if next_hop else None,
                         msg_id]
    if expected_current:
        sql += " AND status = ?"
        params.append(expected_current)

    cursor = conn.execute(sql, params)
    conn.commit()
    return cursor.rowcount > 0


def get_message(conn: sqlite3.Connection, msg_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM messages WHERE msg_id = ?", (msg_id,)
    ).fetchone()
    if not row:
        return None
    return dict(row)


def get_messages_by_status(
    conn: sqlite3.Connection, status: str, limit: int = 100
) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM messages WHERE status = ? ORDER BY updated_at LIMIT ?",
        (status, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_messages_by_statuses(
    conn: sqlite3.Connection, statuses: list[str], limit: int = 200
) -> list[dict]:
    """依多個狀態查訊息（ 用於 watchdog 掃描 ）。"""
    placeholders = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"SELECT * FROM messages WHERE status IN ({placeholders}) ORDER BY updated_at LIMIT ?",
        statuses + [limit],
    ).fetchall()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# Watchdog Job 管理
# ──────────────────────────────────────────────

def get_threshold_for_kind(conn: sqlite3.Connection, kind: str) -> int:
    """查預設 threshold。若 config 表沒設定，回傳 unknown 預設值。"""
    row = conn.execute(
        "SELECT config_value FROM config WHERE config_key=?", (f"threshold.{kind}",),
    ).fetchone()
    if row:
        try:
            return int(row["config_value"])
        except ValueError:
            pass
    return DEFAULT_THRESHOLDS.get("unknown", 300)


def arm_watchdog_job(
    conn: sqlite3.Connection,
    msg_id: str,
    kind: str = "unknown",
    threshold_override: Optional[int] = None,
    label: Optional[str] = None,
) -> str:
    """
    為一個已存在的訊息 arm 一個 watchdog job。

    回傳 watchdog_tag（唯一標籤）。
    若訊息不存在則回傳空字串。
    """
    msg = get_message(conn, msg_id)
    if not msg:
        return ""

    watchdog_tag = f"WD-{uuid.uuid4().hex[:12].upper()}"
    now = utc_now_iso()
    threshold = threshold_override or get_threshold_for_kind(conn, kind)

    # arm 시점의 기준 시각을 메시지 updated_at으로 맞춘다.
    # 그래야 watchdog timer가 메시지 진행 상태와 동기화된다.
    armed_at = msg["updated_at"] if msg and "updated_at" in msg else now

    conn.execute("""
        INSERT INTO watchdog_jobs
            (watchdog_tag, msg_id, state, armed_at, no_progress_threshold, next_review_at, kind, label)
        VALUES (?, ?, 'armed', ?, ?, ?, ?, ?)
    """, (
        watchdog_tag, msg_id,
        armed_at,
        threshold,
        _compute_next_review(armed_at, threshold),
        kind,
        label,
    ))
    conn.commit()
    return watchdog_tag


def _compute_next_review(iso_at: str, threshold_seconds: int) -> str:
    ts = parse_iso_to_ts(iso_at) + threshold_seconds
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def heartbeat(
    conn: sqlite3.Connection,
    watchdog_tag: str,
    evidence: Optional[str] = None,
) -> bool:
    """
    為指定 watchdog job 記錄一次 heartbeat（ 復原 stalled 狀態 ）。

    回傳 True 表示有找到該 job 並更新。
    """
    now = utc_now_iso()
    cursor = conn.execute("""
        UPDATE watchdog_jobs
        SET state = 'armed',
            last_heartbeat_at = ?,
            next_review_at = ?
        WHERE watchdog_tag = ?
    """, (now, _compute_next_review(now, _get_job_threshold(conn, watchdog_tag)), watchdog_tag))
    conn.commit()
    return cursor.rowcount > 0


def _get_job_threshold(conn: sqlite3.Connection, watchdog_tag: str) -> int:
    row = conn.execute(
        "SELECT no_progress_threshold FROM watchdog_jobs WHERE watchdog_tag = ?",
        (watchdog_tag,),
    ).fetchone()
    return int(row["no_progress_threshold"]) if row else 300


def disarm_watchdog_job(
    conn: sqlite3.Connection,
    watchdog_tag: str,
    reason: str,
) -> bool:
    """結束一個 watchdog job。"""
    now = utc_now_iso()
    cursor = conn.execute("""
        UPDATE watchdog_jobs
        SET state = 'disarmed'
        WHERE watchdog_tag = ?
    """, (watchdog_tag,))
    conn.commit()
    if cursor.rowcount > 0:
        # 順便記一筆 incident，標示已解決
        create_incident(
            conn,
            watchdog_tag=watchdog_tag,
            msg_id="",
            severity="info",
            evidence=json.dumps({"disarm_reason": reason}),
            status="resolved",
            resolved_at=now,
        )
    return cursor.rowcount > 0


def get_active_watchdog_jobs(conn: sqlite3.Connection) -> list[dict]:
    """取得所有未 disarmed 的 job。"""
    rows = conn.execute("""
        SELECT w.*, m.status AS msg_status, m.updated_at AS msg_updated_at
        FROM watchdog_jobs w
        JOIN messages m ON w.msg_id = m.msg_id
        WHERE w.state IN ('armed', 'stalled', 'review_due')
        ORDER BY w.armed_at
    """).fetchall()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# Incident  management
# ──────────────────────────────────────────────

def create_incident(
    conn: sqlite3.Connection,
    watchdog_tag: str,
    msg_id: str,
    severity: str,
    evidence: str,
    status: str = "open",
    resolved_at: Optional[str] = None,
    creator: str = WATCHDOG_SENDER,
) -> str:
    """
    建立一筆 incident。

    - 帶有 watchdog_tag 與 msg_id。
    - 若 status 是 'resolved'，需提供 resolved_at。
    - 回傳 incident_id。
    """
    incident_id = f"INC-{uuid.uuid4().hex[:12].upper()}"
    now = utc_now_iso()
    conn.execute("""
        INSERT INTO incidents
            (incident_id, watchdog_tag, msg_id, severity, evidence, created_at, resolved_at, status, creator)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        incident_id, watchdog_tag, msg_id, severity,
        evidence, now, resolved_at, status, creator,
    ))
    conn.commit()
    return incident_id


def get_open_incidents(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute("""
        SELECT i.*, w.kind, w.no_progress_threshold
        FROM incidents i
        JOIN watchdog_jobs w ON i.watchdog_tag = w.watchdog_tag
        WHERE i.status = 'open'
        ORDER BY i.created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def resolve_incident(
    conn: sqlite3.Connection,
    incident_id: str,
    reason: str,
) -> bool:
    """將 incident 標示為已解決。"""
    now = utc_now_iso()
    cursor = conn.execute("""
        UPDATE incidents
        SET status = 'resolved',
            resolved_at = ?
        WHERE incident_id = ?
    """, (now, incident_id))
    conn.commit()
    return cursor.rowcount > 0


# ──────────────────────────────────────────────
# Watchdog 核心檢查邏輯
# ──────────────────────────────────────────────

def check_and_report_stale(
    conn: sqlite3.Connection,
    check_interval_seconds: int = HEARTBEAT_CHECK_INTERVAL,
) -> list[dict]:
    """
    核心 watchdog 掃描：

    1. 取得所有 active 的 watchdog_jobs（ armed / stalled / review_due ）
    2. 針對每個 job，判斷其對應訊息的最新狀態與更新時間
    3. 根據 no_progress_threshold 與更新時間，判定是否應標示為 stalled / review_due
    4. 針對 review_due 的 job，建立 incident（ 若尚未有 open 的同類 incident ）

    回傳本次掃描建立或更新的 incident 列表。
    """
    created_incidents: list[dict] = []
    jobs = get_active_watchdog_jobs(conn)

    for job in jobs:
        msg_status = job["msg_status"]
        msg_updated_ts = parse_iso_to_ts(job["msg_updated_at"])
        now_ts = utc_now_ts()
        threshold = job["no_progress_threshold"]
        last_heartbeat_ts = parse_iso_to_ts(job.get("last_heartbeat_at") or None)

        # 計算自從最新「可驗證進度」以來的無進度時間
        # 基準點為 msg.updated_at（訊息最後更新時間）與 watchdog 的 heartbeat，
        # 不使用 armed_at（僅為 job 建立時間，非進度指標）。
        if last_heartbeat_ts:
            latest_progress_ts = max(msg_updated_ts, last_heartbeat_ts)
        else:
            latest_progress_ts = msg_updated_ts
        idle_seconds = now_ts - latest_progress_ts

        job_state = job["state"]
        watchdog_tag = job["watchdog_tag"]
        msg_id = job["msg_id"]

        # ── 最終狀態：directly disarm ──────────────────────────────
        if msg_status in ("completed", "failed", "cancelled"):
            disarm_watchdog_job(conn, watchdog_tag, f"訊息已進入最終狀態 {msg_status}")
            created_incidents.append({"action": "disarmed", "watchdog_tag": watchdog_tag, "msg_id": msg_id})
            continue

        # ── 檢查是否從 stalled 恢復 ─────────────────────────────────────
        # 若 job 先前處於 stalled/review_due，但現在訊息已有進度（ idle < threshold ），
        # 表示已恢復，重置為 armed。
        if job_state in ("stalled", "review_due") and idle_seconds < threshold:
            conn.execute("""
                UPDATE watchdog_jobs SET state = 'armed', last_heartbeat_at = ?
                WHERE watchdog_tag = ?
            """, (utc_now_iso(), watchdog_tag))
            conn.commit()
            for inc in get_open_incidents(conn, 50):
                if inc["msg_id"] == msg_id and inc["status"] == "open":
                    resolve_incident(conn, inc["incident_id"], f"訊息狀態更新至 {msg_status}")
            created_incidents.append({"action": "reset", "watchdog_tag": watchdog_tag, "msg_id": msg_id})
            continue

        # ── 中間狀態：檢查 idle 是否超時 ────────────────────────────────
        # submitted / acknowledged / working / input-required 都可能卡住
        if msg_status in ("submitted", "acknowledged", "working", "input-required"):
            if idle_seconds >= threshold:
                conn.execute("""
                    UPDATE watchdog_jobs SET state = 'stalled'
                    WHERE watchdog_tag = ?
                """, (watchdog_tag,))
                conn.commit()
                if not _has_open_incident_for_msg(conn, msg_id, watchdog_tag):
                    inc_id = create_incident(
                        conn,
                        watchdog_tag=watchdog_tag,
                        msg_id=msg_id,
                        severity="review",
                        evidence=json.dumps({
                            "reason": f"{msg_status} 狀態超時",
                            "idle_seconds": round(idle_seconds, 1),
                            "threshold_seconds": threshold,
                            "msg_status": msg_status,
                            "sender": _get_msg_sender(conn, msg_id),
                            "receiver": _get_msg_receiver(conn, msg_id),
                        }),
                    )
                    created_incidents.append({"action": "created", "incident_id": inc_id, "msg_id": msg_id, "watchdog_tag": watchdog_tag})
            continue

    return created_incidents


def _has_open_incident_for_msg(
    conn: sqlite3.Connection, msg_id: str, watchdog_tag: str
) -> bool:
    """檢查是否已有 open 的 incident 屬於該 msg_id 與 watchdog_tag。"""
    row = conn.execute("""
        SELECT 1 FROM incidents
        WHERE msg_id = ? AND watchdog_tag = ? AND status = 'open'
        LIMIT 1
    """, (msg_id, watchdog_tag)).fetchone()
    return row is not None

    return row is not None


def _get_msg_sender(conn: sqlite3.Connection, msg_id: str) -> str:
    row = conn.execute("SELECT sender FROM messages WHERE msg_id = ?", (msg_id,)).fetchone()
    return row["sender"] if row else "unknown"

def _get_msg_receiver(conn: sqlite3.Connection, msg_id: str) -> str:
    row = conn.execute("SELECT receiver FROM messages WHERE msg_id = ?", (msg_id,)).fetchone()
    return row["receiver"] if row else "unknown"


# ──────────────────────────────────────────────
# CLI 模式（ 給 cronjob  ）
# ──────────────────────────────────────────────

def cmd_run(args) -> None:
    """執行一次 watchdog 掃描。"""
    conn = init_db(args.db)
    try:
        incidents = check_and_report_stale(conn, check_interval_seconds=args.interval)
        print(f"=== Watchdog scan complete ===")
        print(f"Active jobs scanned: {len(get_active_watchdog_jobs(conn))}")
        print(f"Incidents created/updated this run: {len(incidents)}")
        for inc in incidents:
            print(f"  - {inc}")
    finally:
        conn.close()


def cmd_status(args) -> None:
    """顯示目前 watchdog 狀態摘要。"""
    conn = init_db(args.db)
    try:
        jobs = get_active_watchdog_jobs(conn)
        print(f"=== Watchdog Status ===")
        print(f"Active jobs: {len(jobs)}")
        for j in jobs:
            print(f"  [{j['state']:10s}] {j['watchdog_tag']}  msg={j['msg_id']}  kind={j['kind']}  threshold={j['no_progress_threshold']}s")
        print()
        open_incs = get_open_incidents(conn)
        print(f"Open incidents: {len(open_incs)}")
        for inc in open_incs[:10]:
            print(f"  [{inc['severity']:7s}] {inc['incident_id']}  msg={inc['msg_id']}  watchdog={inc['watchdog_tag']}")
    finally:
        conn.close()


def cmd_arm(args) -> None:
    """為指定 msg_id arm 一個 watchdog job。"""
    conn = init_db(args.db)
    try:
        tag = arm_watchdog_job(
            conn,
            msg_id=args.msg_id,
            kind=args.kind or "unknown",
            threshold_override=args.threshold,
            label=args.label,
        )
        if tag:
            print(f"Armed: {tag}  (msg_id={args.msg_id})")
        else:
            print(f"ERROR: msg_id {args.msg_id} 不存在")
    finally:
        conn.close()


def cmd_heartbeat(args) -> None:
    """為指定 watchdog tag 送出 heartbeat。"""
    conn = init_db(args.db)
    try:
        ok = heartbeat(conn, args.tag, args.evidence)
        if ok:
            print(f"Heartbeat recorded for {args.tag}")
        else:
            print(f"WARNING: 無此 watchdog tag {args.tag}")
    finally:
        conn.close()


def cmd_disarm(args) -> None:
    """Disarm 指定 watchdog tag。"""
    conn = init_db(args.db)
    try:
        ok = disarm_watchdog_job(conn, args.tag, args.reason)
        if ok:
            print(f"Disarmed: {args.tag}  reason={args.reason}")
        else:
            print(f"WARNING: 無此 watchdog tag {args.tag}")
    finally:
        conn.close()


def cmd_create_message(args) -> None:
    """建立一則訊息（ 測試用 ）。"""
    conn = init_db(args.db)
    try:
        payload = {}
        if args.payload:
            payload = json.loads(args.payload)
        create_message(
            conn,
            msg_id=args.msg_id,
            sender=args.sender,
            receiver=args.receiver,
            payload=payload,
        )
        print(f"Created message: {args.msg_id}")
    finally:
        conn.close()


def cmd_update_message(args) -> None:
    """更新訊息狀態（ 測試用 ）。"""
    conn = init_db(args.db)
    try:
        result = None
        errors = None
        next_hop = None
        if args.result:
            result = json.loads(args.result)
        if args.errors:
            errors = json.loads(args.errors)
        if args.next_hop:
            next_hop = json.loads(args.next_hop)
        ok = update_message_status(
            conn,
            msg_id=args.msg_id,
            new_status=args.new_status,
            expected_current=args.expected_current,
            result=result,
            errors=errors,
            next_hop=next_hop,
        )
        if ok:
            print(f"Updated: {args.msg_id} -> {args.new_status}")
        else:
            print(f"ERROR: 無法更新（ 條件不吻合或 msg_id 不存在 ）")
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Agent Mesh Watchdog (SQLite 版) — 背景 watchdog 與訊息狀態追蹤工具"
    )
    parser.add_argument("--db", type=Path, default=DB_PATH, help="SQLite 資料庫路徑")

    sub = parser.add_subparsers(dest="command")

    # run
    p_run = sub.add_parser("run", help="執行一次 watchdog 掃描")
    p_run.add_argument("--interval", type=int, default=HEARTBEAT_CHECK_INTERVAL, help="檢查間隔（ 秒， 僅供參考 ）")
    p_run.set_defaults(func=cmd_run)

    # status
    p_status = sub.add_parser("status", help="顯示 watchdog 狀態摘要")
    p_status.set_defaults(func=cmd_status)

    # arm
    p_arm = sub.add_parser("arm", help="為訊息 arm watchdog job")
    p_arm.add_argument("msg_id")
    p_arm.add_argument("--kind", help="任務類型（ 決定預設 threshold ）")
    p_arm.add_argument("--threshold", type=int, help="覆寫 no-progress threshold（ 秒 ）")
    p_arm.add_argument("--label", help="job 標籤")
    p_arm.set_defaults(func=cmd_arm)

    # heartbeat
    p_heart = sub.add_parser("heartbeat", help="送出 heartbeat")
    p_heart.add_argument("tag")
    p_heart.add_argument("--evidence", help="附加證據文字")
    p_heart.set_defaults(func=cmd_heartbeat)

    # disarm
    p_disarm = sub.add_parser("disarm", help="disarm 指定 tag")
    p_disarm.add_argument("tag")
    p_disarm.add_argument("reason")
    p_disarm.set_defaults(func=cmd_disarm)

    # create_message
    p_cm = sub.add_parser("create-message", help="建立測試訊息")
    p_cm.add_argument("msg_id")
    p_cm.add_argument("--sender", default="tester")
    p_cm.add_argument("--receiver", default="agent")
    p_cm.add_argument("--payload", help="JSON payload")
    p_cm.set_defaults(func=cmd_create_message)

    # update_message
    p_um = sub.add_parser("update-message", help="更新訊息狀態（ 測試用 ）")
    p_um.add_argument("msg_id")
    p_um.add_argument("new_status")
    p_um.add_argument("--expected-current", help="期望的目前狀態（ 原子更新條件 ）")
    p_um.add_argument("--result", help="JSON result")
    p_um.add_argument("--errors", help="JSON errors")
    p_um.add_argument("--next-hop", help="JSON next_hop")
    p_um.set_defaults(func=cmd_update_message)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


def status(conn: sqlite3.Connection) -> None:
    """현재 watchdog 상태를 사람이 읽기 쉽게 출력한다."""
    jobs = get_active_watchdog_jobs(conn)
    print(f"=== Watchdog Status ===")
    print(f"Active jobs: {len(jobs)}")
    for j in jobs:
        print(f"  [{j['state']:10s}] {j['watchdog_tag']}  msg={j['msg_id']}  kind={j['kind']}  threshold={j['no_progress_threshold']}s")
    print()
    open_incs = get_open_incidents(conn)
    print(f"Open incidents: {len(open_incs)}")
    for inc in open_incs[:10]:
        print(f"  [{inc['severity']:7s}] {inc['incident_id']}  msg={inc['msg_id']}  watchdog={inc['watchdog_tag']}")


if __name__ == "__main__":
    main()
