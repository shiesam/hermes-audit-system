# Hermes Audit System — 雙 Agent 主動協作架構

> 主機（Linux VirtualBox）與蝦米（Windows 筆電）共享 SQLite 資料庫，協同執行任務。

---

## 簡介

Hermes Audit System 旨在強化兩個平等 Agent 之間的主動協作能力，包含雙向通訊、訊息格式驗證、確認收到、回報缺失、卡住回報、做完回覆等功能。本系統使用 SQLite 作為共享狀態庫，提供 watchdog 機制來偵測任務卡住並產生事件。

兩個 Agent **不直接通訊**，而是共同讀寫同一份 SQLite 資料庫。角色不固定 — 任何端都可既發起任務也執行任務，角色由訊息的 `sender` / `receiver` 決定。

---

## 兩端一覽

|  | 主機（host） | 蝦米（shrimp） |
|---|---|---|
| **環境** | Linux VirtualBox, 192.168.0.68 | Windows 11 筆電 |
| **預設角色** | 發起端（也可執行端） | 執行端（也可發起端） |
| **核心檔案** | `agent_initiator.py`、`agent_executor.py`、`watchdog_db.py`、`notify_tasks.py`、`hermes-executor.service` | `shrimp_agent.py`、`agent_executor.py`、`SHRIMP_GUIDE.md`、`SHRIMP_QUICK_START.md` |
| **主要文件** | `HOST_GUIDE.md`、`HOST_EXECUTOR_GUIDE.md`、`docs/HOST_STATUS_2026-08-20.md` | `SHRIMP_GUIDE.md`、`SHRIMP_QUICK_START.md` |

---

## 架構設計

完整設計請參閱 [ARCHITECTURE.md](ARCHITECTURE.md)。

簡要來說：

- **共享層**：`agent-mesh.db`（SQLite，WAL 模式）放在主機 Samba 共享 `//192.168.0.68/hermes-audit` 上，兩端都掛載存取。
- **訊息表** `messages`：儲存任務訊息與狀態（submitted → acknowledged → working → completed / failed / cancelled）。
- **Watchdog** `watchdog_jobs` + `incidents`：背景掃描偵測卡住，產生 incident。
- **角色互換**：角色不固化，可透過改變 sender/receiver 互換（見 `ROLE_SWAP_GUIDE.md`）。

---

## 文件地圖

### 主機端

| 文件 | 內容 |
|---|---|
| `HOST_GUIDE.md` | 主機部署指南：Samba 設定、cronjob、systemd 服務 |
| `HOST_EXECUTOR_GUIDE.md` | 主機執行端操作細節 |
| `notify_tasks.py` | 任務通知腳本 |
| `hermes-executor.service` | systemd 服務檔 |
| `docs/HOST_STATUS_2026-08-20.md` | 主機狀態記錄 |
| `docs/ARCHITECTURE_CURRENT.md` | 當前架構快照 |
| `docs/LESSONS_LEARNED.md` | 心得與教訓 |
| `docs/AGENT_QUICK_REFERENCE.md` | Agent 快速參考 |

### 蝦米端

| 文件 | 內容 |
|---|---|
| `SHRIMP_GUIDE.md` | 蝦米完整部署指南（安裝、執行、連線、故障排查） |
| `SHRIMP_QUICK_START.md` | 5 分鐘快速上線：環境準備 → 克隆 → 測試 → 三種運行方式 |
| `shrimp_agent.py` | 蝦米專用 Agent 包裝（executor 與 initiator 兩種模式） |
| `shrimp_config.env.example` | 環境變數範本（複製為 `shrimp_config.env` 並填入實際值） |
| `agent_executor.py` | 通用執行端（主機與蝦米皆可用） |
| `agent_initiator.py` | 通用發起端 |
| `ROLE_SWAP_GUIDE.md` | 角色互換指南 |
| `test_scenario.py` / `test_scenario_swapped.py` | 角色互換測試腳本 |

