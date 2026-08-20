# 主機 Agent 部署指南 (Linux VirtualBox)

## 📋 目錄

1. 快速開始
2. 安裝步驟
3. 執行方式
4. 角色選擇
5. Cronjob 設置
6. 監控和故障排查
7. 常見問題

---

## 1️⃣ 快速開始

### 最快 5 分鐘上線

```bash
# 1. 克隆倉庫
git clone https://github.com/shiesam/hermes-audit-system.git
cd hermes-audit-system

# 2. 初始化資料庫
python3 -c "from watchdog_db import init_db; init_db()"

# 3. 運行測試驗證環境
python3 test_scenario.py

# 4. 啟動 watchdog 掃描 (後台)
nohup python3 watchdog_db.py run > /tmp/watchdog.log 2>&1 &

# 5. 啟動執行端監聽 (另一個終端)
python3 agent_executor.py --agent host
```

---

## 2️⃣ 安裝步驟

### 環境要求

```bash
# Linux (VirtualBox)
- Python 3.7+
- SQLite3 (內建)
- Git

# 檢查版本
python3 --version
sqlite3 --version
```

### 詳細安裝

```bash
# 1. 克隆倉庫到 /home/vboxuser/hermes-audit-system
cd /home/vboxuser
git clone https://github.com/shiesam/hermes-audit-system.git
cd hermes-audit-system

# 2. 驗證文件完整性
ls -la
# 應該看到:
#   watchdog_db.py
#   agent_executor.py
#   agent_initiator.py
#   test_scenario.py
#   test_scenario_swapped.py

# 3. 初始化資料庫 (第一次執行)
python3 -c "from watchdog_db import init_db; init_db()"
# 會建立 agent-mesh.db

# 4. 驗證資料庫
sqlite3 agent-mesh.db ".tables"
# 應該看到:
#   messages  watchdog_jobs  incidents  config
```

### 測試驗證

```bash
# 測試 1: 原始場景 (蝦米當執行端)
python3 test_scenario.py

# 輸出應包含:
#   ✅ 建立訊息
#   ✅ Arm Watchdog
#   ✅ 狀態轉移
#   ✅ Incident 偵測
#   [✓] 所有步驟都通過

# 測試 2: 角色互換場景 (主機當執行端)
python3 test_scenario_swapped.py

# 輸出應包含:
#   ✅ 訊息建立 (主機 → 蝦米)
#   ✅ Watchdog arm
#   ...
#   系統設計本身是「角色無關」的 (role-agnostic)
```

---

## 3️⃣ 執行方式

### A. 主機當「發起端」

主機建立任務，蝦米執行任務。

```bash
# 終端 1: 啟動主機發起端
python3 agent_initiator.py --agent host --interactive

# 交互式輸入:
# 任務類型: collection
# 任務描述: 收集某些數據
# 超時時間: [按 Enter 使用預設]

# 會輸出:
# ✅ 建立訊息: m-xxxxxxxx
# ✅ Arm Watchdog: WD-xxxxxxxx
# ⏳ 等待任務完成...
# (等待蝦米執行)
```

**或批次模式**

```bash
python3 agent_initiator.py \
  --agent host \
  --task-type collection \
  --description "收集數據測試" \
  --threshold 300
```

### B. 主機當「執行端」

蝦米建立任務，主機執行任務。

```bash
# 終端 1: 啟動主機執行端（持續監聽）
python3 agent_executor.py --agent host

# 會輸出:
# ════════════════════════════════════════════════════════════
#   主機 (Linux VirtualBox) - 執行端
#   監聽對象: shrimp 的任務
#   輪詢間隔: 5s
# ════════════════════════════════════════════════════════════
#
# ⏳ [1] 沒有新訊息
# ⏳ [2] 沒有新訊息
# ...
# (等待蝦米發起任務)
```

### C. Watchdog 掃描（必須執行）

無論哪種角色，**watchdog 掃描必須持續執行**！

```bash
# 終端 3: 啟動 watchdog 掃描
python3 watchdog_db.py run

# 或後台運行
nohup python3 watchdog_db.py run > /tmp/watchdog.log 2>&1 &

# 檢查狀態
python3 watchdog_db.py status

# 輸出示例:
# === Watchdog Status ===
# Active jobs: 2
#   [armed  ] WD-ABC123  msg=m-001  kind=collection  threshold=600s
#   [stalled] WD-DEF456  msg=m-002  kind=processing  threshold=300s
#
# Open incidents: 1
#   [review] INC-XYZ001  msg=m-002  watchdog=WD-DEF456
```

---

## 4️⃣ 角色選擇

### 情景 A: 主機主要負責執行

```
蝦米 (Windows)          主機 (Linux)
   │                      │
   ├─ 建立任務 ──────→  監聽 & 執行
   │                      │
   ├─ 等待結果 ←──── 回報完成
   │
```

**設置步驟**

1. **蝦米 (Windows 筆電)**
   ```bash
   # 在筆電上執行
   python3 agent_initiator.py --agent shrimp --interactive
   ```

