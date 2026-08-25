#!/usr/bin/env python3
"""
Hermes Agent Executor（純 Python + sqlite3 版）

不依賴 watchdog/mesh 模組，可在 Windows（MSYS /z 工作目錄）與 Linux 主機上執行。
使用 messages 表格（不是 mesh_tasks）。
"""
import argparse
import json
import os
import random
import string
import sqlite3
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = "agent-mesh.db"   # 相對路徑（Windows MSYS /z 工作目錄推薦）
DEFAULT_INTERVAL = 5
DEFAULT_AGENT_NAME = "shrimp"


def get_connection(db_path: str) -> sqlite3.Connection:
    """取得 SQLite 連線，啟用 WAL 模式。"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def messages_get_pending(conn: sqlite3.Connection, receiver: str, limit: int = 10) -> list:
    """查詢 receiver=receiver 且 status='submitted' 的訊息，按建立時間排序。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT msg_id, type, status, sender, receiver, created_at, updated_at,
               version, payload, result, errors, next_hop
        FROM messages
        WHERE receiver = ? AND status = 'submitted'
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (receiver, limit),
    )
    rows = cur.fetchall()
    return [dict(row) for row in rows]


def messages_update(conn: sqlite3.Connection, msg_id: str, status: str,
                    result: Optional[Dict[str, Any]] = None,
                    errors: Optional[Dict[str, Any]] = None,
                    expected_current: Optional[str] = None) -> bool:
    """更新訊息狀態（含樂觀鎖）。"""
    cur = conn.cursor()
    sets = ["status = ?"]
    params = [status]
    if result is not None:
        sets.append("result = ?")
        params.append(json.dumps(result))
    if errors is not None:
        sets.append("errors = ?")
        params.append(json.dumps(errors))
    now = datetime.now(timezone.utc).isoformat()
    sets.append("updated_at = ?")
    params.append(now)
    where = "msg_id = ?"
    params.append(msg_id)
    if expected_current is not None:
        where += " AND status = ?"
        params.append(expected_current)
    cur.execute(
        f"UPDATE messages SET {', '.join(sets)} WHERE {where}",
        params,
    )
    conn.commit()
    return cur.rowcount > 0


