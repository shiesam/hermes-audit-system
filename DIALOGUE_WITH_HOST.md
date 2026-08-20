# 給主機的對話稿：先照目前「真的能用」的狀態來講

> 目的：不是討論理想版，而是把現在倉庫裡**已經實作、已經能跑、但還沒完全產品化**的狀態說清楚。

---

**我：** 我這次重新看了一輪程式和文檔，想先跟你對一下：現在系統不是「完全沒做」，而是「核心流程其實有了，但部署還停在半手動狀態」。

**主機：** 所以我說它現在不會自動接單，這句話對嗎？

**我：** 如果你的意思是「開機後自己常駐、完全不用人管」，那你說得對，**目前還不行**。因為倉庫裡沒有真正安裝完成的 `hermes-executor.service`，也沒有現成可直接啟用的 `hermes-watchdog.service`。所以現在要靠人手動執行 Python。

**主機：** 那你之前又說它會自動接單？

**我：** 這句也不是錯，差別在「自動接單」跟「自動啟動」是兩件事。

- `agent_executor.py` 所代表的 executor 邏輯，加上 `shrimp_agent.py executor` / `test_host_executor.py` 這類可執行入口，本身就是**輪詢 DB、自動發現新任務、自動 ack、自動執行、自動回報結果**。
- 也就是說：**只要這個 executor process 已經在跑，它就真的會自動接單。**
- 但現在缺的是 systemd 常駐化，所以它**不會自己開機啟動，也不會自己永遠待命**。

**主機：** 所以正確說法應該是？

**我：** 可以這樣講最準：

> 系統的「自動接單邏輯」已經實作完成；
> 但系統的「常駐部署方式」尚未完成，現在仍需手動啟動 executor。

---

## 目前已經有的東西

**我：** 先講已經能用的部分。

### 1. 核心共享狀態庫已經有了
- `src/watchdog/watchdog_db.py`
- 用 SQLite 當共享狀態庫
- 有 `messages`、`watchdog_jobs`、`incidents`、`progress_events`、`config`
- 有 WAL、`busy_timeout`、以及訊息狀態更新的樂觀式條件控制

### 2. 任務流程主體已經有了
- 發起端可以建立任務、arm watchdog、等結果
- 執行端可以輪詢 `submitted` 任務
- 接到後會走：`submitted -> acknowledged -> working -> completed/failed`
- 中間會送 heartbeat，並記錄 progress event

### 3. Watchdog 核心邏輯已經有了
- `watchdog_db.py run` 可以掃描卡住的任務
- 超時會建立 incident
- 任務完成後會 disarm watchdog
- 有明確的 timeout / stale / recover 行為

### 4. 通知機制有一半已經產品化
- 倉庫裡有 `notify_tasks.py`
- 也有 `hermes-notify.service` 和 `hermes-notify.timer`
- 這套是用來定期掃描 DB，通知主機目前有哪些任務在跑

---

## 跟理想狀態的差異

**主機：** 那離理想狀態還差什麼？

**我：** 差的主要不是演算法，而是部署收尾。

### 理想狀態應該是
1. executor 常駐（systemd）
2. watchdog scanner 常駐或定期執行（systemd/cron）
3. DB 路徑全系統統一
4. 所有文檔都描述同一套實際部署方法

### 但目前現狀是
1. **executor 還要手動跑**
2. **watchdog service 只有文檔草案，倉庫裡沒有正式 service 檔**
3. **DB 路徑正在收斂，但還沒有全倉統一**
4. **部分架構文檔還在寫理想版，不完全等於現況**

---

## 關於你做的 DB 路徑修改

**我：** 這次最值得保留的方向，是你把 DB 路徑往這個位置統一：

```text
/srv/samba/hermes-audit/agent-mesh.db
```

這個方向是合理的，因為它符合「主機與對端共用同一份資料庫」的部署思路。

**主機：** 那現在不是已經統一了嗎？

**我：** 還不能這樣說，只能說**已經開始往這個方向改**。

### 目前看得出來已經往 `/srv/samba/...` 靠攏的地方
- `HOST_EXECUTOR_GUIDE.md` 內已有這條路徑
- `test_host_executor.py` 的使用說明文字已有這條路徑
- 部分測試/操作指令也已經假設主機共享 DB 在 Samba 路徑下

### 但還沒完全跟上的地方
- `agent_executor.py` 預設 DB 仍是 repo 內的 `agent-mesh.db`
- `notify_tasks.py` 預設 DB 仍是 repo 內的 `agent-mesh.db`
- `hermes-notify.service` 目前仍寫 `%h/hermes-audit-system/agent-mesh.db`
- `src/watchdog/watchdog_db.py` 的內建預設值也仍指向 repo 根目錄下的 `agent-mesh.db`
- 還有舊腳本仍保留 `/home/vboxuser/...` 或舊 import 寫法

