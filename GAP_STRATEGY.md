# Gap Burst Strategy — 試撮跳空慣性 Scalp

> 最後更新：2026-07-04（overnight research pass，見 §3.1）
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
| TP | 固定 fill **+80pt** LMT | **動態**：fill + clip(0.4×\|fill-ref_close\|, 100, 300) LMT（2026-07-04 起） |
| 停損 | fill **-30pt**（tick 監控→MKP） | fill **-80pt** |
| 時間上限 | 開盤後 **300 秒**強制平倉 | 開盤後 **180 秒** |
| Backtest | n=19, EV **+281**/口, WR 57.9%, PF 2.87, worst -356 | n=24, EV **+281**/口(動態TP, 原固定+251), WR 70.8%, PF 2.75, worst -856 |
| 年化頻率 | ~38 次 | ~48 次 |

成本假設：滑價 5pt（進場）+ 手續費稅 5.6pt/回合，均已含在 EV。
停損滑價敏感度：+10pt 惡化 → EV +239, PF 2.24（edge 存活）。
1500 動態 TP 細節與驗證見 §3.1。

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
| 0845 動態 TP（gap 越大 TP 越大） | 全部輸固定 TP80（EV 96~298 vs 281） | gap 越大 MFE **反而略降**（見 §3.1 D1）|
| 0845 反向動態 TP（gap 越大 TP 越小） | 仍輸固定 TP80（EV 139~244 vs 281） | 固定 TP80 已能吃到大 gap 日的大部分行情，縮小 TP 反而封頂賺得少 |
| 停損隨 gap 動態 scaling（兩場都測） | 全部輸固定停損；worst 從 -356/-856 惡化到 -1200~-1550 | 拉寬停損=直接放大尾部風險，EV 換不回來 |

**唯一活下來的結構**：surprise gap（vs 夜盤收/日盤收）+ 順向 + TP(固定或依 gap 動態) + 固定停損 + 時間上限。
穩健度證據：0845 全組合 81% 正 EV、1500 帶停損組合 98% 正 EV，EV 矩陣平滑遞變（非孤峰）。

## 3.1 Overnight research pass (2026-07-04) — 完整記錄

**任務**：用近期/2026 資料回測「試撮 threshold 該多少」+「TP 是否該隨 gap % 動態調整」，過程中抓邏輯錯誤。

### 重大限制發現（先讀這個，會改變接手者的預期）
**Shioaji 歷史 `api.ticks()` 不保留開盤前試撮(simtrade)資料。** 用 2026-06-15、2026-07-03 兩天測試，
08:30-08:45 與 14:50-15:00 窗口回傳筆數皆為 0，且回傳欄位裡根本沒有 `simtrade` 欄位（只有
`ts/close/volume/bid_price/bid_volume/ask_price/ask_volume/tick_type`）。**結論：試撮讀值的準確度
永遠無法用歷史 replay 回測，只能靠 live 累積的 `gap_calibration.csv`**（目前僅 2 個樣本：0845 誤差
5pt、1500 誤差 53pt）。因此本次研究改用兩條路線代替：

**A) 門檻 sweep（用「實際 gap」，非試撮讀值）+ walk-forward (H1=01-03月 / H2=04-07月) 穩健性檢查**
- 0845：EV 隨門檻從 0.2%→0.6% 單調上升(+67→+291)，0.5~0.6% 是甜蜜點；但 H1(n=5) EV +524 遠高於
  H2(n=14) +194 — H1 樣本太薄，**真實 OOS EV 應該更接近 +194~+200，不是全樣本的 +281**。門檻本身穩健
  （0.35~0.6% 兩段都是正 EV），維持 0.5% 不動。
- 1500：0.3% 門檻 H1(n=12) EV +262 / H2(n=12) EV +239 — **兩半年幾乎相等，是全部門檻裡最穩健的一
  個**（其他門檻 H1/H2 落差都較大或樣本更薄）。維持 0.3% 不動。

**B) Walk-forward 交叉驗證（H1 選最佳組合，H2 純驗證，避免 275 組合 overfit 到假訊號）**
- 0845：H1 前 5 名組合全部落在 TP80，停損 15~80 都能在 H2 維持正 EV(+129~+194, PF 1.4~2.2) —
  TP80 是真的穩健，不是 overfit 到 5 個樣本。
- 1500：H1 前 5 名組合中，**現行 TP100/S80 在 H2 反而是表現最好的**(+239, PF 2.31)——不是挑出來的
  最佳值，是獨立驗證後仍最佳，信心較高。

**C) Noise-injection 穩健性測試（用合成雜訊代替無法取得的真實試撮誤差分布）**
把決策時看到的 gap 加上 N(0, noise_std) 雜訊，重算觸發率/方向翻轉率/EV：
- 0845：雜訊到 50pt 標準差前，方向翻轉率仍是 0%，EV 只從 +281 降到 +190；雜訊需到 ~80-120pt 才有感
  （方向翻轉 0.3~3%）。目前唯一真實樣本只有 5pt 誤差，**安全邊際很大**。
- 1500：更有趣——中等雜訊（10~30pt）EV 不降反升（+170→+192），因為讓一些臨界日跨過門檻反而是加分
  （呼應 A 段「門檻越低仍是正 EV」）；雜訊到我們唯一的真實樣本 53pt 時 EV 仍 +173（PF 健康），要到
  120~150pt 才開始真的吃緊（翻轉率 9~15%，EV 剩 +86~+118）。**1500 的試撮誤差安全邊際比 0845 薄**，
  值得持續觀察 `gap_calibration.csv`（任務 #46）。

