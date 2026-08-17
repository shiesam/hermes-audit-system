# Hermes Audit System — 雙向 Agent 協作架構 & Watchdog 機制

## 📋 目錄

1. 架構設計
2. 雙向協作流程圖
3. Watchdog 機制詳解
4. Incident 分級標準
5. Agent 角色（互換支持）
6. 部署指南
7. 常見問題
8. 資料庫 Schema

---

## 1️⃣ 架構設計

### 核心組件

```
┌─────────────────────────────────────────────┐
│  Hermes Audit System (SQLite 資料庫)       │
├─────────────────────────────────────────────┤
│                                             │
│  ┌──────────────┐   ┌──────────────┐      │
│  │   messages   │   │watchdog_jobs │      │
│  ├──────────────┤   ├──────────────┤      │
│  │ msg_id (PK)  │   │watchdog_tag  │      │
│  │ type         │   │ msg_id (FK)  │      │
│  │ status       │   │ state        │      │
│  │ sender       │   │ armed_at     │      │
│  │ receiver     │   │ threshold    │      │
│  │ version      │   │ heartbeat_at │      │
│  │ payload      │   └──────────────┘      │
│  │ result       │                          │
│  │ errors       │   ┌──────────────┐      │
│  │ next_hop     │   │  incidents   │      │
│  └──────────────┘   ├──────────────┤      │
│                     │ incident_id  │      │
│  ┌──────────────┐   │ watchdog_tag │      │
│  │    config    │   │ msg_id       │      │
│  ├──────────────┤   │ severity     │      │
│  │ threshold.*  │   │ evidence     │      │
│  │ review_cd    │   │ status       │      │
│  └──────────────┘   └──────────────┘      │
│                                             │
└─────────────────────────────────────────────┘
```

### 訊息流轉（雙向）

```
Agent X (角色 1)                Agent Y (角色 2)
        │                               │
        ├─ 1. 發送任務 ───────────────→ │
        │     (m-001, submitted)        │
        │                               ├─ 2. 監聽訊息
        │                               │
        ├─ 3. Arm Watchdog ────────────┤
        │     (WD-xxxx)                 │
        │                               ├─ 4. Heartbeat (確認收到)
        │                               │     (acknowledged)
        │                       ← ─ ─ ─ ─
        │
        ├─ 5. 等待結果                  │
        │                               ├─ 6. 工作進行中 (working)
        │                       ← ─ ─ ─ ─
        │
        │     (循環 heartbeat)          ├─ heartbeat (認可進度)
        │                       ← ─ ─ ─ ─
        │
        │                               ├─ 7. 工作完成 (completed)
        │                               │     帶著 result
        │                       ← ─ ─ ─ ─
        │
        └─ 8. Disarm Watchdog           │
              (任務結束)                  │
```

---

## 2️⃣ 雙向協作流程圖

### 正常流程

```
時間 ───────────────────────────────────────────────────────────→

X: create_message(m-001)
   ↓ state: submitted
   ├─ arm_watchdog(WD-1, threshold=600s)
   │
   ├─ wait for result
   │
   └─ [30s 間隔] check_and_report_stale()
                  ├─ msg idle < threshold? → continue
                  └─ msg idle >= threshold? → create_incident
                     (severity: review)

Y: 監聽訊息 (dedicated listener)
   ↓ 看到 m-001 submitted
   ├─ heartbeat(WD-1) → state: acknowledged
   │
   ├─ 開始工作
   ├─ heartbeat(WD-1) → state: working
   │
   ├─ 進度中...
   ├─ heartbeat(WD-1) → 重置超時計時器
   │
   ├─ 完成工作
   ├─ update_message_status(m-001, completed, result={...})
   │
   └─ [watchdog 掃描偵測] → disarm(WD-1, reason: completed)
```

### 超時流程

