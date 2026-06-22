# NQ → TMF Strategy（v2 配置 B）

> 最後更新：2026-06-22
> Supervisor service: `trading-tmf-nq`（原 `trading-nq`，已於 2026-06-22 改名）
> 跟 V38 (`trading-app`) 完全獨立，互不干擾

---

## 1. 策略核心

利用「亞洲時段 NQ 期貨變化」推測台股期貨方向，於台指期 session 開盤集合競價（MOO）進場 2 口 TMF。

| Session | 訊號計算 | 進場時間 (Taipei) | 強制平倉 |
|---|---|---|---|
| **0845** | NQ 05:00 → 08:00 變化 % | 08:45:00 | 13:44 |
| **1500** | NQ 13:00 → 15:00 變化 % | 15:00:00 | 23:00 |

進場方向 = sign(NQ%)。|NQ%| 必須超過 threshold 才進場。

---

## 2. 目前部署參數（v2 配置 B，2026-06-22 上線）

```python
# nq_strategy.py
THRESHOLD_1500   = 0.05  # |NQ%| > 0.05%
THRESHOLD_0845   = 0.5

TP1_TICKS_1500   = 150
TP2_TICKS_1500   = 300
STOP_TICKS_1500  = 75

TP1_TICKS_0845   = 100
TP2_TICKS_0845   = 200
STOP_TICKS_0845  = 150

POSITION_QTY     = 2       # 2 口（1 給 TP1, 1 給 TP2）
USE_SIMULATION   = True    # Shioaji 模擬模式（paper trade）
DRY_RUN          = False
```

### 出場規則（兩口都用 fixed TP + hard stop）
- 進場後**同時掛 TP1 限價 (LMT)** 在 +TP1 點、**TP2 限價** 在 +TP2 點
- Stop 由 Python tick callback 監控，觸發時市價 (MKP) 平倉
- 若 cutoff 時間到（13:44 / 23:00），剩餘部位 MKP 強制平倉

---

## 3. 從 v1 → v2(B) 的演進

### v1（2026-06-15 ~ 06-22）參數
- 1500: thr 0.10%, TP +100/+200, stop -50, cutoff 23:00
- 0845: thr 0.5%, TP +100/+200, stop -150, cutoff 13:25
- Paper trade 6 天，0 進場（門檻沒過 + 週末沒交易）

### v2(B)（2026-06-22 起）改動原因
2026-06-22 跑了 5 個 sweep（共 71 個配置 × 5 半年）找「edge 隨時間穩定或上升」的配置：

| Sweep | 結論 |
|---|---|
| **cutoff sweep** (4 cutoff × 3 exit) | 1500 cutoff 21:30~05:00 影響 < 3%；0845 cutoff 13:25→13:44 +9% EV |
| **TP / trailing exit sweep** | D 純 trailing 全期 Sharpe 最高，但 **2026H1 已衰退**（slope -31） |
| **threshold sweep** | 1500 thr 0.10→0.05 多 39 筆/年、walk-forward test total +190K 最高 |
| **2026 regime check** | 「全期最佳」≠「2026 最佳」，需找跨 regime 穩定的配置 |
| **edge stability + trend** | **「寬 stop (75) + 大階梯 TP」5/5 期 EV 正、slope +60/期、2026H1 EV 最高** |

選 **A +150/+300 stop=75 thr 0.05%** 作為部署 B：
- 5 半年 EV 軌跡：313 → 574 → 537 → 572 → **615**（明顯上升）
- 全期 EV +532 / Sharpe 3.71 / maxDD -11K
- 對比 v1（A +100/+200 stop=50）全期 EV +461 / Sharpe 4.22
- 換取**上升 edge + 較高 EV**，代價是 Sharpe 略低 + maxDD 略大

### 為什麼不選 D 純 trailing
| 配置 | 全期 EV | 2024H1 | 2026H1 | slope | 結論 |
|---|---|---|---|---|---|
| D trail=50 stop=30 | +525 | +534 | +432 | **-31** | 看似最佳但**edge 在衰退** |
| **A +150/+300 stop=75** | +532 | +313 | **+615** | **+60** | **edge 上升** |

---

## 4. Backtest 樣本

- 資料源：`mxf_1min.csv`（FinMind 1 分 K）+ `intraday_signals.csv`（yfinance NQ hourly）
- 期間：2024-01-02 ~ 2026-06-13（2.5 年，726 個交易日）
- 1500 訊號 @ thr 0.05%：**445 筆 / 2.5 年 = 178 筆/年**
- 0845 訊號 @ thr 0.5%：**55 筆 / 2.5 年 = 22 筆/年**

### 已知 backtest 限制
1. **TP+Stop 同根 K bar**：保守假設 stop 先觸發（偏低估獲利）
2. **cutoff 強制平倉**：沒模 MKP 滑價（偏高估獲利）
3. **trailing 用 K bar Close 更新 peak**（沒用 intra-bar high，偏低估）
4. **commission 假設 5.6 點/口 RT**：實盤 4.2 點/口（backtest 略偏保守 +5%）

整體 backtest **略偏保守**，實盤大概率比 backtest 略好。

---

## 5. 預期表現（per year）

| 指標 | 1500 | 0845 | 合計 |
|---|---|---|---|
| 訊號筆數 | ~178 | ~22 | ~200 |
| EV/單 | +532 | +680 | — |
| 年化獲利 | ~+95K | ~+15K | **~+110K** |
| maxDD | -11K | -10K | — |
| Sharpe | 3.71 | 4.35 | — |
| 月份賺錢比例 | ~87% | — | — |

---

## 6. 已知問題

