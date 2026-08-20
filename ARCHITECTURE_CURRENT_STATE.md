# Hermes Audit System — Current State Architecture

> 這份文件描述的是 **目前倉庫內已實作、可操作、可部署到半手動狀態** 的架構。  
> 它不是理想藍圖，而是現況盤點。對外說明時，應以本文件優先於舊版 `ARCHITECTURE.md`。

---

## 1. Executive Summary

Hermes Audit System 目前是一個以 **共享 SQLite 資料庫** 為中心的雙 Agent 協作系統雛形。

它已經具備：
- message-based task queue
- watchdog timeout detection
- incident reporting
- progress event tracking
- executor polling and auto-pickup logic
- host-side notification polling via systemd timer

它目前**尚未完成**的，是把這些能力收斂成完整的常駐服務部署：
- 沒有正式交付的 `hermes-executor.service`
- 沒有倉庫內可直接安裝的 `hermes-watchdog.service`
- DB 路徑尚未全倉統一
- 舊文檔和舊腳本仍混用不同路徑/匯入方式

因此，當前狀態最準確的描述是：

> **核心邏輯已完成，部署產品化尚未完成。**

---

## 2. Repository Modules and Implementation Status

| 模組/檔案 | 角色 | 目前狀態 | 備註 |
|---|---|---|---|
| `src/watchdog/watchdog_db.py` | 共享資料庫、watchdog、incident、CLI | **已實裝** | 目前系統最核心、最完整的模組 |
| `src/mesh/progress_tracker.py` | 高階進度事件 API | **已實裝** | 封裝 `progress_events` 寫入與查詢 |
| `notify_tasks.py` | 主機端任務通知輪詢 | **已實裝** | 可配合 systemd timer 反覆掃描 DB |
| `hermes-notify.service` | 通知 service | **已實裝** | 目前唯一真正交付在 repo 內的 systemd service |
| `hermes-notify.timer` | 通知 timer | **已實裝** | 每 2 秒觸發一次通知掃描 |
| `agent_executor.py` | 通用 executor 迴圈 | **部分可用 / 入口待整理** | 自動接單邏輯存在，但直接執行仍受 import/path 影響 |
| `shrimp_agent.py` | Windows/蝦米端包裝器 | **已實裝（手動啟動）** | 封裝 initiator/executor，改善 sys.path 與路徑處理 |
| `test_host_executor.py` | 主機端 E2E 執行腳本 | **已實裝** | 偏向操作/驗證腳本，不是正式 service |
| `test_shrimp_initiator.py` | 蝦米端 E2E 發起腳本 | **已實裝** | 用於建立任務並等待主機結果 |
| `test_notify_tasks.py` | 通知腳本測試 | **已實裝** | 自成一體，可作為快速驗證 |
| `test_progress_tracking_integration.py` | 進度追蹤整合測試 | **已實裝** | 驗證 progress event API |
| `agent_initiator.py` | 舊版 initiator 腳本 | **部分可用 / 偏舊** | 仍使用舊 import 方式，與新 `src/` 佈局不一致 |
| `test_scenario.py` | 舊 watchdog scenario 腳本 | **過時** | 硬編碼 `/home/vboxuser/...` 且匯入方式舊 |
| `test_scenario_swapped.py` | 舊角色互換 scenario | **過時** | 與目前 `src/` 模組佈局不完全一致 |
| `ARCHITECTURE.md` / `architecture.md` | 歷史架構文檔 | **部分過時** | 部分內容描述理想態或舊結構，不等於現況 |

---

## 3. Actual Runtime Architecture

```text
                           ┌──────────────────────────────┐
                           │ Shared SQLite database       │
                           │ agent-mesh.db                │
                           ├──────────────────────────────┤
                           │ messages                     │
                           │ watchdog_jobs                │
                           │ incidents                    │
                           │ progress_events              │
                           │ config                       │
                           └──────────────┬───────────────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    │                     │                     │
                    ▼                     ▼                     ▼
        ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
        │ Initiator        │   │ Executor         │   │ Watchdog scanner │
        │ test_shrimp_*    │   │ agent_executor   │   │ watchdog_db run  │
        │ / agent_initiator│   │ / shrimp_agent   │   │ manual/cron      │
        └──────────────────┘   └──────────────────┘   └──────────────────┘
                    │                     │                     │
                    └────────────┬────────┴────────┬────────────┘
                                 │                 │
                                 ▼                 ▼
                      ┌──────────────────┐  ┌──────────────────┐
                      │ host notify      │  │ docs / operators │
                      │ notify_tasks.py  │  │ inspect status   │
                      │ + timer/service  │  │ / incidents      │
                      └──────────────────┘  └──────────────────┘
```