```
X: arm_watchdog(WD-1, threshold=300s)
   ├─ wait...
   │
   └─ [掃描] idle_seconds = 350s
              → idle_seconds >= threshold
              → state = 'stalled'
              → create_incident(severity=review)

事件報告：
  {
    "incident_id": "INC-ABC123",
    "watchdog_tag": "WD-1",
    "msg_id": "m-001",
    "severity": "review",
    "evidence": {
      "reason": "submitted 狀態超時",
      "idle_seconds": 350.5,
      "threshold_seconds": 300,
      "sender": "agent-x",
      "receiver": "agent-y"
    },
    "status": "open"
  }

X 的選擇：
  ├─ 忽略（可能 Y 還在忙）
  ├─ 增加 threshold 再重新嘗試
  └─ 宣告失敗，結束任務
```

---

## 3️⃣ Watchdog 機制詳解

### 核心狀態機

```
watchdog_jobs.state:

  armed
    ↓
  [定期掃描 check_and_report_stale()]
    ↓
  idle_seconds >= threshold?
    ├─ YES → state = 'stalled'
    │         create_incident()
    │
    └─ NO → 保持 armed

  stalled
    ↓
  [下次掃描]
    ↓
  有新的 heartbeat 或訊息更新?
    ├─ YES → state = 'armed'
    │         resolve_incident()
    │
    └─ NO → 保持 stalled

  [任何時刻]
    ├─ msg_status in (completed/failed/cancelled)
    │  → state = 'disarmed'
    │     create_incident(severity=info, resolved_at=now)
    │
    └─ 手動 disarm()
       → state = 'disarmed'
```

### Heartbeat 機制

```python
# Agent Y 調用
heartbeat(conn, watchdog_tag="WD-1")
  ↓
  UPDATE watchdog_jobs
  SET state = 'armed',
      last_heartbeat_at = now(),
      next_review_at = now() + threshold
  ↓
  重置計時器，表示「我還活著」
```

### 掃描邏輯

```python
check_and_report_stale() 每 30 秒執行一次（cronjob）
  ↓
  for job in get_active_watchdog_jobs():
    ├─ 計算 idle_seconds = now() - max(msg.updated_at, job.last_heartbeat_at)
    │
    ├─ if msg.status in (completed/failed/cancelled):
    │  │  disarm_watchdog_job()
    │  │  create_incident(severity=info, resolved_at=now)
    │  └─ continue
    │
    ├─ if job.state in (stalled, review_due) and idle_seconds < threshold:
    │  │  reset to armed
    │  │  resolve_incident()
    │  └─ continue
    │
    ├─ if msg.status in (submitted/acknowledged/working/input-required):
    │  │  if idle_seconds >= threshold:
    │  │  │  state = 'stalled'
    │  │  │  if not _has_open_incident_for_msg():
    │  │  │  │  create_incident(severity=review)
    │  │  │  └─ append to created_incidents
    │  │  └─
    │  └─
    │
    └─ [最後 return created_incidents]
```

---

## 4️⃣ Incident 分級標準

| 分級 | 觸發條件 | 應對方式 | 例子 |
|------|---------|---------|------|
| **info** | 任務正常完成 / 主動 disarm | 記錄日誌，可忽略 | `{"disarm_reason": "completed"}` |
| **warning** | 預留（未來擴展） | 警告但可重試 |（未定義） |
| **review** | idle_seconds >= threshold（超時）| 需主動檢查狀態 | `{"reason": "working 狀態超時", "idle_seconds": 450}` |
| **critical** | 預留（未來擴展） | 緊急干預 | （未定義） |

### Incident 生命週期

```
open → 被檢查、分析、決定 → resolved

create_incident(status='open')
  ├─ 應對端看到 open incident
  │
  ├─ 選擇 A：重試 / 增加 threshold
  │  → 任務進行中 → heartbeat → idle_seconds < threshold → resolve
  │
  ├─ 選擇 B：放棄任務
  │  → update_message_status(completed/failed)
  │  → watchdog 掃描偵測 → disarm → resolve
  │
  └─ 選擇 C：等待
     → heartbeat 恢復 → resolve

resolve_incident(incident_id, reason)
  └─ status = 'resolved', resolved_at = now()
```

