# Hermes Audit System — Agent Quick Reference

> 快速查詢：系統架構、常見改動、測試腳本、已知陷阱、故障排查。
> 寫給開發/維護這套系統的人，查一眼就知道怎麼動。

---

## 1️⃣ 系統快速了解

### 跑著的三個 systemd 單元

| 單元 | 型別 | 作用 | 觸發/輪詢 | 日誌 |
|------|------|------|-----------|------|
| `hermes-executor.service` | simple (常駐) | Agent Executor（host 角色）。輪詢 DB，接 `receiver=host` 的任務，執行，更新狀態 | 每 5 秒 poll | `/var/log/hermes-executor.log` |
| `hermes-notify.timer` | timer (每 2 秒) | 查 DB 裡 `receiver=host` 的任務，寫摘要到日志 | 每 2 秒觸發 `hermes-notify.service` | `/var/log/hermes-notify.log` |
| `hermes-watchdog.timer` | timer (每 30 秒) | 觸發 `hermes-watchdog.service` 掃描 watchdog job，偵測卡住/產生 incident | 每 30 秒觸發一次 oneshot service | `/var/log/hermes-watchdog.log` |

### 核心 DB

- **路徑**：`/srv/samba/hermes-audit/agent-mesh.db`
- **所有者**：`hermes:hermes`，權限 `664`
- **存取**：vboxuser 透過 `hermes` 群組（Samba 共享 `[hermes-audit]`，帳密 `hermes / hermes-audit-2026`）
- **網路位址**：主機 `192.168.0.68`

### 任務流程大概

```
發起端（例如蝦米）          執行端（主機 executor）
       │                            │
       ├─ 寫入消息到 DB ──────────→ │  （status=submitted, receiver=host）
       │                            │
       │            executor 每 5 秒 poll DB
       │                            │
       │                     ↙      │  看到 submitted 且 receiver=host
       │              更新 status   │  → acknowledged
       │              → working    │  → 開始 do_work()
       │              → completed  │  → 填 result
       │                            │
       │            notify 每 2 秒查  │  寫任務摘要到日志
       │                            │
       │            watchdog 每 30 秒掃 │  看任務有無卡住，產生/解決 incident
       │                            │
       └─ 讀結果 ←─────────────────┘  （透過 DB 查詢）
```

---

## 2️⃣ 常見改動場景

### 2.1 新增 task_type

| 需求 | 改哪個檔案 | 位置 | 注意事項 |
|------|-----------|------|----------|
| 新增一個 task_type 的處理邏輯 | `agent_executor.py` | `do_work()` 函數，176-244 行 | 在 `do_work()` 裡加 `elif task_type == "你的類型":` 分支。參考現有的 `collection`、`processing`、`verification` 分支模式。若無對應處理，保留 stub 回傳 `{"status":"unknown","result":"..."}`。 |

### 2.2 改 executor 輪詢間隔

| 需求 | 改哪個檔案 | 位置 | 注意事項 |
|------|-----------|------|----------|
| 改 executor 每次 poll 的間隔 | `hermes-executor.service` | `ExecStart` 裡的 `--interval <秒>` | 修改後必須 `sudo systemctl daemon-reload && sudo systemctl restart hermes-executor.service`。預設 5 秒。 |
| 改 watchdog 掃描間隔 | `hermes-watchdog.timer` | `OnUnitActiveSec=<秒>sec` | 修改後必須 `sudo systemctl daemon-reload && sudo systemctl restart hermes-watchdog.timer`。預設 30 秒。 |

### 2.3 改 DB 路徑

| 需求 | 改哪個檔案 | 位置 | 注意事項 |
|------|-----------|------|----------|
| 把 DB 路徑從預設值改為別的位置 | 多個檔案 | 每個用到 DB 的檔案裡的 `DEFAULT_DB_PATH` 或 `--db` 參數 | **非常重要**：DB 路徑改了要確保每個用到它的檔案都改，包括所有 service 檔案。否則 executor 會讀錯位 DB，看不到蝦米寫的消息。改完掃全部檔案確認沒有舊路徑殘留。 |
| 查看當前所有 DB 路徑設定 | `grep` | `grep -n "agent-mesh.db\|/srv/samba" agent_executor.py agent_initiator.py test_*.py src/watchdog/watchdog_db.py` | 一次查完，確認一致。 |

### 2.4 查看/修改 watchdog 設定