### 關鍵點
- **沒有中央 API server。** 模組全都直接讀寫同一個 SQLite。
- **沒有 broker。** `messages` 表本身就是任務佇列。
- **沒有正式常駐 executor service。** executor 存在，但要手動啟動。
- **watchdog scan 存在，但排程方式未定型。** 可手動跑，也可照文檔自行做 cron/systemd。

---

## 4. Task Flow (Current, Working Path)

以下流程描述的是 **目前最可用的一條主路徑**：蝦米端發起任務，主機端執行，watchdog 監控，notify timer 提示主機。

### 4.1 High-level flow

```text
Shrimp side initiator
  │
  │ create_message()
  │ arm_watchdog_job()
  │ record progress started
  ▼
messages.status = submitted
  │
  ├─ notify_tasks.py 可看到 host 的新任務
  │
  └─ executor poll loop 掃到 receiver=host 的 submitted 任務
        │
        │ update_message_status(..., acknowledged, expected_current=submitted)
        │ heartbeat()
        │ record_acknowledged()
        ▼
    messages.status = acknowledged
        │
        │ update_message_status(..., working, expected_current=acknowledged)
        │ record_progress(25%)
        │ do_work()
        ▼
    messages.status = working
        │
        │ heartbeat()
        │ record_progress(75%)
        │ update_message_status(..., completed, expected_current=working)
        │ record_completed()
        ▼
    messages.status = completed
        │
        ├─ initiator wait loop 讀到 result
        └─ watchdog_db run 發現最終狀態，將 job disarm
```

### 4.2 Detailed step-by-step flow

#### Step 1 — Initiator creates a message
入口可為：
- `test_shrimp_initiator.py`
- `agent_initiator.py`（較舊）
- 或任何直接調用 `create_message()` 的腳本

寫入：
- `messages.msg_id`
- `sender`
- `receiver`
- `payload`
- 初始狀態 `submitted`

#### Step 2 — Initiator arms watchdog
`arm_watchdog_job()` 會：
- 建立 `watchdog_jobs` 記錄
- 根據 `kind` 或 override 設定 threshold
- 將 `armed_at` 對齊到 message 的 `updated_at`

#### Step 3 — Initiator records started progress
透過 `ProgressTracker.record_started()` 寫入 `progress_events`。

#### Step 4 — Executor polls submitted tasks
入口可為：
- `shrimp_agent.py executor`
- `test_host_executor.py`
- `agent_executor.py --agent host`（設計存在，但目前直接執行仍受 import/path 影響）

Executor 的輪詢邏輯是：
1. 查 `status='submitted'`
2. 篩出 `receiver == self`
3. 嘗試以 `expected_current='submitted'` 原子搶單

#### Step 5 — Executor acknowledges receipt
若搶單成功：
- 將訊息設成 `acknowledged`
- 送 heartbeat
- 記錄 acknowledged progress event

#### Step 6 — Executor marks working and runs business logic
- 將訊息設成 `working`
- 執行 `do_work()`
- 記錄進度事件

目前 `do_work()` 是**模擬業務邏輯**：
- `collection`
- `processing`
- `verification`
- fallback unknown

這代表框架可用，但真實任務處理器還不是插件式正式實作。

#### Step 7 — Executor writes final result
成功時：
- `status='completed'`
- `result=<json>`
- `progress_events` 記錄 completed

失敗時：
- `status='failed'`
- `errors=<json>`
- `progress_events` 記錄 failed

#### Step 8 — Initiator waits and reads result
發起端等待迴圈會輪詢訊息狀態，直到：
- `completed`
- `failed`
- `cancelled`
- timeout

若 watchdog 產生 incident，等待迴圈也會印出警告。

#### Step 9 — Watchdog scan resolves / escalates
`watchdog_db.py run` 會：
- 對 active watchdog job 計算 idle time
- 若超時，標為 `stalled` 並建立 `review` incident
- 若訊息進入 `completed/failed/cancelled`，直接 disarm
- 若 stalled job 恢復進度，將 state reset 為 `armed` 並 resolve incident

---

## 5. Notification Flow (Current Host-side UX)

