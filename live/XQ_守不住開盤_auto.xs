// ============================================================
// 守不住開盤 V8 — XQ 策略腳本 v4.6
// ============================================================
// ⚠️  必須建立為「策略」類型 (Position/SetPosition/MARKET 才有效)
//     XQ → 自動交易中心 → 交易策略 → 新增策略腳本
//
// v4.4→v4.5:
//   BUG FIX: Trail stop 不應在進場當根 bar 執行（Python 從 entry_bar 的下一根才開始）
//   加 JustEntered 旗標：進場當根設 1，下一根 bar 開頭重設 0
//   Trail stop 順序改回與 Python 一致：先 UPDATE RunningLow，再 CHECK High（UPDATE→CHECK）
//   原始順序才正確：先更新 running_low，再判斷 High >= cur_stop
// ============================================================

// v4.5→v4.6:
//   BUG FIX: SetPosition(0, CurrentStop) 立即把 Position 設為 0（即使限價單未成交）
//            導致 11:30 強平 (Position <> 0) 看不到殘留部位 → 隔夜未平倉
//   Trail stop 出場改用限價 SetPosition(0, CurrentStop)，對齊 Python exit_price = cur_stop
//   Trail stop 條件改為 Position < 0（SetPosition 後 Position 馬上歸零，自然只觸發一次）
//   11:30 強平改用 Filled <> 0（偵測實際未成交部位），SetPosition(0, MARKET) 強制覆蓋限價單
// ── 策略參數 ─────────────────────────────────────────────
input: EntryPct(0.0005);        // 從 MorningHigh 回落 0.05%
input: AorMaxPct(0.030);        // 早盤振幅上限 3%
input: MhToLimitMin(0.010);     // 距漲停至少 1%
input: GapMin(0.005);           // Gap up 下限 0.5%
input: GapMax(0.10);            // Gap up 上限 10%
input: PositionDollar(1000000); // 每檔預算 100 萬

// ── 狀態變數 ─────────────────────────────────────────────
var: MorningHigh(0);
var: DayOpen(0);
var: PrevClose(0);
var: LimitPrice(0);
var: GapPct(0);
var: Aor(0);
var: MhToLimit(0);
var: TriggerPrice(0);
var: HasEntry(0);       // 0=未進場, 1=已進場
var: JustEntered(0);   // 進場當根 bar=1，下一根 bar 開頭重設 0（trail stop 跳過進場 bar）
var: EntryPx(0);
var: EntryLots(0);
var: RunningLow(0);
var: CurrentStop(0);
var: CurTickSize(0);
var: StopCand(0);
var: InWindow(0);
var: TrigOK(0);
var: GapOK(0);
var: BarsFromOpen(0);  // [D3] 每日 Bar 計數 (1=09:00, 36=09:35, 151=11:30)

// ── 每 Bar 最開頭：重設進場旗標 ──────────────────────────
if JustEntered > 0 then JustEntered = 0;

// ══════════════════════════════════════════════════════════
// ① 隔日重置 + 開盤初始化  [D1/D2: 合併，避免 Time 格式問題]
//    Date <> Date[1] = 每日第一根 Bar，Open 即是開盤價
// ══════════════════════════════════════════════════════════
if Date <> Date[1] then begin
    MorningHigh  = 0;
    DayOpen      = 0;
    GapPct       = 0;
    LimitPrice   = 0;
    HasEntry     = 0;
    JustEntered  = 0;
    EntryPx      = 0;
    EntryLots    = 0;
    RunningLow   = 0;
    CurrentStop  = 0;
    GapOK        = 0;
    InWindow     = 0;
    TrigOK       = 0;
    BarsFromOpen = 0;

    // 第一根 Bar 的 Open = 開盤價，直接取 (不依賴 Time 格式)
    PrevClose  = CloseD(1);
    if Open > 0 and PrevClose > 0 then begin
        DayOpen    = Open;
        GapPct     = (DayOpen - PrevClose) / PrevClose;
        LimitPrice = PrevClose * 1.10;
    end;

    // [D4] 診斷 Alert: 確認 Time 格式 / CloseD / Gap 計算
    // 看執行 tab 的 Alert 輸出，T= 那個值就是 XQ 的 Time 格式
    Alert("INIT|" + Symbol + "|T=" + NumToStr(Time, 0) + "|O=" + NumToStr(DayOpen, 2) + "|PC=" + NumToStr(PrevClose, 2) + "|Gap=" + NumToStr(GapPct * 100, 2) + "%");
end;

// ── 每 Bar 計數 ──────────────────────────────────────────
BarsFromOpen = BarsFromOpen + 1;

// ══════════════════════════════════════════════════════════
// ② Gap 篩選
// ══════════════════════════════════════════════════════════
GapOK = 0;
if DayOpen > 0 and GapPct >= GapMin and GapPct <= GapMax then GapOK = 1;

