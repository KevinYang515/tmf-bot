# Strategy D 出處置動能跟進 Playbook

> 最後更新：2026-06-23
> 狀態：研究完成、實單未上線（全部模擬）
> 相關策略：[TS-QAN 處置股橡皮筋](https://github.com/KevinYang515/disposal-signals) — 同一市場結構的不同 phase

---

## 0. 兩個獨立 Track（**先讀這個**）

同一個訊號（漲多處置+ret≥9+post 1-14+大中型+價≥300）拆兩條獨立的執行路徑：

| Track | 商品 | 進場時機 | 樣本 | 狀態 | Sharpe |
|---|---|---|---|---|---|
| **D-Cash** | 現股當沖 | **09:00 集合競價** | 135 筆 / 3.5 年 | ✅ backtest 完整 | **8.89** |
| **D-SSF** | 個股期貨 | **08:45 期貨開盤** | 30 筆（重疊 D-Cash）| ⏳ paper trade 階段 | **未驗證** |

### Coverage
- 我們的 universe 319 檔股票中只 81 檔有 SSF（25%）
- 同一個訊號在沒 SSF 的股票（75%）只能跑 D-Cash
- 在有 SSF 的股票（25%）兩個 track 都可以做（甚至同時開倉）

### 為什麼 D-SSF 還沒驗證
- 嘗試了 Shioaji ticks / FinMind tick / TAIFEX 官方 / Goodinfo / Fugle API / yfinance
- 全部**沒有免費歷史 SSF intraday 資料**
- 用 FinMind daily SSF OHLC 粗估：optimistic ~+200 / mid ~+150 / pessimistic ~-30（vs Cash +123）
- 真實表現只能 paper trade 累積樣本後驗證

### 行動計畫
1. **D-Cash 立刻上線**（Sharpe 8.89 已驗證，不冒險）
2. **D-SSF 同時 paper trade**（記錄真實 8:45 SSF 開盤價 + 後續走勢，累積 ≥10 筆後評估）
3. 如果 D-SSF paper test 結果好 → 正式上線
4. 如果差或不確定 → 維持 D-Cash only

---

## 1. 核心 Thesis

**台股漲多 20 分鐘撮合處置股**，在處置**結束後 1-14 天內**，若**前一日漲幅再次 >= 9%**，當日 09:00 集合競價買進，TP=10 ticks / trail=2 ticks 出場。

```
漲多進處置 (前 21 日累積 >= 0%)
    ↓
20 分鐘撮合處置 (壓抑買盤)
    ↓
處置結束 (T 日)
    ↓
T+1 ~ T+14 任一天 前一日漲幅 >= 9%（動能再起）
    ↓
當日 09:00 集合競價買進 → TP +10t / trail -2t 出場
    ↓
賺「壓力解除後第二波動能」
```

**這個 alpha 跟 [[TS-QAN]] 是同一個市場結構的不同 phase：**
- TS-QAN：處置中跌深 D3-D8 買 → T+1 開盤賣 → 賺「壓力解除瞬間」
- Strategy D：處置結束後新動能 → 同日 +10t 出 → 賺「動能延續」

---

## 2. 進場條件（所有條件必須同時滿足）

| 條件 | 規則 | 資料來源 |
|---|---|---|
| 處置類型 | **20 分鐘撮合處置**（不要 5 分鐘）| `disposal-signals/data/history.csv` 「處置類型」 |
| 處置原因 | **漲多處置**（處置起始前 1-21 日累積漲幅 ≥ 0）| 同上「近20日漲幅 >= 0」 |
| 距處置結束 | **1 ≤ days_post ≤ 14** | 同上「出關日」 |
| 不在處置期間 | 當日不能在任何處置區間內 | `disposal_information.feather` |
| 市值（trade date）| 大型(>500億) OR 中型(100-500億)，**on-date 計算** | finlab close × shares |
| 股價 | 09:00 開盤價 ≥ NT$ 300 | bar01.Open |
| 前一日漲跌幅 | **ret_prev >= 9%** | `prev_ret = close.pct_change()` |
| 量比 | 前一日成交股數 / 20 日均量 ≥ 1.0 | `volume.rolling(20).mean()` |

**為什麼是這些條件：**
- 20 分鐘 > 5 分鐘：Sharpe 7.98 vs 1.71（橡皮筋效應 20 分鐘才明顯，5 分鐘量太小）
- 漲多 > 跌深：跌深處置出來後通常繼續弱勢，無 follow-through
- post 1-14：見 [year 9: timing analysis](#timing-analysis)
- ret_prev ≥ 9%：**ret 2-9% 區段全部賠錢**，9-11% 直接暴賺（非線性 edge）
- 大+中型 + 價 >= 300：小型股 + 低價股 noise 太多、避開
- 量比 >= 1：確保有真實買盤

---

## 3. 出場條件

| 出場類型 | 規則 |
|---|---|
| **TP** | 進場價 + 10 ticks（限價單）|
| **Trail Stop** | 動態移動停損：每根 bar 將 stop 上調至 `close - 2 ticks`，取較高者 |
| **強制平倉** | 13:00 收盤（避免過夜）|

**Tick size table（台股標準）：**
- < 10 元：0.01
- 10-50：0.05
- 50-100：0.1
- 100-500：0.5
- 500-1000：1
- ≥ 1000：5

**範例：1000 元股票 → tick = 5 → TP = +50 元 / trail stop = -10 元**

---

## 4. 交易成本（永豐 2 折）

```python
BUY_RATE  = 0.001425 * 0.20            # = 0.000285 (手續費 2 折)
SELL_RATE = 0.001425 * 0.20 + 0.0015   # = 0.001785 (含當沖減半證交稅)
ROUND_TRIP = 0.00207                    # 約 0.207%
```

進場 entry × BUY_RATE + 出場 exit × SELL_RATE 從毛利扣除。

---

## 5. 回測表現（v9b/v10/v11，2023-01-01 ~ 2026-06-18）

### 主要指標

| 指標 | 數值 |
|---|---|
| 樣本期間 | 3.5 年 |
| 總交易筆數 | **135 筆** |
| 平均每年 | ~40 筆 |
| 勝率 (PnL > 0) | **62.2%** |
| TP hit rate | 53.3% |
| 總 PnL | **+675 元/股** |
| 平均 PnL | **+5.00 元/股** |
| **Sharpe** | **8.89** |

### 年度穩定性

| 年 | n | WR | total | avg |
|---|---|---|---|---|
| 2023 | 6 | 83% | +43 | +7.10 |
| 2024 | 24 | 58% | +23 | +0.96 |
| 2025 | 19 | 58% | +21 | +1.12 |
| **2026** | **128** | **61%** | **+423** | **+3.30** |

（注：2026 數字是 v9b 的 D0 post 1-14 ret≥9 + 漲多，全市值。 20 分鐘子集 135 筆中 2026 約佔 80%）

### Timing Analysis（出關第幾天）

| Day | n | WR | total | avg | Sharpe |
|---|---|---|---|---|---|
| **Day 1** | 30 | **70%** | **+230** | **+7.66** | **11.19** |
| Day 2 | 7 | 57% | +24 | 3.37 | 8.31 |
| Day 3-6 | 48 | 56% | +66 | — | 5-8 |
| **Day 7-10** | 26 | 62% | +160 | 6.17 | 9.45 |
| **Day 11-14** | 24 | 67% | +195 | 8.14 | 9.21 |

→ Day 1 最強，但 Day 2-6 也都正報酬。Day 11-14 又強起來（二次動能？）

### Top 10 個股獲利集中度

（v6 baseline A 數據，Strategy D 應類似）

| 股號 | 名稱 | n | WR | total | avg |
|---|---|---|---|---|---|
| 7734 | 印能科技 | 9 | 67% | +122 | +13.58 |
| 3163 | 波若威 | 10 | 70% | +92 | +9.22 |
| 3491 | 昇達科 | 14 | 50% | +67 | +4.75 |
| 6442 | 光聖 | 22 | 59% | +65 | +2.94 |
| 5289 | 宜鼎 | 15 | 67% | +60 | +3.99 |

→ 集中現象明顯，Top 10 個股貢獻 ~70% 獲利

---

## 6. 實單可行性

### 進場時機 — **必須是 09:00 集合競價**

| 時機 | Sharpe | 結論 |
|---|---|---|
| **09:00 集合競價** | **8.89** | ✓ 主要 alpha |
| 09:01 進 | -0.11 | edge 消失 |
| 09:05 進 | -6.08 | 大虧 |
| 09:30 進 | -5.91 | 大虧 |

→ **整個策略的 alpha 只在 09:00 集合競價**。延遲 1 分鐘 edge 就歸零。

### 集合競價委託規則

- 8:30-9:00 之間下單，**掛 limit buy @ 漲停價**（或高於預期成交價）
- 9:00:00 cross 出來，**所有「願買價 >= cross」的單都成交在 cross price**
- 你掛高（漲停）但實際成交在開盤價 = **無滑點**

### 漲停買不到的風險

| 狀況 | 比例（135 筆中）|
|---|---|
| 開盤就在漲停 + 量小 | **1 / 135 = 0.7%** |
| 開盤就在漲停 + 量大 | 2 / 135 = 1.5%（部分散戶可 fill）|
| 第一 bar OHLC 全相同 | 5 / 135 = 3.7%（但多數能 fill）|

→ 實際 fill rate ~99%

### 流動性

bar01 (09:01 那根 1-min K) 成交量（**單位：張**）：

| 統計 | 張 | 換算 NT$（用 500 元/股估）|
|---|---|---|
| Median | 440 | NT$ 2.2 億/分 |
| Mean | 690 | NT$ 3.45 億/分 |
| Min | 10 | NT$ 500 萬/分 |

→ 散戶 1-10 張不會有 fill 問題

---

## 7. 資料來源

| 資料 | 路徑 |
|---|---|
| Finlab 收盤/開盤/量 | `D:/stock/finlab_db/price#*.feather` |
| 公司基本資料（股本）| `D:/stock/finlab_db/company_basic_info.feather` |
| 處置紀錄（原始）| `D:/stock/finlab_db/disposal_information.feather` |
| **處置分類（漲多/跌深/類型）** | `D:/stock/disposal-signals/data/history.csv` |
| 1-min K（319 檔）| `D:/stock/tmf-bot/backtest/strategy_c/kbars/*.csv` |

**重要：1-min K 從 Shioaji 抓**：
- 每根 bar 從 09:01 開始，代表 09:00:00 ~ 09:01:00 的成交
- bar01.Open = 09:00:00 集合競價 cross price = 進場價
- **Volume 單位是「張」，不是「股」**（早期 v9 v10 誤判過）

---

## 8. 主要 backtest 腳本

| 檔名 | 用途 |
|---|---|
| `backtest_strategy_d_v9b.py` | 主要切片分析（漲多 × 5分/20分 × 大戶因子）|
| `backtest_strategy_d_v10_tp_grid.py` | TP × trail grid（135 trades 子集）|
| `backtest_strategy_d_v11_timing.py` | 出關第幾天 + 進場時機分析 |
| `check_limit_up_problem.py` | 漲停買不到問題的驗證 |

執行：`& "D:\Users\USER\Miniconda3\envs\stock312\python.exe" <script>`

---

## 9. 待辦 / Open Questions

### D-Cash 上線前
- [x] 漲停買不到風險檢驗（0.7%，可忽略）
- [x] 滑點風險（集合競價委託無滑點）
- [x] 流動性檢驗（median 440 張/分鐘，散戶 1-10 張無問題）
- [ ] **Shioaji 集合競價委託 API 確認** — 用 `OrderType.MOC`、`order_lot=Common`、price=漲停價
- [ ] Daily signal generator script（`backtest/daily_signal.py`）
- [ ] Forward paper trade 1-2 週測 fill rate

### D-SSF paper trade 階段
- [ ] 累積 ≥10 筆 SSF 8:45 真實成交記錄
- [ ] 比對 paper test 結果 vs D-Cash 同訊號結果
- [ ] 如果勝過 D-Cash → 正式上線

### 長期研究方向
- [ ] 月度穩定性更細的分析（哪幾個月特別強）
- [ ] 把 5 分鐘處置子集 (Sharpe 4.38) 併入 strategy 看 total return
- [ ] 加 NQ 期貨方向篩選看看（隔夜 NQ 漲跌可能影響）

## 10. SSF Intraday 資料源狀況

已試遍所有 known 免費管道，全部失敗：

| 管道 | 結果 |
|---|---|
| Shioaji `api.kbars` | 過期合約 0 筆 |
| Shioaji `api.ticks` | 過期合約 0 筆，活合約也 0 筆 |
| FinMind 免費 tick | `Your level is free, please update` |
| FinMind daily | ✓ 只有 daily OHLC（已用）|
| TAIFEX `dlFutDataDown` | 直接 0 bytes / 900 bytes 錯誤頁 |
| Goodinfo 個股期貨頁 | 404 |
| Fugle Marketdata API | 404（需 key）|
| yfinance | TW SSF 不存在 |
| TWSE openAPI | 沒提供期貨 |
| finlab VIP | 沒期貨 dataset |

**結論**：D-SSF intraday backtest 需要付費資料（FinMind paid / TEJ）或 paper trade。

---

## 10. 相關文件

- `tmf-bot/PLAYBOOK.md` — TMF 主交易系統
- `tmf-bot/NQ_TMF_STRATEGY.md` — NQ-TMF v2(B) 策略
- `disposal-signals/PLAYBOOK.md` — TS-QAN 橡皮筋系統
- `CLAUDE.md` (D:\stock 根目錄) — VM/本機分工