### 6.1 0845 週一 SKIP（**結構性，不是 bug**）
- NQ 期貨週末 18:00 ET 才開盤（= 週一 06:00~07:00 Taipei，視夏冬令）
- 我們程式在 05:00 Taipei 抓 NQ 基準價 → 週一 05:00 NQ 尚未開盤 → 「NQ 5:00 資料缺」→ SKIP
- 後果：0845 每週一全部 SKIP（一年少 ~50 筆）
- backtest 已內建（NQ data 對週一也是 NaN）→ 實盤跟 backtest 一致
- 暫不修，0845 有限樣本問題用其他方式解（見 §8）

### 6.2 0845 樣本不足（**核心疑慮**）
- 22 筆/年，Sharpe 數字統計信心弱
- 2025H1 18 筆 EV +34 差點打平
- backtest 全期 Sharpe 4.35 大半由 2024H2 + 2026H1 兩段強勢撐起
- → **0845 是否真有 edge 不確定**，建議只當實驗、不放大部位

### 6.3 Edge 衰減（**所有交易策略通病**）
- 1500 v1 配置 EV 從 2024H1 +988 → 2026H1 +421（衰退 57%）
- v2(B) 配置目前 5/5 期上升，但**未來繼續上升不保證**
- 必須月度監控

---

## 7. 監控指引

### 7.1 日常 health check
```bash
# 連 VM
gcloud compute ssh kevin850515123456789@instance-20260515-172729 --zone=us-west1-b

# 查狀態
sudo supervisorctl status trading-tmf-nq

# 即時 log
tail -f /home/kevin850515123456789/stock/logs/tmf_nq_out.log
tail -f /home/kevin850515123456789/stock/logs/nq_strategy.log
```

### 7.2 每週 review
- 訊號筆數是否符合預期（1500 約 3~4 筆/週）
- EV/單是否符合 backtest +500 上下
- 是否有 NQ 抓取失敗（yfinance 偶爾抖）
- Shioaji 連線是否有斷線

### 7.3 暫停 trigger（自動停損機制 — TODO 還沒實作）
- 連續 3 個月負 PnL → 停下檢討
- 月 maxDD > NT$15K → 停下檢討
- Sharpe 連 2 期 < 1 → 重評估
- 任何 edge 衰減訊號出現 → 重評估

---

## 8. 待辦 / 未來方向

| 項目 | 優先級 | 備註 |
|---|---|---|
| 觀察 v2(B) 上線 1 個月實盤 vs backtest 對齊度 | 🔴 高 | 2026-07-22 review |
| 實作自動暫停機制（連虧、maxDD 觸發）| 🟡 中 | 還沒做 |
| 0845 樣本不足 — 是否引入「OR 多訊號邏輯」（NQ OR ES OR Nikkei）| 🟡 中 | sweep B+C 沒跑 |
| 1500 改 trailing-only D 策略（v3 候選）| 🟢 低 | 等 v2(B) 跑 3 個月看 edge 趨勢 |
| 延長 backtest 期間（撈 2022/2023 K bar）| 🟢 低 | 解決樣本不足根本問題 |
| Edge stability sweep 自動化每月跑 | 🟢 低 | 監控 edge 是否還在 |
| 升級 VM 到 e2-small（從 e2-micro）| 🟢 低 | 之前 OOM 過一次 |

---

## 9. 部署 / 變更記錄

| 日期 | 動作 | 備註 |
|---|---|---|
| 2026-06-15 | 首次部署 v1 | thr 0.10/0.5, TP +100/+200, stop -50/-150 |
| 2026-06-18 | 修時區 bug | VM 用 UTC，加 `zoneinfo.ZoneInfo("Asia/Taipei")` |
| 2026-06-18 | 修 fill_price retry + snapshot fallback | Shioaji 模擬模式 MOO 取不到成交回報 |
| 2026-06-18 | execute_stop_close 改純 MKP | 取消階梯式 LMT，避免快市場滑價 |
| **2026-06-22** | **改名 trading-nq → trading-tmf-nq** | 名字更清楚 |
| **2026-06-22** | **部署 v2(B)** | thr 1500=0.05, TP +150/+300, stop -75; 0845 cutoff 13:25→13:44 |

---

## 10. 程式碼結構

```
tmf-bot/
├── nq_strategy.py              ← 主程式（部署在 VM）
├── NQ_TMF_STRATEGY.md          ← 本文件
├── PLAYBOOK.md                 ← V38 主 playbook
└── backtest/
    ├── mxf_1min.csv            ← 1 分 K（FinMind）
    ├── intraday_signals.csv    ← NQ/ES/Nikkei/KOSPI hourly 訊號
    ├── daily_open.csv          ← FinMind daily open
    ├── sweep_cutoff_exit.py    ← cutoff × exit 策略 sweep
    ├── sweep_threshold.py      ← threshold sweep
    ├── sweep_2026_regime.py    ← 2026 regime check
    ├── sweep_1500_exit_optimize.py  ← exit strategy 細部 sweep
    ├── sweep_edge_stability.py ← edge trend / stability 分析
    └── sweep_1500_detail.py    ← 1500 threshold 詳細對照
```

---

## 11. 相關 V38 文件

V38（台指期波動率策略 via TradingView webhook）詳見 [PLAYBOOK.md](./PLAYBOOK.md)。

兩個系統**完全獨立**：
- V38 service: `trading-app` (Flask + Shioaji)
- NQ-TMF service: `trading-tmf-nq` (本策略)
- 共用同一個 Shioaji 帳戶但獨立 session（不共用 lock）
- 兩個策略可能同時持有 TMF 部位（V38 + NQ-TMF）