2. **主機 (Linux VirtualBox)**
   ```bash
   # 終端 1: 監聽
   python3 agent_executor.py --agent host
   
   # 終端 2: Watchdog 掃描
   python3 watchdog_db.py run
   ```

---

### 情景 B: 主機主要負責發起

```
主機 (Linux)           蝦米 (Windows)
   │                      │
   ├─ 建立任務 ──────→  監聽 & 執行
   │                      │
   ├─ 等待結果 ←──── 回報完成
   │
```

**設置步驟**

1. **主機 (Linux VirtualBox)**
   ```bash
   # 終端 1: 發起任務
   python3 agent_initiator.py --agent host --interactive
   
   # 終端 2: Watchdog 掃描
   python3 watchdog_db.py run
   ```

2. **蝦米 (Windows 筆電)**
   ```bash
   # 監聽
   python3 agent_executor.py --agent shrimp
   ```

---

### 情景 C: 雙向協作

```
主機可以既發起也執行
蝦米也可以既發起也執行

只需改變 --agent 參數即可！
```

**範例**

```bash
# 主機既可以發起
python3 agent_initiator.py --agent host --task-type collection --description "test"

# 主機也可以執行
python3 agent_executor.py --agent host

# 蝦米既可以發起
python3 agent_initiator.py --agent shrimp --task-type verification --description "verify"

# 蝦米也可以執行
python3 agent_executor.py --agent shrimp
```

---

## 5️⃣ Cronjob 設置

### 為什麼需要 Cronjob？

- 主機需要 **定期掃描** watchdog job
- 偵測超時，產生 incident
- 自動 disarm 完成的任務

### 設置方式

#### 方式 1: 每分鐘執行 2 次（推薦）

```bash
# 編輯 crontab
crontab -e

# 加入以下行
# 每分鐘的第 0 和 30 秒各執行一次
* * * * * cd /home/vboxuser/hermes-audit-system && python3 watchdog_db.py run >> /var/log/hermes-watchdog.log 2>&1
* * * * * (sleep 30; cd /home/vboxuser/hermes-audit-system && python3 watchdog_db.py run >> /var/log/hermes-watchdog.log 2>&1)
```

#### 方式 2: 每 30 秒執行一次（更精確）

```bash
# 建立腳本 /usr/local/bin/watchdog-loop.sh
#!/bin/bash
while true; do
    cd /home/vboxuser/hermes-audit-system
    python3 watchdog_db.py run >> /var/log/hermes-watchdog.log 2>&1
    sleep 30
done

# 執行
chmod +x /usr/local/bin/watchdog-loop.sh
nohup /usr/local/bin/watchdog-loop.sh &

# 或用 systemd service
cat > /etc/systemd/system/hermes-watchdog.service << EOF
[Unit]
Description=Hermes Watchdog Scanner
After=network.target

[Service]
Type=simple
User=vboxuser
WorkingDirectory=/home/vboxuser/hermes-audit-system
ExecStart=/usr/bin/python3 watchdog_db.py run
Restart=on-failure
RestartSec=10
StandardOutput=append:/var/log/hermes-watchdog.log
StandardError=append:/var/log/hermes-watchdog.log

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl start hermes-watchdog
sudo systemctl enable hermes-watchdog
```

### 檢查 Cronjob

```bash
# 查看現在運行的 cronjob
crontab -l

# 檢查日誌
tail -f /var/log/hermes-watchdog.log

# 應該看到:
# [2026-08-17 14:30:00] Scanning 3 active jobs...
# [2026-08-17 14:30:00] Created 0 incidents
# [2026-08-17 14:31:00] Scanning 3 active jobs...
# ...
```

### 任務通知（systemd timer，每 2 秒）

用途：偵測 `receiver='host'` 且狀態為 `submitted/acknowledged/working/input-required` 的任務，
並輸出任務摘要（`msg_id/task_type/sender/receiver/status/created_at`）到日誌。

```bash
# 1) 安裝通知腳本與 systemd 設定
cd ~/hermes-audit-system
sudo cp hermes-notify.service /etc/systemd/system/hermes-notify.service
sudo cp hermes-notify.timer /etc/systemd/system/hermes-notify.timer

# 2) 啟用 timer（開機後 10 秒啟動；每 2 秒觸發一次）
sudo systemctl daemon-reload
sudo systemctl enable hermes-notify.timer
sudo systemctl start hermes-notify.timer

# 3) 驗證
sudo systemctl status hermes-notify.timer --no-pager
sudo systemctl list-timers --all | grep hermes-notify
tail -f /var/log/hermes-notify.log
```

預期：
- 出現新任務或狀態變更時，`/var/log/hermes-notify.log` 會輸出表格
- 無任務時輸出 `idle: 無新任務`

> 註：`hermes-notify.service` 依需求預設 `User=vboxuser`。若你的主機使用不同帳號，請先調整 service 檔再啟動。

