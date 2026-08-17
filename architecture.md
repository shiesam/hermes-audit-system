# 雙 Agent 協作架構設計

## 1. 架構概覽

```
┌─────────────────────────────────────────────────────────────┐
│                    agent-mesh/ 共享目錄                      │
│  ┌─────────────┬─────────────┬─────────────┬─────────────┐ │
│  │  messages/  │   data/     │   state/    │    log/     │ │
│  │  (訊息檔案) │ (任務資料)  │ (狀態檔案)  │  (日誌)     │ │
│  └─────────────┴─────────────┴─────────────┴─────────────┘ │
│                          │                                  │
│                     agent-mesh.db (SQLite)                  │
│  ┌──────────────────────┴──────────────────────────────┐   │
│  │  messages  │  watchdog_jobs  │  incidents  │ config │   │
│  └──────────────────────┴──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
           │                 │
           ▼                 ▼
     ┌───────────┐    ┌───────────┐
     │  Agent A  │    │  Agent B  │
     │  (處理端) │    │  (蒐集端) │
     └───────────┘    └───────────┘
           │                 │
           └───────┬───────┘
                   │
           watchdog_db.py (背景掃描)
                   │
                   ▼
            產生 incidents / report
```

## 2. Agent 角色與職責

### Agent A（處理端）
- 主要職責：接收 Agent B 的蒐集結果，進行處理（分析、轉換、產生輸出）。
- 任務類型範例：processing、verification。
- 行為規範：
  - 收到訊息後，先驗證格式。
  - 若格式有誤，回覆 input-required。
  - 處理中若發現問題，回報。
  - 處理完成後，寫入 result，更新狀態為 completed，設定 next_hop。

### Agent B（蒐集端）
- 主要職責：蒐集資料（如從網站、下載、資料庫等），將結果交給 Agent A 處理。
- 任務類型範例：collection。
- 行為規範：
  - 收到任務後，確認能否處理；若缺少資料，可自行取得或回覆 input-required。
  - 蒐集過程中若發生問題，回報。
  - 蒐集完成後，寫入結果，更新狀態為 completed，設定 next_hop 指向 Agent A。

### 角色對調
- 任務流程中，角色可互換。視任務類型與 Agent 能力而定。

## 3. 通訊與協作方式

### 訊息格式
訊息儲存在 `messages` 表，包含欄位：
- msg_id: 唯一識別符
- type: 訊息類型（預設 task，可擴充 report、input-required 等）
- status: 狀態（submitted、acknowledged、working、input-required、completed、failed、cancelled）
- sender: 发送者 Agent ID
- receiver: 接收者 Agent ID
- created_at / updated_at: 時間戳
- payload: JSON（任務類型、描述、輸入參考等）
- result: JSON（處理結果）
- errors: JSON（錯誤訊息）
- next_hop: JSON（下一步提示）

### 狀態流程
任務訊息生命週期：
submitted → acknowledged → working → completed / failed / cancelled
              ↑                ↓
        (watchdog 掃描)   (卡住時可回覆 input-required)

### 協作流程範例（A 處理，B 蒐集）
1. 任務创建：建立訊息，狀態 submitted，指定 sender、receiver。
2. 分配 watchdog job：Agent 收到訊息後，建立 watchdog job（arm_watchdog_job），設定任務類型與 threshold。
3. 確認收到：接收方將狀態更新為 acknowledged（原子更新）。
4. 處理中：接收方將狀態更新為 working，開始執行任務。
5. 結果回報：
   - 若處理完成，寫入 result，狀態更新為 completed，設定 next_hop。
   - 若發生錯誤，寫入 errors，狀態更新為 failed 或 input-required。
6. 角色對調：若 A 處理完，可能將任務交給 B 繼續，或 B 處理完交給 A。

### 共享狀態庫（SQLite）
- 兩個 Agent 共用同一 db 檔案，所有訊息、watchdog job、incidents 都儲存於此。
- 資料庫使用 WAL 模式與 busy_timeout，支援基礎併發。
- Agent 之間不直接通訊，而是透過共同讀寫資料庫協同。

## 4. Watchdog 機制

### 目的
偵測任務是否卡住，產生事件以便介入或回報。

### 工作原理
- `watchdog_db.py` 的 `check_and_report_stale()` 函式定時掃描所有活躍的 watchdog job。
- 針對每個 job，計算 `idle_seconds`（以 msg.updated_at 與 heartbeat 為準，不使用 armed_at）。
- 若訊息狀態為 submitted、acknowledged、working、input-required，且 idle_seconds >= no_progress_threshold，則將 job 標示為 stalled，並建立 review 級別的 incident。
- 若訊息狀態為最終狀態（completed、failed、cancelled），則直接 disarm job。
- 若 job 預先處於 stalled/review_due，但現在訊息已有進度（idle_seconds < threshold），則重置為 armed，並解決已有的 open incidents。

