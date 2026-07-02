# Gap Burst Strategy — 試撮跳空慣性 Scalp

> 最後更新：2026-07-02（部署日）
> 狀態：**PAPER TRADE 中**（VM supervisor `trading-tmf-gap`，Shioaji simulation）
> 前身：`nq_strategy.py`（trading-tmf-nq，已退役，見文末）
> 給接手的 session/model：讀完本文件 + PLAYBOOK.md §0 就能接手。

---

## 1. 策略一句話

**開盤集合競價的跳空若是「最後一段時間的 surprise」（而非隔夜已消化的舊聞），開盤後有 1~3 分鐘的順向慣性 burst — 用試撮價在開盤前偵測，預掛市價單吃開盤價，TP+停損+時間上限快進快出。**

## 2. 定版參數（tick 級回測 2026-01~2026-07 定案）

| | 0845 日盤開盤 | 1500 夜盤開盤 |
|---|---|---|
| 參考收盤 | 夜盤收（今日 05:00 bar close） | 日盤收（今日 13:45 bar close） |
| surprise 窗口 | 05:00→08:45（3h45m，日韓開盤反應） | 13:45→15:00（75min，美股期貨） |
| 訊號 | 08:44:50 試撮價 vs 參考收 | 14:59:50 試撮價 vs 參考收 |
| 門檻 | \|gap\| ≥ **0.5%** | \|gap\| ≥ **0.3%** |
| 進場 | 預掛 ROD/MKP 順 gap 方向 1 口 TMF | 同左 |
| TP | fill **+80pt** LMT | fill **+100pt** LMT |
| 停損 | fill **-30pt**（tick 監控→MKP） | fill **-80pt** |
| 時間上限 | 開盤後 **300 秒**強制平倉 | 開盤後 **180 秒** |
| Backtest | n=19, EV **+281**/口, WR 57.9%, PF 2.87, worst -356 | n=24, EV **+251**/口, WR 70.8%, PF 2.57, worst -856 |
| 年化頻率 | ~38 次 | ~48 次 |

成本假設：滑價 5pt（進場）+ 手續費稅 5.6pt/回合，均已含在 EV。
停損滑價敏感度：+10pt 惡化 → EV +239, PF 2.24（edge 存活）。

## 3. 為什麼是這些參數 — 研究結論總表（別重複造輪子）

以下全部測過並**否決**，接手者不要再走回頭路：

| 想法 | 結果 | 為什麼死 |
|---|---|---|
| gap vs **前日日盤收** 當訊號 | 275 組合僅 0.4% 正 EV | 夜盤已消化，開盤價 priced in |
| KOSPI/NKX 當獨立訊號 | PF < 1.0 | 同上 — 高相關 ≠ 有 follow-through edge |
| 試撮 gap 當 V0 (NQ) 的 filter | PF 1.44~1.54，輸 KOSPI filter | 開盤價已反映，無增量資訊 |
| TP-only 不停損（高勝率） | 勝率 83~94% 但 EV 負/脆弱 | 負偏態：一筆凹到收盤 -5K~-7K 吃掉 5~7 筆 TP |
| 順 gap + trailing 全日持有 | PF 0.6~0.9 | 慣性只活 1~3 分鐘，其餘是隨機漫步 |
| tick 級加 trailing（取代或疊加 TP） | 15 種變體全輸 fixed TP | 秒級路徑雜訊 20~40pt，trail 在雜訊裡被踢出 |
| NQ 當 1500 的 filter | corr(gap,NQ)=0.70，加了反而降穩健度 | gap 本身就是 NQ 的聚合，冗餘 |
| 點數門檻取代 % 門檻 | 正 EV 組合比例全面較低 | burst 尺寸跟波動(%)成比例 |

**唯一活下來的結構**：surprise gap（vs 夜盤收/日盤收）+ 順向 + fixed TP + 停損 + 時間上限。
穩健度證據：0845 全組合 81% 正 EV、1500 帶停損組合 98% 正 EV，EV 矩陣平滑遞變（非孤峰）。

## 4. 為什麼散戶做得起（vs HFT）

- **進場 = 集合競價**：預掛市價單跟所有人拿同一個開盤撮合價，無速度競爭
- **TP = 躺簿 LMT**：晚 2 秒掛也無害（過價的限價單瞬間以更好價成交）
- **停損 = 唯一速度暴露**：tick→MKP 迴圈 ~0.2s，+10pt 滑價敏感度測試過活著
- Shioaji **沒有**觸價單/智慧單 API（永豐智慧單只在大戶投/eLeader），自建 tick 監控是唯一路

## 5. 部署細節

