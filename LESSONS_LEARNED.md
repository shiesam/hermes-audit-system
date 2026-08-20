# Lessons Learned from the Current Hermes Audit System

這份筆記不是宣傳稿，而是把目前這套系統在實作過程中已經暴露出來的模式、取捨與教訓整理下來，供後續開發者少走彎路。

---

## 1. 系統設計模式

### 1.1 SQLite + WAL + 樂觀鎖的並發設計

這套系統最重要的工程選擇之一，是直接把 SQLite 當成共享狀態庫，而不是一開始就上完整的訊息中介或網路資料庫。

這樣做能快速得到幾個好處：
- 狀態集中
- 部署簡單
- 除錯容易
- 每個節點都能直接看資料

更重要的是，目前實作並不是「裸寫 SQLite」，而是有幾個關鍵控制點：
- WAL 模式降低讀寫互斥帶來的痛感
- `busy_timeout` 讓短暫競爭不會立刻噴錯
- `update_message_status()` 用條件式更新與版本號，形成簡單但有效的樂觀鎖

這證明了一件事：

> 在節點數不大、流量不高、共享儲存可接受的前提下，SQLite 完全可以支撐一個小型分布式協作狀態機。

### 1.2 Message-based task queue 的簡單實現

`messages` 表本質上就是一個很輕量的 task queue。

它沒有 RabbitMQ/Kafka 那種完整 broker 能力，但對目前需求已經夠用：
- `submitted` 表示新任務
- `acknowledged` 表示接單成功
- `working` 表示執行中
- `completed / failed / cancelled` 表示結束

再加上 sender / receiver / payload / result / errors，這個 queue 已經足夠支持「一端派工，另一端接單，最後回報結果」的閉環。

教訓是：

> 很多時候先把狀態模型做對，比先上重型基礎設施更重要。

### 1.3 Watchdog + incident 的超時偵測模式

這套系統的另一個關鍵模式，是把「逾時」拆成兩層：
- `watchdog_jobs`：負責計時與狀態
- `incidents`：負責留下可檢查、可回溯的事件記錄

這樣的好處比單純 timeout flag 更大：
- 可以 distinguish 工作正常完成 vs 工作卡住
- 可以在 stalled 之後恢復並 resolve
- 可以保留操作痕跡
- 可以在未來接通知系統或 dashboard

這種模式值得保留，因為它天然地把「系統判斷」和「人類介入」分開了。

### 1.4 Timer + one-shot service 的輪詢方案

通知端目前採用的不是 daemon 常駐 while-loop，而是：
- `hermes-notify.timer`
- 觸發 `hermes-notify.service`
- service 單次執行 `notify_tasks.py`

這個模式很輕，對運維也友好：
- 每次執行是獨立 process
- 出錯後容易重啟
- systemd 原生可觀察
- 不需要自己管理 background loop lifecycle

這是一個很適合「低負載輪詢任務」的模式，也可套用到 watchdog scanner。

---

## 2. 分布式協調的啟示

### 2.1 無中央管理的 peer-to-peer 任務執行

目前系統沒有中央 controller，也沒有 API gateway。

它的協調方式其實很樸素：
- 所有節點看同一份共享狀態
- 誰是 sender、誰是 receiver，寫在 message 內
- 誰該做事，由 executor 自己在輪詢時決定

這讓整體架構保有很高的透明度：
- 不需要猜 broker 裡發生了什麼
- 不需要維護額外控制平面
- 所有狀態都能直接查 DB

但代價也清楚：
- 節點之間耦合在同一份共享儲存上
- 網路檔案系統品質會直接影響協調可靠性
- 擴展到多節點或高吞吐時會很快逼近 SQLite / shared FS 的天花板

### 2.2 狀態機 + 樂觀鎖的原子性保證

目前的原子性不是靠分散式鎖服務，而是靠：
- 明確狀態機
- 條件式 `UPDATE ... WHERE status = ?`
- 可選的 `expected_version`

這種方法簡單，但非常夠用。

例如搶單這件事，本質上就是：
- 大家都看到 `submitted`
- 但只有第一個成功把它改成 `acknowledged` 的執行者算搶到

這個模式的啟示是：

> 如果狀態轉移夠清楚，很多「分布式協調」問題可以轉化成單行 SQL 的條件更新問題。

### 2.3 共享文件系統的利弊

整套系統暗示了一個部署前提：多端共用同一份 DB 檔案，或至少能透過 Samba/網路共享去讀寫它。

這個選擇的優點：
- 快速
- 直觀
- 容易部署原型
- 沒有額外 server dependency

缺點同樣直接：
- 路徑規劃一亂，整個系統會亂
- 主機本地路徑、共享掛載路徑、文檔示例路徑很容易分裂
- 檔案鎖與網路檔案系統行為要特別小心

本案中最明顯的教訓就是 DB 路徑分裂：
- repo local `agent-mesh.db`
- `/home/vboxuser/...`
- `/srv/samba/hermes-audit/...`

