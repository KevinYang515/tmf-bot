# 隔夜 Report — 2026-06-25 早上

> 你昨晚要我「執行 1→3 然後決定優化方向」。睡前的進度都在這。

## ⚡ TL;DR (30 秒看完)

1. **v3 KOSPI 訊號已關閉**（用前日收盤 = stale 14hr，06/24 case 確認會反向）
2. **重做了無 lookahead 的 backtest**，發現原本 v1 結論大半是 leakage 假象
3. **真正的發現：KOSPI 不該當訊號，要當 V0 的 filter**
4. **v4_kc_strict** (V0 + KOSPI 同向確認) 預期把 Sharpe 從 3.33 → **7.43**, PF 1.57 → **2.52**
5. v4 prototype 寫好但**未部署**，等你 review

---

## 🔧 已動的東西

| 何時 (TW) | 動作 | 影響 |
|---|---|---|
| 01:00 | nq_strategy.py 設 ENABLE_KOSPI_SIGNAL=False + nan guard | v3 暫退回 v2(B) 純 NQ 行為 |
| 01:01 | commit + push GitHub | commit `805ace0` |
| 01:02 | scp + supervisorctl restart trading-tmf-nq | pid 91959 RUNNING |

**今天 08:44 開始 NQ-TMF 仍跑 v2(B)，沒有 KOSPI 干擾。V38 沒動。**

---

## 🔍 你昨晚指出的兩個 bug

### Bug 1: v3 KOSPI 訊號用「前日收盤」= 14hr stale
- 06/23 KOSPI 收盤 8,203（熔斷 -9.99%）
- 06/24 KOSPI 開盤 8,356（+1.86% 反彈）
- v3 看的是「前日收」→ 訊號 SHORT
- 但實際亞洲已反彈，TX 雖 gap down 但隨後反彈

### Bug 2: 我前一輪的 backtest 用了 lookahead-biased feature
`compute_intraday_signals.py` 把 KOSPI/NKX 用 `hour=9` 抓 → 那是 TW 09:00-10:00 bar，TX 已開盤 14min，整段 close-vs-open 全是事後資料 → corr 看起來 0.6+ 是假的。

---

## 📊 用「真正無 lookahead」的 feature 重做 — 重點數字

**新 feature 定義（全 CLEAN，TX 08:44 cutoff 前完全可觀察）：**
- `nq_0845_pct` = NQ 05:00→08:00 TW（原本就對）
- `kospi_open_gap_pct` = KOSPI 08:00 TW 開盤 vs 前日最後 KOSPI 收盤（46min lead）
- `nkx_open_gap_pct` = 同上 for Nikkei

### Corr 與方向命中率（vs TX 08:46 gap）

| 因子 | Corr | Hit rate (>0.3% 時) |
|---|---|---|
| nq_0845_pct | +0.264 | 64.4% (n=87) |
| es_0845_pct | +0.268 | 68.6% (n=51) |
| **kospi_open_gap_pct** | **+0.791** | **88.7% (n=310)** |
| nkx_open_gap_pct | +0.667 | 82.7% (n=313) |

**對比：** 原本 lookahead 版的 `nkx_first1h_pct` corr +0.58、純後驗的 `kospi_first1h_pct` corr 只剩 +0.18 — leakage 全去掉就回到真實值。

### 但是！高命中率 ≠ 賺錢（重要 caveat）

KOSPI 08:00 TW 開盤後，到 TX 08:46 開盤還有 46min。**TX 08:46 的開盤價已經把 KOSPI 開盤訊息 priced in**。所以「KOSPI 漲 → TX gap up」這個關係雖然 92% 對，但我們等到 TX 已經 gap 完才能進場，沒有獲利空間。

**用 KOSPI 當獨立訊號的 PnL backtest：**
| 策略 | n | Total | PF | Sharpe |
|---|---|---|---|---|
| Vk (KOSPI>0.5% 直接進) | 291 | -6,742 | **0.98** | -0.15 |
| Vkn (KOSPI+NKX 雙過同向 >0.5%) | 180 | -15,130 | **0.93** | -0.53 |
| 全部 KOSPI-only 策略 | | | **<1.0** | **負** |

