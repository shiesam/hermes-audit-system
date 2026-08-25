# techContext.md — 工具、環境、限制

> 對應 V6.0 §1-2 環境與硬體資產地圖。只放「Agent 需要知道才能動手」的環境事實 + 連結，完整操作步驟一律點進連結看。

## A. 系統伺服端環境（完整見 `ARCHITECTURE.md` §2、§3，最新現況見 `docs/ARCHITECTURE_CURRENT.md`）

| 項目 | 內容 |
|---|---|
| 主機 | Linux VirtualBox, 192.168.0.68 |
| 蝦米 | Windows 11 筆電 |
| 共享層 | `agent-mesh.db`（SQLite, WAL mode），Samba 共享 `//192.168.0.68/hermes-audit` |
| 常駐服務 | `hermes-executor.service`（5秒 poll）、`hermes-notify.timer`（2秒）、`hermes-watchdog.timer`（30秒）— 詳見 `docs/AGENT_QUICK_REFERENCE.md` §1 |

## B. 軟體與工具實體路徑（V6.0 §1-2-1）

> ⚠️ 待補：以下為佔位表格，尚未填入實際版本/路徑，Agent 動手前若發現本表未填，須先向人確認，不可自行假設路徑。

| 工具 | 版本 | 實體路徑 | 備註 |
|---|---|---|---|
| ODA File Converter | 待補 | 待補 | 用於 DWG/DXF 批次轉檔 |
| AutoCAD | 待補 | 待補 | |
| Python | 待補 | 待補 | |
| （其他工具） | | | |

## C. 磁碟與案場目錄結構（V6.0 §1-2-2）

> ⚠️ 待補：以下為佔位表格，尚未填入實際目錄，Agent 不可自行猜測案場資料夾位置。

| 位置類型 | 路徑 | 說明 |
|---|---|---|
| D:\ 槽 | 待補 | |
| 雲端資料夾 | 待補 | |
| 各案場圖說主目錄 | 待補 | 例如：星鑽、成德、仁發和、和館各自的圖說資料夾位置 |

## D. 工具/檔案速查（系統程式碼相關，不要重寫，直接跳轉）

- 常見改動場景（新增 task_type、改輪詢間隔、改 DB 路徑…）→ `docs/AGENT_QUICK_REFERENCE.md` §2
- 已知陷阱（systemd `%h`、sys.path、watchdog Type 選擇、CLI 參數順序…）→ `docs/AGENT_QUICK_REFERENCE.md` §4，**動手前必看，不要重踩**
- 故障排查流程 → `docs/AGENT_QUICK_REFERENCE.md` §5
- 檔案位置總表 → `docs/AGENT_QUICK_REFERENCE.md` §6
- 部署經驗教訓（更詳細的來龍去脈）→ `docs/LESSONS_LEARNED.md`

## 限制（不變，Agent 必須遵守）

1. **DB 路徑一旦改動，必須同步改所有引用檔案**（見已知陷阱 4.3），否則 Agent 之間會讀到不同的 DB。
2. **watchdog 是 oneshot，不可用常駐型 systemd Type**（見已知陷阱 4.5）。
3. **改 systemd 設定後必須 `daemon-reload` + `restart`**，不會自動生效。
4. **軟體/工具路徑（B、C 節）若未填寫，Agent 不可自行假設或猜測**，須標記待人補充。
5. **審圖判斷不算工具限制範圍**，那是 `domainKnowledge/regulations/` 的事，不要混在這裡。

## 更新規則

若發現本文件連結的規範文件已經過時（例如檔案搬家、服務改名），**先去更新規範文件本身**（`docs/AGENT_QUICK_REFERENCE.md` 等），再回來確認本文件的連結仍然有效。B、C 節的待補表格由人逐步補齊，不必一次填滿。
