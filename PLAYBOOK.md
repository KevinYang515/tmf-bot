# TMF 自動交易系統 Playbook

> 最後更新：2026-05-23  
> 適用：新 session 快速 onboarding、策略回顧、系統維護

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

- `tv/TF_V38_v20.pine` — 前一版
- `tv/TF_V38_v21.pine` — **當前部署版本**

### 策略核心邏輯（V38 系列）

- **商品：** MXF1!（5分K）
- **入場：** 60分K EMA 大趨勢濾網 + 本週期 EMA 多空判斷 + ADX（僅 L_Cmd 用，門檻 20）
- **加碼：** 最多 4 層（pyramiding=4），間距 ATR 倍數
- **日夜盤分流：** 日盤游擊追蹤 0.8 ATR，夜盤 1.5 ATR（夜盤洗盤大，需放寬）
- **v21 差異：** 移除 BE Stop（保本移停損）→ 改回 v3 出場邏輯，ADX 只套用 L_Cmd

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

## 7. 近期實盤績效（截至 2026-05-22）

| 指標 | 數值 |
|------|------|
| 交易天數 | 4 天（5/19–5/22） |
| 完成 FIFO round-trips | ~17 筆 |
| Win Rate | ~70.6% |
| 已實現損益 | +NT$10,730（FIFO 估算） |
| 市場環境 | 強勢上漲趨勢 |

**注意：** 4 天都在上漲趨勢，數據量太少，不足以評估策略。建議跑 1–3 個月（含橫盤、下跌段）再做定論。

### 目前帳戶狀態（2026-05-22 手動快照）

| 項目 | 金額 |
|------|------|
| 權益數 (equity) | NT$121,346 |
| 本日餘額 | NT$122,176 |
| 平倉損益 (交易所) | -NT$2,690 |
| 浮動損益 | -NT$830 |
| 可動用保證金 | NT$95,046 |

---

## 8. GitHub Repo 結構

```
KevinYang515/trading-dashboard (public)
└── logs/
    ├── trade_records.csv   ← 每筆成交後 push
    └── balance_log.csv     ← 每日兩次快照
```

Streamlit 透過 GitHub Contents API 讀取（base64 decode），cache TTL 60 秒。

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
│   ├── TF_V38_v21.pine     ← 當前部署策略
│   ├── TF_V38_v20.pine     ← 前一版備份
│   └── result/             ← TV 策略績效 CSV（v2~v27）
├── disposal-rubberband/    ← 另一套選股策略（TS-QAN）
├── logs/
│   ├── trade_records.csv
│   └── balance_log.csv
├── requirements.txt
├── supervisor.conf
└── .env                    ← 敏感資訊，不入 git
```

---

## 10. 待辦事項

- [ ] **回測資料：** 等期貨全收盤後（05:10 之後）在 VM 跑 `fetch_kbars.py`，然後 SCP 回 Cloud Shell 跑 `backtest_breakout.py`
- [ ] **策略驗證期限：** 跑 1–3 個月含不同行情，再決定是否擴大到小台（MTX）
- [ ] **P&L 核實：** balance_log 累積 2–3 週後，與永豐月結單對比確認系統損益
- [ ] **策略調整：** v21 的夜盤游擊追蹤 1.5 ATR 是否適當，需看回測結果定奪

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