---

## 快速開始

### 途徑 A：主機發起 → 蝦米執行（預設推薦）

```bash
# 主機端（Linux 終端 1）：發起端
python agent_initiator.py --agent host --interactive

# 主機端（cronjob）：watchdog 掃描每分鐘一次
* * * * * cd /home/vboxuser/hermes-audit-system && python3 watchdog_db.py run

# 蝦米端（Windows PowerShell）：執行端
cd Z:\hermes-audit-system
python shrimp_agent.py executor
```

### 途徑 B：蝦米發起 → 主機執行

```powershell
# 蝦米端（PowerShell）：發起端互動模式
python shrimp_agent.py initiator --interactive

# 主機端（Linux 終端）：執行端
python agent_executor.py --agent host
```

### 途徑 C：雙向協作（兩端都既發起也執行）

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

## 測試

### 角色互換測試

```bash
# A 發起、B 執行
python test_scenario.py

# B 發起、A 執行（互換）
python test_scenario_swapped.py
```

兩個測試都該看到 ✅ 所有步驟通過。

### 蝦米端快速驗證

```powershell
# 進入倉庫目錄
cd Z:\hermes-audit-system

# 運行測試
python shrimp_agent.py executor --max-iterations 3
```

預期看到「蝦米 — 執行端模式」的輸出，輪詢 3 次後停止。

---

## 運行方式（蝦米端三選一）

蝦米可透過 `shrimp_agent.py` 跑三種模式：

| 模式 | 命令 | 說明 |
|---|---|---|
| **執行端**（推薦） | `python shrimp_agent.py executor` | 監聽主機任務，自動確認並回報結果 |
| **發起端 互動** | `python shrimp_agent.py initiator --interactive` | 逐個輸入任務參數，建立任務並等待結果 |
| **發起端 批次** | `python shrimp_agent.py initiator --task-type collection --description "蒐集數據"` | 一次建立一個任務，可選擇不等待結果 |

完整用法與參數請見 `SHRIMP_QUICK_START.md`。

---

## 環境變數設定（蝦米端）

複製 `shrimp_config.env.example` 為 `shrimp_config.env` 並修改：

| 變數 | 預設 / 範例 | 說明 |
|---|---|---|
| `AGENT_NAME` | `shrimp` | Agent 名稱 |
| `AGENT_ROLE` | `laptop` | 角色標示 |
| `HERMES_WORKSPACE` | `D:/hermes-workspace/hermes-audit-system` | 工作目錄 |
| `HOST_IP` | `192.168.0.68` | 主機 IP |
| `HOST_SMB_USER` | `hermes` | Samba 使用者 |
| `HOST_SMB_PASS` | <需填入> | Samba 密碼 |
| `HOST_SMB_SHARE` | `hermes-audit` | 共享名稱 |
| `HOST_SMB_PATH` | `//192.168.0.68/hermes-audit` | 共享路徑 |
| `SMB_MOUNT_DRIVE` | `Z:` | 掛載後的磁碟機 |
| `AGENT_MESH_DB_PATH` | `${SMB_MOUNT_DRIVE}/agent-mesh.db` | 資料庫路徑 |
| `WATCHDOG_INTERVAL_SEC` | `60` | 輪詢間隔 |
| `LOG_LEVEL` | `INFO` | 日誌等級 |

---

## 連結文件

- [ARCHITECTURE.md](ARCHITECTURE.md) — 完整雙 Agent 協同架構設計
- [SHRIMP_GUIDE.md](SHRIMP_GUIDE.md) — 蝦米完整部署指南
- [SHRIMP_QUICK_START.md](SHRIMP_QUICK_START.md) — 蝦米 5 分鐘快速上線
- [ROLE_SWAP_GUIDE.md](ROLE_SWAP_GUIDE.md) — 角色互換指南
- [HOST_GUIDE.md](HOST_GUIDE.md) — 主機部署指南

---

## 授權

本專案採用 MIT 授權。