| 需求 | 改哪個檔案 | 位置 | 注意事項 |
|------|-----------|------|----------|
| 查詢 watchdog 狀態 | `watchdog_db.py` CLI | `python3 src/watchdog/watchdog_db.py --db /srv/samba/.../agent-mesh.db status` | 顯示 active jobs 與 open incidents。 |
| 手動 arm 一個 watchdog job | `watchdog_db.py` CLI | `python3 src/watchdog/watchdog_db.py --db /srv/samba/.../agent-mesh.db arm <msg_id> --kind <類型>` | 成功返回 watchdog_tag。 |
| 手動 disarm | `watchdog_db.py` CLI | `python3 src/watchdog/watchdog_db.py --db /srv/samba/.../agent-mesh.db disarm <tag> <reason>` | 標注任務已解決。 |
| 送 heartbeat | `watchdog_db.py` CLI | `python3 src/watchdog/watchdog_db.py --db /srv/samba/.../agent-mesh.db heartbeat <tag>` | 重置該 job 的 stalled 狀態。 |

### 2.5 systemctl 操作速查

| 操作 | 指令 |
|------|------|
| 看 executor 狀態 | `sudo systemctl status hermes-executor.service --no-pager -l` |
| 看 watchdog timer 狀態 | `sudo systemctl status hermes-watchdog.timer --no-pager` |
| 看 timer 列表與下次觸發時間 | `sudo systemctl list-timers --all \| grep hermes` |
| 重載系統服務配置 | `sudo systemctl daemon-reload` |
| 重啟 executor | `sudo systemctl restart hermes-executor.service` |
| 重啟 watchdog timer | `sudo systemctl restart hermes-watchdog.timer` |
| 查看 executor 日誌 | `sudo journalctl -u hermes-executor.service -n 30 --no-pager` |
| 查看 watchdog 日誌 | `tail -20 /var/log/hermes-watchdog.log` |
| 查看 notify 日誌 | `tail -20 /var/log/hermes-notify.log` |

---

## 3️⃣ 測試檔案速查

### 3.1 test_host_executor.py

> 主機端 End-to-End 測試腳本。模擬主機執行端，監聽蝦米的訊息並執行任務。

**用法**：
```bash
# 基本用法（會一直跑，模擬 executor 監聽）
python3 test_host_executor.py --db /srv/samba/hermes-audit/agent-mesh.db

# 只接一次任務然後退出（--once）
python3 test_host_executor.py --db /srv/samba/hermes-audit/agent-mesh.db --once
```

**說明文件**：`HOST_EXECUTOR_GUIDE.md`

### 3.2 test_shrimp_initiator.py

> 蝦米端 End-to-End 測試腳本。蝦米（Windows 筆電）發起任務，arm watchdog，等待主機回報結果。

**用法（Windows PowerShell）**：
```powershell
# 建立任務並等待結果（共享 DB 用網路路徑）
python test_shrimp_initiator.py --db "\\192.168.1.100\hermes\hermes-audit-system\agent-mesh.db"

# 建立任務後不等待（讓主機去執行）
python test_shrimp_initiator.py --no-wait

# 自訂任務內容
python test_shrimp_initiator.py --task-type processing --description "my task"
```

**說明文件**：`SHRIMP_EXECUTOR_TEST.md`

### 3.3 test_scenario.py

> 完整場景測試：建立訊息 → arm watchdog → 更新狀態 → 掃描（可模擬超時）→ completed → disarm。

**用法**：
```bash
python3 test_scenario.py
```

**內容大綱**：
1. 建立訊息 `m-001`
2. arm watchdog job
3. 更新 status 到 acknowledged、working
4. （可選）模擬超時：修改 updated_at 為老時間
5. 更新 status 到 completed
6. 掃描，disarm watchdog job

### 3.4 其他測試檔案

| 檔案 |  purpose |
|------|----------|
| `test_scenario_swapped.py` | 角色互換場景測試（主機當發起端、蝦米當執行端） |
| `test_progress_tracking_integration.py` | 進度追蹤整合測試 |
| `test_notify_tasks.py` | notify_tasks.py 的測試 |

---

## 4️⃣ 已知陷阱

### 4.1 systemd 服務路徑要用絕對路徑，別用 `%h`