`notify_tasks.py` + `hermes-notify.service` + `hermes-notify.timer` 是目前 repo 內最接近「正式部署」的一段。

### 作用
- 查詢 `receiver='host'` 的 active task
- 比對 state file，判斷新任務或狀態變化
- 印出簡潔表格/摘要
- 對剛完成的任務印出 elapsed summary

### 運作方式
```text
systemd timer (every 2s)
  -> hermes-notify.service
     -> python3 notify_tasks.py --db ... --receiver host --deliver origin --state-file ...
        -> compare previous state vs current state
        -> log changes
```

### 限制
- 它是**通知器**，不是 executor
- 它不會執行任務，只會提示主機「有任務」或「任務狀態變了」

---

## 6. Database Design and Sharing Model

## 6.1 Why SQLite works here

目前設計是「兩端共享一個小型狀態庫」，SQLite 的優點是：
- 無需額外部署 DB server
- schema 簡單
- 可直接當 message queue + coordination store
- WAL 模式可改善讀寫並行

## 6.2 Concurrency controls already implemented

在 `get_connection()` 中已啟用：
- `PRAGMA journal_mode=WAL`
- `PRAGMA busy_timeout=5000`

在 `update_message_status()` 中已有：
- `expected_current` 條件更新
- `expected_version` 條件更新
- `version = version + 1`

這代表目前的原子性保證不是靠外部 lock server，而是靠：
- SQLite 單寫事務
- 條件式 UPDATE
- 樂觀鎖版本號

## 6.3 Shared-state tables

### `messages`
主任務表，兼具 queue 與 state machine 功能。

主要欄位：
- `msg_id`
- `type`
- `status`
- `sender`
- `receiver`
- `created_at`
- `updated_at`
- `version`
- `payload`
- `result`
- `errors`
- `next_hop`

### `watchdog_jobs`
每個 message 可綁一個 watchdog 工作，負責 timeout 判定。

主要欄位：
- `watchdog_tag`
- `msg_id`
- `state`
- `armed_at`
- `last_heartbeat_at`
- `no_progress_threshold`
- `next_review_at`
- `kind`
- `label`

### `incidents`
記錄超時、恢復、disarm 等事件。

主要用途：
- operator review
- 問題追蹤
- 之後可擴充成通知或 dashboard 資料來源

### `progress_events`
比 `messages.status` 更細粒度的時間序列記錄。

可記錄：
- `started`
- `acknowledged`
- `heartbeat`
- `progress`
- `completed`
- `failed`

### `config`
存 threshold 與冷卻等配置。

---

## 7. Implemented vs Not Implemented

## 7.1 Implemented now

- [x] 共享 SQLite 狀態庫
- [x] `messages` 任務狀態機
- [x] watchdog job 建立、heartbeat、disarm
- [x] incident 建立與 resolve
- [x] progress event tracking
- [x] executor polling auto-pickup logic
- [x] host-side notify timer/service
- [x] Windows/蝦米端包裝器 `shrimp_agent.py`
- [x] 手動 E2E 操作腳本
- [x] CLI 管理入口：`watchdog_db.py run/status/arm/heartbeat/disarm/...`

## 7.2 Partially implemented

- [~] DB 路徑統一：方向明確，但 repo 內仍混用 repo-local、`/home/vboxuser/...`、`/srv/samba/...`
- [~] Initiator/Executor 腳本收斂：新舊腳本並存，import 風格不一致
- [~] 部署文檔：已有大量內容，但部分仍描述理想態或舊結構

## 7.3 Not implemented / not delivered in repo

- [ ] `hermes-executor.service`
- [ ] `hermes-watchdog.service`
- [ ] executor 開機自啟與常駐部署
- [ ] 單一、統一、全倉一致的共享 DB 預設路徑
- [ ] 正式的 plugin-based task handlers
- [ ] RPC / network API 層
- [ ] 集中式 observability / dashboard

---

## 8. Current Deployment Guide (Reality-based)

這裡只描述**目前真的可以照著做**的方式。

### 8.1 Prepare repository
1. 取得 repo 到本機
2. 使用 Python 3.11+
3. 從 repo root 執行腳本
4. 若要匹配 `pyproject.toml` 宣告，可自行安裝依賴（例如 `uv sync` 或其他等價方式）