一旦共享儲存成為協調核心，**路徑就是系統設計的一部分**，不能只當成部署細節。

---

## 3. 開發經驗

### 3.1 `sys.path` 管理的陷阱

倉庫目前同時存在兩種匯入風格：
- 新寫法：先把 `src/` 加進 `sys.path`，再 `from watchdog.watchdog_db import ...`
- 舊寫法：直接 `from watchdog_db import *`

這說明專案在演進過程中，模組位置改過，但舊腳本沒有完全一起收斂。

教訓很簡單：

> 只要專案不是標準安裝型套件，`sys.path` 問題早晚會浮上來，而且最常先炸在運維腳本上。

這件事值得在下一輪整理時優先處理，因為它會同時影響：
- 可攜性
- 文檔正確性
- 新人上手成本
- 自動化部署穩定性

### 3.2 DB 路徑硬編碼 vs 相對路徑的取捨

目前可以看到三種心態並存：
- 用 repo 相對路徑，方便本機開發
- 用 `/home/vboxuser/...`，方便某一台主機直接跑
- 用 `/srv/samba/hermes-audit/...`，方便共享部署

三種都各自合理，但如果同時出現在同一個 repo，就會讓系統語義模糊掉：
- 「預設 DB」到底是本機測試 DB？
- 還是主機正式 DB？
- 還是共享掛載 DB？

經驗是：

> 在單機原型階段，相對路徑很方便；但一旦進入跨機共享階段，應盡快定義唯一 canonical DB path，其他都改成 override，而不是再讓多種預設值並存。

### 3.3 文件與代碼的版本控制

這個專案非常典型地展示了另一個現象：

> 代碼的真實狀態，常常比架構文檔更晚被同步回來。

舊的 `ARCHITECTURE.md`、`architecture.md`、若干 guide 裡面混有：
- 理想態描述
- 中間態描述
- 已過時的操作方式

這不代表文檔沒有價值，而是提醒我們：
- 文檔也要有「現況版」與「願景版」之分
- 不然讀的人會把未完成部署誤認成已交付功能

### 3.4 systemd service 設計與實現

目前通知層已經展示了不錯的 service/timer pattern，但 executor 層與 watchdog 層沒有收尾。

這代表設計上其實已經知道要往哪裡走，只是還沒全部交付成可裝的 unit files。

重要的開發經驗是：
- service 化不是附屬工作，而是產品化的一部分
- 「可以手動跑」和「能被 operator 穩定操作」是兩個成熟度
- systemd 單元檔、重啟策略、工作目錄、日誌輸出、DB 路徑，都是架構的一部分

---

## 4. 未來改進方向

### 4.1 從 SQLite 升級到網路 DB（PostgreSQL）

當前設計在原型和小規模部署下成立，但若要提升可靠性與可擴展性，最直接的方向就是把共享 DB 從檔案升級為網路資料庫。

例如 PostgreSQL 可帶來：
- 更穩定的多端並發寫入
- 更清楚的連線與權限管理
- 不必依賴共享檔案系統語義
- 更容易接 dashboard / analytics / API

不過，這應該是**在保留現有狀態機與資料模型前提下**升級，而不是重做整個系統。

### 4.2 從 file-based 共享升級到 RPC（gRPC）

第二個自然升級方向，是把「大家都直接寫 DB」改成「透過 RPC 協調」。

例如：
- initiator 呼叫 coordinator / executor API
- executor 透過 gRPC 回報 heartbeat / progress / result
- watchdog 變成 server-side background worker

這樣的好處是：
- 把共享檔案系統依賴拿掉
- 可以更細緻地做驗證、授權、重試與流控
- 更適合未來多機、多角色、多工作類型的擴張

### 4.3 Executor 的模擬工作邏輯擴展為插件系統

目前 `do_work()` 仍偏示意：
- 收到 `collection` 做一種模擬回應
- 收到 `processing` 做另一種模擬回應
- `verification` 同理

這已經足夠證明狀態機沒問題，但如果要變成真正可擴展的協作系統，就應該讓它長成：
- handler registry
- plugin interface
- per-task-type executor
- schema-validated payload/result

也就是說，下一步不是重寫 executor loop，而是**保留 loop，把 work handler 抽換掉**。

---

## 5. 最重要的總結

Hermes Audit System 目前最大的收穫，不只是做出了一套雙 Agent 原型，而是把幾件事用很低成本驗證清楚了：

1. 共享 SQLite 可以支撐小型協作狀態機
2. watchdog + incident 是實用的 timeout 模式
3. polling 雖然不華麗，但在 systemd/timer 輔助下非常務實
4. 真正的困難常常不是核心邏輯，而是部署收斂、路徑統一、文檔同步

如果把這些教訓吸收好，下一輪不管是繼續留在 SQLite，還是升級到 PostgreSQL / gRPC，都會輕鬆很多。

換句話說：

> 這個專案目前最值得學的，不只是它做對了什麼，還包括它在哪些地方提醒了我們：
> **架構、部署、路徑、文檔，最後一定要收斂成同一個真相。**
