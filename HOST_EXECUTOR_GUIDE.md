# HOST_EXECUTOR_GUIDE.md — 主機執行端使用說明

> 適用對象：主機（Linux VirtualBox）的管理員  
> 對應腳本：`test_host_executor.py`

---

## 前置條件

### 1. 環境確認

```bash
# 確認 Python 版本（需 3.9+）
python3 --version

# 確認倉庫目錄
cd /home/vboxuser/hermes-audit-system
ls src/watchdog/watchdog_db.py   # 應存在
```

### 2. 資料庫路徑

主機的 DB 通常在：
```
/srv/samba/hermes-audit/agent-mesh.db
```

查詢實際路徑：
```bash
find /home/vboxuser -name "agent-mesh.db" 2>/dev/null
find /srv -name "agent-mesh.db" 2>/dev/null
```

### 3. Samba 共享設定（讓蝦米能連接 DB）

蝦米需要透過網路連接主機的 DB。若尚未設定，執行：

```bash
# 安裝 Samba
sudo apt install -y samba

# 查詢主機 IP
hostname -I

# 編輯 Samba 設定
sudo nano /etc/samba/smb.conf
```

在 `smb.conf` 末尾加入：
```ini
[hermes]
   path = /home/vboxuser/hermes-audit-system
   available = yes
   browsable = yes
   public = yes
   writable = yes
   guest ok = yes
   force user = vboxuser
```

> ⚠️ **安全提示**：以上設定允許區域網路上所有裝置無需密碼讀寫 DB 文件。  
> 在正式環境中，建議改用 Samba 使用者帳號驗證（移除 `guest ok = yes`，改用 `valid users`）。  
> 測試環境中確保 VirtualBox 使用 Host-only 或 Internal 網路，降低暴露風險。

```bash
# 重啟 Samba
sudo systemctl restart smbd nmbd

# 驗證共享已啟用
smbclient -L localhost -N
```

---

## 運行步驟

### 方式 A：單次掃描（快速測試）

```bash
cd /home/vboxuser/hermes-audit-system

# 掃描一輪，處理所有待處理訊息後退出
python3 test_host_executor.py --once
```

### 方式 B：持續監聽（正式使用）

```bash
cd /home/vboxuser/hermes-audit-system

# 持續監聽蝦米的訊息（每 5 秒輪詢一次）
python3 test_host_executor.py

# 自訂輪詢間隔（10 秒）
python3 test_host_executor.py --interval 10
```

### 方式 C：指定 DB 路徑

```bash
# 使用 Samba 共享的 DB
python3 test_host_executor.py --db /srv/samba/hermes-audit/agent-mesh.db

# 使用自訂路徑
python3 test_host_executor.py --db /path/to/agent-mesh.db --once
```

---

## 預期輸出

### 啟動時（無待處理訊息）

```
============================================================
  🖥️  主機執行端 (Host Executor) — 端到端測試
  監聽對象: shrimp 的訊息
  資料庫:   /srv/samba/hermes-audit/agent-mesh.db
  輪詢間隔: 5s
  模式:     持續監聽（Ctrl+C 停止）
============================================================

✅ 資料庫連線成功

⏳ [1] 沒有新訊息（已處理 0 個任務）
⏳ [2] 沒有新訊息（已處理 0 個任務）
...
```

### 收到蝦米訊息並執行

```
📬 [3] 發現 1 個新訊息

  ┌─ 訊息: m-6330c9ee
  │  來自: shrimp
  │  目前狀態: submitted
  │  ✅ 確認收到 (acknowledged)
  │  💓 Heartbeat 已發送 (watchdog=WD-XXXXXXXX)
  │  🔄 開始執行 (working)
  │  📋 任務類型: collection
  │  📝 描述:     test from shrimp laptop
  │  ⏳ 執行中...
  │  ✅ 任務完成 (completed)
  │  📊 結果: {"task_type": "collection", "status": "completed", ...}
  │  🔓 Watchdog WD-XXXXXXXX 將自動 disarm
  └─
```

