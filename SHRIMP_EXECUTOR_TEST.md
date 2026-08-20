# SHRIMP_EXECUTOR_TEST.md — 蝦米測試說明書

> 適用對象：蝦米（Windows 筆電）  
> 對應腳本：`test_shrimp_initiator.py`

---

## 快速開始（3 步）

### Step 1：Clone 倉庫

```powershell
git clone https://github.com/shiesam/hermes-audit-system.git
cd hermes-audit-system
```

### Step 2：確認 Python

```powershell
python --version   # 需要 3.9+
```

### Step 3：發起測試任務

```powershell
# 使用主機的共享 DB（把 IP 換成主機實際 IP）
python test_shrimp_initiator.py --db \\192.168.1.100\hermes\hermes-audit-system\agent-mesh.db
```

---

## 完整流程說明

### 流程圖

```
蝦米端（Windows）                      主機端（Linux）
     │
     ├─ test_shrimp_initiator.py
     │  ├─ 建立 m-xxxxx（submitted）
     │  ├─ arm watchdog
     │  └─ 等待結果...
     │
     │                    ←─ 輪詢 DB ────────────
     │                    │  test_host_executor.py
     │                    ├─ submitted → acknowledged
     │                    ├─ acknowledged → working
     │                    ├─ 執行工作
     │                    ├─ working → completed
     │                    └─ watchdog 自動 disarm
     │
     └─ 接收結果 ✅
```

### 狀態說明

| 狀態 | 意義 |
|------|------|
| `submitted` | 蝦米已建立任務，等待主機接收 |
| `acknowledged` | 主機已確認收到任務 |
| `working` | 主機正在執行任務 |
| `completed` | 任務完成，結果已回填 |
| `failed` | 任務失敗，錯誤已記錄 |

---

## 運行方式

### 方式 A：建立任務並等待結果（標準）

```powershell
# 使用共享 DB，等待主機完成任務
python test_shrimp_initiator.py --db \\192.168.1.100\hermes\hermes-audit-system\agent-mesh.db
```

預期輸出：
```
============================================================
  🦐 蝦米發起端（Shrimp Initiator）— 端到端測試
  目標執行端: host（主機）
  資料庫:     \\192.168.1.100\hermes\hermes-audit-system\agent-mesh.db
  任務類型:   collection
  任務描述:   test from shrimp laptop
============================================================

✅ 資料庫連線成功

✅ 建立訊息: m-6330c9ee
   發起端: shrimp（蝦米）
   執行端: host（主機）
✅ 記錄進度事件: started
✅ Arm Watchdog: WD-XXXXXXXX
   超時時間: 600s

訊息 ID:      m-6330c9ee
Watchdog Tag: WD-XXXXXXXX

⏳ 等待主機執行...
   訊息: m-6330c9ee
   超時: 660s
   輪詢間隔: 5s

  [1] ⏳ 狀態: submitted（已等待 5s）
  [2] ⏳ 狀態: acknowledged（已等待 10s）
  [3] ⏳ 狀態: working（已等待 15s）
  [4] ⏳ 狀態: working（已等待 20s）

✅ 任務完成！
   結果: {
     "task_type": "collection",
     "status": "completed",
     "records": 42,
     ...
   }

🎉 端到端測試成功！蝦米 → 主機 → 蝦米
```

---

### 方式 B：建立任務後不等待

```powershell
# 建立任務後立刻結束，讓主機去執行
python test_shrimp_initiator.py --no-wait --db \\192.168.1.100\hermes\hermes-audit-system\agent-mesh.db
```

之後查詢結果：
```powershell
# 把 m-xxxxxxxx 換成實際的訊息 ID
python test_shrimp_initiator.py --check m-6330c9ee --db \\192.168.1.100\hermes\hermes-audit-system\agent-mesh.db
```

---

### 方式 C：自訂任務類型和描述

```powershell
python test_shrimp_initiator.py `
  --task-type processing `
  --description "稽核資料批次處理" `
  --db \\192.168.1.100\hermes\hermes-audit-system\agent-mesh.db