// ══════════════════════════════════════════════════════════
// ③ 09:00-09:34 累積 MorningHigh  [D3: Bar 1-35]
// ══════════════════════════════════════════════════════════
if GapOK > 0 and BarsFromOpen >= 1 and BarsFromOpen <= 35 then begin
    if High > MorningHigh then MorningHigh = High;
end;

// ══════════════════════════════════════════════════════════
// ④ 動態 Tick Size
// ══════════════════════════════════════════════════════════
if Close < 10 then CurTickSize = 0.01;
if Close >= 10 and Close < 50 then CurTickSize = 0.05;
if Close >= 50 and Close < 100 then CurTickSize = 0.10;
if Close >= 100 and Close < 500 then CurTickSize = 0.50;
if Close >= 500 and Close < 1000 then CurTickSize = 1.00;
if Close >= 1000 then CurTickSize = 5.00;

// ══════════════════════════════════════════════════════════
// ⑤ 09:35-09:36 觸發偵測 + 進場  [D3: Bar 36-37]
// ══════════════════════════════════════════════════════════
InWindow = 0;
if GapOK > 0 and BarsFromOpen >= 36 and BarsFromOpen <= 37 then InWindow = 1;

if InWindow > 0 and HasEntry < 1 and MorningHigh > 0 then begin

    Aor          = MorningHigh / DayOpen - 1;
    MhToLimit    = (LimitPrice - MorningHigh) / MorningHigh;
    TriggerPrice = MorningHigh * (1 - EntryPct);

    TrigOK = 0;
    if Aor < AorMaxPct and MhToLimit >= MhToLimitMin and Low <= TriggerPrice then TrigOK = 1;

    if TrigOK > 0 then begin
        EntryLots = IntPortion(PositionDollar / (TriggerPrice * 1000));

        if EntryLots >= 1 then begin
            CurrentStop = MorningHigh + CurTickSize;
            StopCand    = LimitPrice  - CurTickSize;
            if StopCand < CurrentStop then CurrentStop = StopCand;

            EntryPx      = TriggerPrice;
            RunningLow   = TriggerPrice;
            HasEntry     = 1;
            JustEntered  = 1;   // 本 bar 不執行 trail stop，下一根 bar 才開始

            SetPosition(-EntryLots, TriggerPrice);

            Alert("ENTRY|" + Symbol + "|Bar=" + NumToStr(BarsFromOpen, 0) + "|" + NumToStr(EntryLots, 0) + "z|@" + NumToStr(TriggerPrice, 2) + "|aor=" + NumToStr(Aor * 100, 2) + "%|stop=" + NumToStr(CurrentStop, 2));
        end;
    end;
end;

// ══════════════════════════════════════════════════════════
// ⑥ Trail Stop  [v4.5: JustEntered 防護 + UPDATE→CHECK 順序（與 Python 一致）]
//    Python 邏輯: after = bars strictly AFTER entry bar
//      for bar in after:
//        if bar.Low < running_low: update running_low, cur_stop  ← 先 UPDATE
//        if bar.High >= cur_stop: exit at cur_stop               ← 後 CHECK
//    JustEntered = 1 讓進場當根 bar 跳過，下一根才開始執行
// ══════════════════════════════════════════════════════════
if HasEntry > 0 and JustEntered < 1 and Position < 0 then begin

    // Step 1 (UPDATE): 更新 RunningLow → 壓低 CurrentStop（鎖獲利）
    if Low < RunningLow then begin
        RunningLow  = Low;
        CurrentStop = RunningLow + CurTickSize;
        StopCand    = LimitPrice - CurTickSize;
        if StopCand < CurrentStop then CurrentStop = StopCand;
    end;

    // Step 2 (CHECK): 判斷當根 High 是否觸及（已更新的）CurrentStop
    if High >= CurrentStop then begin
        SetPosition(0, CurrentStop);   // 限價補回，對齊 Python 的 exit_price = cur_stop
        Alert("TRAIL|" + Symbol + "|stop=" + NumToStr(CurrentStop, 2));
    end;

end;

// ══════════════════════════════════════════════════════════
// ⑦ 11:30 強平  [D3: Bar 151 = 09:00+150min = 11:30]
// ══════════════════════════════════════════════════════════
if HasEntry > 0 and Filled <> 0 and BarsFromOpen >= 151 then begin
    SetPosition(0, MARKET);
    Alert("TIMEEXIT|" + Symbol + "|Bar=" + NumToStr(BarsFromOpen, 0));
end;

// ============================================================
// ⚠️  VERIFY LIST (若還有紅線)
// ============================================================
// IntPortion(x) → 若紅線改 Floor(x)
// MARKET        → 若紅線改 Market
// NumToStr(n,d) → 若紅線改 Text(n)
// CloseD(1)     → 若紅線改 Close[1] of data2
// ============================================================