### 停止時

```
────────────────────────────────────────────────────────────
  執行摘要：共處理 1 個任務（共輪詢 5 次）
────────────────────────────────────────────────────────────
👋 主機執行端已停止
```

---

## 與蝦米協作的完整流程

```
蝦米（Windows）                    主機（Linux）
     │                                  │
     │  python test_shrimp_initiator.py │
     │  ├─ 建立 m-xxxxxxxx              │
     │  ├─ arm watchdog                 │
     │  └─ 等待結果...                  │
     │                                  │
     │                 ←─ 輪詢 DB ─────────
     │                 │ python3 test_host_executor.py
     │                 ├─ submitted → acknowledged
     │                 ├─ acknowledged → working
     │                 ├─ 執行工作
     │                 ├─ working → completed
     │                 └─ watchdog 自動 disarm
     │                                  │
     └─ 接收結果 ✅ ────────────────────┘
```

### 雙端同時運行（推薦）

**主機端（Linux，先啟動）：**
```bash
python3 test_host_executor.py --db /srv/samba/hermes-audit/agent-mesh.db
```

**蝦米端（Windows，後發起）：**
```powershell
python test_shrimp_initiator.py --db \\192.168.1.100\hermes\hermes-audit-system\agent-mesh.db
```

---

## 故障排查

### Q1：`資料庫不存在` 錯誤

```
❌ 資料庫不存在: /path/to/agent-mesh.db
```

**原因**：DB 路徑錯誤，或蝦米還沒有建立任何訊息（DB 從未初始化）。

**解決方法**：
```bash
# 確認 DB 路徑
find / -name "agent-mesh.db" 2>/dev/null

# 或手動初始化 DB
python3 -c "
from src.watchdog.watchdog_db import init_db
from pathlib import Path
conn = init_db(Path('agent-mesh.db'))
conn.close()
print('DB 初始化成功')
"
```

---

### Q2：`Import 失敗`

```
❌ Import 失敗: No module named 'watchdog'
```

**解決方法**：
```bash
# 確認在正確的目錄下運行
pwd   # 應輸出 .../hermes-audit-system

# 確認 src/ 結構
ls src/watchdog/watchdog_db.py
ls src/mesh/progress_tracker.py
```

---

### Q3：訊息狀態卡在 `submitted`

**可能原因**：
1. 主機執行端沒有在運行 → 啟動 `test_host_executor.py`
2. DB 路徑不一致（主機和蝦米用不同的 DB 文件）

**檢查 DB 訊息**：
```bash
python3 -c "
from src.watchdog.watchdog_db import init_db, get_messages_by_status
from pathlib import Path

conn = init_db(Path('agent-mesh.db'))
msgs = get_messages_by_status(conn, 'submitted')
print(f'submitted 訊息數: {len(msgs)}')
for m in msgs:
    print(f'  {m[\"msg_id\"]}: sender={m[\"sender\"]}, receiver={m[\"receiver\"]}')
conn.close()
"
```

---

### Q4：蝦米無法連接主機的 DB

**確認 Samba 共享正常**：
```bash
# 主機上測試共享
smbclient //localhost/hermes -N -c "ls"

# 主機防火牆放行 Samba
sudo ufw allow samba
```

**蝦米 Windows 上測試**：
```powershell
# 測試連通性
ping 192.168.1.100

# 測試共享訪問
dir \\192.168.1.100\hermes
```

---

### Q5：`watchdog disarm` 沒有發生

watchdog 的 disarm 由 `watchdog_db.py` 掃描執行，不是即時的。

```bash
# 手動觸發 watchdog 掃描
python3 -m src.watchdog.watchdog_db run
```

---

## 參數說明

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `--db` | SQLite 資料庫路徑 | `./agent-mesh.db` |
| `--once` | 掃描一輪後退出 | 否（持續監聽） |
| `--interval` | 輪詢間隔（秒） | `5` |
| `--max-iterations` | 最大迭代次數 | 無限 |