> 注意：部分舊腳本仍使用舊 import 方式；目前最可靠的是使用已處理 `src/` 路徑的腳本，例如 `notify_tasks.py`、`test_host_executor.py`、`test_shrimp_initiator.py`、`shrimp_agent.py`。`agent_executor.py` 的核心邏輯雖在，但其直接執行入口仍需 import/path 收斂。

### 8.2 Initialize or locate the DB
目前倉庫內的程式**預設**大多仍指向 repo 根目錄下的 `agent-mesh.db`。  
若要改用共享 DB，實際部署時必須手動把 `--db` 指向共享檔案。

### 8.3 Run executor manually
主機端（目前較務實的入口）：
```bash
python3 /absolute/path/to/test_host_executor.py --db /absolute/path/to/agent-mesh.db
```

主機端（設計上的通用 executor）：
```bash
python3 /absolute/path/to/agent_executor.py --agent host --db /absolute/path/to/agent-mesh.db
```

蝦米端（包裝器）：
```bash
python3 /absolute/path/to/shrimp_agent.py executor --db /absolute/path/to/agent-mesh.db
```

### 8.4 Run watchdog scan manually or via your own scheduler
單次執行：
```bash
python3 /absolute/path/to/src/watchdog/watchdog_db.py --db /absolute/path/to/agent-mesh.db run
```

目前 repo **沒有** 可直接安裝的 `hermes-watchdog.service`，因此：
- 可手動執行
- 可自行用 cron 包起來
- 可依 `HOST_GUIDE.md` 範例自行做 service

### 8.5 Enable host notifications
repo 內可直接使用：
- `hermes-notify.service`
- `hermes-notify.timer`

但請注意：它們目前的 `ExecStart` 仍使用 `%h/hermes-audit-system/agent-mesh.db`。  
如果你要以 `/srv/samba/hermes-audit/agent-mesh.db` 為唯一共享 DB，安裝前需要同步修改 service 參數。

### 8.6 End-to-end manual validation path
目前最務實的驗證方式是：
1. 在一端啟動 executor
2. 在另一端用 initiator/E2E script 建立任務
3. 観察 `messages`、`progress_events`、`incidents`
4. 手動執行 watchdog scan
5. 檢查 notify timer 日誌

---

## 9. Known Gaps and Risks

### 9.1 DB path divergence
目前有至少三種路徑觀念並存：
- repo-local `agent-mesh.db`
- `/home/vboxuser/hermes-audit-system/agent-mesh.db`
- `/srv/samba/hermes-audit/agent-mesh.db`

這會造成：
- 文檔與程式預設值不一致
- service 實際讀的 DB 跟操作人以為的 DB 不同
- 測試腳本與正式部署行為分離

### 9.2 Mixed import styles
目前有兩派腳本：
- 新版：先把 `src/` 加入 `sys.path`，再 `from watchdog.watchdog_db import ...`
- 舊版：直接 `from watchdog_db import ...`

這代表 repo 已經重構過一次，但舊腳本未完全清理。

### 9.3 Service layer is incomplete
executor / watchdog 都還沒有收斂成可直接 `systemctl enable --now ...` 的最終形態。

---

## 10. Recommended Next Steps

### Priority 1 — Make deployment honest
1. 保留本文件作為現況基準
2. 將舊 `ARCHITECTURE.md` 標記為歷史/理想版，避免誤用
3. 在所有對外文檔明確標示「executor 需手動啟動」

### Priority 2 — Finish the service layer
1. 新增 `hermes-executor.service`（或 template service）
2. 新增正式版 `hermes-watchdog.service` 或 `hermes-watchdog.timer`
3. 讓 host/shrimp 的啟動方式變成可安裝、可 enable、可 restart

### Priority 3 — Normalize DB path and imports
1. 決定唯一 DB 路徑
2. 讓所有程式預設值、service、文檔都對齊
3. 清理舊 import 方式與舊 scenario 腳本

### Priority 4 — Productize execution logic
1. 把 `do_work()` 從模擬邏輯抽成 handler/plugin
2. 為不同 task type 建立明確處理器
3. 規範 result/errors payload schema

---

## 11. Bottom Line

目前 Hermes Audit System 已經不是空架構圖，而是一套 **可以手動跑通核心協作流程** 的系統原型。  
它最大的短板不是資料模型，也不是 watchdog，而是**最後一哩部署**：service 化、路徑統一、舊腳本清理、文檔與現況同步。

因此，接下來所有架構說明都應先承認這個事實：

> **現在是 usable current state，不是 fully automated production state。**
