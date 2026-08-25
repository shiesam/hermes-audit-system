# Core Memory Bank — 使用規則

> 這是 Hermes 的「磁芯」：Agent 每次啟動任務前必須先讀這七份檔案，再決定要不要去翻其他文件。

## 唯一鐵律：不重複、只連結

**這個資料夾裡的每一份檔案，都不可以複製貼上其他文件（ARCHITECTURE.md / HOST_GUIDE.md / SHRIMP_GUIDE.md / docs/learning/* 等）裡已經寫好的內容。**

- 已經有規範寫死的事（例如：DB 路徑、systemd 型別選擇、CLI 參數順序），只能用一行「連結 + 一句話重點」帶過，細節一律用 `詳見 <文件>` 指回原文件。
- Memory Bank 只記錄三種東西：
  1. **不會變的原則**（projectbrief / systemPatterns 的決策模式）
  2. **目前沒有寫在任何規範文件裡的東西**（auditBasis 的審圖依據、productContext 的痛點分析）
  3. **會變動的狀態**（activeContext 現在卡在哪、progress 學到什麼）

## 每次任務開始前的檢查順序（Agent 必須照做）

1. 讀 `projectbrief.md` — 確認身分與使命沒有變。
2. 讀 `activeContext.md` — 看現在卡在哪、上次決定了什麼，**不要重新摸索已經決定過的事**。
3. 若任務跟審圖決策有關 → 讀 `auditBasis.md`，**這是唯一依據，不可自行猜測法規**。
4. 若任務跟系統操作/協作有關 → 讀 `systemPatterns.md` + `techContext.md`，若裡面連結到 `AGENT_QUICK_REFERENCE.md` 或 `LESSONS_LEARNED.md`，**必須點進去看完整內容**，不要因為 Memory Bank 只寫一行摘要就跳過。
5. 任務做完後 → 更新 `progress.md`（做了什麼、學到什麼）與 `activeContext.md`（現在的狀態），如果本次踩到規範文件沒寫的坑，**新增到規範文件本身**（例如 `docs/learning/LESSONS_LEARNED.md` 或 `docs/AGENT_QUICK_REFERENCE.md`），而不是留在 Memory Bank 裡重複記一次。

## 防止「每次都像第一次」的具體規則

- **禁止**：在 `activeContext.md` 或 `progress.md` 裡重新寫一遍「watchdog 要用 oneshot + timer」「DB 路徑在哪」這類已經是規範的事 — 這些屬於 `techContext.md` 連結出去的範圍，一旦寫進規範文件，Memory Bank 只保留連結。
- **禁止**：每次任務都重新「發現」同一個已知陷阱（見 `docs/AGENT_QUICK_REFERENCE.md` §4、`docs/LESSONS_LEARNED.md`）。Agent 必须先查表，查到才能算「新問題」。
- **要求**：`activeContext.md` 只保留「現在」這一份快照，舊的進度移到 `progress.md` 的時間軸，不要讓 activeContext 越滾越大變成第二個規範文件。