---

## 6️⃣ 監控和故障排查

### 查看系統狀態

```bash
# 狀態一覽
python3 watchdog_db.py status

# 輸出:
# === Watchdog Status ===
# Active jobs: 2
#   [armed  ] WD-ABC123  msg=m-001  kind=collection  threshold=600s
#   [stalled] WD-DEF456  msg=m-002  kind=processing  threshold=300s
#
# Open incidents: 1
#   [review] INC-XYZ001  msg=m-002  watchdog=WD-DEF456
```

### 查詢訊息詳情

```bash
# 查詢特定訊息
python3 -c "
from watchdog_db import *
import json
conn = init_db()
msg = get_message(conn, 'm-001')
print(f'Status: {msg[\"status\"]}')
print(f'Sender: {msg[\"sender\"]}')
print(f'Receiver: {msg[\"receiver\"]}')
print(f'Payload: {json.loads(msg[\"payload\"])}')
if msg['result']:
    print(f'Result: {json.loads(msg[\"result\"])}')
"
```

### 查詢 Incident

```bash
# 查詢所有開放的 incident
python3 -c "
from watchdog_db import *
import json
conn = init_db()
incs = get_open_incidents(conn)
for inc in incs:
    evidence = json.loads(inc['evidence']) if inc['evidence'] else {}
    print(f'{inc[\"incident_id\"]}: {inc[\"severity\"]} - {evidence.get(\"reason\")}')
"
```

### 常見問題排查

#### 1. 訊息一直是 submitted，沒有 acknowledged

**原因**: 沒有執行端在監聽

**解決**:
```bash
# 檢查是否有執行端在運行
ps aux | grep agent_executor

# 沒有的話啟動
python3 agent_executor.py --agent host
```

#### 2. Watchdog 沒有產生 incident

**原因**: Cronjob 沒有執行

**解決**:
```bash
# 檢查 cronjob
crontab -l

# 手動執行看看
python3 watchdog_db.py run

# 檢查日誌
tail -f /var/log/hermes-watchdog.log
```

#### 3. 資料庫鎖定錯誤

**原因**: 多個進程同時讀寫

**解決**:
```bash
# 檢查是否有被鎖定
sqlite3 agent-mesh.db "PRAGMA integrity_check;"

# 如果需要重置
rm agent-mesh.db
python3 -c "from watchdog_db import init_db; init_db()"
```

---

## 7️⃣ 常見問題

### Q1: 如何在蝦米和主機之間共享資料庫？

**方式 A: NFS 掛載**
```bash
# 主機 (Linux) - 設置 NFS server
sudo apt install nfs-kernel-server
sudo exportfs -a

# 蝦米 (Windows) - 通過 SMB/NFS 客戶端掛載
```

**方式 B: Samba 共享**
```bash
# 主機 (Linux) - 設置 Samba
sudo apt install samba
# 在 /etc/samba/smb.conf 中加入:
[hermes]
path = /home/vboxuser/hermes-audit-system
available = yes
browsable = yes
```

**方式 C: 遠程 SSH**
```bash
# 蝦米直接透過 SSH 訪問
python3 agent_executor.py --db ssh://vboxuser@192.168.x.x/path/to/agent-mesh.db
```

### Q2: 如何增加超時時間？

```bash
# 建立任務時指定
python3 agent_initiator.py \
  --agent host \
  --task-type collection \
  --description "test" \
  --threshold 1800  # 30 分鐘

# 或修改全局設置
sqlite3 agent-mesh.db "UPDATE config SET config_value='1800' WHERE config_key='threshold.collection';"
```

### Q3: 如何手動結束任務？

```bash
python3 -c "
from watchdog_db import *
conn = init_db()
update_message_status(conn, 'm-001', 'failed', errors={'reason': 'manual termination'})
"
```

### Q4: 如何查看任務的完整歷史？

```bash
# 查詢特定訊息的所有 incident
sqlite3 agent-mesh.db "SELECT incident_id, severity, status, created_at FROM incidents WHERE msg_id='m-001';"

# 查詢特定訊息的狀態變化
sqlite3 agent-mesh.db "
  SELECT msg_id, status, updated_at FROM messages 
  WHERE msg_id='m-001' 
  ORDER BY updated_at;
"
```

---

## 📚 相關文件

- `ARCHITECTURE.md` - 系統架構設計
- `SHRIMP_GUIDE.md` - 蝦米 (Windows) 部署指南
- `watchdog_db.py` - 核心模組
- `agent_executor.py` - 執行端代碼
- `agent_initiator.py` - 發起端代碼

---

## 🆘 獲得幫助

遇到問題？

1. 查看 `/var/log/hermes-watchdog.log`
2. 執行 `python3 watchdog_db.py status`
3. 查看 `ARCHITECTURE.md` 的常見問題章節
4. 檢查是否有 incident: `python3 -c "from watchdog_db import *; print(get_open_incidents(init_db()))"`

---

**最後更新**: 2026-08-17
