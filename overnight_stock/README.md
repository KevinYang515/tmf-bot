# 隔日沖即時策略 (overnight_stock)

> 與 TMF 完全隔離：不同子目錄、不同 cron、預設 SIMULATION=True (永豐 sandbox)
> 任何修改不會影響 ../app.py (TMF live trading)

## 策略

- 中型 50-300億 + F1+F2+F3 + 漲幅 ≥ 2% + 超大量 3x + NH20 突破 + 漲幅排名前 2
- 進場：當日尾盤 13:25-13:30 撮合
- 出場：隔日 09:00 開盤集合競價

回測 (扣費 0.357% 後):
- Sharpe 3.76, 年化 195.6%, DD -10.9%, 勝率 57.8%

## 檔案

```
overnight_stock/
├── overnight_live.py      # 主腳本 (buy / sell / status / dry)
├── fetch_finlab.py        # 抓 finlab EOD 資料
├── finlab_db/             # finlab 資料 (gitignored)
└── logs/                  # 交易紀錄 (gitignored)
```

## VM 部署

1. **拉 code**:
   ```bash
   cd ~/tmf-bot && git pull
   ```

2. **裝 finlab** (TMF 環境若已有 pip):
   ```bash
   ~/stock/bin/pip install finlab
   ```

3. **環境變數** (寫進 ~/.bashrc 或 systemd env):
   ```bash
   export SJ_API_KEY=...        # 與 TMF 共用
   export SJ_SECRET_KEY=...
   export FINLAB_TOKEN=...      # 若不放 env 會 fallback 到腳本內預設
   ```

4. **手動測試** (順序):
   ```bash
   # a. 抓資料
   cd ~/tmf-bot/overnight_stock && python fetch_finlab.py

   # b. 純計算 (不下單)
   python overnight_live.py dry

   # c. 連 sandbox 試 buy mode
   python overnight_live.py buy
   # 看是否出現 [sj] logged in 訊息 + 候選股 + 下單回報

   # d. 隔日試 sell mode
   python overnight_live.py sell
   ```

5. **cron 排程** (`crontab -e`):
   ```cron
   # 隔日沖：抓資料 (週一到五 03:00)
   0  3 * * 1-5  cd /home/USER/tmf-bot/overnight_stock && /home/USER/stock/bin/python fetch_finlab.py >> logs/fetch.log 2>&1

   # 13:25 算候選 + 下尾盤撮合單
   25 13 * * 1-5 cd /home/USER/tmf-bot/overnight_stock && /home/USER/stock/bin/python overnight_live.py buy >> logs/buy.log 2>&1

   # 09:00 開盤前下賣單
   55  8 * * 1-5 cd /home/USER/tmf-bot/overnight_stock && /home/USER/stock/bin/python overnight_live.py sell >> logs/sell.log 2>&1
   ```

   *注：sell 設 08:55 是預留時間讓集合競價單進入 09:00 cross。*

## 從 SIMULATION 切到 LIVE

當 paper trade 結果穩定 (Sharpe > 2、勝率 > 55%、滑價 < 15 bps) 後：

1. 編輯 `overnight_live.py`，設 `SIMULATION = False`
2. 補環境變數 `SJ_CA_PATH`, `SJ_CA_PASS`, `SJ_PERSON_ID` (TMF 已有的可共用)
3. 小額測試 (改 `CAPITAL = 100000` 先跑一週)

## 與 TMF 共存注意

- TMF 用 `api.futopt_account`, 此策略用 `api.stock_account` → 帳戶獨立
- TMF webhook 隨時觸發, 此策略 cron 固定時點 → 互不干擾
- SIMULATION=True 時連永豐 sandbox, 完全不會碰到 TMF live 帳戶

## Log 檔位置

- `logs/buy_YYYY-MM-DD.csv` — 每日候選 + 委託紀錄
- `logs/sell_YYYY-MM-DD.csv` — 每日賣出委託
- `logs/fetch.log` / `logs/buy.log` / `logs/sell.log` — cron 標準輸出
