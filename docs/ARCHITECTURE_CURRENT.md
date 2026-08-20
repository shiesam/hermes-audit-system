# Hermes Audit System — 當前實際架構（2026-08-20）

> 這是當下實際跑起來的樣子，不是理想設計。寫給後來人看的真實狀態。

## 核心組件（實際存在的）

```
主機 (vboxuser-PRO-Cubi-Z-AI-8M-MS-B032, 192.168.0.68)
├── systemd: hermes-executor.service (active, running)
│   └── agent_executor.py --agent host --db /srv/samba/.../agent-mesh.db --interval 5
│       每 5 秒 poll DB，處理 receiver=host 的任務
├── systemd: hermes-notify.timer (active, waiting)
│   └── 每 2 秒觸發 hermes-notify.service → notify_tasks.py
│       查 DB，寫任務摘要到 /var/log/hermes-notify.log
├── Samba 共享: /srv/samba/hermes-audit/ (帳密 hermes/hermes-audit-2026)
│   └── agent-mesh.db (hermes:hermes, 664)
│       ├── messages 表: 目前 1 條 (m-4efbf2f1, shrimp→host, completed)
│       ├── watchdog_jobs 表: 空
│       ├── incidents 表: 空
│       └── config 表: 預設 threshold 等設定
└── 日誌
    ├── /var/log/hermes-executor.log
    └── /var/log/hermes-notify.log

筆電 蝦米 (shies@MSI, ED25519 登入)
├── 執行 agent_initiator.py 或 agent_executor.py
├── 透過 Samba 讀寫同一份 agent-mesh.db
└── 目前行為: 已發送並完成一條任務 (m-4efbf2f1)
```

## 資料流（實際的）

```
蝦米                          主機
  │                            │
  ├─ 寫入消息到 DB ──────────→ │  （m-4efbf2f1, submitted）
  │                            │
  │                     executor│  hermes-executor.service 每 5 秒 poll
  │                     ↙       │  看到 submitted 且 receiver=host
  │               更新 status   │  → acknowledged
  │               → working    │  → 開始處理
  │               → completed  │  → 填 result
  │                            │
  │                     notify │  hermes-notify.timer 每 2 秒查
  │                     → log  │  寫任務摘要到 /var/log/hermes-notify.log
  │                            │
  └─ 讀結果 ←─────────────────┘  （可透過 DB 查詢）
```

## 沒開的部分（現狀）

- **Watchdog 掃描**：`watchdog_db.py run` 沒有被定時呼叫。沒 cronjob，也沒 hermes-watchdog.service。
  - consequence: 訊息卡住不會自動產生 incident，watchdog_jobs 表保持空，incidents 表保持空。
  - 如果需要這功能，需另外建立 systemd service 或 cronjob 來跑 `watchdog_db.py run`。

- **雙向 heartbeat / watchdog arm**：目前這條 m-4efbf2f1 沒有經歷過 watchdog arm 流程。它是直接 submitted → completed，中間沒有 watchdog job。

## 與 ARCHITECTURE.md（理想設計）的差距

| 設計中的東西 | 實際狀態 |
|-------------|----------|
| 雙向角色互換，兩個 agent 都可發起也可執行 | 實際只有 host 當執行端，shrimp 發了一個任務。角色互換程式碼有，但沒演練習。 |
| watchdog_jobs 表有 arm/stalled/disarmed 狀態流轉 | 實際表是空的，沒跑過 watchdog 掃描。 |
| incidents 表會有 open → resolved 流轉 | 實際表是空的，沒產生過 incident。 |
| cronjob/systemd service 跑 watchdog_db.py run | 沒開。 |
| 兩個 agent 都常駐監聽 | 只有 host 常駐 executor，shrimp 目前沒常駐（發完任務就結束了）。 |

## DB Schema（實際）

```sql
CREATE TABLE messages (
    msg_id     TEXT PRIMARY KEY,
    type       TEXT NOT NULL DEFAULT 'task',
    status     TEXT NOT NULL DEFAULT 'submitted',
    sender     TEXT NOT NULL,
    receiver   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version    INTEGER NOT NULL DEFAULT 1,
    payload    TEXT,
    result     TEXT,
    errors     TEXT,
    next_hop   TEXT
);

CREATE TABLE watchdog_jobs (
    watchdog_tag            TEXT PRIMARY KEY,
    msg_id                  TEXT,
    state                   TEXT,
    armed_at                TEXT,
    last_heartbeat_at       TEXT,
    no_progress_threshold   INTEGER,
    next_review_at          TEXT,
    kind                    TEXT,
    label                   TEXT
);

CREATE TABLE incidents (
    incident_id TEXT PRIMARY KEY,
    watchdog_tag TEXT,
    msg_id      TEXT,
    severity    TEXT,
    evidence    TEXT,
    created_at  TEXT,
    resolved_at TEXT,
    status      TEXT,
    creator     TEXT
);

CREATE TABLE config (
    config_key   TEXT PRIMARY KEY,
    config_value TEXT
);
```