### 事件類型
- review：任務卡住，需要介入。
- disarmed：任務正常結束。
- info：其他資訊。

## 5. 資料庫 schema

### messages
| 欄位 | 型別 | 說明 |
|------|------|------|
| msg_id | TEXT PK | 訊息唯一 ID |
| type | TEXT | 訊息類型 |
| status | TEXT | 狀態 |
| sender | TEXT | 发送者 |
| receiver | TEXT | 接收者 |
| created_at | TEXT | 建立時間 |
| updated_at | TEXT | 更新時間 |
| payload | TEXT | JSON 任務資訊 |
| result | TEXT | JSON 結果 |
| errors | TEXT | JSON 錯誤 |
| next_hop | TEXT | JSON 下一步 |

### watchdog_jobs
| 欄位 | 型別 | 說明 |
|------|------|------|
| watchdog_tag | TEXT PK | watchdog 標籤 |
| msg_id | TEXT FK | 對應訊息 ID |
| state | TEXT | 狀態（armed、stalled、review_due、disarmed） |
| armed_at | TEXT | armed 時間 |
| last_heartbeat_at | TEXT | 最後 heartbeat 時間 |
| no_progress_threshold | INTEGER | 容許最大 idle 時間（秒） |
| next_review_at | TEXT | 下次 review 時間 |
| kind | TEXT | 任務類型 |
| label | TEXT | 標籤 |

### incidents
| 欄位 | 型別 | 說明 |
|------|------|------|
| incident_id | TEXT PK | 事件唯一 ID |
| watchdog_tag | TEXT | 對應 watchdog 標籤 |
| msg_id | TEXT | 對應訊息 ID |
| severity | TEXT | 嚴重程度（warning、review、critical） |
| evidence | TEXT | JSON 證據 |
| created_at | TEXT | 建立時間 |
| resolved_at | TEXT | 解決時間 |
| status | TEXT | 狀態（open、resolved） |
| creator | TEXT | 建立者 |

### config
| 欄位 | 型別 | 說明 |
|------|------|------|
| config_key | TEXT PK | 設定鍵 |
| config_value | TEXT | 設定值 |

## 6. 已完成項目

- SQLite 架構設計與實作（watchdog_db.py）
- 訊息 CRUD 與原子更新
- watchdog job 管理（arm、heartbeat、disarm）
- incident 建立與解決
- 核心掃描邏輯 `check_and_report_stale()`
- CLI 與 Library 兩種使用模式
- 測試腳本 `test_scenario.py` 驗證完整流程
- Bug 修復：6-7 步無法產 incident 的問題（現已能正確偵測 idle 超時）

## 7. 待完成項目

- [ ] 雙 Agent 實際協同測試（真機載入兩個 Agent 進程）
- [ ] 事件觸發機制（inotify 或 webhook 中間層，取代單純 polling）
- [ ] 行為規範腳本（Prompt / 記憶 / 技能）寫入
- [ ] Disarm 時自動關閉舊 incident（優化）
- [ ] 訊息格式驗證（必要欄位檢查、payload 結構驗證）
- [ ] 任務搶佔與原子更新機制（lock 檔案或更新條件）
- [ ] 日誌與追蹤（log/ 目錄）
- [ ] 排程與部署設定（Hermes cronjob 或系統 crontab）
- [ ] 行為規範提示片段（供 Copilot 檢查）
- [ ] 監控與除錯工具

## 8. 快速參考

### CLI 指令範例

```bash
# 幫助
python3 watchdog_db.py --help

# 建立訊息
python3 watchdog_db.py create-message m-001 --sender A --receiver B --payload '{"task_type":"collection"}'

# Arm watchdog
python3 watchdog_db.py arm m-001 --kind collection

# 狀態更新
python3 watchdog_db.py update-message m-001 acknowledged --expected-current submitted

# 掃描
python3 watchdog_db.py run

# 狀態
python3 watchdog_db.py status
```

### Library 模式範例

```python
from watchdog_db import init_db, create_message, update_message_status, arm_watchdog_job, check_and_report_stale

conn = init_db()
create_message(conn, "m-001", "A", "B", {"task_type":"collection"})
arm_watchdog_job(conn, "m-001", kind="collection")
update_message_status(conn, "m-001", "acknowledged", expected_current="submitted")
# ... 處理中 ...
update_message_status(conn, "m-001", "completed", expected_current="working", result={"output":"..."})
conn.close()
```

## 9. 授權

MIT