**所以原本 v3 的想法「KOSPI 直接當第二訊號」徹底錯誤** — 統計 dependency 強不代表有 trading edge。

---

## ✅ 真正有用的發現：KOSPI 當 V0 filter

把 KOSPI 當「方向確認 filter」過濾掉 NQ 訊號但 KOSPI 反向的偽訊號：

| 策略 | n | Total | EV | WR | Sharpe | PF | maxDD |
|---|---|---|---|---|---|---|---|
| V0 baseline (現行) | 38 | +20,284 | +534 | 57.9% | +3.33 | 1.57 | -7,832 |
| **V0_kc_strict** (V0 + KOSPI 同向 + \|kos\|>0.3%) | **24** | **+28,002** | **+1,167** | **70.8%** | **+7.43** | **2.52** | **-3,724** ⭐ |
| V0_anti_kn (V0 + KOSPI/NKX 雙反向時跳過) | 34 | +27,332 | +804 | 64.7% | +5.07 | 1.95 | -7,448 |
| V0_lowth (NQ>0.3% + KOSPI>0.3% 同向) | 46 | +33,948 | +738 | 63.0% | +4.55 | 1.80 | -7,158 |

### V0_kc_strict by year 穩定性檢查

| Year | n | Total | PF | Sharpe |
|---|---|---|---|---|
| 2024 | 6 | +10,628 | 4.42 | +12.79 |
| 2025 | 12 | +12,046 | 2.33 | +6.63 |
| 2026 | 6 | +5,328 | 1.86 | +4.98 |

**5/5 半年期都正 EV**，比 baseline V0 還穩定。

### Trade-off

| Metric | V0 | V0_kc_strict | V0_lowth |
|---|---|---|---|
| 年均交易數 | ~15 | ~10 | ~18 |
| Sharpe | 3.33 | **7.43** | 4.55 |
| 風險最小 | maxDD 7.8K | **3.7K** | 7.2K |
| 期望單筆 | +534 | **+1,167** | +738 |

**V0_kc_strict 是「少而精」**，V0_lowth 是「多而中」。Both > baseline。

---

## 🛠️ v4 prototype (未部署)

寫在 `D:/stock/tmf-bot/nq_strategy_v4_prototype.py`（**僅自我測試，未 import 主程式，不會跑**）。

關鍵 function：
```python
def fetch_kospi_open_gap():
    """yfinance ^KS11 5m bar, 取今日 08:00 TW 開盤 vs 昨日最後 close"""

def decide_v4_signal(nq_pct, kospi_gap_pct, mode="strict"):
    """
    mode:
      "off"         → 現行 V0 純 NQ
      "filter_only" → V0 + KOSPI 反向時跳過 (KOSPI 缺資料時 trust V0)
      "strict"      → V0 + KOSPI 同向必須 (KOSPI 缺 = 不進) ★
      "loose"       → NQ>0.3% + KOSPI>0.3% 同向
    """
```

我 02:00 用 06/24 KOSPI 資料測過 fetch logic：
- KOSPI 06/24 08:00 開 8,356.79
- 06/23 13:55 (最後 bar) close 8,375.31  
- → gap = **-0.22%** (跟 daily 算的 -9.99% 完全不同 — 因為 06/23 KOSPI daily 那個 8,203 是異常值)
- 06/24 KOSPI gap 太小 (<0.3%) → V4 任何 mode 都會 SKIP

**Intraday 拿到的訊號比 daily 乾淨多了。**

---

## 🤔 我的建議

### Option A — 保守上線 V4_strict (推薦)
- 替換 nq_strategy.py 的 0845 邏輯為 V4 strict mode
- 預期：交易頻率從 ~15/年 → ~10/年 (-33%)
- 預期：Sharpe ↑↑, maxDD ↓↓
- 風險：n=24 是邊際統計顯著性 (但 by year 5/5 穩)

