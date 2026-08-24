# 角色互換指南

## 📋 目錄

1. 核心概念
2. 為什麼可以互換
3. 快速互換
4. 實際案例
5. 互換時的注意事項
6. 測試驗證

---

## 1️⃣ 核心概念

### 系統設計：角色無關（Role-Agnostic）

Hermes Audit System 的核心設計完全**不依賴角色**。

```
傳統思維（有問題）：
  ├─ Agent A = 執行端（死角色）
  └─ Agent B = 發起端（死角色）
  問題：角色固化，不夠靈活

Hermes 設計（正確）：
  ├─ Agent X = 可以既發起也執行
  ├─ Agent Y = 可以既發起也執行
  └─ 角色完全由訊息的 sender/receiver 決定
  優點：最大靈活性，角色動態分配
```

### 訊息模型

```python
create_message(
    conn,
    msg_id="m-001",
    sender="主機",      # ← 只是文字記錄
    receiver="蝦米",    # ← 只是文字記錄
    payload={...},
    msg_type="task"
)

# 系統完全不關心 sender/receiver 的具體內容
# 任何字符串都可以！
```

### Watchdog 機制

```python
# Watchdog 只關心：
# 1. 訊息狀態（submitted/acknowledged/working/completed）
# 2. 時間（idle_seconds）
# 3. 任務類型（kind: collection/processing/verification）

# 完全不關心：
# ✗ sender 是誰
# ✗ receiver 是誰
# ✗ Agent 的身份或角色
```

---

## 2️⃣ 為什麼可以互換

### 證據 1: 相同的狀態機

```
任何 Agent 作為發起端：
  msg_status = submitted
  ├─ arm_watchdog()
  └─ wait_for_result()

任何 Agent 作為執行端：
  msg_status = submitted
  ├─ update_message_status('acknowledged')
  ├─ heartbeat()
  ├─ update_message_status('working')
  └─ update_message_status('completed')

狀態轉移完全相同，無論是誰！
```

### 證據 2: 相同的 API

```python
# 發起端用的函數
- create_message()           # 任何 agent 都能呼叫
- arm_watchdog_job()         # 任何 agent 都能呼叫
- get_open_incidents()       # 任何 agent 都能呼叫

# 執行端用的函數
- get_messages_by_status()   # 任何 agent 都能呼叫
- update_message_status()    # 任何 agent 都能呼叫
- heartbeat()                # 任何 agent 都能呼叫

# 所有函數都是通用的，無角色限制！
```

### 證據 3: 測試驗證

**test_scenario.py**（原始）
```python
sender="A", receiver="B"  # A 發起，B 執行
# 結果：✅ 所有 11 步驟通過
```

**test_scenario_swapped.py**（互換）
```python
sender="B", receiver="A"  # B 發起，A 執行
# 結果：✅ 所有 11 步驟通過
```

**結論**：改一行 sender/receiver，邏輯完全相同！

---

## 3️⃣ 快速互換

### 只需改 2 行

**原始設置**
```python
# agent_initiator.py - 發起端是主機
create_message(
    conn,
    msg_id="m-001",
    sender="host",      # ← 主機是發起端
    receiver="shrimp",  # ← 蝦米是執行端
    payload={...}
)
```

**互換後**
```python
# agent_initiator.py - 發起端變成蝦米
create_message(
    conn,
    msg_id="m-001",
    sender="shrimp",    # ← 蝦米是發起端
    receiver="host",    # ← 主機是執行端
    payload={...}
)
```

### 或者改 CLI 參數

```bash
# 原始：主機發起
python agent_initiator.py --agent host

# 互換：蝦米發起
python agent_initiator.py --agent shrimp

# 內部會自動決定 sender/receiver！
```

---

## 4️⃣ 實際案例

### 案例 1: 主機 → 蝦米（原始）

