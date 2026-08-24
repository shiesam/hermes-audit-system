# 經驗教訓 — Hermes Audit System 主機部署（2026-08-20）

> 這次把 agent_executor.py 弄成 systemd 常駐時，遇過的事與學到的。

## 1. 部署流程的教訓

### 1.1 systemd service 檔案要寫對路徑

- 一開始寫的 service 檔用了 `%h` 展開，結果變成 `/root` 開頭，導致找不到 script。
- 解法：全部改用絕對路徑。`ExecStart=/usr/bin/python3 /home/vboxuser/hermes-audit-system/agent_executor.py ...`
- lesson: systemd 裡 `%h` 不一定是你想要的家目錄，尤其是 service 以 root 身份跑但想用某個一般使用者家目錄時。直接寫絕對路徑最安全。

### 1.2 Python 套件的 import 路徑很微妙

- 專案結構是 `/home/vboxuser/hermes-audit-system/src/watchdog/watchdog_db.py`。
- agent_executor.py 裡寫 `from watchdog.watchdog_db import ...`，但預設 sys.path 只有專案根目錄，不包含 `src/`。
- 結果：service 啟動時 `ModuleNotFoundError: No module named 'watchdog'`。
- 解法：在 agent_executor.py 裡早期加入：
  ```python
  import sys
  from pathlib import Path
  _SRC_DIR = Path(__file__).resolve().parent / "src"
  sys.path.insert(0, str(_SRC_DIR))
  ```
- 這樣 `from watchdog.watchdog_db import ...` 就找到 `src/watchdog/` 下的套件。
- 關鍵：這行要在 import 之前執行。不能靠 systemd 的 Environment=PYTHONPATH 來補。

### 1.3 debug patch 很容易留下爪痕

- 中間為了看函式庫路徑，臨時 patch 了 agent_executor.py 加入 `logging.info(...)`，但忘了檢查是不是已經 `import logging`。
- 結果：service 重啟 50+ 次，每次都噴 `NameError: name 'logging' is not defined`。
- 解法：把 debug patch 刪掉，恢復乾淨的 `if __name__ == "__main__": main()`。
- lesson: debug 改動要記得在真的解決問題後清掉；否則服務在重啟循環裡面會給你誤導你以為還有别的問題。

### 1.4 DB 路徑 Consistency

- 一開始 DB 在 `/home/vboxuser/hermes-audit-system/agent-mesh.db`。
- 後來決定搬到 `/srv/samba/hermes-audit/agent-mesh.db`（因為蝦米要透過 Samba 存取）。
- 把所有 script 的預設 DB 路徑都改過：agent_executor.py, agent_initiator.py, test_host_executor.py, test_shrimp_initiator.py, test_progress_tracking_integration.py, notify_tasks.py, shrimp_agent.py, 以及 systemd service 檔案裡的 `--db` 參數。
- 然後把舊 DB 刪了。
- lesson: DB 路徑改了要確保每個用到它的檔案都改，包括 service 檔案。否則 executor 會讀錯位 DB，看不到蝦米寫的消息。

### 1.5 watchdog 服務的型別選擇

- `watchdog_db.py run` 是**一次性掃描**（執行完就退出，沒有內部循環）。
- 一開始想用 `Type=simple` 常駐，但會導致 service 跑完就退出，又立刻重啟，形成不必要的 restart loop。
- 正確做法：`Type=oneshot` + `systemd timer`。service 每次被 timer 觸發時執行一次掃描，執行完畢 status 變成 inactive (dead)，這是正常的。
- timer 設定：`OnBootSec=10sec`, `OnUnitActiveSec=30sec`，每 30 秒掃一次。
- lesson: 判斷腳本是「一次性工作」還是「持續運行的 daemon」，選對 systemd Type。一次性工作用 oneshot + timer，daemon 用 simple/notify，並確保程式裡有無限循環。

### 1.6 CLI 參數順序問題

