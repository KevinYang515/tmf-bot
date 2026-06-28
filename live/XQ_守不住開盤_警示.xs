// ============================================================
// 守不住開盤 V8 — XQ Script 警示版 (半自動)
// ============================================================
// 用途:
//   1. 09:00-09:35 自動追蹤每檔的早盤最高價 (morning_high)
//   2. 09:35-09:37 偵測「Low <= morning_high * 0.9995」觸發訊號
//   3. 觸發時用 Alert() 彈跳警示 (聲音 + 視窗)
//   4. 使用者手動下單，並掛智慧停損單
//
// 部署:
//   1. 把這支腳本加到 XQ 的「警示」群組
//   2. 設定「選股」範圍 (gap up 0.5%~10% 的當日候選名單)
//   3. 開盤後自動執行
//
// 注意:
//   - XQ Script (XS) 不能自動下單，只能警示
//   - Trail stop 必須手動或半自動 (XQ「條件單」可設「跌破當日低點 1%」等動態停損)
//   - 建議搭配 XQ「智慧單」: 進場同時掛「OCO 觸價單」
// ============================================================

// ── 參數 ──
input1: WaitMin(35, "monitor 起始分鐘");        // 09:35
input2: EndMin(37, "monitor 截止分鐘");          // 09:37
input3: EntryPct(0.05, "從 morning_high 回落 %");
input4: AorMaxPct(3.0, "stock_aor 上限 %");
input5: MhToLimitMinPct(1.0, "mh_to_limit 下限 %");
input6: GapMinPct(0.5, "gap_pct 下限 %");
input7: GapMaxPct(10.0, "gap_pct 上限 %");

// ── 變數 ──
variable: MorningHigh(0), DayOpen(0), AlertSent(false);
variable: GapPct(0), Aor(0), MhToLimit(0), TriggerPrice(0);
variable: LimitPrice(0), PrevClose(0);

// ── 取得前一日收盤 (用 1-day timeframe) ──
PrevClose = close[1] of data2;   // data2 = 日線

// ── 開盤後第一筆 K = 開盤價 ──
if Time = 900 and DayOpen = 0 then DayOpen = open;

// ── 漲停價 (台股 10%) ──
LimitPrice = round(PrevClose * 1.1, 2);

// ── gap 過濾 ──
if DayOpen > 0 and PrevClose > 0 then begin
    GapPct = (DayOpen - PrevClose) / PrevClose * 100;
end;

// ── 09:00 - 09:WaitMin 累積 morning_high ──
if Time >= 900 and Time < (900 + WaitMin) then begin
    if high > MorningHigh then MorningHigh = high;
end;

// ── 09:WaitMin - 09:EndMin trigger detection ──
if Time >= (900 + WaitMin) and Time <= (900 + EndMin) and not AlertSent then begin

    if MorningHigh > 0 and DayOpen > 0 then begin
        Aor = (MorningHigh / DayOpen - 1) * 100;
        MhToLimit = (LimitPrice - MorningHigh) / MorningHigh * 100;
        TriggerPrice = MorningHigh * (1 - EntryPct/100);

        // 所有過濾條件
        if GapPct >= GapMinPct and GapPct <= GapMaxPct
           and Aor < AorMaxPct
           and MhToLimit >= MhToLimitMinPct
           and low <= TriggerPrice then begin

            Alert(
                "守不住開盤觸發: " + Symbol + Text(Time:5:0) +
                " gap=" + Text(GapPct:5:2) + "%" +
                " aor=" + Text(Aor:5:2) + "%" +
                " mh=" + Text(MorningHigh:7:2) +
                " trigger=" + Text(TriggerPrice:7:2) +
                " limit=" + Text(LimitPrice:7:2)
            );
            AlertSent = true;

            // 提示要掛的停損價
            print(
                "→ " + Symbol + " SHORT @ " + Text(TriggerPrice:7:2) +
                " | 停損價 (掛智慧觸價單買回): " +
                Text(MinValue(MorningHigh + 0.5,   // 假設 tick=0.5
                              LimitPrice - 0.5):7:2)
            );
        end;
    end;
end;

// ── 重置 (隔日) ──
if Date <> Date[1] then begin
    MorningHigh = 0;
    DayOpen = 0;
    AlertSent = false;
end;
