# 守不住開盤 V8 → XQ XS 自動交易腳本 — Playbook

> 給接手寫 XS 的 session 用。所有 V8 策略邏輯 + 已知 XS 語法 + 待驗證項目都在這。

---

## 0. 你的任務

把已在 Python backtest 驗證的「**守不住開盤 V8**」空方策略，翻譯成可在 XQ 自動交易中心執行的 XS 腳本。

最終目標：**模擬交易 → 真實上線**。我已寫了草稿（路徑見下），但 XS 語法只到「依官方教學能寫的」程度，需要你跟使用者協作完成 final 版。

---

## 1. 策略邏輯 (V8 上線版規格)

### 1.1 策略概念
「個股早盤 gap up 卻無法守住開盤高點 → 跌破回落 → 短空 → trail stop 鎖獲利 → 11:30 強平」

### 1.2 完整進場規則

```
盤前: 從 universe 篩出 gap up 0.5%~10% 候選股 (~30-50 檔)

對每檔候選股:
  09:00       第一筆 K = day_open
  09:00-09:35 累積 morning_high

  09:35-09:37 trigger detection:
    if (morning_high / day_open - 1) < 0.030 AND          # stock_aor < 3%
       (limit_price - morning_high)/morning_high >= 0.010 AND  # mh_to_limit ≥ 1%
       low <= morning_high * 0.9995:                       # 從 mh 回落 0.05%

      → 進場 SHORT @ morning_high * 0.9995
      → 同時掛初始停損: min(morning_high + 1 tick, limit_price - 1 tick)
```

### 1.3 Trail stop

```
進場後每 tick / 每 K:
  if low < running_low:
    running_low = low
    new_stop = running_low + 1 tick
    cancel 舊停損 + 重新掛 new_stop
```

### 1.4 出場
- Trail stop 觸發 (99% trades 這個 case)
- 11:30 強制市價平倉 (殘留部位)

### 1.5 限制
- N_MAX = 5（同時最多 5 檔部位）→ 在 XQ 自動交易中心設定
- 每檔部位金額 = 100 萬（小型股可能 0 張買不起，自動 skip）
- 排序選 top-5 by `rank_score = gap_pct / (stock_aor + 0.001)` → 看 XQ 自動交易中心是否能設「排序進場優先順序」，否則用「先觸發先進場」近似

### 1.6 重要參數一覽

| 參數 | 值 | 意義 |
|---|---|---|
| GAP_MIN | 0.005 | 開盤 gap up 至少 +0.5% |
| GAP_MAX | 0.10 | gap 上限 |
| STOCK_AOR_MAX | 0.030 | morning_high/day_open-1 < 3% |
| MH_TO_LIMIT_MIN | 0.010 | morning_high 距漲停 ≥ 1% |
| WAIT_MIN | 35 | 09:35 開始監看 |
| END_MIN | 37 | 09:37 截止 |
| ENTRY_BUFFER | 0.0005 | 從 mh 回落 0.05% trigger |
| STOP_TICKS | 1 | 停損 = mh + 1 tick |
| EXIT_TIME | 11:30 | 強平時間 |
| BUDGET | 5,000,000 | 同時暴露上限 |
| N_MAX | 5 | 同時部位數 |

---

## 2. V8 Backtest 績效（用來檢驗 XS 結果）

| 指標 | 值 |
|---|---|
| 訊號數 (3.5 年) | 30,333 |
| fills/day | 4.55 |
| CAGR | +116.6% |
| **Sharpe** | **29.28** |
| MaxDD | ~0% |
| WR | 99.9% |
| 月勝率 | 100% (42/42) |
| 漲停鎖死真實風險 | 0% |
| Walk-forward TEST Sharpe | 29.65 (TRAIN 29.10) |
| Slippage 0.05% 估計 | Sharpe ~28 |

XS 寫好後跑 XQ 模擬交易，比較跟 Python backtest 是否接近。

---

## 3. 已知 XS 語法 (從 XQ 官方教學整理)

### 3.1 確認的語法

```xs
// 變數宣告
input: GapMin(0.005);          // 可由 GUI 調整
var: MorningHigh(0);           // 內部變數

// 取得前一日收盤
PrevClose = CloseD(1);         // 1 = 前一日

// 部位管理 (核心!)
SetPosition(-1, MARKET);       // 進場 short, target = -1 張
SetPosition(0, addspread(close, +2));  // 平倉, target = 0
Position                       // 當前目標部位
Filled                         // 實際成交部位

// 條件判斷
condition1 = Close < 800;
if Position = 0 and Filled = 0 and condition1 then begin
    SetPosition(1, MARKET);
end;

// 警示
Alert("ENTRY " + Symbol + " @" + Text(price));
```

### 3.2 推測但需驗證的語法

```xs
// 賣空 (有獨立函數 Short, 但簽名不確定)
Short(qty, price, "Limit");    // ⚠️ 不確定參數順序
// 或:
SetPosition(-qty, price);      // 用 SetPosition target 負值

// 平倉 short
Cover(qty, price);              // ⚠️ 不確定
// 或:
SetPosition(0, price);

// 時間 (待驗證 HHMM 還是 HHMMSS)
if Time = 935 then ...          // 若 HHMM = 935 表示 09:35
if Time = 93500 then ...        // 若 HHMMSS

// 觸發停損
// XQ 沒看到 SetStopLoss / SetExitOnClose 範例
// 推測用 SetPosition 配合條件:
if Position = -1 and high >= cur_stop then SetPosition(0, cur_stop);
```