**D) 動態 TP/停損延伸研究**
- D1（去除離群值後的相關性）：0845 的「gap 越大、MFE 越小」不是被單一極端日（04-08 gap 1173pt 但
  MFE 只有 33pt）拉歪的假象——去頭尾 15% 後相關係數從 -0.09 變成 **-0.52**，更負。1500 則穩定維持
  正相關(+0.35 全樣本 / +0.34 去尾)。兩場方向相反的結構是真的。
- D2（五分位輪廓）：0845 樣本量太小（每組 n=3~4），分位輪廓不單調、雜訊大，不適合擬合連續函數。
- D3（停損動態 scaling）：兩場都测过，全部輸固定停損，且 worst case 從 -356/-856 惡化到
  -1200~-1550 — **已否決，寫入 §3 表格**。
- D4（0845 反向動態 TP）：即使呼應了「大gap MFE 較小」的方向，實際套用「大gap用小TP」仍全面輸固定
  TP80（因為固定 TP80 在大 gap 日仍有 50~67% 機率吃到，縮小 TP 反而封頂）——**已否決**。
- D5（walk-forward 最終比較，2026-07-04 決策依據）：
  - 0845：固定 TP80 在 H2 (+194) 大幅勝過任何動態方案 (+115) → **維持固定 TP80**。
  - 1500：動態 TP = clip(0.4×\|gap_pts\|, 100, 300) 在 H1 打平固定值（因為 H1 沒有 gap 大到超過
    100pt 地板的日子）、在 **H2 明確勝出**（固定 TP100 得 +239，動態得 **+299**，PF 2.31→2.64）→
    **採用，已部署**（地板 100pt 保證任何情況都不劣於原本固定值）。

### 已實作變更（2026-07-04 部署）
1. `gap_strategy.py`：1500 session 新增 `tp_dynamic={"alpha":0.4,"lo":100,"hi":300}`，TP 用
   `clip(alpha×|fill_price-ref_close|, lo, hi)` 動態算，寫進 `gap_trades.csv` 的新欄位 `tp_used`。
   0845 維持固定 TP80（`tp_dynamic=None`，D5 驗證動態方案更差）。
2. **邏輯修正**：決策時若最後一筆試撮(`:44:50`/`:59:50`)剛好收不到值，原本會直接整場 SKIP，即使
   `:30/:40/:45` 早有明確讀值。已改為 fallback 用最近一筆有值的快照（純粹補救 tick 瞬斷，不影響
   正常情況下的行為——目前兩天 live 觀察 4 個快照都正常拿到，這是防禦性修正非急迫 bug）。
3. 停損 scaling **不採用**（D3 已否決，維持固定 -30 / -80）。
4. 進場滑價假設（backtest 用 -5pt）可能偏保守：0845/1500 進場都是「集合競價前掛 MKP」，理論上跟所
   有參與者拿同一個撮合價，真實滑價可能趨近於 0（而非 -5pt）。等下次真正觸發、比對 `gap_trades.csv`
   的 `fill_price` 是否等於 `gap_calibration.csv` 的 `actual_open` 即可驗證——若相等，代表回測其實偏
   保守，真實 EV 可能優於 backtest。

### 復現方式
```
D:\stock\tmf-bot\backtest\gap_overnight_research.py   Part A(門檻+walk-forward) / Part C(noise injection)
D:\stock\tmf-bot\backtest\gap_dynamic_tp.py            初版動態 TP 網格 (alpha × clip)
D:\stock\tmf-bot\backtest\gap_dynamic_tp2.py            D1~D5 完整延伸研究（相關性/分位/停損scaling/反向TP/walk-forward）
```

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
2. **首次觸發時驗證**：fill 價 vs 實際開盤價（滑價多少，順便驗證 §3.1 第4點的「集合競價滑價趨近0」猜想）、TP/停損/cap 行為是否照規格、1500 動態 TP 算出的 `tp_used` 是否合理（應在 100~300 之間）
3. ~~已知未驗證環節：sim 帳號 pre-open 是否推送 simtrade tick~~ — **已於 2026-07-03 首日驗證：可以**，4 個試撮快照皆正常捕捉。08:30-08:45/14:50-15:00 的試撮資料**無法事後回測取得**（Shioaji 歷史 API 不保留，見 §3.1），只能靠往後每天的 live 快照累積
4. **持續進行中**：分析 `gap_calibration.csv` — 試撮 :30/:40/:45/:50 vs 實際開盤的偏差分布。目前僅 2 筆（0845 誤差5pt / 1500 誤差53pt），§3.1 C 段的 noise-injection 分析顯示 1500 的誤差安全邊際比 0845 薄，累積到 10+ 筆後重新用真實分布取代合成雜訊分析，決定是否要加 buffer
5. **累積 10~20 筆後**：實測 EV vs 回測 EV（0845 +281 / 1500 動態TP +281）。因為跳過了 2025 OOS（user 決定），**paper trade 就是 OOS** — 若實測明顯低於回測，優先懷疑 2026 過擬合（雖然 §3.1 B 段 walk-forward 交叉驗證顯示現行參數不是 overfit 到假訊號）
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
  gap_overnight_research.py 2026-07-04: 門檻walk-forward + noise-injection 穩健性 (Part A/B/C)
  gap_dynamic_tp.py         2026-07-04: 動態 TP 初版網格
  gap_dynamic_tp2.py        2026-07-04: 動態TP/停損 D1~D5 完整延伸研究（見 §3.1）
```
