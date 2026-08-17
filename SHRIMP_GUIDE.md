# 蝦米 Agent 部署指南 (Windows 筆電)

## 📋 目錄

1. 快速開始
2. 安裝步驟
3. 執行方式
4. 角色選擇
5. 與主機連接
6. 監控和故障排查
7. 常見問題

---

## 1️⃣ 快速開始

### 最快 5 分鐘上線

```bash
# 1. 克隆倉庫 (在 PowerShell 中執行)
git clone https://github.com/shiesam/hermes-audit-system.git
cd hermes-audit-system

# 2. 測試連接到主機的資料庫
python3 -c "from watchdog_db import init_db; init_db()"

# 3. 運行測試驗證環境
python3 test_scenario.py

# 4. 啟動執行端監聽
python3 agent_executor.py --agent shrimp
```

---

## 2️⃣ 安裝步驟

### 環境要求

```
Windows 10/11
- Python 3.7+ (從 python.org 下載)
- Git (從 git-scm.com 下載)
- 網路連接到主機

檢查版本:
  python --version
  git --version
```

### 詳細安裝

#### Step 1: 安裝 Python

1. 下載 Python 3.10+ (https://www.python.org/downloads/)
2. 安裝時 **勾選** "Add Python to PATH"
3. 驗證:
```powershell
python --version
python -m pip --version
```

#### Step 2: 安裝 Git

1. 下載 Git (https://git-scm.com/download/win)
2. 使用預設設置安裝
3. 驗證:
```powershell
git --version
```

#### Step 3: 克隆倉庫

```powershell
# 在 PowerShell 中執行
cd ~\Documents
git clone https://github.com/shiesam/hermes-audit-system.git
cd hermes-audit-system

# 驗證文件
dir
# 應該看到:
#   watchdog_db.py
#   agent_executor.py
#   agent_initiator.py
#   test_scenario.py
#   ARCHITECTURE.md
#   HOST_GUIDE.md
```

#### Step 4: 配置資料庫連接

**重要**: 蝦米需要連接到主機的資料庫！

##### 方式 A: NFS/SMB 共享（推薦）

```powershell
# 在 Windows 檔案總管中
# 按 Win+R，輸入: \\192.168.x.x\hermes

# 然後在 PowerShell 中
cd \\192.168.x.x\hermes\hermes-audit-system

# 或映射為網路磁碟
net use Z: \\192.168.x.x\hermes
cd Z:\hermes-audit-system
```

##### 方式 B: SSH + SFTP（備選）

```powershell
# 使用 SSH 遠程執行（需要 plink 或 putty）
# 或使用 WinSCP 映射遠程資料夾
```

##### 方式 C: 本地副本 + 同步（備選）

```powershell
# 定期從主機複製 agent-mesh.db
# 這種方式可能會有延遲，不推薦用於生產環境
```

#### Step 5: 測試連接

```powershell
# 測試資料庫連接
python test_scenario.py

# 應該看到:
# ============================================================
#   1️⃣ 訊息 m-001 創建
# ============================================================
# ✅ 建立訊息: m-001
# ...
# [✓] 所有工作流程都按預期運行。
```

---

## 3️⃣ 執行方式

### A. 蝦米當「執行端」（推薦）

蝦米監聽主機發起的任務，執行後回報結果。

```powershell
# 終端 1: 啟動蝦米執行端（持續監聽）
python agent_executor.py --agent shrimp

# 會輸出:
# ============================================================
#   蝦米 (Windows 筆電) - 執行端
#   監聽對象: host 的任務
#   輪詢間隔: 5s
# ============================================================
#
# ⏳ [1] 沒有新訊息
# ⏳ [2] 沒有新訊息
# ...
# (等待主機發起任務)
```

**當主機發起任務時**:
```
📬 [5] 發現 1 個新訊息

  ┌─ 訊息: m-abc12345
  │  來自: host
  │  狀態: submitted
  │  ✅ 確認收到 (acknowledged)
  │  💓 發送 heartbeat (wd=WD-ABC123)
  │  🔄 開始工作 (working)
  │  📋 Task Type: collection
  │  📝 Description: 收集某些數據
  │  ✅ 工作完成
  │  ✅ 標示完成 (completed)
  │  📍 watchdog 會自動 disarm
  └─
```

### B. 蝦米當「發起端」

蝦米建立任務，主機執行任務。

```powershell
# 終端 1: 啟動蝦米發起端（互動模式）
python agent_initiator.py --agent shrimp --interactive

# 交互式輸入:
# 任務類型: processing
# 任務描述: 驗證數據品質
# 超時時間: [按 Enter 使用預設]

# 會輸出:
# ✅ 建立訊息: m-xxxxxxxx
# ✅ Arm Watchdog: WD-xxxxxxxx
# ⏳ 等待任務完成...
# (等待主機執行)
```

**或批次模式**

```powershell
python agent_initiator.py `
  --agent shrimp `
  --task-type verification `
  --description "驗證數據" `
  --threshold 600
```

### C. 同時執行兩個角色

蝦米既可以發起，也可以執行。

```powershell
# 開啟 2 個 PowerShell 視窗

# 視窗 1: 執行端
python agent_executor.py --agent shrimp

# 視窗 2: 發起端（互動模式）
python agent_initiator.py --agent shrimp --interactive
```

---

## 4️⃣ 角色選擇

### 情景 A: 蝦米主要執行（推薦用於筆電）

```
主機 (Linux)           蝦米 (Windows)
   │                      │
   ├─ 建立任務 ──────→  監聽 & 執行
   │                      │
   ├─ 等待結果 ←──── 回報完成
   │
```

**優點**:
- 蝦米不需要運行 cronjob
- 主機更穩定，24/7 運行掃描
- 蝦米可以開發、測試時也能執行任務

**設置**:

1. **主機 (Linux VirtualBox)** - 必須 24/7 運行
   ```bash
   # 終端 1: 發起端
   nohup python3 agent_initiator.py --agent host --interactive > agent-init.log 2>&1 &
   
   # 終端 2: Watchdog 掃描（cronjob）
   */1 * * * * cd /home/vboxuser/hermes-audit-system && python3 watchdog_db.py run >> /var/log/hermes-watchdog.log 2>&1
   ```

2. **蝦米 (Windows)** - 按需運行
   ```powershell
   # 執行端（隨時可以啟動）
   python agent_executor.py --agent shrimp
   ```

---

### 情景 B: 蝦米主要發起

```
蝦米 (Windows)         主機 (Linux)
   │                      │
   ├─ 建立任務 ──────→  監聽 & 執行
   │                      │
   ├─ 等待結果 ←──── 回報完成
   │
```

**優點**:
- 蝦米有更多控制權
- 適合測試、開發、實驗場景

**設置**:

1. **蝦米 (Windows)** - 按需運行
   ```powershell
   # 發起端（互動或批次模式）
   python agent_initiator.py --agent shrimp --interactive
   ```

2. **主機 (Linux)** - 必須 24/7 運行
   ```bash
   # 終端 1: 執行端
   nohup python3 agent_executor.py --agent host > agent-exec.log 2>&1 &
   
   # 終端 2: Watchdog 掃描（cronjob）
   */1 * * * * cd /home/vboxuser/hermes-audit-system && python3 watchdog_db.py run >> /var/log/hermes-watchdog.log 2>&1
   ```

---

### 情景 C: 雙向協作

蝦米既發起也執行，主機也既發起也執行。

```powershell
# 蝦米可以有多個 PowerShell 視窗同時運行

# 視窗 1: 監聽主機的任務
python agent_executor.py --agent shrimp

# 視窗 2: 發起任務給主機
python agent_initiator.py --agent shrimp --interactive

# 視窗 3: 手動發起特定任務
python agent_initiator.py --agent shrimp --task-type verification --description "test"
```

---

## 5️⃣ 與主機連接

### 前置條件

1. 主機 IP 地址: 例如 `192.168.x.x`
2. 網路連通性: ping 主機確保可達
3. 共享資料庫: 主機的 `agent-mesh.db` 對蝦米可見

### 連接方式

#### A. NFS/SMB 共享（Windows 推薦）

**主機端配置 (Linux)**

```bash
# 1. 安裝 Samba
sudo apt install samba

# 2. 編輯 /etc/samba/smb.conf
sudo nano /etc/samba/smb.conf

# 加入以下內容
[hermes]
   path = /home/vboxuser/hermes-audit-system
   available = yes
   browsable = yes
   public = yes
   writable = yes
   guest ok = yes

# 3. 重啟 Samba
sudo systemctl restart smbd
```

**蝦米端連接 (Windows)**

```powershell
# 方式 1: 檔案總管
# 按 Win+R，輸入: \\192.168.x.x\hermes
# 輸入用戶名和密碼（如有設置）

# 方式 2: PowerShell 映射網路磁碟
net use Z: \\192.168.x.x\hermes

# 然後進入該目錄
cd Z:\hermes-audit-system

# 方式 3: PowerShell 直接訪問
cd \\192.168.x.x\hermes\hermes-audit-system
python agent_executor.py --agent shrimp
```

#### B. SSH + 遠程執行（高級）

```powershell
# 使用 SSH 遠程連接
# （需要在主機上安裝 SSH server，例如 OpenSSH）

# 在主機上安裝 SSH
sudo apt install openssh-server
sudo systemctl start ssh

# 在蝦米上，通過 SSH 執行遠程命令
ssh vboxuser@192.168.x.x "cd hermes-audit-system && python3 watchdog_db.py status"

# 或映射遠程資料夾
# 使用 WinSCP、FileZilla 等工具
```

#### C: 本地副本 + 同步（不推薦）

```powershell
# 定期從主機下載最新的 agent-mesh.db
# 這會導致數據不同步，容易出錯

# 更好的方式: 使用網路共享（A 方式）
```

### 測試連接

```powershell
# 1. Ping 主機
ping 192.168.x.x
# 應該有回應

# 2. 訪問共享資料夾
dir \\192.168.x.x\hermes
# 應該看到 hermes-audit-system 資料夾

# 3. 驗證資料庫可訪問
python -c "from pathlib import Path; print(Path('\\\\192.168.x.x\\hermes\\hermes-audit-system\\agent-mesh.db').exists())"
# 應該輸出: True

# 4. 運行測試
cd \\192.168.x.x\hermes\hermes-audit-system
python test_scenario.py
```

---

## 6️⃣ 監控和故障排查

### 查看系統狀態

```powershell
# 狀態一覽（連接到主機的資料庫）
python watchdog_db.py status

# 輸出:
# === Watchdog Status ===
# Active jobs: 2
#   [armed  ] WD-ABC123  msg=m-001  kind=collection  threshold=600s
#   [stalled] WD-DEF456  msg=m-002  kind=processing  threshold=300s
#
# Open incidents: 1
#   [review] INC-XYZ001  msg=m-002  watchdog=WD-DEF456
```

### 查詢特定訊息

```powershell
python -c "
from watchdog_db import *
import json
conn = init_db()
msg = get_message(conn, 'm-001')
print(f'Status: {msg[\"status\"]}')
print(f'Sender: {msg[\"sender\"]}')
print(f'Receiver: {msg[\"receiver\"]}')
"
```

### 常見問題排查

#### 1. 連接不到資料庫

**錯誤信息**:
```
sqlite3.OperationalError: unable to open database file
```

**解決**:
```powershell
# 1. 檢查路徑
Test-Path \\192.168.x.x\hermes\hermes-audit-system\agent-mesh.db

# 2. 檢查網路連接
ping 192.168.x.x

# 3. 檢查共享設置
dir \\192.168.x.x\hermes

# 4. 重新映射網路磁碟
net use Z: /delete
net use Z: \\192.168.x.x\hermes
```

#### 2. 訊息卡在 submitted

**原因**: 沒有執行端在監聽

**解決**:
```powershell
# 檢查執行端是否運行
Get-Process python | Where-Object {$_.Name -like "*agent_executor*"}

# 如果沒有，啟動執行端
python agent_executor.py --agent shrimp
```

#### 3. Incident 卡在 open

**原因**: Watchdog 沒有掃描，或任務真的超時了

**解決**:
```powershell
# 檢查主機上的 cronjob 是否運行
# SSH 連接到主機
ssh vboxuser@192.168.x.x
crontab -l
tail -f /var/log/hermes-watchdog.log

# 或手動觸發掃描
python watchdog_db.py run
```

#### 4. 資料庫鎖定

**錯誤信息**:
```
sqlite3.OperationalError: database is locked
```

**解決**:
```powershell
# 1. 檢查是否有其他進程持有鎖
Get-Process python

# 2. 關閉所有 Python 進程
Stop-Process -Name python -Force

# 3. 檢查資料庫完整性
sqlite3 agent-mesh.db "PRAGMA integrity_check;"

# 4. 如果需要重置
Remove-Item agent-mesh.db
python -c "from watchdog_db import init_db; init_db()"
```

---

## 7️⃣ 常見問題

### Q1: 蝦米可以離線工作嗎？

**不行**。蝦米需要實時訪問主機的資料庫。

**解決方案**:
- 使用 VPN 保持連接
- 使用遠程桌面訪問主機
- 在主機上定期執行 agent_initiator.py

### Q2: 多個蝦米可以同時執行嗎？

**可以！** 但需要注意：

```powershell
# 蝦米 1
python agent_executor.py --agent shrimp

# 蝦米 2
python agent_executor.py --agent shrimp-02  # 需要修改 agent 名稱

# 或者兩個蝦米都叫 shrimp
# 但要在代碼中區分，或使用負載均衡
```

### Q3: 如何停止執行中的任務？

```powershell
# 方式 1: 在執行端按 Ctrl+C 中斷

# 方式 2: 手動標示失敗
python -c "
from watchdog_db import *
conn = init_db()
update_message_status(conn, 'm-001', 'failed', errors={'reason': 'manual termination'})
"
```

### Q4: 蝦米在 Windows 睡眠時會發生什麼？

**資料庫連接會中斷！**

**解決方案**:
- 設置 Windows 不進入睡眠: `powercfg /change monitor-timeout-ac 0`
- 使用任務排程器在後台運行
- 或將 agent 部署到另一台 Linux 伺服器

### Q5: 如何檢查蝦米和主機是否同步？

```powershell
# 查看最近的訊息和 incident
python -c "
from watchdog_db import *
import json
conn = init_db()
msgs = conn.execute('SELECT msg_id, status, updated_at FROM messages ORDER BY updated_at DESC LIMIT 5').fetchall()
for msg in msgs:
    print(f'{msg[\"msg_id\"]}: {msg[\"status\"]} ({msg[\"updated_at\"]})')
"
```

---

## 📚 相關文件

- `ARCHITECTURE.md` - 系統架構設計
- `HOST_GUIDE.md` - 主機 (Linux) 部署指南
- `watchdog_db.py` - 核心模組
- `agent_executor.py` - 執行端代碼
- `agent_initiator.py` - 發起端代碼

---

## 🆘 獲得幫助

遇到問題？

1. 檢查網路連接: `ping 192.168.x.x`
2. 檢查資料庫訪問: `Test-Path \\192.168.x.x\hermes\...`
3. 查看系統狀態: `python watchdog_db.py status`
4. 檢查是否有 incident: `python -c "from watchdog_db import *; print(get_open_incidents(init_db()))"`
5. 查看 `HOST_GUIDE.md` 的故障排查章節

---

**最後更新**: 2026-08-17
