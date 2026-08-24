# 主機現狀總結 — 2026-08-20

> 寫給之後接手這台主機的人。說明「現在到底在跑什麼、缺了什麼、DB 在哪、怎麼看」。

## 一句話

主機（vboxuser-PRO-Cubi-Z-AI-8M-MS-B032）上跑著三個 systemd 單元：

- `hermes-executor.service` — Agent Executor（host 角色），常駐，每 5 秒輪詢共享 DB，自動接 `receiver=host` 的任務，處理完再報完。
- `hermes-notify.timer` — 每 2 秒觸發一次，查 DB 看有沒有新任務/狀態變更，寫日志 `/var/log/hermes-notify.log`。
- `hermes-watchdog.timer` → `hermes-watchdog.service` — 每 30 秒掃一次 DB，偵測卡住的 watchdog job 並產生 incident。

---

## 跑著的東西（2026-08-20 確認）

| 單元 | 狀態 | 作用 | 日誌 |
|------|------|------|------|
| `hermes-executor.service` | active (running) | 執行端。poll DB，見 `receiver=host` 的 submitted/acknowledged/working 訊息就領工，做完更新狀態 | `/var/log/hermes-executor.log` |
| `hermes-notify.timer` | active (waiting) | 通知器。每 2 秒查一次 DB，寫任務摘要到日志 | `/var/log/hermes-notify.log` |
| `hermes-watchdog.timer` | active (waiting) | 每 30 秒觸發一次掃描。偵測卡住的 watchdog job，產生/解決 incident | `/var/log/hermes-watchdog.log` |
| `hermes-watchdog.service` | inactive (dead) | oneshot。每次被 timer 觸發時執行一次掃描，跑完就退出（正常） | 同上 |

### hermes-executor.service 細節

- Type: simple
- User: vboxuser
- WorkingDirectory: `/home/vboxuser/hermes-audit-system`
- ExecStart:
  ```
  /usr/bin/python3 /home/vboxuser/hermes-audit-system/agent_executor.py \
    --agent host \
    --db /srv/samba/hermes-audit/agent-mesh.db \
    --interval 5
  ```
- Restart: on-failure, RestartSec=3
- stdout/stderr 追加到 `/var/log/hermes-executor.log`
- 啟用（enable）且開機自動啟動

### hermes-notify.timer 細節

- 每 2 秒觸發一次 `hermes-notify.service`
- `hermes-notify.service` 會執行 `notify_tasks.py`，查 DB 裡 `receiver=host` 的任務，寫日志
- 日誌格式大概是表格：`msg_id | task_type | sender | receiver | status | created_at`
- 無任務時寫 `idle: 無新任務`

### hermes-watchdog.timer + service 細節

- `hermes-watchdog.timer`:
  - OnBootSec=10sec（開機後 10 秒首次觸發）
  - OnUnitActiveSec=30sec（每 30 秒觸發一次 service）
  - 啟用（enable）且開機自動啟動
- `hermes-watchdog.service`:
  - Type: oneshot（執行完就退出，不是常駐）
  - 執行 `watchdog_db.py run --db /srv/samba/hermes-audit/agent-mesh.db`
  - 掃描所有 watchdog job，看有沒 stagnant 的，產生或解決 incident
  - 主 process 執行完畢後 status 變成 inactive (dead)，這是正常的

### 不跑的東西

- **舊 DB**：`/home/vboxuser/hermes-audit-system/agent-mesh.db` 已刪除。請勿重新建立。

---

## 共享 DB

| 屬性 | 值 |
|------|------|
| 路徑 | `/srv/samba/hermes-audit/agent-mesh.db` |
| 所有者 | hermes:hermes |
| permissions | 664 |
| 存取方式 | vboxuser 透過 hermes 群組讀寫（群組 hermes 成員） |
| Samba 共享名 | `[hermes-audit]`，帳密 `hermes / hermes-audit-2026` |
| 內容（2026-08-20） | 1 條訊息：`m-4efbf2f1` (shrimp→host, completed) |

### 目前的 message 狀態

```
msg_id        sender  receiver  status     type   created_at
m-4efbf2f1    shrimp  host      completed  task   2026-08-20T00:46:43Z
```

只有這一條。沒有 pending/processing 的任務。

### 目前的 watchdog job 狀態

```
watchdog_tag      msg_id      state    kind       no_progress_threshold
WD-DEA455F45E27   m-4efbf2f1  disarmed collection  600
```

這是該消息的 watchdog job，狀態是 disarmed（因為消息已完成，watchdog 掃描偵測到 completed 狀態後自動 disarm）。

---

## 怎麼看state

```bash
# 服務狀態
sudo systemctl status hermes-executor.service --no-pager -l
sudo systemctl status hermes-notify.timer --no-pager
sudo systemctl status hermes-watchdog.timer --no-pager
sudo systemctl status hermes-watchdog.service --no-pager -l

# timer 列表（看下次觸發時間）
sudo systemctl list-timers --all | grep hermes

# 日誌
sudo journalctl -u hermes-executor.service -n 30 --no-pager
tail -20 /var/log/hermes-notify.log
tail -20 /var/log/hermes-watchdog.log

# DB 裡的消息
sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
  "SELECT msg_id, sender, receiver, status, created_at FROM messages ORDER BY created_at DESC LIMIT 10;"

# DB 裡的 watchdog job
sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
  "SELECT watchdog_tag, msg_id, state, kind, no_progress_threshold FROM watchdog_jobs;"

# DB 裡的 incidents
sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
  "SELECT incident_id, msg_id, severity, status, created_at FROM incidents;"
```

---

## 怎麼加一個任務進來測試自動接單

```bash
# 往 DB 插入一條 submitted 訊息（receiver=host）
sudo -u hermes sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
"INSERT INTO messages (msg_id, sender, receiver, status, payload) VALUES (
  'm-test-' || lower(hex(randomblob(8))),
  'shrimp',
  'host',
  'submitted',
  json_object('task_type','collection','description','manual test from host')
);"

# 過 5~10 秒後查狀態，應該看到 status 從 submitted → acknowledged → working → completed
sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
"SELECT msg_id, status, updated_at FROM messages WHERE msg_id LIKE 'm-test-%' ORDER BY updated_at DESC LIMIT 1;"
```

預期 executor 會在最多 5 秒內領到這條訊息，開始處理。

---

## 聯絡/ 재건축

- 主機 IP: `192.168.0.68`
- Samba 共享: `[hermes-audit]`，帳密 `hermes / hermes-audit-2026`
- SSH 金鑰登入已關閉密碼（vboxuser 用 shies@MSI 的 ED25519 金鑰）
- 專案目錄: `/home/vboxuser/hermes-audit-system`
- 筆電暱稱: 蝦米（shrimp），SSH 金鑰 `shies@MSI (ED25519)`
