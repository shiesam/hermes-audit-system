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
| ~~工程安全紅線~~ | 暫不建立（見下方說明） | 1-4 工程執行邊界與安全 SOP |
| 法規 | `domainKnowledge/regulations/` | 1-5-1-1 |
| 案場記錄 | `domainKnowledge/projectRecords/` | 1-5-1-2 |
| 報價 | `domainKnowledge/costEstimation/` | 1-5-1-3 |
| 材料對照 | `domainKnowledge/materialsGlossary/` | 1-5-1-4 |
| ~~圖層映射~~ | 暫不建立（跳號保留） | 1-5-1-5 |
| 設備資料 | `domainKnowledge/equipmentData/` | 1-5-1-6 |
| ~~投資分析~~ | 暫不建立（跳號保留） | 1-5-2（預留） |

> 📌 **跳號保留的分類：1-4（工程執行邊界與安全 SOP）、1-5-1-5（圖層映射）、1-5-2（投資分析）。**
> 目前尚未想好內容，等之後有明確想法再回來建立對應資料夾，不先做空殼佔位。

## 記憶庫擴充原則

1. **新增分類 = 新增資料夾，不擠進既有檔案**：若未來出現一種新的專業知識（現有 `domainKnowledge/` 子資料夾都放不下），先新增獨立資料夾，並在本檔「記憶庫地圖」與「建置進度」補上一列，而不是硬塞進既有檔案。
2. **跳號保留是常態，不是例外**：某個代號（如 1-4、1-5-1-5、1-5-2）目前想不清楚要放什麼，允許先跳過、只留代號位置，不建空殼檔案。等有明確內容再回來建立。
3. **代號對照 V6.0 架構文件**：所有資料夾/檔案的章節代號都必須能對應回 V6.0 多 Agent 工務管理架構的原始編號，方便未來查證「這份文件對應原始規劃的哪一條」。
4. **先寫規則骨架，內容留白待補**：新建檔案時，優先把「這裡放什麼」「使用規則」「目前狀態」寫清楚，實際內容（法規條文、報價數字等）留給人逐步填入，不要求一次到位。
5. **擴充前先查有沒有現成位置**：新增內容前，先對照本檔「記憶庫地圖」表格，確認不是已經有地方放，避免重複造輪子。

## 建置進度（逐份完成，不求一次到位）

- [x] `README.md`（本檔，1-0）
- [x] `activeContext.md`（1-1-2）
- [x] `progress.md`（1-1-1）
- [x] `techContext.md`（1-2）
- [x] `commSOP.md`（1-3）
- [x] `systemPatterns.md`（1-0-1）
- [ ] ~~`guardrails/README.md`（1-4）~~ — 跳號保留，暫不建立
- [x] `domainKnowledge/regulations/README.md`（1-5-1-1）
- [x] `domainKnowledge/projectRecords/README.md`（1-5-1-2）
- [x] `domainKnowledge/costEstimation/README.md`（1-5-1-3）
- [x] `domainKnowledge/materialsGlossary/README.md`（1-5-1-4）
- [ ] ~~`domainKnowledge/layerMapping/README.md`（1-5-1-5）~~ — 跳號保留，暫不建立
- [x] `domainKnowledge/equipmentData/README.md`（1-5-1-6）
- [ ] ~~`domainKnowledge/investment/README.md`（1-5-2，預留）~~ — 跳號保留，暫不建立