---

## 5️⃣ Agent 角色（互換支持）

### 核心特性：角色無關（Role-Agnostic）

系統設計完全對稱，**任何 Agent 都可以是發起端或執行端**。

```
原始設定                角色互換
─────────────────────────────────
Agent A (執行端)    ←→  Agent A (發起端)
Agent B (發起端)    ←→  Agent B (執行端)

代碼邏輯相同，只需改 sender/receiver
```

### Agent 角色定義

| 角色 | 職責 | 主要函數 |
|------|------|---------|
| **發起端** | 建立任務、arm watchdog、等待結果 | `create_message()`, `arm_watchdog_job()`, `wait_for_result()` |
| **執行端** | 監聽訊息、執行工作、回報進度 | `get_messages_by_status()`, `heartbeat()`, `update_message_status()` |

### 互換方式

```python
# 原始：Agent A 是執行端，Agent B 是發起端
create_message(conn, "m-001", sender="B", receiver="A", ...)

# 互換：Agent A 是發起端，Agent B 是執行端
create_message(conn, "m-001", sender="A", receiver="B", ...)

# 核心邏輯完全相同！
```

---

## 6️⃣ 部署指南

### 1. 環境準備

```bash
# 1. 克隆倉庫
git clone https://github.com/shiesam/hermes-audit-system.git
cd hermes-audit-system

# 2. 初始化資料庫
python3 -c "from watchdog_db import init_db; init_db()"

# 3. 驗證測試
python3 test_scenario.py
python3 test_scenario_swapped.py
```

### 2. Cronjob 設置（Watchdog 掃描）

```bash
# 編輯 crontab
crontab -e

# 每 30 秒執行一次掃描（建議最少 30 秒）
* * * * * cd /home/user/hermes-audit-system && python3 watchdog_db.py run >> /var/log/hermes-watchdog.log 2>&1
* * * * * sleep 30; cd /home/user/hermes-audit-system && python3 watchdog_db.py run >> /var/log/hermes-watchdog.log 2>&1

# 每 5 分鐘查看狀態
*/5 * * * * cd /home/user/hermes-audit-system && python3 watchdog_db.py status >> /var/log/hermes-status.log 2>&1
```

### 3. 單機部署（VirtualBox）

```bash
# 啟動 watchdog cronjob
*/1 * * * * cd /home/vboxuser/hermes-audit-system && python3 watchdog_db.py run >> /var/log/hermes-watchdog.log 2>&1

# 定期查看狀態
*/5 * * * * cd /home/vboxuser/hermes-audit-system && python3 watchdog_db.py status >> /var/log/hermes-status.log 2>&1
```

### 4. 分佈式部署（VirtualBox + 筆電）

```
VirtualBox (主機)
├─ watchdog_db.py (核心)
├─ agent-mesh.db (共享 SQLite)
├─ cronjob (掃描)
│
筆電 (客戶端)
├─ clone 倉庫
├─ 連接 VirtualBox 的 DB
├─ agent_x_executor.py 或 agent_x_initiator.py
└─ 定期同步

共享方式：
├─ NFS mount
├─ Samba 共享
└─ 遠程 SSH
```

### 5. 監控儀表板

```bash
# CLI 查看狀態
python3 watchdog_db.py status

# 輸出示例
=== Watchdog Status ===
Active jobs: 3
  [armed     ] WD-ABC123  msg=m-001  kind=collection  threshold=600s
  [stalled   ] WD-DEF456  msg=m-002  kind=processing  threshold=900s
  [armed     ] WD-GHI789  msg=m-003  kind=verification  threshold=600s

Open incidents: 1
  [review  ] INC-XYZ001  msg=m-002  watchdog=WD-DEF456
```

---

## 7️⃣ 常見問題

### Q1: 如何增加 threshold？