```

---

### 方式 D：本地測試（蝦米和主機在同一台機器）

```powershell
# 不需要指定 --db，使用本地 agent-mesh.db
python test_shrimp_initiator.py --task-type collection --description "local test" --no-wait
```

---

## 常見問題

### Q1：`Import 失敗: No module named 'watchdog'`

**解決方法**：確認在 `hermes-audit-system` 目錄下運行：

```powershell
cd hermes-audit-system
dir src\watchdog\watchdog_db.py   # 確認文件存在
python test_shrimp_initiator.py
```

---

### Q2：無法連接主機 DB（網路路徑）

**步驟 1：確認網路通**
```powershell
ping 192.168.1.100
```

**步驟 2：確認共享可訪問**
```powershell
dir \\192.168.1.100\hermes
```

**步驟 3：如果看到 `拒絕存取`，嘗試映射網路磁碟**
```powershell
net use Z: \\192.168.1.100\hermes
python test_shrimp_initiator.py --db Z:\hermes-audit-system\agent-mesh.db
```

**如果 Samba 還沒設定**，通知主機管理員執行以下設定：
```bash
# 主機（Linux）上
sudo apt install -y samba
# 按 HOST_EXECUTOR_GUIDE.md 的 Samba 設定章節設置
```

---

### Q3：任務一直停在 `submitted`，沒有進展

主機執行端可能沒有在運行。通知主機管理員：

```bash
# 主機（Linux）上啟動執行端
python3 test_host_executor.py --db /srv/samba/hermes-audit/agent-mesh.db
```

等 5-10 秒後，蝦米端狀態應從 `submitted` 變為 `acknowledged`。

---

### Q4：`超時` 錯誤

預設超時時間：
- `collection`: 660 秒（10 分鐘 + 1 分鐘）
- `processing`: 960 秒（15 分鐘 + 1 分鐘）
- `verification`: 660 秒（10 分鐘 + 1 分鐘）

可以用 `--threshold` 調整：
```powershell
# 設定 30 秒超時（快速測試用）
python test_shrimp_initiator.py --threshold 30
```

---

## 參數說明

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `--db` | SQLite 資料庫路徑（支援 UNC 網路路徑） | `./agent-mesh.db` |
| `--task-type` | 任務類型：`collection` / `processing` / `verification` | `collection` |
| `--description` | 任務描述 | `test from shrimp laptop` |
| `--threshold` | 超時時間（秒） | 依任務類型 |
| `--no-wait` | 建立任務後不等待結果 | 否 |
| `--interval` | 等待時的輪詢間隔（秒） | `5` |
| `--check MSG_ID` | 查詢指定訊息的狀態（不建立新任務） | — |

---

## 與主機協作的完整圖解

```
              共享 SQLite DB
              （存在主機上，
               透過 Samba/NFS 共享）
                     │
         ┌───────────┴───────────┐
         │                       │
    蝦米（Windows）          主機（Linux）
    ─────────────────        ─────────────────
    test_shrimp_             test_host_
    initiator.py             executor.py
         │                       │
    1. 建立訊息              3. 讀取訊息
    2. Arm watchdog          4. submitted → acknowledged
                             5. acknowledged → working
                             6. 執行任務
                             7. working → completed
                             8. watchdog 自動 disarm
         │                       │
    9. 輪詢看到 completed ←──────┘
   10. 顯示結果 ✅
```

---

## 文件清單

| 文件 | 說明 |
|------|------|
| `test_shrimp_initiator.py` | 蝦米發起端測試腳本（本文件對應腳本） |
| `SHRIMP_EXECUTOR_TEST.md` | 本文件（蝦米使用說明） |
| `test_host_executor.py` | 主機執行端測試腳本 |
| `HOST_EXECUTOR_GUIDE.md` | 主機使用說明 |
| `SHRIMP_QUICK_START.md` | 蝦米快速上手指南（更完整） |
