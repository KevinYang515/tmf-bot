// ============================================================
// 守不住開盤 V8 — XQ Script 自動下單版
// ============================================================
//
// 部署方式:
//   1. 把這支腳本「掛到」每一檔候選股 (用 XQ 的自動交易中心 → 加入監控)
//   2. 在自動交易中心設定: N_MAX=5 (最多同時 5 檔部位)
//   3. 設定執行帳號 (口袋 / 國泰 / 永豐, 看 XQ 支援哪家)
//   4. 啟動模擬交易先驗證 1-2 週
//   5. 通過後切到實盤
//
// 重要前提:
//   - 候選股名單由「另一支選股腳本」每日盤前產生 (gap up 0.5%~10%)
//   - 本腳本只處理單一商品的進場 / trail / 出場
//
// 限制:
//   - XS 無法跨腳本協調，所以「top-5 排序」要靠 XQ 自動交易中心的「最大同時部位 5」設定
//     (順序: 先觸發先進場，達上限後不再進場)
//   - Trail stop 用「自定義停損價」變數 + 定時 update
// ============================================================

// ── 策略參數 ──
input1: WaitMin(35);              // 09:35 開始監看
input2: EndMin(37);               // 09:37 截止
input3: EntryPct(0.05);           // 從 morning_high 回落 0.05%
input4: AorMaxPct(3.0);           // stock_aor 上限
input5: MhToLimitMinPct(1.0);     // mh_to_limit 下限
input6: GapMinPct(0.5);
input7: GapMaxPct(10.0);
input8: PositionDollar(1000000);  // 單檔部位金額 100 萬

// ── 狀態變數 ──
variable: MorningHigh(0), DayOpen(0), PrevClose(0);
variable: GapPct(0), Aor(0), MhToLimit(0), TriggerPrice(0), LimitPrice(0);
variable: Entered(false), EntryPrice(0), EntryQty(0);
variable: RunningLow(0), CurrentStop(0);
variable: ForceExited(false);

// ── 取得前一日收盤 ──
PrevClose = close[1] of data2;   // data2 = 日線

// ── 開盤價 ──
if Time = 900 and DayOpen = 0 then begin
    DayOpen = open;
    if PrevClose > 0 then
        GapPct = (DayOpen - PrevClose) / PrevClose * 100;
    LimitPrice = round(PrevClose * 1.1, 2);
end;

// ── Gap 過濾 (不符合就完全不做這檔) ──
if GapPct < GapMinPct or GapPct > GapMaxPct then exit;

// ── 09:00 - 09:35 累積 morning_high ──
if Time >= 900 and Time < (900 + WaitMin) then begin
    if high > MorningHigh then MorningHigh = high;
end;

// ── 09:35 - 09:37 trigger detection + 進場 ──
if Time >= (900 + WaitMin) and Time <= (900 + EndMin)
   and not Entered and MorningHigh > 0 and DayOpen > 0 then begin

    Aor = (MorningHigh / DayOpen - 1) * 100;
    MhToLimit = (LimitPrice - MorningHigh) / MorningHigh * 100;
    TriggerPrice = round(MorningHigh * (1 - EntryPct/100), 2);

    // 全部 filter 通過才進場
    if Aor < AorMaxPct
       and MhToLimit >= MhToLimitMinPct
       and low <= TriggerPrice then begin

        EntryQty = int(PositionDollar / (TriggerPrice * 1000));
        if EntryQty >= 1 then begin

            // 進場 SHORT (現股當沖賣出)
            // Trade.Open 是 XS 的下單函數 (依 XQ 版本可能略不同)
            //   side="Short" / "Sell"  ← 看 XQ 設定當沖 / 借券放空
            //   priceType="LMT"
            //   price=TriggerPrice
            //   qty=EntryQty (張)
            SetExitOnClose(true);   // 確保收盤前平倉 (current bar 不要長期持有)
            ShortNextBar(EntryQty * 1000, TriggerPrice, Limit);  // 賣空 EntryQty*1000 股
            EntryPrice = TriggerPrice;
            Entered = true;
            RunningLow = TriggerPrice;
            CurrentStop = MinValue(MorningHigh + 0.05,   // 1 tick (50元股=0.05; 高價股要動態算)
                                    LimitPrice - 0.05);

            Alert("ENTRY " + Symbol + " short@" + Text(TriggerPrice) +
                  " qty=" + Text(EntryQty) + " stop@" + Text(CurrentStop));
        end;
    end;
end;

// ── 進場後: Trail stop 邏輯 ──
if Entered and not ForceExited then begin

    // 新低 → trail stop 下移
    if low < RunningLow then begin
        RunningLow = low;
        CurrentStop = MinValue(RunningLow + 0.05,    // running_low + 1 tick
                                LimitPrice - 0.05);
    end;

    // ⚠️ 停損觸發 (high 突破 CurrentStop = 觸價)
    if high >= CurrentStop then begin
        BuyToCoverNextBar(EntryQty * 1000, CurrentStop, Limit);
        Alert("TRAIL EXIT " + Symbol + " @" + Text(CurrentStop));
        ForceExited = true;
    end;
end;

// ── 11:30 強制平倉 ──
if Entered and not ForceExited and Time >= 1130 then begin
    BuyToCoverNextBar(EntryQty * 1000, 0, Market);    // 市價回補
    Alert("TIME EXIT " + Symbol + " @ market");
    ForceExited = true;
end;

// ── 隔日重置 ──
if Date <> Date[1] then begin
    MorningHigh = 0;
    DayOpen = 0;
    GapPct = 0;
    Entered = false;
    EntryPrice = 0;
    EntryQty = 0;
    RunningLow = 0;
    CurrentStop = 0;
    ForceExited = false;
end;

// ============================================================
// ⚠️ XS 語法 verification 待辦:
//   - ShortNextBar / BuyToCoverNextBar 在 XQ 是否就是這個名稱?
//     (TradeStation EasyLanguage 是, XS 可能略有不同)
//   - tick size 0.05 是 50 元股, 高價股要動態算 (台股階梯)
//     真實上線前要寫一個 TickSize() function
//   - Order routing (現股當沖 vs 借券放空) 在 XQ 自動交易中心設定
// ============================================================