def messages_insert(conn: sqlite3.Connection, msg_id: str, sender: str, receiver: str,
                    payload: Dict[str, Any], *, version: int = 1,
                    next_hop: Optional[Dict[str, Any]] = None) -> bool:
    """建立新訊息（task）。"""
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO messages (msg_id, type, status, sender, receiver, created_at, updated_at,
                              version, payload, result, errors, next_hop)
        VALUES (?, 'task', 'submitted', ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
        """,
        (msg_id, sender, receiver, now, now, version, json.dumps(payload),
         json.dumps(next_hop) if next_hop else None),
    )
    conn.commit()
    return True


def generate_msg_id() -> str:
    """產生 m-<timestamp>-<random6> 格式的 msg_id。"""
    ts = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    rnd = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"m-{ts}-{rnd}"


def do_work(payload: dict) -> dict:
    """執行任務，根據 type 分派。"""
    task_type = payload.get('type', 'unknown')
    if task_type == 'regulation_read':
        return _do_regulation_read(payload)
    elif task_type == 'collection':
        return {'status': 'ok', 'message': '[collection] 處理完成'}
    elif task_type == 'processing':
        return {'status': 'ok', 'message': '[processing] 處理完成'}
    elif task_type == 'verification':
        return {'status': 'ok', 'message': '[verification] 驗證完成'}
    else:
        return {'status': 'error', 'message': f'Unknown task type: {task_type}'}


def _do_regulation_read(payload: dict) -> dict:
    """閱讀法規 PDF 檔案。從 payload 中讀取 pdf_dir 與 file_names。"""
    pdf_dir = payload.get('pdf_dir', '')
    file_names = payload.get('file_names', [])
    result = {}
    for fname in file_names:
        fpath = os.path.join(pdf_dir, fname)
        if not os.path.exists(fpath):
            result[fname] = {'error': f'檔案不存在：{fpath}'}
            continue
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(fpath)
            page_count = doc.page_count
            text = ''
            for page in doc:
                text += page.get_text()
            doc.close()
            result[fname] = {'page_count': page_count, 'text': text}
        except Exception as e:
            result[fname] = {'error': str(e)}
    return result


def main():
    MEMORY_BANK_README = "/srv/samba/hermes-audit/memory-bank/README.md"

    def load_memory_bank_readme():
        try:
            with open(MEMORY_BANK_README, "r", encoding="utf-8") as f:
                content = f.read()
                print(f"📖 已讀取記憶庫規則：{MEMORY_BANK_README}（{len(content)} 字元）", flush=True)
                return content
        except FileNotFoundError:
            print(f"[WARN] 找不到記憶庫入口文件：{MEMORY_BANK_README}，本次啟動未載入記憶庫規則。", flush=True)
            return None

    memory_bank_readme = load_memory_bank_readme()
    parser = argparse.ArgumentParser(description='Hermes Agent Executor')
    parser.add_argument('--agent', type=str, default=DEFAULT_AGENT_NAME,
                        help='代理名稱（角色）')
    parser.add_argument('--db', type=str, default=DEFAULT_DB_PATH,
                        help='SQLite DB 路徑（絕對或相對）')
    parser.add_argument('--interval', type=int, default=DEFAULT_INTERVAL,
                        help='輪詢間隔（秒）')
    parser.add_argument('--once', action='store_true',
                        help='處理一個訊息後退出（測試用）')
    args = parser.parse_args()

    db_path = os.path.abspath(args.db) if not os.path.isabs(args.db) else args.db
    if not os.path.exists(db_path):
        print(f"⚠️  DB 檔案不存在：{db_path}，將建立新檔案")

    print(f"📡 Hermes Agent Executor 啟動")
    print(f"   代理名稱：{args.agent}")
    print(f"   DB 路徑：{db_path}")
    print(f"   輪詢間隔：{args.interval} 秒")
    print(f"   模式：{'--once（處理一個後退出）' if args.once else '持續輪詢'}")

    conn = get_connection(db_path)

    # 確認 messages 表格存在
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            msg_id         TEXT PRIMARY KEY,
            type           TEXT NOT NULL DEFAULT 'task',
            status         TEXT NOT NULL DEFAULT 'submitted',
            sender         TEXT NOT NULL,
            receiver       TEXT NOT NULL,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL,
            version        INTEGER NOT NULL DEFAULT 1,
            payload        TEXT,
            result         TEXT,
            errors         TEXT,
            next_hop       TEXT
        )
    """)

    while True:
        pending = messages_get_pending(conn, args.agent, limit=10)
        if pending:
            print(f"\n📬 発見 {len(pending)} 个新訊息")
            for msg in pending:
                msg_id = msg['msg_id']
                payload = json.loads(msg['payload']) if msg['payload'] else {}
                print(f"\n  ┌─ 訊息: {msg_id}")
                print(f"  │  來自: {msg['sender']}")
                print(f"  │  類型: {msg['type']}")
                print(f"  │  狀態: {msg['status']}")
                try:
                    # 1. 標示 acknowledged
                    if messages_update(conn, msg_id, 'acknowledged',
                                       expected_current='submitted'):
                        print(f"  │  ✅ 已確認（acknowledged）")
                    else:
                        print(f"  │  ❌ 確認失敗（可能已被其他代理處理）")
                        continue

                    # 2. 標示 working
                    if messages_update(conn, msg_id, 'working',
                                       expected_current='acknowledged'):
                        print(f"  │  🔄 開始執行（working）")
                    else:
                        print(f"  │  ❌ 開始執行失敗")
                        continue

                    # 3. 執行任務
                    result = do_work(payload)

                    # 4. 標示 completed
                    if messages_update(conn, msg_id, 'completed', result=result):
                        print(f"  │  ✅ 執行完成（completed）")
                        print(f"  │  結果: {json.dumps(result, indent=2)}")
                    else:
                        print(f"  │  ❌ 標示 completed 失敗")
                except Exception as e:
                    print(f"  │  ❌ 執行異常: {e}")
                    messages_update(conn, msg_id, 'failed',
                                    errors={'error': str(e)},
                                    expected_current='working')
                finally:
                    if args.once:
                        break
            if args.once:
                break
        else:
            print(f"🔍 沒有新訊息，{args.interval} 秒後重試...")
            time.sleep(args.interval)


if __name__ == '__main__':
    main()
