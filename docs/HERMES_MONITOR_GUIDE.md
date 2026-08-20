# Hermes 任務監控指南

## 架構

```
主機 (notify_tasks.py)
├─ HTTP Server :8888
│  ├─ GET /api/tasks   → JSON 任務列表
│  ├─ GET /health      → 健康檢查
│  └─ GET /metrics     → 請求統計
│
↓ HTTP polling（預設 2 秒一次）
│
Copilot Session (hermes_monitor.py)
├─ 偵測新任務
├─ 顯示狀態變化
└─ 通知任務完成
```

## 快速開始

### 1. 在主機上啟動監控服務

```bash
# 單次執行
python notify_tasks.py

# 持續輪詢（推薦）
python notify_tasks.py --loop --interval 2

# 自訂端口
python notify_tasks.py --loop --http-port 9000

# 停用 HTTP server（僅輸出日誌）
python notify_tasks.py --loop --no-http

# 啟用 GZIP 壓縮
python notify_tasks.py --loop --gzip
```

### 2. 在 Copilot session 中啟動監控

```bash
python hermes_monitor.py
```

### 3. 發送任務（Windows 側）

```bash
python shrimp_agent.py initiator --task-type collection --description "蒐集數據"
```

立即在 Copilot session 中看到實時通知！

---

## API 端點

### `GET /api/tasks`

返回當前所有活躍任務和最近完成任務。

```json
{
  "timestamp": "2026-08-20T10:38:47Z",
  "active_tasks": [
    {
      "msg_id": "m-6a5f9d2e",
      "task_type": "processing",
      "sender": "shrimp",
      "receiver": "host",
      "status": "working",
      "created_at": "2026-08-20T10:38:45Z",
      "updated_at": "2026-08-20T10:38:47Z",
      "elapsed": "2s"
    }
  ],
  "finalized_tasks": [
    {
      "msg_id": "m-5d4c8e2a",
      "task_type": "verification",
      "sender": "shrimp",
      "receiver": "host",
      "status": "completed",
      "created_at": "2026-08-20T10:37:00Z",
      "updated_at": "2026-08-20T10:37:45Z",
      "elapsed": "45s"
    }
  ]
}
```

### `GET /health`

健康檢查端點。

```json
{
  "status": "ok",
  "uptime_seconds": 120.5,
  "active_task_count": 2
}
```

### `GET /metrics`

請求統計。

```json
{
  "request_count": 47,
  "avg_response_time_ms": 0.823,
  "uptime_seconds": 120.5
}
```

---

## 預期輸出

```
🔌 連接 Hermes 任務監控服務
📡 監聽: http://localhost:8888/api/tasks
按 Ctrl+C 停止

[10:38:47] 📬 新任務檢測！
┌────────────────────────────────┐
│ m-6a5f9d2e                     │
│ processing                     │
│ shrimp → host                  │
│ submitted                      │
└────────────────────────────────┘

[10:38:49] 👀 狀態變化
  m-6a5f9d2e: submitted → acknowledged (2s)

[10:38:55] ⏳ 狀態變化
  m-6a5f9d2e: acknowledged → working (8s)

[10:39:15] ✅ 任務完成
  m-6a5f9d2e: completed (30s)
```

---

## 進階選項

### hermes_monitor.py

| 選項 | 預設值 | 說明 |
|------|--------|------|
| `--url` | `http://localhost:8888` | notify_tasks.py HTTP server URL |
| `--interval` | `2.0` | 輪詢間隔（秒） |
| `--reconnect-delay` | `5.0` | 連接失敗後等待重連的時間（秒） |

```bash
# 連接到非預設端口
python hermes_monitor.py --url http://localhost:9000

# 加快輪詢速度
python hermes_monitor.py --interval 1

# 連接失敗時更快重試
python hermes_monitor.py --reconnect-delay 2
```

### notify_tasks.py

| 選項 | 預設值 | 說明 |
|------|--------|------|
| `--http-port` | `8888` | HTTP server 埠號 |
| `--no-http` | `false` | 停用 HTTP server |
| `--gzip` | `false` | 啟用 GZIP 壓縮 |
| `--loop` | `false` | 持續輪詢模式 |
| `--interval` | `2.0` | 輪詢間隔（秒） |
| `--db` | `agent-mesh.db` | SQLite 資料庫路徑 |
| `--receiver` | `host` | 任務接收方 |
| `--log-file` | `none` | 日誌輸出檔案 |

---

## 故障排查

### 無法連接到 HTTP server

1. 確認 `notify_tasks.py` 正在執行：
   ```bash
   curl http://localhost:8888/health
   ```

2. 確認端口沒有被占用：
   ```bash
   lsof -i :8888
   ```

3. 如果使用 systemd service，確認 service 已啟動：
   ```bash
   systemctl status hermes-notify
   ```

### 看不到任務更新

1. 確認 `notify_tasks.py` 用 `--loop` 模式執行：
   ```bash
   python notify_tasks.py --loop --interval 2
   ```

2. 直接查詢 API：
   ```bash
   curl -s http://localhost:8888/api/tasks | python -m json.tool
   ```

### systemd service 設定

如需在 systemd 中使用 HTTP server，確認 `hermes-notify.service` 包含正確的 `ExecStart`：

```ini
[Service]
ExecStart=/usr/bin/python3 /path/to/notify_tasks.py --loop --interval 2
```
