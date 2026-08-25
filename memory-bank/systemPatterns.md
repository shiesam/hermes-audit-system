# systemPatterns.md — 工作流程、決策模式、跨 Agent 協作

> 這裡只放「模式與原則摘要 + 連結」，完整細節一律點進連結看，不在這裡複製。

## 訊息/任務流程（完整定義見 `ARCHITECTURE.md` §5、`docs/AGENT_QUICK_REFERENCE.md` §1）

狀態機：`submitted → acknowledged → working → completed / failed / cancelled`（卡住可回 `input-required`）。

**Agent 決策模式**：
1. 收到 `receiver=自己` 的 `submitted` 訊息 → 先 `acknowledged`，再 `working`。
2. 若任務屬於審圖類型 → 判斷前必須先查 `auditBasis.md`，找不到依據就標記 `input-required`，不可自行推斷法規。
3. 完成 → `completed` 並附 `result`；失敗 → `failed` 並附 `errors`。
4. 任何卡住 > threshold → 由 watchdog 自動產生 incident，不需要 Agent 自己判斷「要不要通報」。

## 跨 Agent 協作原則

- 兩個 Agent **不直接通訊**，只透過共享 DB 的 `messages` / `watchdog_jobs` / `incidents` 表協作。細節：`ARCHITECTURE.md` §3、§7。
- 角色不固化：`ROLE_SWAP_GUIDE.md`。
- Watchdog 是唯一的「卡住偵測」機制，運作細節見 `ARCHITECTURE.md` §6、`docs/AGENT_QUICK_REFERENCE.md` §2.4。

## 決策前必查清單（避免每次重新摸索）

在動手改系統行為 / 執行任務前，Agent 應依序確認：

1. 這個場景在 `docs/AGENT_QUICK_REFERENCE.md` §2（常見改動場景）或 §4（已知陷阱）有沒有先例？
2. 這是不是审图判断？是的話，`auditBasis.md` 有沒有對應條目？沒有 → 停下來，標記 `input-required`，不要臆測。
3. 這件事上次是不是做過、卡過？查 `activeContext.md` 和 `progress.md` 的歷史記錄，不要重複踩坑。

## 本文件不管的事

| 想找什麼 | 去哪裡 |
|---|---|
| 系統元件/服務清單、DB schema | `techContext.md` → `ARCHITECTURE.md` §7 |
| 已知陷阱/故障排查 | `docs/AGENT_QUICK_REFERENCE.md` §4、§5 |
| 部署經驗教訓 | `docs/LESSONS_LEARNED.md` |