- systemd 裡 `%h` 展開可能不是你想要的家目錄，尤其 service 以 root 身份跑但想用某個一般使用者家目錄時。
- **正確做法**：`ExecStart=/usr/bin/python3 /home/vboxuser/hermes-audit-system/agent_executor.py --agent host ...` 全部寫絕對路徑。

### 4.2 sys.path 要在 import 前插入

- 專案結構是 `/home/vboxuser/hermes-audit-system/src/watchdog/watchdog_db.py`。
- agent_executor.py 裡寫 `from watchdog.watchdog_db import ...`，但預設 sys.path 只有專案根目錄，不包含 `src/`。
- **正確做法**：在 import 之前執行：
  ```python
  import sys
  from pathlib import Path
  _SRC_DIR = Path(__file__).resolve().parent / "src"
  sys.path.insert(0, str(_SRC_DIR))
  ```
- **注意**：不能靠 systemd 的 `Environment=PYTHONPATH` 來補（有些設定下不會穿透）。

### 4.3 DB 路徑改了要全檔掃描

- DB 路徑從 `/home/vboxuser/.../agent-mesh.db` 搬到 `/srv/samba/hermes-audit/agent-mesh.db` 後，要確保所有檔案的預設 DB 路徑都改過。
- 包含：`agent_executor.py`、`agent_initiator.py`、所有 test 腳本、`watchdog_db.py`、所有 systemd service 檔案裡的 `--db` 參數。
- 舊 DB（`/home/vboxuser/.../agent-mesh.db`）已刪除，**請勿重新建立**。

### 4.4 watchdog CLI 的參數順序

- `watchdog_db.py` 的 `--db` 選項是全域的（在 `run` 子命令之前）。
- **正確**：`watchdog_db.py --db <路徑> run --interval 30`
- **錯誤**：`watchdog_db.py run --db <路徑>`（argparse 會認為 `--db` 是 run 子命令的參數而報錯）

### 4.5 watchdog 服務型別選擇

- `watchdog_db.py run` 是**一次性掃描**（執行完就退出，沒有內部循環）。
- **錯誤做法**：用 `Type=simple` 常駐，會導致 service 跑完就退出，立刻重啟，形成 restart loop。
- **正確做法**：`Type=oneshot` + `systemd timer`。service 每次被 timer 觸發時執行一次掃描，執行完畢 status 變成 inactive (dead)，這是正常的。

### 4.6 debug patch 要清掉

- 中間為了查路徑，臨時 patch 了 agent_executor.py 加入 `logging.info(...)`，但忘了 `import logging`。
- 結果：service 重啟 50+ 次，每次噴 `NameError: name 'logging' is not defined`。
- **教訓**：debug 改動要記得在真的解決問題後清掉，否則 service 重啟循環會誤導你以為還有別的問題。

---

## 5️⃣ 故障排查速查

### 5.1 任務一直是 submitted，沒有 acknowledged

**可能原因**：沒有 executor 在監聽。

**查法**：
```bash
# 檢查 executor 是否在跑
sudo systemctl status hermes-executor.service --no-pager -l
ps aux | grep agent_executor

# 檢查 DB 裡的消息狀態
sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
  "SELECT msg_id, sender, receiver, status, created_at FROM messages WHERE receiver='host' ORDER BY created_at DESC LIMIT 5;"
```

**解法**：如果 service 不在跑，`sudo systemctl restart hermes-executor.service`。如果有在跑但沒反應，看 executor 日誌：
```bash
sudo journalctl -u hermes-executor.service -n 30 --no-pager
tail -30 /var/log/hermes-executor.log
```

### 5.2 service 起不動 / 一直重啟

**可能原因**：
- import 錯誤（`ModuleNotFoundError`、`NameError`）
- DB 路徑錯誤
- 語法錯誤、缺少函式庫

**查法**：
```bash
# 看 service 狀態
sudo systemctl status hermes-executor.service --no-pager -l

# 看 journalctl 錯誤訊息
sudo journalctl -u hermes-executor.service -n 30 --no-pager -o short-precise

# 看日誌檔案
tail -50 /var/log/hermes-executor.log
```

**解法**：
- 如果是 import 錯誤：檢查 `sys.path.insert` 是否有插入 `src/`，檢查 `src/watchdog/__init__.py` 是否存在。
- 如果是 DB 路徑錯誤：檢查 service 裡的 `--db` 參數與程式碼裡的 `DEFAULT_DB_PATH` 是否一致。
- 如果是語法錯誤：直接執行 `python3 agent_executor.py --agent host` 看錯誤訊息。