```
主機 (Linux VirtualBox)              蝦米 (Windows 筆電)
│                                      │
├─ python agent_initiator.py \
   --agent host \
   --task-type collection \
   --description "Collect data"        │
│                                      │
├─ create_message(                     │
   sender="host",  ← 記住這是主機      │
   receiver="shrimp"                   │
  )                                    │
│                                      │
├─ arm_watchdog(WD-123)               │
│                                      │
├─ wait_for_result("m-001")           │
│                                      ├─ python agent_executor.py \
│                                      │  --agent shrimp
│                                      │
│                                      ├─ 監聽 receiver=shrimp 的訊息
│                                      │
│                                      ├─ 看到 m-001 (from=host)
│                                      │
│                                      ├─ update_message_status(acknowledged)
│                                      │
│                                      ├─ do_work()
│                                      │
│                                      ├─ update_message_status(completed)
│                                      │
├─ receive result ←─ ─ ─ ─ ─ ─ ─ ─ ─ ┤
│                                      │
└─ ✅ done                             └─ ✅ done
```

### 案例 2: 蝦米 → 主機（互換）

```
主機 (Linux VirtualBox)              蝦米 (Windows 筆電)
│                                      │
│                                      ├─ python agent_initiator.py \
│                                      │  --agent shrimp \
│                                      │  --task-type processing \
│                                      │  --description "Verify data"
│                                      │
│                                      ├─ create_message(
│                                      │   sender="shrimp",  ← 記住這是蝦米
│                                      │   receiver="host"
│                                      │  )
│                                      │
│                                      ├─ arm_watchdog(WD-456)
│                                      │
│                                      ├─ wait_for_result("m-002")
│                                      │
├─ python agent_executor.py \          │
│  --agent host                        │
│                                      │
├─ 監聽 receiver=host 的訊息           │
│                                      │
├─ 看到 m-002 (from=shrimp)            │
│                                      │
├─ update_message_status(acknowledged)│
│                                      │
├─ do_work()                          │
│                                      │
├─ update_message_status(completed)   │
│                                      │
│                                      ├─ receive result ←─ ─ ─ ─ ─ ─
│                                      │
│                                      └─ ✅ done
└─ ✅ done
```

### 案例 3: 多向協作

```
主機 可以：
  ├─ 發起任務給蝦米
  ├─ 執行蝦米的任務
  └─ 與其他機器協作

蝦米 可以：
  ├─ 發起任務給主機
  ├─ 執行主機的任務
  └─ 與其他機器協作

完全對稱！
```

**範例配置**

```bash
# 主機：既發起也執行
# 終端 1
python agent_initiator.py --agent host --interactive

# 終端 2
python agent_executor.py --agent host

# 終端 3
python watchdog_db.py run

# ─────────────────────────────────

# 蝦米：既發起也執行
# 終端 1
python agent_initiator.py --agent shrimp --interactive

# 終端 2
python agent_executor.py --agent shrimp
```

---

## 5️⃣ 互換時的注意事項

### ⚠️ 1. sender 和 receiver 必須不同

❌ **錯誤**
```python
create_message(
    conn,
    sender="host",
    receiver="host"  # 不能是自己！
)
```

✅ **正確**
```python
create_message(
    conn,
    sender="host",
    receiver="shrimp"  # 必須是另一個 agent
)
```

### ⚠️ 2. 確保接收端在監聽

❌ **問題**
```bash
# 主機發起
python agent_initiator.py --agent host

# 但蝦米沒有運行執行端
# → 訊息會卡在 submitted，直到超時
```

✅ **正確**
```bash
# 終端 1: 主機發起
python agent_initiator.py --agent host

# 終端 2: 蝦米執行（另一台機器）
python agent_executor.py --agent shrimp
```

### ⚠️ 3. Watchdog 必須運行

❌ **問題**
```bash
# 發起任務但沒有 watchdog 掃描
# → incident 不會被產生
# → 系統無法偵測超時
```

✅ **正確**
```bash
# 任何時刻都要有一個進程在掃描
python watchdog_db.py run

# 或通過 cronjob
*/1 * * * * cd /path/to/hermes && python3 watchdog_db.py run
```

### ⚠️ 4. 資料庫要共享

❌ **問題**
```python
# 主機用的 DB: /home/vboxuser/agent-mesh.db
# 蝦米用的 DB: C:\Users\...\agent-mesh.db
# ← 兩個不同的資料庫，無法協作！
```

