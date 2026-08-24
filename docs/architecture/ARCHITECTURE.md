# Hermes Audit System — 雙 Agent 協同架構

> 主機（Linux VirtualBox）＋ 蝦米（Windows 筆電）共享 SQLite，協同執行任務。

---

## 1. 架構概覽

```
┌────────────────────────────────────────────────────────────────────┐
│                     共享層：agent-mesh.db (SQLite)               │
│  ┌────────────┬──────────────┬─────────────┬──────────────────┐  │
│  │  messages  │ watchdog_jobs│  incidents  │     config       │  │
│  └────────────┴──────────────┴─────────────┴──────────────────┘  │
│         ▲                        ▲                ▲              │
│         │                        │                │              │
│   ┌─────┴─────┐            ┌─────┴─────┐   ┌─────┴─────┐       │
│   │   主機     │            │   蝦米     │   │  watchdog  │       │
│   │ (Linux)    │            │ (Windows) │   │  背景掃描  │       │
│   │            │            │           │   │  (cronjob) │       │
│   └────────────┘            └───────────┘   └────────────┘       │
│         │                        │                                 │
│         └────────── SMB/NFS ────┘                                 │
│              //192.168.0.68/hermes-audit                         │
└────────────────────────────────────────────────────────────────────┘
```

兩個 Agent **不直接通訊**，而是共同讀寫同一份 SQLite 資料庫。訊息透過 `messages` 表流轉，watchdog 透過 `watchdog_jobs` 偵測卡住，incident 則記錄在 `incidents` 表。

---

## 2. 兩端角色

|  | 主機（host） | 蝦米（shrimp） |
|---|---|---|
| **OS** | Linux VirtualBox (192.168.0.68) | Windows 11 筆電 |
| **角色** | 發起端、執行端（視任務） | 執行端（預設）、發起端（選配） |
| **關鍵檔案** | `agent_initiator.py`、`agent_executor.py`、`watchdog_db.py`、`notify_tasks.py`、`hermes-executor.service` | `shrimp_agent.py`、`agent_executor.py` |
| **文件** | `HOST_GUIDE.md`、`HOST_EXECUTOR_GUIDE.md` | `SHRIMP_GUIDE.md`、`SHRIMP_QUICK_START.md` |

兩端都可 **既發起也執行**，角色由訊息的 `sender`/`receiver` 決定 — 架構本身不固化角色（見第 4 節）。

---

## 3. 共享資料庫

### 放置方式

主機的 Samba 共享 `//192.168.0.68/hermes-audit`，掛載給 Windows 後即成為 `Z:\`（預設）。兩端都讀寫同一份 `agent-mesh.db`。

### 蝦米端連線設定（範例）

詳見各指南中的連線設置章節，核心變數：

| 變數 | 說明 |
|---|---|
| `HOST_IP` | 192.168.0.68 |
| `HOST_SMB_USER` / `HOST_SMB_PASS` | Samba 認證 |
| `SMB_MOUNT_DRIVE` | 掛載後的磁碟機代稱（預設 `Z:`) |
| `AGENT_MESH_DB_PATH` | 資料庫完整路徑 |

### WAL 模式與併發

資料庫啟用 `PRAGMA journal_mode=WAL` 與 `busy_timeout=5000`，支援基礎併發。兩端不要同時寫入同一筆訊息的競爭狀態由樂觀鎖（`expected_current`）處理。

---

## 4. 角色互換（Role-Agnostic）

系統設計上 **不依賴角色**。任何 Agent 都可透過改變 `sender`/`receiver` 成為發起端或執行端。

詳細請參閱 `ROLE_SWAP_GUIDE.md`，核心重點：

- 訊息流程完全相同：`submitted → acknowledged → working → completed`
- API 皆通用：`create_message()`、`arm_watchdog_job()`、`update_message_status()`、`heartbeat()` 不受角色限制
- 已通過 `test_scenario.py`（A 發 B 執行）與 `test_scenario_swapped.py`（B 發 A 執行）驗證

---

## 5. 訊息流程

```
主機（或蝦米）建立訊息                    另一端執行端監聽
┌──────────────────────┐          ┌──────────────────────────┐
│ create_message()     │          │ get_messages_by_status() │
│ status = submitted   │─────────▶│ 篩選 receiver=自己的訊息   │
│ arm watchdog job     │          └──────────────────────────┘
└──────────────────────┘                     │
                           ┌──────────────────▼──────────────────┐
                           │ update_message_status(acknowledged) │
                           │ update_message_status(working)      │
                           │ do_work(payload)                    │
                           │ update_message_status(completed)    │
                           │   result = {...}                    │
                           └─────────────────────────────────────┘
