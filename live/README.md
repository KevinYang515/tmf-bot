# 守不住開盤 V8 Live Trading 框架

## 檔案結構

```
live/
├── 守不住開盤_live.py        ← 主程式 (Shioaji 全自動)
├── universe_builder.py        ← 盤前候選股建立 (08:30 cron)
├── XQ_守不住開盤_警示.xs      ← XQ Script 警示版 (半自動 fallback)
└── README.md
```

## 模式對照

| 模式 | DRY_RUN | SIMULATION | 用途 |
|---|---|---|---|
| **Pure dry-run** | True | — | 完全不下單，只 log signal。**第一階段建議跑 1 週**|
| **Shioaji 模擬單** | False | True | 真實 quote + Shioaji 假成交（不動真錢）|
| **Real trading** | False | False | ⚠️ 真實下單，極謹慎 |

## 部署 (GCP VM)

```bash
# 1. 上傳到 VM
scp -r D:\stock\tmf-bot\live kevin850515123456789@35.212.129.240:~/stock/live/

# 2. 確認 Shioaji 已安裝
ssh kevin850515123456789@35.212.129.240
source ~/stock/bin/activate
pip install shioaji

# 3. 設定環境變數 (~/.bashrc)
export SHIOAJI_API_KEY="xxx"
export SHIOAJI_SECRET="xxx"

# 4. 設定 cron
crontab -e

# 08:30 每日更新候選股
30 8 * * 1-5 /home/.../python /home/.../live/universe_builder.py

# 08:50 啟動 live (DRY_RUN 模式)
50 8 * * 1-5 /home/.../python /home/.../live/守不住開盤_live.py
```

## TODO 清單

### 上線前必驗 (Phase 0: paper trade 1 週)
- [ ] **Shioaji 觸價單 API**：確認 `trigger_price` 參數正確命名 (Shioaji 文檔可能有更新)
- [ ] **借券 / 現股當沖空 API**：確認 `first_sell=Yes` 是否觸發當沖
- [ ] **訂閱 throughput**：50 檔 tick 同時訂閱是否穩定
- [ ] **Tick callback format**：`quote["close"]` 是否就是最新成交價
- [ ] **時間同步**：VM 時間 vs 台股交易所時間
- [ ] **斷線重連**：market 中途斷線怎麼處理

### 風控驗證 (Phase 1: 模擬單 4 週)
- [ ] **Layer 1 觸價單成交**：模擬單 trigger 時是否真的觸發
- [ ] **Trail stop replace**：cancel + replace 是否 race condition
- [ ] **同時多筆 entry**：09:35-09:37 5 筆同時送單是否會 partial fill
- [ ] **fill 價格 vs 假設**：真實 fill - backtest entry_price = 平均 slippage

### 上線後監控 (Phase 2: 真實 50 萬規模)
- [ ] **每日 trade log 比對**：live fills vs backtest signals
- [ ] **Slippage 累積統計**：每週 review，超過 0.1% 警示
- [ ] **借券失敗率**：每日有幾檔借不到券
- [ ] **撤單失敗事件**：trail update 撤單失敗的處理

## V8 完整邏輯複習

### 進場 (09:35-09:37)
```
for 每檔候選股:
  if 09:00-09:35 morning_high / day_open - 1 < 3.0% AND
     morning_high 距漲停 ≥ 1.0% AND
     09:35-09:37 期間有 1 分 K Low ≤ morning_high × 0.9995:
    → 進場 SHORT @ morning_high × 0.9995
    → 同時掛觸價單 BUY @ min(morning_high + 1 tick, 漲停 - 1 tick)
```

### Trail Stop (09:37 - 11:30)
```
每秒檢查所有未平倉部位:
  if 當前價 < 部位 running_low:
    running_low = 當前價
    new_stop = running_low + 1 tick
    cancel 舊觸價單
    重新掛 BUY @ new_stop
```

### 強平 (11:30)
```
所有未平倉部位 → 市價 IOC 平倉
```

## XQ Script 半自動版

如果 Shioaji API 等不及/額度不夠，先用 XQ Script 警示：
1. 把 `XQ_守不住開盤_警示.xs` import 到 XQ
2. 開盤後自動 monitor 警示
3. 觸發時手動下單 + 手動掛智慧停損

**缺點**：XS 不能自動下單和 trail，trail 的 alpha 損失（Sharpe 28 → 22 估計）。

## Live trade log 格式

每日 11:31 寫到 `logs/trades_YYYYMMDD.json`:
```json
[
  {
    "ticker": "2330",
    "prev_close": 850, "day_open": 855, "morning_high": 858,
    "stock_aor": 0.0035, "gap_pct": 0.0059, "mh_to_limit": 0.0875,
    "entry_price": 857.57, "entry_time": "...",
    "entry_qty": 1000,
    "exit_price": 849.5, "exit_reason": "trail",
    "running_low": 848.5, "current_stop": 849,
    "return": 0.0094
  }
]
```

定期 (週末) 跑 reconciliation：對比 live trades vs backtest signals，量化 slippage。