### 5.3 DB 鎖定錯誤

**可能原因**：多個進程同時讀寫同一個 SQLite DB 檔案。

**查法**：
```bash
# 檢查 DB 完整性
sqlite3 /srv/samba/hermes-audit/agent-mesh.db "PRAGMA integrity_check;"

# 檢查是否有鎖定檔案
ls -la /srv/samba/hermes-audit/agent-mesh.db-*
```

**解法**：
```bash
# SQLite 已啟用 WAL mode（PRAGMA journal_mode=WAL）與 busy_timeout=5000
# 通常鎖定是暫時的，等待幾秒後重試。

# 若真的卡住，檢查是否有 dangling 進程佔據 DB
sudo fuser -v /srv/samba/hermes-audit/agent-mesh.db

# 若需要重置（務必確認沒重要資料）
# rm /srv/samba/hermes-audit/agent-mesh.db
# python3 -c "from watchdog_db import init_db; init_db()"
```

### 5.4 watchdog 沒產生 incident

**可能原因**：
- watchdog timer/service 沒在跑
- 任務沒有 arm watchdog job（直接 submitted → completed）
- 任務沒有卡住（還在正常運行）

**查法**：
```bash
# 看 watchdog timer 是否 active
sudo systemctl status hermes-watchdog.timer --no-pager
sudo systemctl list-timers --all | grep hermes-watchdog

# 看 watchdog service 是否有成功執行過
sudo systemctl status hermes-watchdog.service --no-pager -l
sudo journalctl -u hermes-watchdog.service -n 10 --no-pager

# 看 watchdog_jobs 表是否有 job
sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
  "SELECT watchdog_tag, msg_id, state, kind, no_progress_threshold FROM watchdog_jobs;"

# 看 incidents 表
sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
  "SELECT incident_id, msg_id, severity, status, created_at FROM incidents;"
```

**解法**：
- 如果 timer/service 不在跑：`sudo systemctl restart hermes-watchdog.timer`
- 如果任務沒有 arm job：用 `watchdog_db.py arm <msg_id> --kind <類型>` 手動 arm，或者確認任務建立時有呼叫 arm 函數。
- 如果任務確實卡住了但沒 incident：檢查 watchdog_jobs 表裡該 job 的 state 是否為 stalled，檢查 incidents 表是否有 open incident。

### 5.5 任務 state 卡在 working，不往 completed 走

**可能原因**：
- executor 的 `do_work()` 卡住了（任務邏輯有 bug、外部資源無法存取）
- executor service 掛了（被殺掉、記憶體不足）

**查法**：
```bash
# 看 executor 狀態
sudo systemctl status hermes-executor.service --no-pager -l

# 看 executor 日誌，找 do_work 相關輸出
sudo journalctl -u hermes-executor.service -n 50 --no-pager | grep -i "work\|error\|exception"
tail -50 /var/log/hermes-executor.log
```

**解法**：
- 如果 executor service 掛了：`sudo systemctl restart hermes-executor.service`
- 如果是任務邏輯 bug：查 `do_work()` 的程式碼（`agent_executor.py` 176-244 行），看卡在哪個 task_type 的處理裡。
- 如果需要手動結束任務：用 `watchdog_db.py update-message` 把 status 改為 completed 或 failed。

---

## 6️⃣ 檔案位置速查

