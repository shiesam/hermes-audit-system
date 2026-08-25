# systemPatterns.md — 工作流程、決策模式、跨 Agent 協作

> 對應 V6.0 §1-0-1（多獨立 Agent 協作監聽）與 §1-1（執行紀錄與狀態快照的協作邏輯）。
> 這裡只放「模式與原則摘要 + 連結」，完整細節一律點進連結看，不在這裡複製。

## 多獨立 Agent 協作模式（V6.0 §1-0-1）

四個核心能力，缺一不可：

1. **發起端**：任何 Agent 都可建立任務（`create_message()`），寫入 `messages` 表。
2. **接收端**：任何 Agent 都可監聽屬於自己的任務（`receiver=自己`），依狀態機處理。
3. **進度追蹤**：透過 `watchdog_jobs` 表追蹤 idle 時間，卡住自動產生 `incidents`。
4. **主動執行 + 時時回覆操作者進度**：Agent 不是被動等待查詢，而是主動更新狀態，並透過 `commSOP.md` 的通訊鏈（如 LINE 推播）主動回報進度給操作者，不是等人來問才說。

## 訊息/任務流程（完整定義見 `ARCHITECTURE.md` §5、`docs/AGENT_QUICK_REFERENCE.md` §1）

狀態機：`submitted → acknowledged → working → completed / failed / cancelled`（卡住可回 `input-required`）。

**Agent 決策模式**：
1. 收到 `receiver=自己` 的 `submitted` 訊息 → 先 `acknowledged`，再 `working`。
2. 若任務屬於審圖類型 → 判斷前必須先查 `domainKnowledge/regulations/`，找不到依據就標記 `input-required`，不可自行推斷法規。
3. 完成 → `completed` 並附 `result`；失敗 → `failed` 並附 `errors`。
4. 任何卡住 > threshold → 由 watchdog 自動產生 incident，不需要 Agent 自己判斷「要不要通報」。

## 跨 Agent 協作原則

- 兩個 Agent **不直接通訊**，只透過共享 DB 的 `messages` / `watchdog_jobs` / `incidents` 表協作。細節：`ARCHITECTURE.md` §3、§7。
- 角色不固化：`ROLE_SWAP_GUIDE.md`。
- Watchdog 是唯一的「卡住偵測」機制，運作細節見 `ARCHITECTURE.md` §6、`docs/AGENT_QUICK_REFERENCE.md` §2.4。
- 通訊/推播/自我修復規則另見 `commSOP.md`（V6.0 §1-3）。

## 決策前必查清單（避免每次重新摸索）

在動手改系統行為 / 執行任務前，Agent 應依序確認：

1. 這個場景在 `docs/AGENT_QUICK_REFERENCE.md` §2（常見改動場景）或 §4（已知陷阱）有沒有先例？
2. 這是不是審圖判斷？是的話，`domainKnowledge/regulations/` 有沒有對應條目？沒有 → 停下來，標記 `input-required`，不要臆測。
3. 這件事上次是不是做過、卡過？查 `activeContext.md` 和 `progress.md` 的歷史記錄，不要重複踩坑。
4. 這是不是需要用到工具/硬體？先查 `techContext.md` 的環境速覽與待補表格，路徑不明就不要自行假設。

## 本文件不管的事

| 想找什麼 | 去哪裡 |
|---|---|
| 系統元件/服務清單、DB schema | `techContext.md` → `ARCHITECTURE.md` §7 |
| 已知陷阱/故障排查 | `docs/AGENT_QUICK_REFERENCE.md` §4、§5 |
| 部署經驗教訓 | `docs/LESSONS_LEARNED.md` |
| 跨平台通訊/推播/自我修復規則 | `commSOP.md` |
| 審圖依據、案場記錄、報價、材料、圖層、設備、投資資料 | `domainKnowledge/` 各子資料夾 |
| 工程執行邊界與安全 SOP | `guardrails/` |