### 3.3 完全未知 (需要找)
- tick size 動態計算 (50元股 0.05, 500元股 0.5, 1000+元股 5.0)
- floor() / MinValue() / round() 是否內建
- Alert 的精確簽名 (用 + 接還是 , 接)
- 取得當日 open / high / low / close 的標準寫法

### 3.4 XS 官方資源

- 主教學: https://www.xq.com.tw/learning/xs-編輯器：交易腳本撰寫教學/
- 自動交易中心: https://www.xq.com.tw/learning/自動交易中心：自動交易中心功能介紹教學/
- 函數庫 (簡略): https://xshelp.xq.com.tw/XSHelp/

---

## 4. 目前已寫的檔案

### 4.1 Shioaji Python 框架（**權威 reference**）
```
D:\stock\tmf-bot\live\守不住開盤_live.py
```
完整 V8 邏輯的 Python 版，含 trail stop / 11:30 強平 / 多檔管理。
**XS 邏輯必須與此一致** — 出 bug 對照這份。

### 4.2 XS 草稿 (你的修改目標)
```
D:\stock\tmf-bot\live\XQ_守不住開盤_auto.xs       ← 主腳本 (進場+trail+強平)
D:\stock\tmf-bot\live\XQ_守不住開盤_選股.xs       ← 盤前選股
```

### 4.3 部署文檔
```
D:\stock\tmf-bot\live\README.md
```

### 4.4 完整策略報告
```
D:\stock\守不住開盤_策略報告.md
```
看 §16 (V8 升級) 與 TL;DR 的完整參數。

### 4.5 8 輪升級歷程 (背景)
```
C:\Users\USER\.claude\projects\D--stock\memory\project_守不住開盤_空策略.md
```

---

## 5. 待處理的關鍵問題 (按優先順序)

### P0 (必須解決才能上線)
1. **SetPosition 的 short 寫法**：是 `SetPosition(-qty, price)` 還是 `Short(qty, price, type)`？
2. **N_MAX=5 怎麼設定**：自動交易中心是否有「最大同時部位數」限制？
3. **Top-5 排序**：跨多檔股票進場時，能否按 rank_score 排序？或只能「先到先入」？

### P1 (影響真實 fill 品質)
4. **觸發 trigger 後下單延遲**：09:35-09:37 內，從 Low 觸發到 SetPosition 送出單要多久？太慢會 fill 在更糟價格。
5. **trail stop cancel-replace 速度**：每秒檢查 running_low + 動態調整 stop，XQ 能否承受？
6. **Tick size 動態計算函數**

### P2 (上線監控用)
7. **如何 log 每筆 fill**：給後續 reconciliation 用
8. **回測模擬模式**：XQ 自動交易中心是否支援 paper trade

---

## 6. 工作流程建議

1. **第一步：跑通模擬交易**
   - 用 `XQ_守不住開盤_auto.xs` 草稿，貼到 XQ 編輯器
   - 處理所有 syntax error（會有的）
   - 在 XQ 模擬交易環境跑 1 週
   - 比對結果跟 Python backtest 是否吻合（fills 數量 / 進場價）

2. **第二步：驗證真實 execution**
   - 用使用者實際帳戶（口袋 / 國泰 2000萬 額度）開模擬單
   - 觀察 trail stop 反應速度
   - 觀察 cancel-replace 失敗率

3. **第三步：實盤上線**
   - 從小額度開始 (100 萬部位)
   - 每日跑 reconciliation: live fills vs backtest signals

---

## 7. 使用者個人狀況

- 帳戶: 口袋證券 / 國泰證券（2000 萬額度），永豐（50 萬 — 太小不適合）
- XQ 操作: 熟練
- 程式背景: 已用 Python 跑 backtest，XS 不熟
- 期待: 全自動 + 零漲停鎖死風險 + 模擬單先驗證

---

## 8. 與使用者溝通建議

- 使用者熟 XQ 介面，但 XS 語法他也不熟 → 共同摸索
- 建議他做的事:
  - **打開 XQ XS 編輯器，貼草稿進去看紅線錯誤**
  - **截圖錯誤訊息回貼**
  - **查 XQ 客服: 自動交易中心是否支援多檔同時部位 N_MAX、排序**
- 不需要他立刻提供額外資料，先把 XS 修到「能跑」最重要

---

## 9. 不要做的事

- 不要改 V8 策略邏輯（已調 8 輪，過 walk-forward）
- 不要 hardcode tick size (0.05) — 高價股會錯
- 不要省略 Layer 1 觸價單防護（漲停鎖死保險）
- 不要在 XS 內處理「現股當沖 vs 借券放空」— 那是 XQ 自動交易中心 GUI 設定

---

## 10. 完成標準

✅ XQ XS 編輯器 syntax check 全綠
✅ XQ 模擬交易跑 1 週，每日訊號數量接近 Python backtest（誤差 < 10%）
✅ 漲停鎖死真實風險仍是 0%
✅ 11:30 強平機制運作正常
✅ 使用者能讀懂腳本邏輯（每段有清楚 comment）
