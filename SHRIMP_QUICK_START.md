# 🦐 蝦米（Windows 筆電）快速開始指南

> 給蝦米的：你需要做什麼、要下載哪些文件、怎麼運行

---

## 📋 5 分鐘快速上線

### **Step 1: 準備環境**

```powershell
# 1. 安裝 Python 3.11+（如果還沒有）
#    下載: https://www.python.org/downloads/
#    記得勾選 "Add Python to PATH"
python --version

# 2. 安裝 Git（如果還沒有）
#    下載: https://git-scm.com/download/win
git --version
```

### **Step 2: 克隆倉庫**

```powershell
# 在你想放的位置執行（例如 Documents）
cd ~\Documents

# 克隆倉庫
git clone https://github.com/shiesam/hermes-audit-system.git
cd hermes-audit-system

# 查看文件列表（應該看到下面列出的文件）
dir
```

### **Step 3: 檢查關鍵文件**

下載完後，**必須有這些文件**：

```
hermes-audit-system/
├── 🆕 shrimp_agent.py          ← 蝦米專用！（新文件）
│
├── watchdog_db.py              ← 核心 watchdog 模組
├── agent_executor.py           ← 執行端（舊方式）
├── agent_initiator.py          ← 發起端（舊方式）
│
├── test_scenario.py            ← 測試檔
├── test_scenario_swapped.py    ← 角色互換測試
│
├── src/
│   ├── watchdog/
│   │   └── watchdog_db.py      ← 核心 watchdog（src 版本）
│   └── mesh/
│       └── progress_tracker.py ← 進度追蹤模組
│
├── agent-mesh.db               ← SQLite 資料庫（會自動生成）
├── README.md
├── ARCHITECTURE.md
├── HOST_GUIDE.md               ← 主機的指南
├── SHRIMP_GUIDE.md             ← 蝦米的舊指南（可參考）
└── SHRIMP_QUICK_START.md       ← 這份文件
```

**最重要的是 `shrimp_agent.py`！** 這是為你準備的新代碼。

---

## 🚀 三種運行方式

### **方式 1：執行端（推薦大多數情況）**

蝦米監聽主機的任務，自動執行並回報結果。

```powershell
# 基本用法
python shrimp_agent.py executor

# 自訂資料庫路徑（如果是網路共享）
python shrimp_agent.py executor --db \\192.168.1.100\hermes\agent-mesh.db

# 測試用：只執行 3 次輪詢後停止
python shrimp_agent.py executor --max-iterations 3
```

**預期輸出：**
```
============================================================
  蝦米 (Windows 筆電) — 執行端模式
  監聽對象: host 的任務
  資料庫:   hermes-audit-system/agent-mesh.db
  輪詢間隔: 5s
============================================================

⏳ [1] 沒有新訊息
⏳ [2] 沒有新訊息
...
（等待主機發起任務）
```

---

### **方式 2：發起端互動模式**

蝦米建立任務給主機執行，逐個輸入任務參數。

```powershell
# 互動模式
python shrimp_agent.py initiator --interactive
```

**互動流程：**
```
============================================================
  蝦米 (Windows 筆電) — 發起端互動模式
  目標: host
  資料庫: hermes-audit-system/agent-mesh.db
============================================================

📋 建立新任務
----------------------------------------
任務類型 (collection/processing/verification) [collection]: collection
任務描述: 蒐集系統日誌
超時時間（秒，預設=600）: [按 Enter 使用預設]

✅ 建立訊息: m-abc12345
✅ Arm Watchdog: WD-XYZ789
✅ 記錄進度事件: started

⏳ 等待任務完成...
   訊息: m-abc12345
   超時: 660s
   輪詢間隔: 5s

  [1] ⏳ 狀態: submitted (已等待 5s)
  [2] ⏳ 狀態: acknowledged (已等待 10s)
  [3] ⏳ 狀態: working (已等待 15s)
  ...
✅ 任務完成!
   結果: {...}

繼續? (y/n) [y]: n

👋 執行端已停止
```

---

### **方式 3：發起端批次模式**

蝦米通過命令行參數建立單個任務。

```powershell
# 基本用法（建立任務並等待結果）
python shrimp_agent.py initiator `
  --task-type collection `
  --description "蒐集數據"

# 自訂超時時間
python shrimp_agent.py initiator `
  --task-type processing `
  --description "驗證數據" `
  --threshold 300

# 建立任務但不等待結果
python shrimp_agent.py initiator `
  --task-type verification `
  --description "檢查結果" `
  --no-wait
```

---

## 🧪 測試步驟（確保環境正確）

### **測試 1：基本功能測試**

```powershell
# 進入倉庫目錄
cd hermes-audit-system

# 運行測試
python test_scenario.py
python test_scenario_swapped.py

# 預期：兩個測試都通過，看到 ✅ 標記
```

### **測試 2：執行端測試（模擬運行）**

```powershell
# 短時間執行（3 次迴圈後停止）
python shrimp_agent.py executor --max-iterations 3

# 預期：看到「蝦米執行端模式」的輸出，然後停止
```

### **測試 3：發起端測試**

```powershell
# 發起一個任務（但要確保主機執行端在運行）
python shrimp_agent.py initiator --task-type collection --description "test"

# 預期：
# ✅ 建立訊息
# ✅ Arm Watchdog
# ⏳ 等待任務完成
# （如果主機沒有執行端，會一直等待直到超時）
```

---

## 🌐 與主機連接（重要！）

如果資料庫在主機上，需要設置網路共享。

### **設置 NFS/SMB 共享（主機 Linux 側）**

