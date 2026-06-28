// ============================================================
// 守不住開盤 V8 — XQ Script 自動下單版 (修正版 v2)
// ============================================================
//
// ⚠️ 重要前置說明
// 此腳本根據 XQ 官方文件已知語法撰寫，但有以下不確定處需在 XQ 編輯器內驗證：
//   - SetPosition 完整參數簽名
//   - Short / Cover 函數的具體用法
//   - CloseD(N) 取前 N 日收盤
//   - 觸發停損的最佳寫法
//
// 強烈建議:
//   1. 用 XQ XS 編輯器開新腳本
//   2. 把這個邏輯複製進去，編輯器會自動 syntax check
//   3. 若有紅線，貼到 ChatGPT / 我，幫你修正
//
// 部署:
//   1. 每日 08:50 用 XQ_守不住開盤_選股.xs 篩選 gap up 候選股
//   2. 把這個策略 attach 到候選股觀察清單
//   3. 自動交易中心: 最大部位 = 5 (= N_MAX)
//   4. 模擬交易跑 1-2 週驗證後再切實盤
// ============================================================

// ── 策略參數 (input 讓使用者可在 GUI 調) ──
input: WaitMin(35);              // 09:35 開始監看
input: EndMin(37);               // 09:37 截止
input: EntryPct(0.0005);         // 從 morning_high 回落 0.05%
input: AorMaxPct(0.030);         // stock_aor 上限 3.0%
input: MhToLimitMin(0.010);      // mh_to_limit 下限 1.0%
input: GapMin(0.005);            // gap_pct 下限
input: GapMax(0.10);             // gap_pct 上限
input: PositionDollar(1000000);  // 單檔部位金額 100 萬
input: ForceExitTime(1130);      // 11:30 強平

// ── 狀態變數 ──
var: MorningHigh(0), DayOpen(0), PrevClose(0);
var: GapPct(0), Aor(0), MhToLimit(0), TriggerPrice(0), LimitPrice(0);
var: HasEntry(false), EntryPrice(0), EntryQty(0);
var: RunningLow(0), CurrentStop(0);

// ── 取得前一日收盤 (XS 內建 CloseD) ──
PrevClose = CloseD(1);    // 1 = 前一日

// ── 第一筆 K = 開盤價 ──
if Time = 900 and DayOpen = 0 and open > 0 then begin
    DayOpen = open;
    if PrevClose > 0 then GapPct = (DayOpen - PrevClose) / PrevClose;
    LimitPrice = round(PrevClose * 1.10, 2);
end;

// ── Gap 範圍 filter (不符合就 exit 該根 K 處理) ──
if GapPct < GapMin or GapPct > GapMax then exit;

// ── 09:00 - 09:35 累積 morning_high ──
if Time >= 900 and Time < (900 + WaitMin) then begin
    if high > MorningHigh then MorningHigh = high;
end;

// ── 09:35 - 09:37 trigger detection + 進場 ──
if Time >= (900 + WaitMin) and Time <= (900 + EndMin)
   and not HasEntry and MorningHigh > 0 and DayOpen > 0 then begin

    Aor = (MorningHigh / DayOpen - 1);
    MhToLimit = (LimitPrice - MorningHigh) / MorningHigh;
    TriggerPrice = round(MorningHigh * (1 - EntryPct), 2);

    // V8 全部 filter
    if Aor < AorMaxPct and MhToLimit >= MhToLimitMin and low <= TriggerPrice then begin

        EntryQty = floor(PositionDollar / (TriggerPrice * 1000));
        if EntryQty >= 1 then begin
            // 進場 SHORT
            // XQ 推薦寫法: SetPosition(-1, ...) target 是負部位
            // 或: Short(qty, price, "Limit")
            // ⚠️ 真實語法請在 XQ 編輯器內驗證
            SetPosition(-EntryQty, TriggerPrice);   // 預設限價

            EntryPrice = TriggerPrice;
            HasEntry = true;
            RunningLow = TriggerPrice;
            CurrentStop = MinValue(MorningHigh + 0.05,     // 1 tick (要動態算)
                                    LimitPrice - 0.05);

            Alert("ENTRY " + Symbol + " short " + Text(EntryQty) +
                  "張 @" + Text(TriggerPrice) +
                  " stop=" + Text(CurrentStop));
        end;
    end;
end;

// ── 進場後: Trail stop 邏輯 ──
if HasEntry and Position = -EntryQty then begin

    // 新低 → trail stop 下移 (running_low + 1 tick)
    if low < RunningLow then begin
        RunningLow = low;
        CurrentStop = MinValue(RunningLow + 0.05,
                                LimitPrice - 0.05);
    end;

    // ⚠️ 高點突破 CurrentStop → 觸發停損 (回補)
    if high >= CurrentStop then begin
        SetPosition(0, CurrentStop);   // 目標部位 0 = 平倉
        Alert("TRAIL EXIT " + Symbol + " @" + Text(CurrentStop));
    end;
end;

// ── 11:30 強制平倉 ──
if HasEntry and Position <> 0 and Time >= ForceExitTime then begin
    SetPosition(0, Market);             // 市價回補
    Alert("TIME EXIT " + Symbol + " @market");
end;

// ── 隔日重置 (用日期變化判斷) ──
if Date <> Date[1] then begin
    MorningHigh = 0;
    DayOpen = 0;
    GapPct = 0;
    HasEntry = false;
    EntryPrice = 0;
    EntryQty = 0;
    RunningLow = 0;
    CurrentStop = 0;
end;

// ============================================================
// ⚠️ 待 XQ 編輯器驗證的細節
// 1. SetPosition 的價格參數: 直接傳 price 還是 (price, "Limit"/"Market")?
// 2. Short / Cover 是不是 SetPosition 之外的替代寫法?
// 3. tick size 0.05 hardcoded 是錯的, 高價股不對 (要寫 GetTickSize())
// 4. Alert 是否支援字串接 (用 + 還是 ,)
// 5. floor() 是否內建 (或要用 int())
// 6. MinValue() 是否內建
// 7. CloseD(1) 是否就是前一日收盤
// 8. Time 格式 (HHMM 還是 HHMMSS)
// 9. 現股當沖 / 借券放空: 在 XQ 自動交易中心設定, 腳本內不需處理
// ============================================================