**我：** 所以比較準確的描述是：

> 你已經把部署方向改成「共享 DB 應放在 `/srv/samba/hermes-audit/agent-mesh.db`」，
> 但目前倉庫內容還沒有完全收斂到這個單一路徑。

---

## 為什麼我會說「它確實會自動接單」

**主機：** 這個你要講清楚，因為我覺得現在明明沒有自動。

**我：** 關鍵在 executor 的設計。

目前這套 executor 邏輯的工作方式是：

1. 持續輪詢資料庫
2. 找 `status='submitted'` 的訊息
3. 篩出 `receiver` 是自己的任務
4. 成功搶到後，把狀態改成 `acknowledged`
5. 接著改成 `working`
6. 執行工作
7. 寫回 `completed` 或 `failed`
8. 送 heartbeat / 記 progress

這整套行為就是「自動接單 + 自動執行 + 自動回報」。

**但前提是：那個 process 必須先跑起來。**

補一句比較實際的現況：  
現在 repo 裡**比較穩的可執行入口**是 `shrimp_agent.py executor` 與 `test_host_executor.py`；`agent_executor.py` 本身雖然表達了設計意圖，但目前還有 import/path 的收尾問題。

所以你如果說：
- 「它不會自己在開機後常駐接單」→ **對**
- 「它完全沒有自動接單能力」→ **不對**

---

## 目前還沒實作完成的關鍵項目

**我：** 這兩個東西要明確列成「未完成」：

### 1. `hermes-executor.service`
本來應該讓：
- `agent_executor.py --agent host`
- 或 `shrimp_agent.py executor`

變成常駐服務，開機自動起來，任務來了就接。

**目前：沒有正式 service 檔，也沒有完整安裝流程。**

### 2. `hermes-watchdog.service`
本來應該讓 watchdog scanner：
- 固定時間跑 `watchdog_db.py run`
- 自動掃描 stalled task
- 自動產生 incident

**目前：只有文檔示例，倉庫內沒有正式交付的 service 檔。**

---

## 建議你怎麼改架構說明

**我：** 我建議接下來不要再把架構文檔寫成「理想版已完成」，而是改成兩層：

### 第一層：現在真的能用的
- 共享 SQLite 狀態庫
- message / watchdog / incident / progress event
- 手動啟動 executor 後可自動接單
- 手動或排程執行 watchdog scan
- notify timer 可提供主機端任務提醒

### 第二層：還沒補完的部署件
- `hermes-executor.service`
- `hermes-watchdog.service`
- 全倉一致的 DB 路徑
- 舊腳本/舊文檔清理

這樣主機看文檔時，才不會以為「東西都上線了」，但實際又得手動開。

---

## 這套經驗要不要學起來？

**主機：** 那這件事有沒有什麼值得保留的經驗？

**我：** 有，而且很多。

### 值得保留的經驗
1. **SQLite + WAL + 樂觀鎖** 可以很快做出小型共享協作系統
2. **message-based task queue** 不一定要先上 RabbitMQ 才能做
3. **watchdog + incident** 是很實用的 timeout 偵測模式
4. **timer + one-shot service** 是輕量輪詢方案
5. **systemd 沒補完時，功能存在 ≠ 服務已交付**
6. **文檔一定要跟著現況走，不然會比 bug 更誤導人**
7. **sys.path / import 風格不統一，後面會讓腳本維護成本變高**
8. **DB 路徑一旦變成跨機共享資產，就要盡早統一，不然測試、service、文檔會各寫各的**

---

## 最後一句，給主機的結論版

你可以直接這樣跟主機說：

> 目前 Hermes Audit System 的核心協作邏輯其實已經存在：共享 SQLite、任務狀態機、watchdog、incident、progress tracking、executor 輪詢接單都已實作。  
> 但目前交付狀態仍屬「可用但半手動」：executor 需要手動啟動，watchdog service 尚未正式安裝，DB 路徑也還在收斂中。  
> 所以架構文檔應該改成描述「當前可用狀態」，而不是直接寫成「理想部署已完整落地」。

---

## 下一步建議

1. 先以 `ARCHITECTURE_CURRENT_STATE.md` 作為正式現況文檔
2. 把 `hermes-executor.service` 補齊
3. 把 `hermes-watchdog.service` 補齊，或明確改用 cron/timer
4. 決定唯一 DB 路徑（若要走 Samba，就全倉收斂到 `/srv/samba/hermes-audit/agent-mesh.db`）
5. 清理舊腳本的 import 與舊路徑說法
6. 最後再回頭更新 `ARCHITECTURE.md` / `README.md` 等對外文檔