✅ **正確**
```python
# 兩個都連接到同一個資料庫
# 方式 A: 主機上的 DB 透過 NFS/SMB 共享
# 方式 B: 遠程 SQLite（需要改代碼支持）
# 方式 C: 更換為網路 DB（如 PostgreSQL、MySQL）
```

---

## 6️⃣ 測試驗證

### 快速測試互換

```bash
# 1. 運行原始測試（A 發起，B 執行）
python test_scenario.py
# 預期：✅ 所有 11 步驟通過

# 2. 運行互換測試（B 發起，A 執行）
python test_scenario_swapped.py
# 預期：✅ 所有 11 步驟通過

# 結論：結果相同，角色無關！
```

### 自訂測試

```python
#!/usr/bin/env python3
"""測試任意角色互換"""

from watchdog_db import *

def test_role_swap(sender, receiver):
    conn = init_db()
    
    # 1. 建立訊息
    msg_id = f"m-test-{sender}-{receiver}"
    create_message(
        conn, msg_id,
        sender=sender,
        receiver=receiver,
        payload={"task_type": "collection"}
    )
    print(f"✅ 建立: {sender} → {receiver}")
    
    # 2. Arm
    wd_tag = arm_watchdog_job(conn, msg_id, kind="collection")
    print(f"✅ Arm: {wd_tag}")
    
    # 3. 模擬執行端行為
    update_message_status(conn, msg_id, 'acknowledged')
    heartbeat(conn, wd_tag)
    update_message_status(conn, msg_id, 'working')
    update_message_status(
        conn, msg_id, 'completed',
        result={"status": "done"}
    )
    print(f"✅ 完成")
    
    # 4. 驗證
    msg = get_message(conn, msg_id)
    assert msg['status'] == 'completed'
    print(f"✅ 驗證通過")
    
    conn.close()

# 測試所有組合
test_role_swap("host", "shrimp")    # 原始
test_role_swap("shrimp", "host")    # 互換
test_role_swap("agent-a", "agent-b")  # 自訂名稱
test_role_swap("x", "y")            # 任意字符串

print("\n✅ 所有角色組合都能正常運作！")
```

---

## 📊 互換檢查清單

在決定互換角色時，檢查以下項目：

| 項目 | 檢查 | 狀態 |
|------|------|------|
| **資料庫連接** | 兩個 agent 都能訪問同一個 DB | ✅ |
| **sender/receiver** | 不相同，且符合邏輯 | ✅ |
| **執行端監聽** | receiver 對應的 agent 有執行端在運行 | ✅ |
| **Watchdog 掃描** | 有 cronjob 或進程在定期掃描 | ✅ |
| **threshold 設置** | 根據任務類型設置合理超時 | ✅ |
| **測試運行** | 用 test_scenario.py 驗證設置 | ✅ |

---

## 🎯 結論

### 核心要點

1. ✅ **Hermes 系統是角色無關的**
2. ✅ **任何兩個 agent 都可以協作**
3. ✅ **只需改變 sender/receiver**
4. ✅ **邏輯完全相同，無需修改核心代碼**
5. ✅ **已通過測試驗證**

### 可能的互換

```
主機 ↔ 蝦米
主機 ↔ 其他機器
蝦米 ↔ 其他機器
多向協作（M 個 agent × N 個任務）

所有組合都支持！
```

### 推薦用法

```bash
# 場景 1: 主機為中樞
主機發起 → 蝦米執行
蝦米發起 → 主機執行
主機發起 → 其他機器執行

# 場景 2: 蝦米為中心
蝦米發起 → 主機執行
蝦米發起 → 其他機器執行

# 場景 3: 完全去中心化
任何 agent 都可以與任何 agent 協作
```

---

**最後更新**: 2026-08-17

---

## 相關資源

- `../architecture/ARCHITECTURE.md` - 完整架構設計
- `HOST_GUIDE.md` - 主機部署指南
- `SHRIMP_GUIDE.md` - 蝦米部署指南
- `../../test_scenario.py` - 原始測試場景
- `../../test_scenario_swapped.py` - 互換測試場景
