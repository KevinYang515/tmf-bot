# TMF 自動交易系統 Playbook

> 最後更新：2026-07-09（Gap Burst：門檻放寬測試否決、試撮外插修正已部署，見 GAP_STRATEGY.md §3.5）／2026-07-04（門檻/動態TP walk-forward 驗證、1500只做空、修復週一ref_close與週末誤觸發兩個bug）
> 適用：新 session 快速 onboarding、策略回顧、系統維護
>
> **相關文件**：
> - [GAP_STRATEGY.md](./GAP_STRATEGY.md) — **現役第二策略**：試撮跳空 burst scalp（service: `trading-tmf-gap`，paper trade 中）— 接手必讀，§3.1 是 07/04 overnight research 完整記錄
> - [NQ_TMF_STRATEGY.md](./NQ_TMF_STRATEGY.md) — 已退役（2026-07-02 被 gap 策略取代）：NQ 訊號交易 TMF

## ⚡ 2026-07-04 現況速覽（給接手的 session）

| 系統 | 狀態 | 錢 |
|---|---|---|
| V38 (trading-app, app.py) | RUNNING，TV webhook 下單 | **實盤** TMF，權益 ~1.16M（07/02 補錢後） |
| Gap Burst (trading-tmf-gap) | RUNNING，07/03~07/08 六場皆 SKIP 未觸發，07/04 兩輪 overnight research 部署 1500動態TP+只做空+兩bug修復，**07/09 新增試撮外插修正**（門檻放寬 0.49%/0.48% 已細掃否決；改用最後兩筆試撮快照斜率外插到開盤時間點判斷觸發，n=2 驗證有效，門檻值/TP/停損不變，見 GAP_STRATEGY.md §3.5） | 模擬（paper trade），尚無實際成交筆數 |
| NQ 策略 (trading-tmf-nq) | **已退役** | — |
| balance_log.csv | ✅ 07/02 修復（06/23~07/01 斷檔：app.py 重寫時誤刪 snapshot thread，已補回） | — |

近期待辦：Gap 策略等第一個真正觸發日（驗證 fill/TP/停損/cap 鏈路，見 GAP_STRATEGY.md §6）、**持續追蹤 07/09 新增的 `gap_projected_pct` vs `gap_actual_pct` 準度（n=2，優先監控項）**、0845 秒級出場變體待首批真實成交驗證後切換、V38 漏單 root cause（webhook_raw.csv 累積中）、V38 Status.Failed=可委託金額不足（user 已補錢）。