主機需要執行：
```bash
# 主機（Linux）上
sudo apt install samba
sudo nano /etc/samba/smb.conf

# 在 smb.conf 中加入
[hermes]
   path = /home/vboxuser/hermes-audit-system
   available = yes
   browsable = yes
   public = yes
   writable = yes
   guest ok = yes

sudo systemctl restart smbd
```

### **蝦米 Windows 連接**

```powershell
# 方式 A：在檔案總管中
# 按 Win+R，輸入: \\192.168.1.100\hermes
# （將 192.168.1.100 改為主機 IP）

# 方式 B：命令行映射網路磁碟
net use Z: \\192.168.1.100\hermes

# 然後進入那個目錄
cd Z:\hermes-audit-system
python shrimp_agent.py executor --db Z:\hermes-audit-system\agent-mesh.db
```

### **指定資料庫路徑**

```powershell
# 如果資料庫在網路共享上
python shrimp_agent.py executor --db \\192.168.1.100\hermes\agent-mesh.db

# 或映射後使用網路磁碟
python shrimp_agent.py executor --db Z:\hermes-audit-system\agent-mesh.db
```

---

## 📊 三種角色組合

### **角色組合 1：蝦米是執行端（推薦）**

```
主機 (Linux)                蝦米 (Windows)
  │                            │
  ├─ 發起任務               
  │  (initiator)               │
  │                            │
  ├─ arm watchdog              │
  │                            │
  │                   ←────────┤
  │            監聽 & 執行
  │         (shrimp_agent.py executor)
  │                            │
  ├─ 等待結果              回報完成
  │  (監控 incident) ←────────┤
  │
```

**運行命令：**
```bash
# 主機（終端 1）
python agent_initiator.py --agent host --interactive

# 主機（終端 2）
python watchdog_db.py run  # 或通過 cronjob 定期執行

# 蝦米（Windows）
python shrimp_agent.py executor
```

---

### **角色組合 2：蝦米是發起端**

```
蝦米 (Windows)              主機 (Linux)
  │                            │
  ├─ 發起任務               
  │  (shrimp_agent.py initiator)
  │                            │
  ├─ arm watchdog              │
  │                            │
  │                   ←────────┤
  │                    監聽 & 執行
  │              (agent_executor.py --agent host)
  │                            │
  ├─ 等待結果              回報完成
  │
```

**運行命令：**
```bash
# 蝦米（Windows）
python shrimp_agent.py initiator --interactive

# 主機（終端 1）
python agent_executor.py --agent host

# 主機（終端 2）
python watchdog_db.py run
```

---

## 🔧 常見問題

### **Q1: 執行時報錯 `ImportError: cannot import name xxx`**

**原因：** Python path 設置不對

**解決：**
```powershell
# 確認你在 hermes-audit-system 目錄中
cd hermes-audit-system
pwd  # 應該顯示 .../hermes-audit-system

# 檢查 src/ 目錄存在
dir src

# 重新執行
python shrimp_agent.py executor
```

---

### **Q2: 連接不到資料庫 `unable to open database file`**

**原因：** 資料庫路徑不正確或網路共享沒配置

**檢查項目：**
```powershell
# 1. 檢查本地資料庫
Test-Path .\agent-mesh.db
# 應該輸出 True

# 2. 檢查網路共享
Test-Path \\192.168.1.100\hermes\agent-mesh.db
# 如果是網路共享，應該返回 True

# 3. 明確指定路徑
python shrimp_agent.py executor --db .\agent-mesh.db
```

---

### **Q3: 任務卡在 `submitted` 狀態，不進行**

**原因：** 沒有執行端在監聽，或主機的 watchdog 沒有運行

**檢查項目：**
```powershell
# 1. 確認執行端在運行
# （如果是蝦米執行，應該看到蝦米的監聽輸出）

# 2. 確認主機的 watchdog 在運行
# 在主機上：python watchdog_db.py status
# 應該看到活躍的 watchdog job

# 3. 檢查是否有 incident
# python watchdog_db.py status
```

---

### **Q4: Windows 路徑用反斜槓 `\` 總是出錯**

**解決：** 用單引號或雙反斜槓

```powershell
# ❌ 錯誤
python shrimp_agent.py executor --db \\192.168.1.100\hermes\agent-mesh.db

# ✅ 正確（轉義）
python shrimp_agent.py executor --db '\\192.168.1.100\hermes\agent-mesh.db'

# ✅ 正確（網路路徑）
python shrimp_agent.py executor --db \\\\192.168.1.100\\hermes\\agent-mesh.db

# ✅ 最簡單（用 PowerShell 換行符 `）
python shrimp_agent.py executor `
  --db \\192.168.1.100\hermes\agent-mesh.db
```

---

## 📞 還有問題？

查看這些文件：
- `README.md` — 專案概覽
- `ARCHITECTURE.md` — 系統架構（深入了解）
- `SHRIMP_GUIDE.md` — 蝦米的詳細指南（可選閱讀）
- `HOST_GUIDE.md` — 主機的配置指南（了解主機側的設置）

---

## ✅ 核實清單

在開始之前，確認你完成了：

- [ ] Python 3.11+ 已安裝
- [ ] Git 已安裝
- [ ] 倉庫已克隆到本地
- [ ] 進入 `hermes-audit-system` 目錄
- [ ] `shrimp_agent.py` 文件存在
- [ ] `src/watchdog/` 和 `src/mesh/` 目錄存在
- [ ] 運行了 `python test_scenario.py` 並通過
- [ ] 已閱讀「三種運行方式」章節

**完成上述所有項目後，你就可以開始了！**

---

**最後更新**: 2026-08-19

**下一步**: 選擇適合你的角色（執行端或發起端）並運行相應的命令。

