# 主機現狀總結 — 2026-08-20

> 寫給之後接手這台主機的人。說明「現在到底在跑什麼、缺了什麼、DB 在哪、怎麼看」。

## 一句話

主機（vboxuser-PRO-Cubi-Z-AI-8M-MS-B032）上跑著兩個 systemd 單元：

- `hermes-executor.service` — Agent Executor（host 角色），常駐，每 5 秒輪詢共享 DB，自動接 `receiver=host` 的任務，處理完再報完。
- `hermes-notify.timer` — 每 2 秒觸發一次，查 DB 看有沒有新任務/狀態變更，寫日志 `/var/log/hermes-notify.log`。

缺掉的：watchdog 掃描 cronjob/systemd service 目前 **沒有在跑**。意思是「卡住偵測 / incident 產生」這條線目前沒啟用。

---

## 跑著的東西（2026-08-20 確認）

| 單元 | 狀態 | 作用 | 日誌 |
|------|------|------|------|
| `hermes-executor.service` | active (running) | 執行端。poll DB，見 `receiver=host` 的 submitted/acknowledged/working 訊息就領工，做完更新狀態 | `/var/log/hermes-executor.log` |
| `hermes-notify.timer` | active (waiting) | 通知器。每 2 秒查一次 DB，寫任務摘要到日志 | `/var/log/hermes-notify.log` |

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

### 不跑的東西

- **watchdog 掃描**：沒 cronjob，沒 systemd service。`watchdog_db.py run` 沒有被定時呼叫。現在的狀態是：executor 會處理任務、 notify timer 會曬任務，**但超時偵測與 incident 產生不會自動發生**。
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

---

## 怎麼看state

```bash
# 服務狀態
sudo systemctl status hermes-executor.service --no-pager -l
sudo systemctl status hermes-notify.timer --no-pager

# 日誌
sudo journalctl -u hermes-executor.service -n 30 --no-pager
tail -20 /var/log/hermes-notify.log

# DB 裡的消息
sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
  "SELECT msg_id, sender, receiver, status, created_at FROM messages ORDER BY created_at DESC LIMIT 10;"

# DB 裡的 watchdog job（目前應該是空的）
sqlite3 /srv/samba/hermes-audit/agent-mesh.db \
  "SELECT watchdog_tag, msg_id, state, kind, no_progress_threshold FROM watchdog_jobs;"
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

## 怎麼補上 watchdog 掃描（待做）

目前沒開。如要補：

```bash
# 選lean的方式：systemd service 常駐跑 watchdog_db.py run
sudo cp /home/vboxuser/hermes-audit-system/watchdog_db.py /usr/local/bin/hermes-watchdog-run
# 或直接寫 service 檔
sudo nano /etc/systemd/system/hermes-watchdog.service
```

大概長這樣：

```ini
[Unit]
Description=Hermes Watchdog Scanner
After=network.target

[Service]
Type=simple
User=vboxuser
WorkingDirectory=/home/vboxuser/hermes-audit-system
ExecStart=/usr/bin/python3 /home/vboxuser/hermes-audit-system/watchdog_db.py run
Restart=on-failure
RestartSec=10
StandardOutput=append:/var/log/hermes-watchdog.log
StandardError=append:/var/log/hermes-watchdog.log

[Install]
WantedBy=multi-user.target
```

然後：

```bash
sudo systemctl daemon-reload
sudo systemctl enable hermes-watchdog.service
sudo systemctl start hermes-watchdog.service
```

---

## 聯絡/ 재건축

- 主機 IP: `192.168.0.68`
- Samba 共享: `[hermes-audit]`，帳密 `hermes / hermes-audit-2026`
- SSH 金鑰登入已關閉密碼（vboxuser 用 shies@MSI 的 ED25519 金鑰）
- 專案目錄: `/home/vboxuser/hermes-audit-system`
- 筆電暱稱: 蝦米（shrimp），SSH 金鑰 `shies@MSI (ED25519)`
