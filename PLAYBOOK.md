# TMF 自動交易系統 Playbook

> 最後更新：2026-06-20（新增 VM / 本機分工原則）
> 適用：新 session 快速 onboarding、策略回顧、系統維護

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

| 項目 | 微型台指 (MXF/TMF) | 小台指 (MTX) |
|------|-------------------|-------------|
| 代號 | TMF (shioaji), MXF! (TV) | MTX (TV) |
| 每點價值 | NT$10 | NT$50 |
| 最小跳動 | 1 點 | 1 點 |
| 手續費 round-trip | NT$40（4點） | NT$120（2.4點）約 |
| 策略最大口數 | 4 口 (1→2→3→4加碼) | 1 口 ≈ 5 MXF |

**手續費明細（永豐，已確認）：**
- 每單邊：期交稅 NT$8 + 手續費 NT$12 = NT$20
- Round-trip：NT$40 = 4 點（以 NT$10/點換算）

**目前不換小台的理由：** 加碼策略（1→2→3→4）若換成 MTX 最小單位是 5× MXF，破壞金字塔節奏；等策略驗證後再評估。

---

## 3. TradingView 策略（Pine Script）

### 版本

- `tv/TF_V38_v26.pine` — **當前部署版本（正式版）**
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

## 7. 近期實盤績效（截至 2026-06-06）

| 指標 | 數值 |
|------|------|
| 期間 | 2026-05-19 ~ 2026-06-06（約 2.5 週） |
| 完成 FIFO round-trips | 88 筆 |
| Win Rate | 73.9%（65W / 23L） |
| 已實現損益 | +NT$177,010（FIFO 計算） |
| Profit Factor | 3.44 |
| 均勝 / 均敗 | NT$3,839 / -NT$3,154 |
| 市場環境 | 強勢上漲趨勢（台指 40K → 42K+） |

**注意：** 2.5 週都在上漲趨勢，PF 3.44 >> 回測 1.53，代表市場條件極為有利，不代表長期表現。需跑到含橫盤、回檔段才能定論。

### 帳戶狀態（2026-06-07 05:01 夜盤快照）

| 項目 | 金額 |
|------|------|
| 權益數 (equity) | NT$201,373 |
| 昨日餘額 | NT$156,034 |
| 平倉損益 (交易所) | +NT$45,980 |
| 浮動損益 | NT$0 |
| 可動用保證金 | NT$201,373 |

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
- [ ] **P&L 核實：** 與永豐月結單對比確認系統損益計算正確（建議每月底執行）
- [ ] **MTX 升級評估：** 目前回測 PF 1.53 已達門檻，但實盤僅 2.5 週且全為上漲行情；建議再跑 2 個月（含回檔/橫盤）後再決定

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
