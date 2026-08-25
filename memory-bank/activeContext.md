# activeContext.md — 現在進行的工作、卡住的問題、需要的決定

> 這是唯一允許「常常改」的檔案。只保留**現在**這一份快照，舊狀態搬到 `progress.md` 的時間軸，不要讓這份越滾越大。

## 現在的狀態快照（2026-08-25）

- 系統目前只有基礎設施（訊息流轉、watchdog、雙角色互換）完成並驗證，見 `docs/ARCHITECTURE_CURRENT.md`。
- **尚未建立實際的審圖判斷邏輯**：`agent_executor.py` 的 `do_work()` 目前處理的是通用 task_type（如 `collection`），還沒有工程審圖專屬的判斷分支。
- Core Memory Bank（本資料夾）剛建立，尚未經過實戰驗證。

## 卡住的問題 / 需要的決定

| # | 問題 | 需要誰決定 | 狀態 |
|---|---|---|---|
| 1 | `auditBasis.md` 尚未填入任何實際法規/標準內容 | 你（提供審圖依據來源） | ⚠️ 阻塞審圖任務執行 |
| 2 | `productContext.md` 的痛點是推論草稿，未經確認 | 你 | ⚠️ 待確認 |
| 3 | `do_work()` 尚無審圖 task_type 分支 | 開發者 | 待規劃 |

## 下一步

1. 你補齊 `auditBasis.md` 的實際法規/檢查清單內容。
2. 確認/修正 `productContext.md` 的痛點描述。
3. 依 `auditBasis.md` 設計 `agent_executor.py` 的審圖 task_type 處理邏輯，並更新 `docs/AGENT_QUICK_REFERENCE.md` §2.1（新增 task_type 的標準做法）。

> 📌 規則提醒：任務做完後，把這份「現在」的快照換成新的現在，舊的移一筆到 `progress.md`；不要在這裡累積歷史。
