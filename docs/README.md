# 📚 Hermes Audit System 文檔中心

> 完整的項目文檔、部署指南、架構設計和常見問題解答

---

## 🏗️ 架構設計（`architecture/`）

### 理想設計與當前狀態

| 文件 | 內容 |
|------|------|
| [`ARCHITECTURE.md`](architecture/ARCHITECTURE.md) | **雙 Agent 協同架構設計** — 完整的系統架構、角色互換、watchdog 機制、資料庫 schema |
| [`ARCHITECTURE_CURRENT.md`](architecture/ARCHITECTURE_CURRENT.md) | **當前實際架構**（2026-08-20）— 系統現狀、已開啟功能、與理想設計的差距 |

---

## 📖 部署指南（`guides/`）

### 主機端（Linux VirtualBox）

| 文件 | 內容 | 適合人 |
|------|------|--------|
| [`HOST_GUIDE.md`](guides/HOST_GUIDE.md) | **主機部署指南** — 完整安裝、執行方式、角色選擇、Cronjob 設置、監控故障排查 | 主機管理員 |
| [`HOST_EXECUTOR_GUIDE.md`](guides/HOST_EXECUTOR_GUIDE.md) | **主機執行端操作細節** — 前置條件、運行步驟、預期輸出、故障排查 | 主機開發者 |

### 蝦米端（Windows 筆電）

| 文件 | 內容 | 適合人 |
|------|------|--------|
| [`SHRIMP_GUIDE.md`](guides/SHRIMP_GUIDE.md) | **蝦米完整部署指南** — 安裝、執行方式、角色選擇、網路連接、監控故障排查 | 蝦米用戶 |
| [`SHRIMP_QUICK_START.md`](guides/SHRIMP_QUICK_START.md) | **蝦米 5 分鐘快速上線** — 環境準備、三種運行方式、常見問題速解 | 急著上手的人 |
| [`SHRIMP_EXECUTOR_TEST.md`](guides/SHRIMP_EXECUTOR_TEST.md) | **蝦米測試說明** — 快速開始、完整流程、常見問題 | 蝦米測試員 |

### 通用指南

| 文件 | 內容 | 適合人 |
|------|------|--------|
| [`ROLE_SWAP_GUIDE.md`](guides/ROLE_SWAP_GUIDE.md) | **角色互換指南** — 為什麼可以互換、快速互換方法、實際案例、互換注意事項 | 想嘗試角色互換的人 |

---

## 📚 經驗與參考（`learning/`）

| 文件 | 內容 | 用途 |
|------|------|------|
| [`AGENT_QUICK_REFERENCE.md`](learning/AGENT_QUICK_REFERENCE.md) | **Agent 快速參考** — 系統架構速查、常見改動場景、測試檔案、已知陷阱、故障排查速查 | 日常維護速查表 |
| [`LESSONS_LEARNED.md`](learning/LESSONS_LEARNED.md) | **部署經驗教訓** — 部署過程中遇到的問題、解決方法、系統設計觀察、文件編寫建議 | 了解系統進化史 |

---

## 🗂️ 文檔結構

```
docs/
├── README.md                           ← 你在這裡
│
├── architecture/
│   ├── ARCHITECTURE.md                 ← 理想架構
│   └── ARCHITECTURE_CURRENT.md         ← 當前狀態
│
├── guides/
│   ├── HOST_GUIDE.md                   ← 主機完整指南
│   ├── HOST_EXECUTOR_GUIDE.md          ← 主機執行端
│   ├── SHRIMP_GUIDE.md                 ← 蝦米完整指南
│   ├── SHRIMP_QUICK_START.md           ← 蝦米快速上線
│   ├── SHRIMP_EXECUTOR_TEST.md         ← 蝦米測試
│   └── ROLE_SWAP_GUIDE.md              ← 角色互換
│
└── learning/
    ├── AGENT_QUICK_REFERENCE.md        ← 速查表
    └── LESSONS_LEARNED.md              ← 經驗教訓
```

---

## 🚀 快速導航

### 我想...

**...部署系統**
- 主機？👉 [`HOST_GUIDE.md`](guides/HOST_GUIDE.md)
- 蝦米？👉 [`SHRIMP_QUICK_START.md`](guides/SHRIMP_QUICK_START.md)

**...了解架構**
- 理想設計？👉 [`ARCHITECTURE.md`](architecture/ARCHITECTURE.md)
- 當前狀態？👉 [`ARCHITECTURE_CURRENT.md`](architecture/ARCHITECTURE_CURRENT.md)

**...快速查詢**
- 日常維護？👉 [`AGENT_QUICK_REFERENCE.md`](learning/AGENT_QUICK_REFERENCE.md)
- 故障排查？👉 [`HOST_GUIDE.md`](guides/HOST_GUIDE.md) 或 [`SHRIMP_GUIDE.md`](guides/SHRIMP_GUIDE.md) 的故障排查章節

**...試試新功能**
- 角色互換？👉 [`ROLE_SWAP_GUIDE.md`](guides/ROLE_SWAP_GUIDE.md)
- 蝦米三種模式？👉 [`SHRIMP_QUICK_START.md`](guides/SHRIMP_QUICK_START.md)#三種運行方式

**...了解經驗**
- 部署過程中學到什麼？👉 [`LESSONS_LEARNED.md`](learning/LESSONS_LEARNED.md)

---

## 📋 文檔快速索引

### 按主題

| 主題 | 相關文件 |
|------|----------|
| **安裝部署** | HOST_GUIDE.md · SHRIMP_GUIDE.md · SHRIMP_QUICK_START.md |
| **日常運維** | AGENT_QUICK_REFERENCE.md · HOST_GUIDE.md（監控故障排查）|
| **架構理解** | ARCHITECTURE.md · ARCHITECTURE_CURRENT.md |
| **故障排查** | 各指南的「故障排查」章節 |
| **角色互換** | ROLE_SWAP_GUIDE.md · test_scenario_swapped.py |
| **測試驗證** | SHRIMP_EXECUTOR_TEST.md · test_scenario.py |

### 按角色

| 角色 | 必讀文件 | 參考文件 |
|------|---------|----------|
| **主機管理員** | HOST_GUIDE.md | ARCHITECTURE.md · AGENT_QUICK_REFERENCE.md |
| **蝦米用戶** | SHRIMP_QUICK_START.md | SHRIMP_GUIDE.md · ROLE_SWAP_GUIDE.md |
| **系統設計師** | ARCHITECTURE.md | ARCHITECTURE_CURRENT.md · LESSONS_LEARNED.md |
| **開發/維護** | AGENT_QUICK_REFERENCE.md | 所有指南 |

---

## ✅ 使用建議

1. **第一次接觸**：先讀 `README.md`（根目錄）了解項目概況
2. **快速上手**：選對角色，讀對應的快速上線指南
3. **深入理解**：讀 ARCHITECTURE.md 了解設計理念
4. **日常維護**：收藏 AGENT_QUICK_REFERENCE.md 作為速查表
5. **遇到問題**：查 AGENT_QUICK_REFERENCE.md 的「故障排查」或對應指南的章節

---

**最後更新**: 2026-08-24  
**倉庫**: https://github.com/shiesam/hermes-audit-system
