# progress.md — 完成了什麼、學到了什麼、下次要避免的錯誤

> 這裡記時間軸與「教訓摘要 + 連結」。**完整的教訓內容寫進規範文件**（`docs/LESSONS_LEARNED.md`、`docs/AGENT_QUICK_REFERENCE.md` §4），這裡只放一行重點 + 連結，避免重複記兩份。

## 時間軸

### 2026-08-20 — 主機部署 + 常駐服務建立
- 完成：`hermes-executor.service`、`hermes-notify.timer`、`hermes-watchdog.timer` 上線，雙角色互換測試通過。
- 教訓摘要（完整見 `docs/LESSONS_LEARNED.md`）：
  - systemd 路徑別用 `%h`，寫絕對路徑。
  - `src/` 套件要在 import 前手動 `sys.path.insert`。
  - debug patch 用完要清掉，否則 service 重啟循環會誤導判斷。
  - DB 路徑搬動要全檔案掃描確認一致。
  - 一次性掃描腳本用 `oneshot + timer`，不要用 `simple` 常駐。
  - 子命令 CLI 的全域參數要放在子命令前面。

### 2026-08-25 — 建立 Core Memory Bank
- 完成：`memory-bank/` 七份核心檔案建立，明確規則「不重複規範文件內容，只連結 + 摘要」。
- 目的：解決「Agent 每次都像第一次做，重新摸索已知陷阱」的問題。
- 待驗證：下一次審圖任務執行時，Agent 是否真的先查 `activeContext.md` + `auditBasis.md`，而不是從頭摸索。

## 下次任務開始前，必須先查的「不要再犯」清單

1. 查 `docs/AGENT_QUICK_REFERENCE.md` §4（已知陷阱）—— 免得重踩 systemd / sys.path / DB 路徑的舊坑。
2. 查本文件的時間軸 —— 免得重新得出同樣的結論。
3. 若任務結束後發現一個「規範文件沒寫過的新坑」，**直接補進規範文件**（例如 `docs/AGENT_QUICK_REFERENCE.md` §4 新增一條），然後在這裡的時間軸只留一行摘要 + 連結，不要整段複製過來。
