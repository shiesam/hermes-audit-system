# projectbrief.md — Hermes 的身份與使命

> 這份檔案只寫「不變的原則」。任何跟系統操作細節有關的東西都不該出現在這裡 — 那些屬於 `techContext.md` 或既有規範文件。

## 身份

Hermes 是一套**雙 Agent 協同審圖系統**：主機（Linux）與蝦米（Windows）透過共享 SQLite（`agent-mesh.db`）協作執行工程圖說審查任務。兩端角色不固化，由 `sender`/`receiver` 決定，詳見 `ARCHITECTURE.md`。

## 使命（不變）

1. **審圖決策必須有依據**：任何審查結論都必須能指出對應的 `auditBasis.md` 條目，不可憑空判斷。
2. **不能悄悄卡住**：任何任務進入 stalled 狀態都必須被 watchdog 偵測並產生 incident，不能無聲無息地消失。
3. **角色互換是設計原則，不是例外**：任何一端都可能是發起端也可能是執行端，不可寫死假設。
4. **記憶不可遺失，但也不可重複**：規範文件寫過的事，Agent 不可再摸索一次；Memory Bank 只補規範沒寫的東西（見 `memory-bank/README.md`）。

## 這份文件不管的事（去別的地方找）

| 想找什麼 | 去哪裡 |
|---|---|
| 系統怎麼運作 | `systemPatterns.md` → `ARCHITECTURE.md` |
| 審圖法規/檢查清單 | `auditBasis.md` |
| 工具/環境/限制 | `techContext.md` |
| 現在卡在哪 | `activeContext.md` |
| 之前學到什麼教訓 | `progress.md` → `docs/LESSONS_LEARNED.md` |
