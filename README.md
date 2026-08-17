# Hermes Audit System — 雙 Agent 主動協作架構

## 簡介

Hermes Audit System 旨在強化兩個平等 Agent 之間的主動協作能力，包含雙向通訊、訊息格式驗證、確認收到、回報缺失、卡住回報、做完回覆等功能。本系統使用 SQLite 作為共享狀態庫，提供 watchdog 機制來偵測任務卡住並產生事件。

## 架構概覽

- `watchdog_db.py`：核心模組，提供訊息 CRUD、watchdog job 管理、incident 建立與解決、以及核心掃描邏輯。支援 CLI 模式（供 cronjob 排程）與 Library 模式（供 Agent 行為規範呼叫）。
- `test_scenario.py`：模擬完整任務流程的測試腳本，驗證 watchdog 行為。
- `agent-mesh.db`：SQLite 資料庫，儲存 messages、watchdog_jobs、incidents、config 等資料。
- `messages/`、`data/`、`state/`、`log/`：共享目錄（預計用於實際部署）。

## 快速開始

### 前提

- Python 3.7+
- SQLite3（內建）

### 安裝

1. 克隆或下載本倉庫。
2. 進入 `agent-mesh/` 目錄。

### 執行測試

```bash
cd agent-mesh
python3 test_scenario.py
```

測試腳本會模擬以下流程：
- 建立訊息
- Arm watchdog job
- 更新狀態為 acknowledged 和 working
- 掃描（超時情境：將 updated_at 改為老時間）
- 更新為 completed
- 最終掃描與 disarm

### CLI 使用範例

```bash
# 顯示幫助
python3 watchdog_db.py --help

# 建立訊息
python3 watchdog_db.py create-message m-001 --sender A --receiver B --payload '{"task_type":"collection"}'

# Arm watchdog
python3 watchdog_db.py arm m-001 --kind collection

# 狀態更新
python3 watchdog_db.py update-message m-001 acknowledged --expected-current submitted

# 掃描
python3 watchdog_db.py run

# 查看狀態
python3 watchdog_db.py status
```

## 架構設計

詳細設計請參閱 [architecture.md](architecture.md)。

## 消息狀態流程

訊息狀態流轉：

```
submitted → acknowledged → working → completed / failed / cancelled
                ↓                ↓
           (watchdog 掃描)   (卡住時可回覆 input-required)
```

## Watchdog 機制

- 每隔一段時間（預設 30 秒）掃描所有活躍的 watchdog job。
- 根據訊息狀態與 idle 時間，判定是否標示為 stalled 並建立 incident。
- 若訊息進入最終狀態，直接 disarm job。
- 支援 heartbeat 來重置 stalled 狀態。

## 共有表結構

- `messages`：訊息主表，包含 msg_id、type、status、sender、receiver、created_at、updated_at、payload、result、errors、next_hop。
- `watchdog_jobs`：watchdog 任務表，包含 watchdog_tag、msg_id、state、armed_at、last_heartbeat_at、no_progress_threshold、next_review_at、kind、label。
- `incidents`：事件表，包含 incident_id、watchdog_tag、msg_id、severity、evidence、created_at、resolved_at、status、creator。
- `config`：設定表，儲存預設 threshold 等設定。

## Agent 角色

- **Agent A（處理端）**：負責處理來自 Agent B 的蒐集結果，進行分析、轉換等。任務類型如 processing、verification。
- **Agent B（蒐集端）**：負責蒐集資料，將結果交給 Agent A。任務類型如 collection。

角色可對調，視任務需求而定。

## 協同方式

兩個 Agent 共享同一 SQLite 資料庫，透過訊息格式與狀態更新進行協同。不直接通訊，而是共同讀寫資料庫。

## 貢獻

歡迎提交 Issue 或 Pull Request。

## 授權

本專案採用 MIT 授權。詳情請參閱 LICENSE 檔案（若有）。