```
VM: 35.212.129.240  (gcloud compute ssh instance-20260515-172729 --zone=us-west1-b)
程式: ~/stock/gap_strategy.py  (repo: KevinYang515/tmf-bot)
Supervisor: trading-tmf-gap  (conf: /etc/supervisor/conf.d/trading-app.conf)
Cron: 每日 22:00 UTC restart（Shioaji token 日更），crontab 內 trading-tmf-gap
日誌: ~/stock/logs/gap_strategy.log (TimedRotating, 30天)
狀態: ~/stock/gap_state.json
帳號: Shioaji SIMULATION（.env 的 SJ_API_KEY/SJ_SECRET_KEY），與 V38 實盤完全隔離
```

**主迴圈時序**（時間全為 Taipei，程式內用 `now_tp()`，VM 是 UTC）：
```
08:42 / 14:57  prep 觸發 → kbars 抓參考收盤 → 訂閱 TMF tick
:44:30/:40/:45/:50 (或 :59:xx)  試撮快照 ×4 → 全部記入 gap_calibration.csv
:44:50 / :59:50  決策 → 過門檻就預掛 MKP
:45:00 / :00:00  開盤 → 捕捉第一筆真實 tick (=開盤價, 校準用)
+2s~12s  取 fill 價 → 掛 TP LMT → tick 停損監控啟動
+300s / +180s  時間上限 → 撤單 + MKP 平倉
```

**輸出 CSV**（在 VM `~/stock/logs/`）：
- `gap_calibration.csv` — **每天都寫**（不論觸發）：4 個試撮快照 + 實際開盤 + gap。用途見 §6
- `gap_trades.csv` — 每筆交易：方向/fill/出場原因/估 PnL

## 6. 接手者的任務清單

1. **每日看** `gap_strategy.log`：08:42~08:50、14:57~15:03 兩個窗口的行為是否正常
2. **首次觸發時驗證**：fill 價 vs 實際開盤價（滑價多少）、TP/停損/cap 行為是否照規格
3. **已知未驗證環節**：sim 帳號 pre-open 是否推送 simtrade tick（`tick.simtrade==1`）。若收不到，log 會顯示試撮 N/A 並 fallback 到 snapshot — 若 snapshot 在盤前也拿不到試撮價，需要改抓法（這是第一天最重要的檢查點）
4. **2~4 週後**：分析 `gap_calibration.csv` — 試撮 :30/:40/:45/:50 vs 實際開盤的偏差分布 → 決定最早可用的決策時點 + 門檻是否要留 buffer
5. **累積 10~20 筆後**：實測 EV vs 回測 EV（0845 +281 / 1500 +251）。因為跳過了 2025 OOS（user 決定），**paper trade 就是 OOS** — 若實測明顯低於回測，優先懷疑 2026 過擬合
6. **TMF 簿薄風險**：回測用 MXF tick 模擬 TMF 成交，paper trade 記錄的真實滑價是關鍵校準

## 7. Rollback

```bash
# 回復 NQ 策略（gap 策略下架）
sudo sed -i -e 's/program:trading-tmf-gap/program:trading-tmf-nq/' \
  -e 's|stock/gap_strategy.py|stock/nq_strategy.py|' \
  -e 's|tmf_gap|tmf_nq|g' /etc/supervisor/conf.d/trading-app.conf
crontab -l | sed 's/trading-tmf-gap/trading-tmf-nq/' | crontab -
sudo supervisorctl reread && sudo supervisorctl update
# 舊 conf 備份: /etc/supervisor/conf.d/trading-app.conf.bak_gapswap
```

## 8. 前身 nq_strategy 的結局（歷史）

- v2(B)：NQ 動能雙 session。1500 最後一週 3 進 3 停損 (-4,600)
- v4：0845 加 KOSPI filter（backtest Sharpe 7.43）— 部署 6 天零觸發，未經實測即被本策略取代
- 檔案保留：`nq_strategy.py`（repo + VM），`NQ_TMF_STRATEGY.md`
- NQ/KOSPI 研究的教訓已吸收進本策略：外圍指數的資訊會被開盤價 price in，**當 filter 有用、當訊號沒用**；而試撮 gap 連 filter 都不用 — 它本身就是聚合了所有外圍資訊的 surprise 量測

## 9. 回測重現

```
本機 D:\stock\tmf-bot\backtest\（python: stock312 env）
資料: gap_ticks\ (0845, 61天) / gap_ticks_1500\ (71天) — Shioaji api.ticks 抓的 MXF 開盤窗口
  重抓: scratchpad 的 fetch_gap_ticks.py / fetch_1500_ticks.py 模式（在 VM 跑, kbars 一次限 30 天）
主要腳本:
  gap_tick_sweep.py         0845 全網格 (275 組合 × 4 篩選)
  gap_tick_sweep_1500.py    1500 全網格 + NQ filter + %vs點數
  gap_with_stop_only.py     強制帶停損排行（定版依據）
  gap_add_trailing.py       trailing 疊加測試（全輸）
  gap_scalp_horizon.py      慣性壽命 (drift @ k分鐘 + MFE/MAE)
  gap_tponly*.py            TP-only 陷阱的完整拆帳
  stop_slip_sensitivity.py  停損滑價敏感度
```
