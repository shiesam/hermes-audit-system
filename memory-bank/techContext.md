# techContext.md — 工具、環境、限制

> 只放「Agent 需要知道才能動手」的環境事實 + 連結，完整操作步驟一律點進連結看。

## 環境速覽（完整見 `ARCHITECTURE.md` §2、§3，最新現況見 `docs/ARCHITECTURE_CURRENT.md`）

| 項目 | 內容 |
|---|---|
| 主機 | Linux VirtualBox, 192.168.0.68 |
| 蝦米 | Windows 11 筆電 |
| 共享層 | `agent-mesh.db`（SQLite, WAL mode），Samba 共享 `//192.168.0.68/hermes-audit` |
| 常駐服務 | `hermes-executor.service`（5秒 poll）、`hermes-notify.timer`（2秒）、`hermes-watchdog.timer`（30秒）— 詳見 `docs/AGENT_QUICK_REFERENCE.md` §1 |

## 工具/檔案速查（不要重寫，直接跳轉）

- 常見改動場景（新增 task_type、改輪詢間隔、改 DB 路徑…）→ `docs/AGENT_QUICK_REFERENCE.md` §2
- 已知陷阱（systemd `%h`、sys.path、watchdog Type 選擇、CLI 參數順序…）→ `docs/AGENT_QUICK_REFERENCE.md` §4，**動手前必看，不要重踩**
- 故障排查流程 → `docs/AGENT_QUICK_REFERENCE.md` §5
- 檔案位置總表 → `docs/AGENT_QUICK_REFERENCE.md` §6
- 部署經驗教訓（更詳細的來龍去脈）→ `docs/LESSONS_LEARNED.md`

## 限制（不變，Agent 必須遵守）

1. **DB 路徑一旦改動，必須同步改所有引用檔案**（見已知陷阱 4.3），否則 Agent 之間會讀到不同的 DB。
2. **watchdog 是 oneshot，不可用常駐型 systemd Type**（見已知陷阱 4.5）。
3. **改 systemd 設定後必須 `daemon-reload` + `restart`**，不會自動生效。
4. **審圖判斷不算工具限制範圍**，那是 `auditBasis.md` 的事，不要混在這裡。

## 更新規則

若發現本文件連結的規範文件已經過時（例如檔案搬家、服務改名），**先去更新規範文件本身**（`docs/AGENT_QUICK_REFERENCE.md` 等），再回來確認本文件的連結還有效，不要在這裡重寫一份新的說明。