- `watchdog_db.py` 的 `--db` 選項是全域的（在 `run` 子命令之前），執行時要寫成 `watchdog_db.py --db <路徑> run --interval 30`。
- 若寫成 `watchdog_db.py run --db <路徑>`，argparse 會認為 `--db` 是 `run` 子命令的參數而報錯（unrecognized arguments）。
- lesson: 子命令架構的 CLI，全域選項要放在子命令名稱之前。systemd service 的 ExecStart 也要照這個順序寫。

## 2. 系統設計層面的觀察

### 2.1 現在的狀態是「執行端有常駐，通知有常駐，watchdog 有開」

- hermes-executor.service: 活著，每 5 秒 poll DB，會自動接 `receiver=host` 的任務。
- hermes-notify.timer: 活著，每 2 秒查 DB，寫日志。
- hermes-watchdog.timer + hermes-watchdog.service (oneshot): 每 30 秒掃一次，偵測卡住的任務，產生/解決 incident。

這三個組成了基本的協作基礎設施。

### 2.2 現有的消息流是單向的

- 目前 DB 裡只有一條消息 m-4efbf2f1，是 shrimp 發給 host 的，狀態 completed。
- 沒有經歷過 watchdog arm → heartbeat → stalled → incident 這條完整流程。
- 如果要驗證 watchdog 機制，得建立一個任務，讓 executor 接，然後讓它故意卡住（或讓 watchdog 掃描跑起來），看看會不會產生 incident。

### 2.3 Samba 共享 + SQLite 的實用性

- SQLite 在網路檔案系統（Samba/NFS）上讀寫要小心。我們目前是 hermes:hermes 755/664，vboxuser 透過 hermes 群組存取。
- 如果兩個 agent 真的同時寫，同一時間寫入同一個 DB 檔案可能會有 lock 問題。
- 目前處理方式是：executor 每 5 秒輪詢，shrimp 寫完就結束。沒有常態的並發寫入，所以還 okay。
- 如果未來真的有兩個 agent 同時寫，可能要考慮别的策略（例如 SQLite WAL mode，或改用别的 DB）。

## 3. 架構文件該怎麼寫

### 3.1 分成「理想設計」和「當前實際狀態」兩份

- ARCHITECTURE.md（原本的）寫的是理想設計：雙向角色互換、watchdog 完整流轉、cronjob scanner、 Incident 分級……
- 實際跑起來的系統現在有 executor 常駐 + notify timer + watchdog timer/service。
- 建議：保留 ARCHITECTURE.md 作為「設計目標」，另外寫一份 ARCHITECTURE_CURRENT.md（或在同一個檔案裡加「現狀」一節），說明目前實際跑起來的樣子。

### 3.2 文件裡的指令要確保路徑正確

- HOST_GUIDE.md 裡寫著 `python3 -c "from watchdog_db import init_db; init_db()"` 來初始化 DB。
  - 這在 DB 改路徑以後不准確：init_db 會建立在當前目錄（或設定的路徑），但現在的 DB 在 `/srv/samba/...`。
  - 建議更新成明確的路徑，或說明「初始化後要把 DB 搬到 Samba 目錄」。

### 3.3 角色互換雖然寫進了文件，但尚未真的測過

- test_scenario_swapped.py 存在，理論上可以跑。
- 但實際部署時主機只跑了 executor（host 角色），蝦米發了一個任務。
- 如果要真的驗證角色互換，需要讓主機當發起端、蝦米當執行端，且兩邊都常駐。

## 4. 小結

幾件事值得記一下：

1. **systemd 服務的路徑別用 %h，直接寫絕對路徑。**
2. **Python 專案有 src/ 套件目錄時，記得在入口檔案裡 insert sys.path。**
3. **debug patch 要清掉，不然 service 重啟循環會誤導你。**
4. **DB 路徑一旦改了，掃全部檔案確認沒有舊路徑殘留。**
5. **現在的系統有 executor 常駐 + notify timer + watchdog timer/service（每 30 秒掃一次）。文件要寫清楚這點。**
6. **現有消息流是單向的，沒有經歷過 watchdog arm/heartbeat/stalled/incident 流程。**