```python
# 建立時指定
wd_tag = arm_watchdog_job(
    conn,
    msg_id="m-001",
    kind="collection",
    threshold_override=1800  # 30 分鐘
)

# 或修改 config 表
conn.execute(
    "UPDATE config SET config_value=? WHERE config_key=?",
    ('1800', 'threshold.collection')
)
conn.commit()
```

### Q2: 如何手動 disarm？

```python
disarm_watchdog_job(
    conn,
    watchdog_tag="WD-ABC123",
    reason="manual disarm - task cancelled"
)
```

### Q3: Heartbeat 應該多頻繁？

- **最少**：工作開始、進行中、完成時各一次
- **推薦**：工作中每 threshold/3 秒發一次
  - 例如 threshold=300s → 每 100s 一次
- **過於頻繁**：無益處，只會增加資料庫負擔

### Q4: 如何知道另一個 Agent 是否收到訊息？

```python
# 檢查是否已更新為 acknowledged
msg = get_message(conn, "m-001")
if msg['status'] == 'acknowledged':
    print("Agent 已收到")
elif msg['status'] == 'submitted':
    print("Agent 還未處理")
```

### Q5: Incident resolved 後還能看到嗎？

```python
# 查看 open 的
open_incs = get_open_incidents(conn)

# 查看全部（包括 resolved）
all_incs = conn.execute(
    "SELECT * FROM incidents WHERE msg_id=?",
    ("m-001",)
).fetchall()
```

### Q6: 角色互換會有問題嗎？

**完全沒有問題！** 系統設計本身是角色無關的。

```python
# 只需改這 2 行
create_message(
    conn,
    msg_id="m-001",
    sender="agent-y",  # 改這裡
    receiver="agent-x",  # 改這裡
    payload={...}
)

# 所有邏輯完全相同
```

---

## 8️⃣ 資料庫 Schema

### messages

| 欄位 | 型別 | 說明 |
|------|------|------|
| msg_id | TEXT PK | 訊息唯一識別 |
| type | TEXT | 訊息類型（通常 'task'） |
| status | TEXT | submitted/acknowledged/working/completed/failed/cancelled/input-required |
| sender | TEXT | 發起者 |
| receiver | TEXT | 接收者 |
| created_at | TEXT | ISO8601 時間戳 |
| updated_at | TEXT | 最後更新時間 |
| version | INTEGER | 樂觀鎖版本號 |
| payload | TEXT | JSON，任務內容 |
| result | TEXT | JSON，結果（完成時） |
| errors | TEXT | JSON，錯誤（失敗時） |
| next_hop | TEXT | JSON，下一步提示（input-required 時） |

### watchdog_jobs

| 欄位 | 型別 | 說明 |
|------|------|------|
| watchdog_tag | TEXT PK | 唯一標籤 WD-xxxx |
| msg_id | TEXT FK | 關聯訊息 |
| state | TEXT | armed/stalled/review_due/disarmed |
| armed_at | TEXT | 建立時間 |
| last_heartbeat_at | TEXT | 最後 heartbeat 時間 |
| no_progress_threshold | INTEGER | 超時秒數 |
| next_review_at | TEXT | 下次掃描時間 |
| kind | TEXT | 任務類型（collection/processing/verification） |
| label | TEXT | 自訂標籤 |

### incidents

| 欄位 | 型別 | 說明 |
|------|------|------|
| incident_id | TEXT PK | 唯一識別 INC-xxxx |
| watchdog_tag | TEXT | 關聯 watchdog job |
| msg_id | TEXT | 關聯訊息 |
| severity | TEXT | info/warning/review/critical |
| evidence | TEXT | JSON，詳細證據 |
| created_at | TEXT | 建立時間 |
| resolved_at | TEXT | 解決時間（若已解決） |
| status | TEXT | open/resolved |
| creator | TEXT | 建立者（通常 'watchdog'） |

---

**最後更新**: 2026-08-17