| 檔案 | 路徑 |  purpose |
|------|------|----------|
| agent_executor.py | `/home/vboxuser/hermes-audit-system/agent_executor.py` | 主機 executor，處理 receiver=host 的任務 |
| agent_initiator.py | `/home/vboxuser/hermes-audit-system/agent_initiator.py` | 主機發起端，可建立任務 |
| watchdog_db.py | `/home/vboxuser/hermes-audit-system/src/watchdog/watchdog_db.py` | watchdog 核心：訊息 CRUD、watchdog job、incident、掃描 |
| test_host_executor.py | `/home/vboxuser/hermes-audit-system/test_host_executor.py` | executor 端對測 |
| test_shrimp_initiator.py | `/home/vboxuser/hermes-audit-system/test_shrimp_initiator.py` | 蝦米發起端對測 |
| test_scenario.py | `/home/vboxuser/hermes-audit-system/test_scenario.py` | 完整場景測試 |
| test_scenario_swapped.py | `/home/vboxuser/hermes-audit-system/test_scenario_swapped.py` | 角色互換場景測試 |
| notify_tasks.py | `/home/vboxuser/hermes-audit-system/notify_tasks.py` | notify 服務的執行腳本 |
| shrimp_agent.py | `/home/vboxuser/hermes-audit-system/shrimp_agent.py` | 蝦米端 agent |
| HOST_GUIDE.md | `/home/vboxuser/hermes-audit-system/HOST_GUIDE.md` | 主機部署指南 |
| HOST_EXECUTOR_GUIDE.md | `/home/vboxuser/hermes-audit-system/HOST_EXECUTOR_GUIDE.md` | executor 端詳細指南 |
| SHRIMP_GUIDE.md | `/home/vboxuser/hermes-audit-system/SHRIMP_GUIDE.md` | 蝦米端指南 |
| SHRIMP_QUICK_START.md | `/home/vboxuser/hermes-audit-system/SHRIMP_QUICK_START.md` | 蝦米端快速上手 |
| ROLE_SWAP_GUIDE.md | `/home/vboxuser/hermes-audit-system/ROLE_SWAP_GUIDE.md` | 角色互換指南 |
| ARCHITECTURE.md | `/home/vboxuser/hermes-audit-system/ARCHITECTURE.md` | 理想設計架構 |
| ARCHITECTURE_CURRENT.md | `/home/vboxuser/hermes-audit-system/docs/ARCHITECTURE_CURRENT.md` | 實際架構（現狀） |
| HOST_STATUS_2026-08-20.md | `/home/vboxuser/hermes-audit-system/docs/HOST_STATUS_2026-08-20.md` | 主機現狀總結 |
| LESSONS_LEARNED.md | `/home/vboxuser/hermes-audit-system/docs/LESSONS_LEARNED.md` | 部署經驗教訓 |
| hermes-executor.service | `/etc/systemd/system/hermes-executor.service` | executor systemd service |
| hermes-watchdog.service | `/etc/systemd/system/hermes-watchdog.service` | watchdog oneshot service |
| hermes-watchdog.timer | `/etc/systemd/system/hermes-watchdog.timer` | watchdog timer (30 秒) |
| hermes-notify.service | `/etc/systemd/system/hermes-notify.service` | notify service |
| hermes-notify.timer | `/etc/systemd/system/hermes-notify.timer` | notify timer (2 秒) |

---

## 7️⃣ 快速命令合集

```bash
# ── 查系統狀態 ──
sudo systemctl status hermes-executor.service --no-pager -l
sudo systemctl status hermes-watchdog.timer --no-pager
sudo systemctl list-timers --all | grep hermes

# ── 看日誌 ──
sudo journalctl -u hermes-executor.service -n 30 --no-pager
tail -20 /var/log/hermes-notify.log
tail -20 /var/log/hermes-watchdog.log

# ── 查 DB ──
# 消息
sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
  "SELECT msg_id, sender, receiver, status, created_at FROM messages ORDER BY created_at DESC LIMIT 10;"

# watchdog job
sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
  "SELECT watchdog_tag, msg_id, state, kind, no_progress_threshold FROM watchdog_jobs;"

# incidents
sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
  "SELECT incident_id, msg_id, severity, status, created_at FROM incidents;"

# ── 手動執行 watchdog 掃描 ──
python3 /home/vboxuser/hermes-audit-system/src/watchdog/watchdog_db.py \
  --db /srv/samba/hermes-audit/agent-mesh.db run

# ── 查 watchdog 狀態 ──
python3 /home/vboxuser/hermes-audit-system/src/watchdog/watchdog_db.py \
  --db /srv/samba/hermes-audit/agent-mesh.db status

# ── 重載並重啟服務 ──
sudo systemctl daemon-reload
sudo systemctl restart hermes-executor.service
sudo systemctl restart hermes-watchdog.timer
sudo systemctl restart hermes-notify.timer

# ── 測試 executor 接單 ──
# 插入一條測試任務
sudo -u hermes sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
"INSERT INTO messages (msg_id, sender, receiver, status, payload) VALUES (
  'm-test-' || lower(hex(randomblob(8))),
  'shrimp',
  'host',
  'submitted',
  json_object('task_type','collection','description','manual test from host')
);"

# 過幾秒後查狀態
sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
"SELECT msg_id, status, updated_at FROM messages WHERE msg_id LIKE 'm-test-%' ORDER BY updated_at DESC LIMIT 1;"
```