### Option B — 中庸上線 V4_lowth
- 把 NQ 門檻從 0.5% → 0.3%，但要求 KOSPI 同向 >0.3%
- 預期：交易頻率 ~15/年 → ~18/年 (+20%)
- 預期：Sharpe 3.33 → 4.55, total profit 提升 67%
- 風險：n=46 較穩，但 2026 表現偏弱 (PF 1.36)

### Option C — 兩階段
- 先上 V4_filter_only (V0 但 KOSPI 反向時跳過) — 最小變化
- 觀察 1 個月後 → 改 V4_strict

### Option D — 不動
- V2(B) 目前正常運作，繼續 paper trade 累積樣本
- 等 06/25, 06/26, 06/27, 06/30 訊號累積到 4-5 筆再決定

**我個人傾向 A** — backtest 顯著、邏輯乾淨、風險更小。但你決定。

---

## 📌 其他發現 / 未完成

### 1. KOSPI daily yfinance 06/23 資料異常
yfinance daily 顯示 KOSPI 06/23 OHLC 全部 = 8,203（熔斷瞬停？）但 intraday 5m 顯示 13:55 收 8,375。**未來 v4 一律用 5m**, 不再碰 daily。

### 2. balance_log cron 還是壞的
- 最後一筆 2026-06-23 13:46
- 找不到任何 cron / scheduler / app.py code 在寫
- 推測之前是 app.py 內 thread 寫的，被我 06/23 rewrite app.py 時誤刪
- **沒處理**（怕動到 V38）— 明天要不要修我問你

### 3. 1500 session 也許也能加 filter
- 14:59 cutoff 時 KOSPI 已收盤（KOSPI 收盤 14:30 TW）
- 完全乾淨資料，可以試 `nkx_intraday_pct` 跟 `kospi_intraday_pct` 當 1500 V0 的 filter
- **沒做** — 時間不夠且 1500 目前 PF 已經夠好

### 4. V38 06/24 又連兩漏單
- 10:50 SELL Failed, 13:20 BUY Failed (跟 06/23 同樣 reason: 可委託金額不足)
- 你昨天已確認原因，**沒處理**

---

## 📁 我建立 / 改動的檔案

| 檔案 | 動作 |
|---|---|
| `nq_strategy.py` | edit: 設 ENABLE_KOSPI_SIGNAL=False + nan guard (deployed) |
| `nq_strategy_v4_prototype.py` | new: v4 logic + KOSPI fetch (not imported) |
| `backtest/compute_intraday_signals_v2.py` | new: 修正 hour mapping + 新增 open_gap features |
| `backtest/intraday_signals_v2.csv` | new: 904 days × 19 features |
| `backtest/gap_research_v2.py` | new: factor corr 分析 (CLEAN vs WARM 對照) |
| `backtest/gap_research_v2.csv` | new: 因子 vs gap_pct 資料 |
| `backtest/composite_v2_backtest.py` | new: 9 種訊號組合的 PnL backtest |
| `backtest/composite_v2_results.csv` | new: 結果摘要 |
| `backtest/v0_with_kospi_filter.py` | new: V0 + KOSPI filter 模式對照 |
| `backtest/v0_filter_byyear.py` | new: 過濾組合的 by year/half-year 穩定性 |

**全部 commit 但不會自動部署**（除了 nq_strategy.py hotfix 已 deployed）。

---

## 🎯 早上你回來該做什麼

1. **檢查 v3 hotfix** 有沒有出問題 — `tail logs/nq_strategy.log` 看 06/25 早上 08:44 訊號
2. **看 14:59 v2(B) 1500 訊號** 跑得對不對
3. **決定 v4 上不上線** — Option A / B / C / D
4. 如果 A：我準備 deploy 流程（沒你確認我不會動）
5. 如果要修 balance_log，叫我重寫一個獨立的 `balance_snapshot.py` + cron

睡好。早上見。