**07/04 overnight research 結論摘要**（user 睡覺期間跑的兩輪，細節見 GAP_STRATEGY.md §3.1/§3.2）：
1. 重大限制：Shioaji 歷史 tick API 不保留開盤前試撮資料，**無法**回測試撮讀值準確度，只能持續累積 live `gap_calibration.csv`
2. 門檻 0.5%(0845)/0.3%(1500) 經 walk-forward(H1 01-03月 / H2 04-07月) 驗證仍是最穩健的選擇，維持不動
3. 動態 TP：0845 測了正向、反向都輸固定 TP80（因為大 gap 日的 MFE 沒有比較大，甚至略小）→ 維持固定；**1500 有效**（gap 越大 follow-through 越大是穩定的正相關），改用 `clip(0.4×gap_pts,100,300)`，H2 樣本外 EV 從 +239 提升到 +299 → **已部署**
4. 動態停損（兩場都測）全部更差，worst case 從 -356/-856 惡化到 -1200~-1550 → 不採用
5. 邏輯修正：試撮讀值若最後一筆(:50)剛好缺值，改 fallback 用最近一筆有值的快照，避免無謂 SKIP
6. **第二輪最大發現：1500 跳空向上(做多) EV 為負（-95，H1/H2 兩段都負），跳空向下(做空) EV 極強(+725，H1/H2 兩段都強正）**→ **1500 改成只做空**，跳空向上不下單（但仍記錄校準資料）。已部署，但 n=11、100%勝率是小樣本，需持續監控（見 GAP_STRATEGY.md §3.2 警語）
7. 星期幾效應、假日後效應、舊聞vs意外反轉、跨session反轉等因子都有隱約訊號但樣本太薄（n=2~13的子分組），只記錄不部署
8. **user 拿實際日期回頭質疑，挖出兩個真的 bug（GAP_STRATEGY.md §3.3）**：(a) 週一 0845 的 ref_close 因為 kbars 日期標記問題永遠抓不到，全年 22% 交易日(24個週一)完全沒被評估過——回填後 6 個週一本來會觸發，但回測顯示 EV -173（勝率16.7%，累積週末的 gap 本質更接近舊聞而非新鮮意外），所以修好 bug 後**週一仍不下單，只記錄校準資料**；(b) 主迴圈沒檢查是不是交易日，週六(07/04)誤觸發過一次產生異常資料列（已清除）。兩個都已修復部署
9. **（07/04 下午，user 提供真實交易者 TXF 成交明細逆向出的新發現，GAP_STRATEGY.md §3.4）0845 出場擬改「3秒全出+停損50」（拿掉TP80/cap300）**：回測 EV +264 vs 現行 +172，H1+358/H2+241 兩段都穩（現行 H2 只剩 +84），06/30 型「開盤雜訊掃停損」問題自動消失。0845 慣性只活頭幾秒（3s→5s EV 從+264掉到+118）。**切換條件**：等首批真實成交驗證 (a) 集合競價 fill 無滑價 (b) 開盤頭幾秒市價出場滑價 ≤5pt，兩者成立才切（只改三參數）。**1500 維持現行不動**（秒級出場 EV +429~463 輸現行動態TP的 +725，1500 的 follow-through 是分鐘級）。同批研究否決：無門檻「只要跳空就做」（TMF 成本下 EV +21 且 H1 為負；該交易者做得起是 TXF 成本占比 <8% 的特權）、降門檻+縮小TP、分段固定小TP、0845 單邊濾網

---

## 0. ⚖️ VM 與本機分工原則（**讀其他章節前必看**）

| 角色 | 機器 | 為什麼 |
|------|------|--------|
| **下單 / Live Trading** | **GCP VM 35.212.129.240** | 24/7 穩定、不受筆電開關機影響 |
| **Backtest / Grid Search** | **本機 D:\stock** | iterate 快、無 SSH lag、debug 容易 |
| **資料抓取 (finlab / Shioaji / yfinance)** | **本機** | VIP token 任何地方都能用 |
| **資料分析 / 探索性研究** | **本機** | 同上 |
| **Streamlit 部署** | GitHub → streamlit.app | 由本機 push |

### VM 上「只能」放的東西
- `app.py`（Flask webhook + Shioaji 下單）
- `logs/`（balance_log.csv、trade_records.csv）
- 必要 cron（balance snapshot、git sync）
- 換月 / 對帳腳本

### VM 上「絕對不要」放的東西
- backtest / grid search 腳本
- 研究用的 1-min K / tick 資料（除非當天要回推給本機）
- 資料探索 notebook、長時間 Python script

### 為什麼這個分工很重要

- **GCP SSH banner exchange 偶爾抽風** → backtest 跑到一半 SSH 斷線、log 沒 flush、結果取不回。本 session（2026-06-20）已遇兩次。
- VM 是 e2-small 等級，跑 grid search 會跟 TMF live trading 搶 CPU/memory
- 本機 iterate 快十倍，IDE debug 直接，print 直接看
- VM 出狀況時，職責單一比較容易救（只跑 app.py 一件事）

### 真正的教訓
- 之前把 Strategy C v1/v2 backtest 直接跑在 VM 上 — 結果 SSH 抽風時取不回，浪費時間。
- 正確流程：scp 資料下來 → 本機跑 → 結果 push GitHub。

### 本機 Python 環境

- **主要 env：** `D:\Users\USER\Miniconda3\envs\stock312\python.exe` (Python 3.12.13)
- **已裝：** finlab 2.0.13, pandas 3.0.3, pyarrow 24.0.0, numpy, scipy

---

## 1. 系統架構一覽

```
TradingView Alert (Pine Script)
        │  POST /webhook?token=...
        ▼
GCP VM (35.212.129.240) — Flask 5000 port
  ├── app.py           ← 交易 bot（勿在交易時間修改）
  ├── logs/
  │   ├── trade_records.csv   ← 每筆成交自動 git push
  │   └── balance_log.csv     ← 每日 13:46 / 05:01 快照 + 手動觸發
  └── git push → GitHub: KevinYang515/trading-dashboard (public)
                    │
                    └── Streamlit Cloud 讀取 (via GitHub API + base64)
                         streamlit_dashboard.py
```

### SSH 連線

```bash
ssh -i ~/.ssh/google_compute_engine -o StrictHostKeyChecking=no \
    kevin850515123456789@35.212.129.240
```

### Supervisor 管理

```bash
# 在 VM 上
sudo supervisorctl status trading-app
sudo supervisorctl restart trading-app
sudo supervisorctl tail -f trading-app   # 即時 log
```

---

## 2. 交易商品規格

| 項目 | 微型台指 (TMF) | 小型台指 (MXF)【2026-07-08 起實盤】 |
|------|---------------|--------------------------------------|
| 代號 | TMF (shioaji) | MXF (shioaji), MXF1! (TV) |
| 每點價值 | NT$10 | NT$50 |
| 最小跳動 | 1 點 | 1 點 |
| 原始/維持保證金 | 31,800 / — | 159,000 / 122,000 (@2026-07) |
| 策略最大口數 | 4 口 (1→2→3→4加碼) | **3 口（app.py MAX_ABS_POS cap，見 §7B）** |

**手續費明細（永豐，已確認，TMF 時代）：**
- 每單邊：期交稅 NT$8 + 手續費 NT$12 = NT$20
- Round-trip：NT$40 = 4 點（以 NT$10/點換算）；MXF 費率待首批成交後回填實際值

**歷程：** 2026-02~07 以 TMF 驗證執行層與策略；2026-07-08 升級 MXF（py cap 3），TV 圖表本來就是 MXF1! 5分K，訊號端零改動。

---

## 3. TradingView 策略（Pine Script）

### 版本

- `tv/TF_V38_v26.pine` — 當前部署版本（TradingView alert 仍跑 v26）
- `tv/TF_V38_v27.pine` — **下一版（2026-07-08 已終驗通過，待 bot 空手時切換）**：v26 + TimeStop + Cooldown，詳見第 10 節
- `tv/TF_V38_v21.pine` — 前一版備份
- `tv/TF_V38_v20.pine` — 舊版備份

### 策略核心邏輯（V38 v26）

- **商品：** MXF1!（5分K）
- **入場：** 60分K EMA 大趨勢濾網 + 本週期 EMA 多空判斷 + ADX（僅 L_Cmd 用，門檻 20）
- **加碼：** 最多 4 層（pyramiding=4），間距 ATR 倍數
- **日夜盤分流：** 日盤游擊追蹤 0.8 ATR，夜盤 1.5 ATR（夜盤洗盤大，需放寬）
- **L_Cmd 快速防守 EMA：** 50 期；**S_Cmd 快速防守 EMA：** 40 期

### Webhook Payload 格式

```json
{
  "ticker": "{{ticker}}",
  "target_pos": 1,
  "signal_price": {{close}}
}
```

- `target_pos`: 整數，正=多、負=空、0=平倉
- app.py 用 position alignment 邏輯處理（比較 target vs 實際部位）

### 有毒時段（不進場）

| 時段 | 原因 |
|------|------|
| 15:00–20:59 | 台期收盤後到夜盤開盤前的空窗 |
| 01:00–02:59 | 美國深夜，流動性差 |
| 04:00–04:59 | 多單加碼禁止 |
| 21:00–21:59 | 空單禁止（美市開盤假突破） |

app.py 額外過濾：13:45–15:00 不接受任何 webhook。

---

## 4. 交易 Bot（app.py）— VM 版本

> **重要：** app.py 在 VM 上，Cloud Shell 的本地 `/home/kevin850515123456789/stock/app.py` 可能版本不同（patches 直接打在 VM 上）。

### 關鍵功能

- **Position Alignment：** 不直接 BUY/SELL，而是比較 target_pos 與實際部位差值
- **換月邏輯：** 自動偵測第三個週三 settlement day，前一日切換合約
- **啟動部位比對：** 重啟時比對 CSV 最後 target_pos vs 永豐實際，不一致發 Line 通知
- **重複信號保護：** 5 秒內相同 target_pos 略過
- **心跳線程：** 每 15 分鐘確認 token，失效則 `os._exit(1)` 讓 supervisor 重啟

### 帳戶餘額快照（balance_log.csv）

已加入 VM 版 app.py：

- **自動觸發：** 每日 13:46（日盤收）、05:01（夜盤收）
- **手動觸發：**
  ```bash
  curl -X POST "http://35.212.129.240:5000/api/balance/snapshot?token=$TOKEN"
  ```
- **欄位：** datetime, session, yesterday_balance, today_balance, equity, future_settle_profitloss, future_open_position, available_margin
- **快照後自動 git push** 到 GitHub → Streamlit 自動更新

### 環境變數（.env）

```
SJ_API_KEY, SJ_SECRET_KEY, SJ_CA_PATH, SJ_CA_PASS, SJ_PERSON_ID
WEBHOOK_SECRET
LINE_NOTIFY_TOKEN
```

---

## 5. Streamlit Dashboard

**部署：** Streamlit Cloud（連 GitHub KevinYang515/trading-dashboard）  
**程式：** `streamlit_dashboard.py`

### 頁面內容

1. **日期選擇器** — 預設今日
2. **摘要卡片：** 成交筆數、今日已實現損益、收盤部位（均價）、平均滑價
3. **成交明細表** — 買單綠底 `#0d2b1a`，賣單紅底 `#2b0d0d`
4. **帳戶餘額折線圖** — 每日取最後一筆 equity，展示權益數趨勢
5. **每日帳戶明細表** — equity/今日餘額/平倉損益/浮動損益/可動用保證金

### 損益計算邏輯（FIFO）

- 從第一筆 `pos_before` 初始化部位
- BUY：先平空倉（realized += (avg_cost - price) × qty × 10），剩餘再開多
- SELL：先平多倉（realized += (price - avg_cost) × qty × 10），剩餘再開空
- `cur_pos` 直接取最後一筆 `target_pos`（最準）

### 永豐 `future_settle_profitloss` vs FIFO 的差異

永豐的數字是**交易所結算價**計算（日盤用 13:30 結算，夜盤用 05:00 結算），與我們用**成交價**做 FIFO 的結果不同，尤其隔夜部位會在次日結算。**用 balance_log 的 equity 做長期追蹤最準**。

---

## 6. 回測框架（MXF 波動突破）

> **待執行：** 需先在 VM 跑 `fetch_kbars.py` 產生資料

### 流程

```bash
# Step 1：在 VM 上（期貨全部收盤後，建議 05:10 後）
ssh ... "cd ~/stock && source venv/bin/activate && \
  nohup python backtest/fetch_kbars.py > backtest/fetch.log 2>&1 & echo PID:\$!"

# Step 2：SCP 到 Cloud Shell
gcloud compute scp instance-20260515-172729:~/stock/backtest/mxf_1min.csv \
  ~/stock/backtest/mxf_1min.csv --zone=us-west1-b --tunnel-through-iap

# Step 3：在 Cloud Shell 跑回測
cd ~/stock && python backtest/backtest_breakout.py
```

### 回測策略設定

- **資料：** MXF 近 90 天 1 分鐘 K
- **邏輯：** 觸發時間點（四選一）K 棒開盤價 ± offset 突破
- **觸發時間：** 08:45（期貨開盤）/ 09:00（現貨開盤）/ 13:30（現貨收）/ 13:45（期貨日盤收）
- **參數格：** offset × target × stop × time_limit（共 5,600 組）
- **成本：** 4 點（round-trip NT$40）
- **輸出：** Top 20 Sharpe、各觸發時間最佳組合、月份穩定性分析

---

## 7. 近期實盤績效（截至 2026-06-22）

> ⚠️ **2026-06-22 更新**：原本截至 06/06 的數字（PF 3.44 / WR 73.9%）只涵蓋 V38_v26 上線後最順風的 2.5 週，未含 06/06 之後的回檔。下表是用完整 5 週資料重算。

### 完整 5 週實況

| 指標 | 截至 06/06（順風期）| **截至 06/22（完整）** |
|------|---------------------|------------------------|
| 期間 | 2.5 週 | **5 週** |
| FIFO Round-trips | 88 | 143 |
| Win Rate | 73.9% | **53.1%**（76W / 65L）|
| Profit Factor | 3.44 | **1.11** |
| 累計 realized PnL | +NT$177K | **+NT$32K** |
| 單日最大 PnL | — | +NT$44,819 (06/06) |
| 單日最大 PnL DD | — | -NT$17,058 (06/12) |
| **MaxDD (peak→trough)** | — | **-NT$47,422（-22.76%）** |

### 週度 PnL 趨勢（**值得警惕**）

| 週 | 筆數 | PnL | 註 |
|---|------|-----|----|
| 2026-W20 (5/19~) | 19 | +36,720 | 上線首週 |
| 2026-W21 | 28 | **+76,850** | 高峰 🥇 |
| 2026-W22 | 41 | +11,390 | |
| 2026-W23 | 27 | -2,570 | 開始反轉 |
| **2026-W24** | 21 | **-49,602** | 💀 |
| **2026-W25 (~06/22)** | 5 | **-40,480** | 💀💀 連兩週重虧 |

連續 3 週負 PnL，最近 2 週 -90K。

### 帳戶曲線

```
121K (5/22 起) → 152K (5/30) → 201K (6/06 ⭐ peak) → 161K (6/15 ⬇️) → 186K (6/22)
```

Peak-to-trough drawdown -23%。

### 帳戶狀態（2026-06-22 13:46 日盤快照）

| 項目 | 金額 |
|------|------|
| 權益數 (equity) | NT$186,651 |
| 今日餘額 | NT$183,901 |
| 平倉損益 (交易所) | +NT$12,440 |
| 浮動損益 | +NT$2,750 |
| 可動用保證金 | NT$91,251 |

### TV 回測 vs 實盤對比（⚠️ 重要：合約規格不同）

**TV 回測用 MXF（NT$50/點），實盤用 TMF（NT$10/點）**。對比時必須換算為同一合約：

| 指標 | TV (MXF) | 換算 TMF | 實盤 (TMF) | 實現率 |
|------|----------|----------|------------|--------|
| 5 週 PnL (5/19~6/22) | +632K | **+126K** | +32K | **25%** |
| 4.4 年累計 (2022-01~2026-06) | +5.18M (PF 1.53) | +1.04M | — | — |
| 4.4 年累計（扣 2pt spread）| +4.56M (PF 1.46) | +912K | — | — |
| MaxDD (4.4 年, MXF) | -188K | **-37.6K** | -47K (5 週實盤) | 實盤 DD 略超 TV |
| 2024 起年化 (穩定期) | +1.66M (PF 1.57) | +332K | — | — |

### 漏單根因分析（已啟動量測）

**問題**：TV 同根 K bar 觸發多個 fills 時，alert message 用 `{{strategy.position_size}}` 只能傳遞**最終淨部位**，中間步驟（如 S_Exit 鎖獲利）對 webhook 完全不可見。

**已部署的量測機制（2026-06-22）**：
- TV alert message 加入 `{{strategy.order.action}}` / `{{strategy.order.comment}}` / `{{strategy.order.id}}` placeholders
- `app.py` 新增 `logs/webhook_raw.csv` 記錄每個收到的 webhook（含被 dedup 殺掉的）
- 預計 2026-06-30 review

**已知具體案例**：
- 06/09 23:25 漏掉 S_Exit @ 43450 → 漏鎖 +NT$31,760 (MXF) ≈ +6.4K (TMF)
- 06/17 15:00 MOO 集合競價滑價 ~240 點 → 漏 ~+48K (MXF) ≈ +9.6K (TMF)

### 結論

- TV 策略本身有 edge（扣 spread 後 PF 仍 1.38-1.46，年年正）
- 實盤實現率約 25% — **執行漏單是真實問題**
- PF 從表面 3.44 降到 1.11 主因是 cherry-pick 樣本（前 2.5 週順風 vs 完整 5 週含回檔）
- 距「正式可用」門檻仍要：執行率 > 50%、PF > 1.5 連 2 個月

### ✅ 更新：TV vs 實盤驗證（2026-07-07，正確 5分K 匯出）

用 `V38.0519_v26_Session_TAIFEX_MXF1!_2026-07-07.csv`（5分K，逐筆訊號與實盤一一對應）重新對齊 5/19~7/7：

| 指標 | TV 理論（換算 TMF） | 實盤（含費滑） | 捕捉率 |
|------|--------------------|---------------|--------|
| 重疊區間淨損益 | +174,910 | **+96,329** | 55% |

**落差 -78.6K 拆解（重要）：**
- 6/6 崩盤夜：-38.9K（極端行情滑價/跳空，換 MXF 後仍會存在）
- 6/26：-15.6K（**6 筆連續 Failed 加碼單 = 保證金不足**，帳戶已補資後此問題消失）
- 其餘 37 個交易日合計僅 ~-24K（≈ -650/日 = 費用+正常滑價），**平日逐日貼合 ±1-2K**

→ 修正 6/22 的「實現率 25%」結論：當時用了錯誤顆粒度的 TV 匯出。**正常日執行接近完美，預期捕捉率 85-90%**（僅極端行情日折損）。實盤程式單 5/19~7/7 淨 +96K、PF 1.50、MDD -43K，與回測 PF 1.53 高度一致。

⚠️ 注意：實盤另有 bot 之外的場外多單（**非 hedge** — 2026-07-08 Shioaji 實查為 6/26 逢低買進的 FZF/PUF/PBF/VJF 多單，浮虧合計 ~-313K），不計入程式單績效；trade_records 有 7 處部位跳號 + 17 筆 Failed，2026-07-08 起 app.py 已加下單後對帳告警。

詳見：
- `backtest/_v38_analysis.py` — 實盤 5 週統計
- `backtest/_tv_v38_analysis.py` — TV 4.4 年原始
- `backtest/_tv_with_spread.py` — TV 扣 spread 修正
- `backtest/_tv_align_to_06_22.py` — TV vs 實盤同期對齊

---

## 7B. MXF 升級評估（**2026-07-08 已執行升級：MXF、執行層 cap 3 口**）

**2026-07-07 重評**：正確顆粒度驗證後，執行捕捉率正常日接近 100%（見第 7 節更新），「實現率 25%」為舊誤判。

### Pyramiding 上限實測（engine_v26，v27 配置 cd30+stale10，2024-01~2026-06 MXF）

| 配置 | 淨損益 | PF | 實測 MDD | Sharpe | 備註 |
|------|--------|-----|----------|--------|------|
| py=4 | +3,807K | 1.53 | -316,850 | 2.55 | 完整策略 |
| **py=3** | **+3,102K** | **1.47** | **-246,400** | 2.39 | **淨利/MDD 比最佳 (12.6)，現行配置** |
| py=2 | +2,284K | 1.45 | -210,180 | 2.39 | |

MDD 非線性縮放：砍掉的是尾端加碼單，DD 降幅大於獲利降幅。

### 帳戶 size 需求（依實測 MDD + 二成餘裕）

| 配置 | DD 預算 | 保證金功能門檻* | 25% DD 線 | 30% DD 線 |
|------|---------|----------------|-----------|-----------|
| py=3 | -300K | 777K | 1.2M | **1.0M ← 2026-07-08 現況 (1,013K)** |
| py=4 | -400K | 1,036K | 1.6M | 1.33M |

*功能門檻 = DD 打底時金字塔加碼單仍不被拒（權益 − DD 預算 ≥ 原始保證金）。追繳線（維持保證金 122K/口）遠低於此，實務上先失能後才可能追繳。
2026-07-08 決策：用戶接受 ~30% 最壞 DD，直接以 py=3 上線；「真的有需要補錢再說」。

### 預期獲利（依 7/7 驗證的捕捉率 85-90%）

- TV 理論近 16 週：+1.69M MXF ≈ 10.5萬/週 → 打 85 折 ≈ 9萬/週（滿配 4 口）；**py=3 約打 81 折 ≈ 7.3萬/週**
- 注意此為多頭+崩盤大行情窗口，長期均值請用 4.4 年 PF 1.53 預期打折

### 升 MXF checklist（2026-07-08 執行紀錄）

1. ✅ TV alert 加 placeholder（2026-06-22）
2. ✅ 執行捕捉率驗證 ≥ 85%（2026-07-07，正常日 ~100%）
3. ✅ 連續正 PnL：5、6、7 月程式單皆為正
4. ✅ 帳戶權益 1,013K ≥ py=3 30% 線 1.0M
5. ✅ **app.py 切換部署（2026-07-08 09:52）**：`CONTRACT_SYMBOL=MXF`、`POINT_VALUE=50`、`MAX_ABS_POS=3`（webhook 層 cap，TV 送 ±4 壓到 ±3）、委託未成交 Line 告警、下單後 Shioaji 部位對帳告警、合約解析排除 MXFR1/R2 連續月。舊版備份 `app_tmf_backup_20260708.py`
6. ⏳ 60 秒反向訊號 debounce（未做；現有 5 秒同 target dedup 保留）
7. ⏳ **場外倉位（非 hedge，係 6/26 逢低買進）**：FZF 2口 -203K、PUF 2口 -161.6K、PBF 2口 +50.5K、VJF 1口 +1K（2026-07-08），佔保證金 ~325K。留倉時 py=3 遇 -300K DD 會擠壓加碼保證金（需 802K > 屆時權益 713K）— 用戶決策：先跑，必要時補錢
8. ⏳ TV alert 換 v27（bot 空手時切換）

---

## 8. GitHub Repo 結構

```
KevinYang515/trading-dashboard (public)   ← 實盤資料
└── logs/
    ├── trade_records.csv   ← 每筆成交後 push
    └── balance_log.csv     ← 每日兩次快照

KevinYang515/tmf-bot (public)             ← 程式碼 + 文件（本 repo）
├── PLAYBOOK.md
├── app.py
├── streamlit_dashboard.py
├── requirements.txt
├── backtest/
│   ├── fetch_kbars.py
│   └── backtest_breakout.py
└── tv/
    ├── TF_V38_v26.pine     ← 當前部署版
    ├── TF_V38_v21.pine
    └── TF_V38_v20.pine
```

Streamlit 透過 GitHub Contents API 讀取 trading-dashboard（base64 decode），cache TTL 60 秒。

---

## 9. 目錄結構（Cloud Shell）

```
~/stock/
├── app.py                  ← Flask bot（VM 版為主）
├── streamlit_dashboard.py  ← Streamlit Cloud 用
├── backtest/
│   ├── fetch_kbars.py      ← VM 上執行，拉 MXF 1min K
│   ├── backtest_breakout.py ← Cloud Shell 執行，不需 Shioaji
│   └── (mxf_1min.csv)      ← fetch 後存在此（gitignore）
├── tv/
│   ├── TF_V38_v26.pine     ← 當前部署策略（正式版）
│   ├── TF_V38_v21.pine     ← 前一版備份
│   └── result/             ← TV 策略績效 CSV（v2~v27，含 v26 0607 最新）
├── disposal-rubberband/    ← 另一套選股策略（TS-QAN）
├── logs/
│   ├── trade_records.csv
│   └── balance_log.csv
├── requirements.txt
├── supervisor.conf
└── .env                    ← 敏感資訊，不入 git
```

---

## 10. 回測結果紀錄

### V38 v26 策略回測（TradingView，正式版）

**資料：** MXF1! 5分K，2022-01-12 ~ 2026-06-07（4.4 年）  
**初始資金：** NT$400,000，手續費 NT$20/單邊，最多 4 口加碼

| 指標 | v21（舊版） | v26（正式版）|
|------|-----------|------------|
| 交易筆數 | 7,060 | 6,247 |
| 勝率 | 54.0% | **55.2%** |
| 淨損益 | 4,119,300 | **5,184,570** |
| Profit Factor | 1.37 | **1.53** |
| 均勝 / 均敗 | 4,033 / -3,473 | **4,318 / -3,464** |
| 最大回撤 | 353,070 | **188,180** |

**v26 改進重點：** 日夜盤分流（夜盤游擊追蹤放寬至 1.5 ATR），最大回撤縮減 47%，Profit Factor 從 1.37 升至 1.53。

> ⚠️ **MDD 修正（2026-07-07）**：`V38.0519_v26_Session_TAIFEX_MXF1!_2026-07-07.csv`（3/18~7/7 視窗）實測 **MDD -338,430**（6/17，肇因 6/11-6/12 盤整雙巴日連虧 -190K）。原 188K 低估，**MXF sizing 一律用 DD 預算 -400K 規劃**。

#### v26 訊號歸因（3/18~7/7，428 筆，MXF 計價）

| 構成 | 損益 | 備註 |
|------|------|------|
| 金字塔加碼單（L_Add/S_Add 進場） | **+1,091K** | PF 2.0~2.7 — 策略核心 edge，加碼單獲利 > 首倉 |
| 首倉（L_Cmd/S_Cmd） | +323K | WR 僅 42~47%，PF 1.5 — 靠加碼放大才賺 |
| 游擊出場（*_Exit_G） | +899K | 100% WR（TP 出場，定義上必勝） |
| Trend Rev 停損出場 | **-560K** | 43 筆全虧，均 -13K/筆 — 結構性成本 |
| Cmd_Fast 快速單 | **-267K** | WR 僅 ~21% — 盤整日翻單來回打的主要出血點 |

**時段發現**：03:00-05:00 進場 PF 3.3~9.0（+618K，美股尾盤動能）；22:00-24:00 PF ~3（+461K）。**虧損時段：00:00-02:00（-31K）與 08:45-09:00 開盤噪音（-36K, PF 0.79）**。持倉 6-12hr 的單整體虧損（PF 0.82，跨時段卡盤整）。

---

### V38 v27 策略（2026-07-08 定版，`tv/TF_V38_v27.pine`）

**開發流程**：v26 pine 移植成本機 Python 引擎（`backtest/strategy_v26/engine_v26.py`，2024-01~2026-06 MXF 1分K，vs TV 逐筆驗證：進場 92% 配對、嚴格配對 pnl 差 +2.5%）→ 21+ 變體 A/B 測試 → TV 4.4 年全史終驗。

**v27 = v26 核心引擎不動 + 三個可開關機制：**

| 機制 | 預設 | 內容 | 依據 |
|------|------|------|------|
| ① TimeStop | 開 | 任一口持倉 ≥10hr（牆鐘時間）仍未獲利 → 下一開盤平該口 | 本機測 8~12hr 皆有效（6hr 有害）；trailing 替代方案（k=0.5~2.0 ATR）測過，全部不如硬平倉 |
| ② Cooldown | 開 | Trend Rev / Cmd_Fast 出場後 30 分鐘禁新首倉（加碼不受限） | 防盤整日雙巴鏈（6/11-12 型損失） |
| ③ OpenBlock | **關** | 08:45~08:59 禁新倉 | 低 DD 配置：MDD -23% 換淨利 -6%；開盤窗口可讓給策略 A 突破單（需先做 app.py 多策略部位隔離） |

**TV 全史終驗（2022-01 ~ 2026-07，MXF，兩版同日匯出對比）：**

| 指標 | v26 | v27 |
|------|-----|-----|
| 淨損益 | 5,499,610 | **5,524,040** (+0.4%) |
| PF | 1.518 | **1.535** |
| Sharpe(日) | 2.39 | **2.42** |
| MDD | -338,430 | -338,430（相同，2026-06-17） |
| 年度差異 | — | 2022 -3.8K / 2023 -1.4K / 2024 +51.6K / 2025 +14.5K / 2026 -36.4K |

**機制驗證**：TimeStop 117 筆出場實現 -224K（均 -1.9K/筆），換得 Trend Rev 虧損 -3,613K → -3,240K（**+374K**）— 滯留爛單提早認小賠、避免拖到趨勢翻轉賠大的，符合設計意圖。

**定位**：穩健性升級（尾部風險、留倉跳空風險、保證金佔用皆改善），非獲利升級。**換版時機：bot 空手時切換 TV alert**，避免持倉中換版。

---

### 策略 A：波動突破（backtest_breakout.py）

**資料：** MXF 1分K，2026-02-23 ~ 2026-05-23，74 個交易日  
**邏輯：** 觸發時間 K 棒開盤價 ± offset，價格突破才進場，TP/SL/TIMEOUT 三種出場

#### 各觸發時間最佳組合

| 觸發 | offset | target | stop | WR | 均獲利/筆 | Sharpe |
|------|--------|--------|------|----|----------|--------|
| 現貨開盤 09:00 | 5 | 100 | 50 | 47.5% | +143 | 3.21 |
| 現貨收盤 13:30 | 5 | 40 | 50 | 77.0% | +153 | 6.38 |
| **期貨日盤收 13:45** | **20** | **100** | **50** | **63.9%** | **+341** | **7.80** |

> 注意：期貨開盤 08:45 無結果，因資料最早從 08:46 開始。

#### 期貨日盤收 13:45 最佳組合月份穩定性（offset=20, target=100, stop=50）

| 月份 | 筆數 | WR | 累計損益 | 均獲利/筆 |
|------|------|----|---------|----------|
| 2026-02 | 4 | 75.0% | NT$1,620 | 405 |
| 2026-03 | 22 | 63.6% | NT$9,120 | 415 |
| 2026-04 | 20 | 65.0% | NT$5,010 | 250 |
| 2026-05 | 15 | 60.0% | NT$5,080 | 339 |
| **合計** | **61** | **63.9%** | **NT$20,830** | **341** |

**結論：** 13:45 期貨日盤收觸發完全壓制，月份穩定，無明顯崩潰月。

### 策略 B：固定進多 + 高掛 Limit（backtest_scalp.py）

**手續費：** 已含 4 點 round-trip（NT$40）

#### 最終最佳組合（方向濾網 + 停損）

| 觸發 | 方向濾網 | target | stop | tlim | 交易天 | TP率 | EV/筆 | Sharpe |
|------|---------|--------|------|------|--------|------|-------|--------|
| 09:00 | 08:46–08:59 收漲 | 20 | 無（純時間） | 15 分 | 33/74 | 97.0% | +118 | 7.81 |
| 08:46 | 夜盤收漲 (15:00–05:00) | 20 | 10 點 | 任意 | 30/74 | 73.3% | +80 | 9.41 |

**縮短時間的影響（09:00）：**
- 1–2 分鐘：TP 率 54–73%，EV 崩潰（開盤波動吃掉）
- 5 分鐘：TP 率 93.9%，EV +95，Sharpe 4.67
- 15 分鐘：最佳，TP 率 97%，EV +118，Sharpe 7.81

**固定停損的影響（09:00）：** 加任何固定 stop 都使 Sharpe 下降——開盤 1 分 K 震幅大，-10 點 stop 觸發率高達 45%。

**08:46 月份穩定性（target=20 stop=10）：**

| 月份 | 筆數 | TP率 | 損益 |
|------|------|------|------|
| 2026-02 | 3 | 66.7% | +180 |
| 2026-03 | 10 | 90.0% | +1,300 |
| 2026-04 | 10 | 70.0% | +700 |
| 2026-05 | 7 | 57.1% | +220 |

**結論：** 08:46 夜盤濾網版 Sharpe 略高（9.41），且最大單筆損失固定（-NT$140）。

---

## 11. 待辦事項

- [x] **回測資料：** 已完成，mxf_1min.csv 74 個交易日（2026-02-23 ~ 2026-05-23）
- [x] **策略 A 回測（波動突破）：** 已完成，結果見第 10 節
- [x] **帳戶餘額快照：** balance_log.csv 已部署，每日 13:46 / 05:01 自動觸發，手動 endpoint 已加入 app.py
- [x] **Streamlit dashboard：** 下方已改成帳戶餘額折線圖（equity 歷史趨勢）
- [x] **程式碼集中管理：** KevinYang515/tmf-bot repo 已建立（2026-06-07）
- [ ] **策略 B 回測（固定時間進單＋高掛幾 tick 掛賣）：** 待實作 backtest_scalp.py（已實作，待跑結果）
- [ ] **策略 C 回測（期貨開盤方向 → 個股當沖）：** 概念如下，詳細設計待後續 session
  - 訊號來源：MXF 08:45–08:59 這段如果是上漲 → 做多訊號
  - 進場：買入大型股（標的待定）
  - 出場：掛 limit 賣單在 entry + 3~5 tick
  - 方向延伸：也可用 NQ 早盤方向、或大週期 EMA 趨勢作為多空依據
  - 需要：個股 tick/1min 資料、決定標的池（台積電？ETF？）
- [x] **策略調整：** v26 夜盤游擊追蹤 1.5 ATR 已確認有效（MDD -47%，PF 1.37→1.53）
- [x] **v27 開發與終驗（2026-07-08）：** 本機 Python 引擎回測 21+ 變體 → TimeStop + Cooldown 存活 → TV 4.4 年全史確認無任何年度劣化（見 §10）。**待辦：bot 空手時把 TV alert 從 v26 切到 v27**
- [x] **MXF 升級（2026-07-08 執行）：** app.py 切 MXF、MAX_ABS_POS=3、未成交告警、下單後 Shioaji 部位對帳告警、排除 R1/R2 合約（見 §7B checklist）
- [ ] **60 秒反向訊號 debounce：** 現有 5 秒同 target dedup 保留，反向 debounce 未做
- [ ] **Failed 單自動 retry：** 目前僅告警不重試，MXF 一口漏單成本 5 倍，優先度提高
- [ ] **場外多單決策（非 hedge）：** FZF/PUF/PBF/VJF 浮虧 ~-313K、佔保證金 ~325K（2026-07-08）；留倉時 py=3 深 DD 會擠壓加碼保證金 — 用戶決定先跑、必要時補錢
- [ ] **P&L 核實：** 與永豐月結單對比確認系統損益計算正確（建議每月底執行）；MXF 首批成交後回填實際手續費率
- [ ] **MXF 首週監控：** 首筆成交確認合約=MXFG6、滑價量級、target_pos cap 行為（TV 送 4 → log 出現 [Cap]）

---

## 11. 常用指令速查

```bash
# 連 VM
ssh -i ~/.ssh/google_compute_engine -o StrictHostKeyChecking=no kevin850515123456789@35.212.129.240

# 查 bot 狀態
sudo supervisorctl status trading-app

# 看即時 log
sudo supervisorctl tail -f trading-app

# 手動觸發帳戶快照（TOKEN 要填）
curl -X POST "http://35.212.129.240:5000/api/balance/snapshot?token=YOUR_TOKEN"

# 手動 git pull/push（在 VM ~/stock 下）
git pull && git push

# 啟動 Streamlit（本機測試）
streamlit run streamlit_dashboard.py
```
