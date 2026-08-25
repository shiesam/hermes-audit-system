# Hermes 最高憲法 — Core Memory Bank 使用規則

> 任何 Agent / AI 模組啟動時，必須先讀這份文件，再決定要讀哪些其他記憶檔案。

對應 V6.0 多 Agent 工務管理架構 §1-0：最高憲法與全域記憶庫。

## 鐵律

1. **絕不失憶**：每次任務卡住或中斷，必須寫入狀態快照（見 `activeContext.md`），
   下次接手直接讀快照，不必重讀整段對話歷史。
2. **不重複內容**：已經寫在其他規範檔案（法規、案場記錄、SOP）裡的東西，
   這裡只放「一句話摘要 + 連結」，不複製貼上完整內容。
3. **專業知識分類存放**：法規、案場記錄、報價、材料對照、圖層映射、設備資料、
   投資分析——每一類都是獨立資料夾，不混放。
4. **判斷沒依據就停下**：找不到對應規則/記錄時，不可自行猜測，
   標記為「需要人決定」，並寫進 `activeContext.md` 的待辦清單。

## 記憶庫地圖

| 類別 | 位置 | 對應 V6.0 章節 |
|---|---|---|
| 現在卡在哪、下一步做什麼 | `activeContext.md` | 1-1-2 狀態快照 |
| 歷史執行記錄 | `progress.md` | 1-1-1 執行紀錄 |
| 環境/工具/硬體路徑 | `techContext.md` | 1-2 環境與硬體資產地圖 |
| 跨平台通訊規則 | `commSOP.md` | 1-3 跨平台通訊與遠端操作鏈 |
| 多 Agent 協作方式 | `systemPatterns.md` | 1-0-1、1-1 |
| 工程安全紅線（占位，待補） | `guardrails/` | 1-4 工程執行邊界與安全 SOP |
| 法規、案場、報價、材料、圖層、設備、投資 | `domainKnowledge/` 底下各資料夾 | 1-5 專業知識與實務數據庫 |

## 建置進度（逐份完成，不求一次到位）

- [x] `README.md`（本檔，1-0）
- [ ] `activeContext.md`（1-1-2）
- [ ] `progress.md`（1-1-1）
- [ ] `techContext.md`（1-2）
- [ ] `commSOP.md`（1-3）
- [ ] `systemPatterns.md`（1-0-1）
- [ ] `guardrails/README.md`（1-4，占位）
- [ ] `domainKnowledge/regulations/README.md`（1-5-1-1）
- [ ] `domainKnowledge/projectRecords/README.md`（1-5-1-2）
- [ ] `domainKnowledge/costEstimation/README.md`（1-5-1-3）
- [ ] `domainKnowledge/materialsGlossary/README.md`（1-5-1-4）
- [ ] `domainKnowledge/layerMapping/README.md`（1-5-1-5）
- [ ] `domainKnowledge/equipmentData/README.md`（1-5-1-6）
- [ ] `domainKnowledge/investment/README.md`（1-5-2，預留）