```

完整的狀態流程：

```
submitted → acknowledged → working → completed / failed / cancelled
                 ↓                ↓
            (watchdog 掃描)   (卡住時可回覆 input-required)
```

---

## 6. Watchdog 機制

### 目的

偵測任務是否卡住，產生 incident 以便介入。

### 工作原理

- `watchdog_db.py` 的 `check_and_report_stale()` 定時掃描所有活躍的 watchdog job。
- 每個 job 計算 `idle_seconds`（以 msg.updated_at 與 heartbeat 為準）。
- 若訊息狀態為 `submitted`、`acknowledged`、`working`、`input-required`，且 `idle_seconds >= no_progress_threshold`，則標示為 `stalled` 並建立 `review` 級別的 incident。
- 若訊息進入最終狀態，直接 disarm job。
- 支援 heartbeat 來重置 stalled 狀態。

### 運行方式

- **主機端**：systemd timer 每 30 秒執行一次 `python3 watchdog_db.py run`
- **蝦米端**：可透過 `shrimp_agent.py executor` 整合 heartbeat，或獨立執行 `python watchdog_db.py run`

---

## 7. 資料庫 Schema

### messages

| 欄位 | 型別 | 說明 |
|---|---|---|
| msg_id | TEXT PK | 訊息唯一 ID |
| type | TEXT | 訊息類型 |
| status | TEXT | 狀態 |
| sender | TEXT | 發送者 |
| receiver | TEXT | 接收者 |
| created_at / updated_at | TEXT | 時間戳 |
| payload | TEXT | JSON 任務資訊 |
| result | TEXT | JSON 結果 |
| errors | TEXT | JSON 錯誤 |
| next_hop | TEXT | JSON 下一步 |

### watchdog_jobs

| 欄位 | 型別 | 說明 |
|---|---|---|
| watchdog_tag | TEXT PK | watchdog 標籤 |
| msg_id | TEXT FK | 對應訊息 ID |
| state | TEXT | armed / stalled / review_due / disarmed |
| armed_at / last_heartbeat_at | TEXT | 時間戳 |
| no_progress_threshold | INTEGER | 容許最大 idle 時間（秒） |
| next_review_at | TEXT | 下次 review 時間 |
| kind | TEXT | 任務類型 |
| label | TEXT | 標籤 |

### incidents

| 欄位 | 型別 | 說明 |
|---|---|---|
| incident_id | TEXT PK | 事件唯一 ID |
| watchdog_tag | TEXT | 對應 watchdog 標籤 |
| msg_id | TEXT | 對應訊息 ID |
| severity | TEXT | warning / review / critical |
| evidence | TEXT | JSON 證據 |
| created_at / resolved_at | TEXT | 時間戳 |
| status | TEXT | open / resolved |
| creator | TEXT | 建立者 |

### config

| 欄位 | 型別 | 說明 |
|---|---|---|
| config_key | TEXT PK | 設定鍵 |
| config_value | TEXT | 設定值 |

---

## 8. 快速上手

### 情境 A：主機發起 → 蝦米執行（預設）

```bash
# 主機端（終端 1）：發起端
python agent_initiator.py --agent host --interactive

# 主機端（systemd timer）：watchdog 掃描每 30 秒一次
# （已由 hermes-watchdog.timer 自動執行）

# 蝦米端（Windows PowerShell）：執行端
cd Z:\hermes-audit-system
python shrimp_agent.py executor
```

### 情境 B：蝦米發起 → 主機執行

```powershell
# 蝦米端（PowerShell）：發起端互動模式
python shrimp_agent.py initiator --interactive

# 主機端（終端）：執行端
python agent_executor.py --agent host
```

### 情境 C：雙向協作（兩端都既發起也執行）

每端各開兩個終端：

```bash
# 主機
python agent_initiator.py --agent host --interactive   # 終端 1
python agent_executor.py --agent host                     # 終端 2

# 蝦米
python shrimp_agent.py initiator --interactive           # PowerShell 1
python shrimp_agent.py executor                           # PowerShell 2
```

---

## 9. 已完成項目

- ✅ 雙 Agent 訊息模型（messages 表 + 原子狀態更新）
- ✅ Watchdog 機制（idle 偵測、incident 產生、heartbeat）
- ✅ 角色互換設計與測試驗證
- ✅ 主機端 Samba 共享 + systemd 服務
- ✅ 蝦米端 `shrimp_agent.py`（Windows 友善包裝）
- ✅ 共享資料庫 WAL 模式 + busy_timeout

---

**更新**: 2026-08-24
