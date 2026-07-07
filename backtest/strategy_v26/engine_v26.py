# -*- coding: utf-8 -*-
"""
V38 v26 Session 策略 Python 移植 (5分K 引擎, 忠實復刻 TF_V38_v26_0623.pine)

執行模型 (對齊 TradingView, 無 bar magnifier):
- 訊號於 5分K 收盤計算, 市價單 (entry / close) 於下一根開盤成交
- stop / trail 出場單盤中成交, bar 內路徑用 TV heuristic:
  high-open < open-low → O→H→L→C, 否則 O→L→H→C
- intrabar_mode="1min" 時改用 1分K 路徑 (更貼近真實)
- trail_points = 啟動獲利門檻 (由該口成交價起算), trail_offset=1 點
"""
import numpy as np
import pandas as pd

POINT_VALUE = 50.0   # MXF
COMMISSION = 20.0    # per side per contract

P = dict(  # v26 預設參數
    l_emaLenLong=130, l_cmdExitLen=50, s_cmdExitLen=40, l_emaLenShort=125,
    g_trailMultDay=0.8, g_trailMultNight=1.5,
    fastEmaLen=35, g_slMult=200.0,
    adxLen=14, adxThresh=20,
    l_slMult=3.0, l_trailBase=5.0, l_trailAdd=3.8, l_pyramid_dist=1.2,
    be_trigger=2.0,
    s_slMult=2.5, s_trailMult=3.0, s_pyramid_dist=1.0,
    addLossL=5.0, addLossS=4.5,
    # ── 優化開關 (baseline 全關) ──
    opt_block_open=False,      # 開盤 08:45-08:59 禁新倉 (hour==8)
    opt_block_h0=False,        # 00:00-00:59 禁新倉
    opt_cooldown_min=0,        # Trend Rev / Cmd_Fast 出場後 N 分鐘禁首倉
    opt_cooldown_scope="both", # "both" | "trev" (只在 Trend Rev 後冷卻)
    opt_adx_short=False,       # S_Cmd 也套 ADX 濾網
    opt_stale_hr=0,            # 持倉超過 N 小時且未獲利 → 觸發滯留處理 (0=off)
    opt_stale_mode="close",    # "close"=下一開盤平倉 | "trail"=改掛追蹤停損
    opt_stale_trail_atr=1.0,   # trail 模式: stop = close ∓ k*ATR, 逐 bar 棘輪收緊
)


def load_1min(path):
    df = pd.read_csv(path, parse_dates=["ts"])
    df = df.rename(columns=str.lower).sort_values("ts").reset_index(drop=True)
    df["open_ts"] = df["ts"] - pd.Timedelta(minutes=1)  # ts 為 bar 結束時間
    return df


def build_bars(df1m, minutes):
    """session 對齊聚合: 日盤錨 08:45, 夜盤錨 15:00 (皆落在 5/60 分邊界)"""
    t = df1m["open_ts"]
    if minutes == 5:
        bin_open = t.dt.floor("5min")
    else:  # 60min: 日盤錨 08:45 需偏移 45 分
        is_day = (t.dt.hour >= 8) & (t.dt.hour <= 13)
        shifted = t - pd.Timedelta(minutes=45)
        day_bin = shifted.dt.floor("60min") + pd.Timedelta(minutes=45)
        night_bin = t.dt.floor("60min")
        bin_open = day_bin.where(is_day, night_bin)
    g = df1m.groupby(bin_open)
    bars = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(),
        "low": g["low"].min(), "close": g["close"].last(),
        "close_ts": g["ts"].max(),
    })
    bars.index.name = "open_ts"
    return bars.reset_index()


def pine_ema(s, length):
    return s.ewm(span=length, adjust=False).mean()


def pine_rma(s, length):
    return s.ewm(alpha=1.0 / length, adjust=False).mean()


def atr(bars, length=14):
    pc = bars["close"].shift(1)
    tr = pd.concat([bars["high"] - bars["low"],
                    (bars["high"] - pc).abs(),
                    (bars["low"] - pc).abs()], axis=1).max(axis=1)
    return pine_rma(tr, length)


def adx(bars, length=14):
    up = bars["high"].diff()
    dn = -bars["low"].diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = bars["close"].shift(1)
    tr = pd.concat([bars["high"] - bars["low"],
                    (bars["high"] - pc).abs(),
                    (bars["low"] - pc).abs()], axis=1).max(axis=1)
    atr_ = pine_rma(tr, length)
    plus_di = 100 * pine_rma(pd.Series(plus_dm, index=bars.index), length) / atr_
    minus_di = 100 * pine_rma(pd.Series(minus_dm, index=bars.index), length) / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return pine_rma(dx.fillna(0), length)


def prepare(df1m, p):
    b5 = build_bars(df1m, 5)
    b60 = build_bars(df1m, 60)
    b5["ema_long"] = pine_ema(b5["close"], p["l_emaLenLong"])
    b5["ema_short"] = pine_ema(b5["close"], p["l_emaLenShort"])
    b5["ema_fast"] = pine_ema(b5["close"], p["fastEmaLen"])
    b5["ema_cmd_l"] = pine_ema(b5["close"], p["l_cmdExitLen"])
    b5["ema_cmd_s"] = pine_ema(b5["close"], p["s_cmdExitLen"])
    b5["ema10"] = pine_ema(b5["close"], 10)
    b5["ema30"] = pine_ema(b5["close"], 30)
    b5["atr"] = atr(b5, 14)
    b5["adx"] = adx(b5, p["adxLen"])
    b5["hh20_prev"] = b5["high"].rolling(20).max().shift(1)
    b5["ll20_prev"] = b5["low"].rolling(20).min().shift(1)

    # MTF 60分: lookahead_off → 5分bar 取「收盤時間 <= 該5分bar收盤時間」的最後一根已完成60分bar
    b60["mtf_bull"] = b60["close"] > pine_ema(b60["close"], p["l_emaLenLong"])
    b60["mtf_bear"] = b60["close"] < pine_ema(b60["close"], p["l_emaLenShort"])
    idx = np.searchsorted(b60["close_ts"].values, b5["close_ts"].values, side="right") - 1
    b5["mtf_bull"] = np.where(idx >= 0, b60["mtf_bull"].values[np.clip(idx, 0, None)], False)
    b5["mtf_bear"] = np.where(idx >= 0, b60["mtf_bear"].values[np.clip(idx, 0, None)], False)

    b5["hour"] = b5["open_ts"].dt.hour
    return b5


def _segments(o, h, l, c):
    """TV 無 magnifier 的 bar 內路徑假設"""
    if (h - o) < (o - l):
        return [(o, h), (h, l), (l, c)]
    return [(o, l), (l, h), (h, c)]


class Lot:
    __slots__ = ("kind", "entry_px", "entry_ts", "trail_act", "trail_on",
                 "peak", "loss_stop", "be_stop", "bracket_live", "stale_stop", "tv_id")

    def __init__(self, kind, entry_px, entry_ts, bracket_live):
        self.kind = kind          # 'Cmd' / 'Add' / 'G'
        self.entry_px = entry_px
        self.entry_ts = entry_ts
        self.trail_act = None     # 啟動價位
        self.trail_on = False
        self.peak = None
        self.loss_stop = None
        self.be_stop = None
        self.stale_stop = None    # 滯留追蹤停損 (opt_stale_mode="trail")
        self.bracket_live = bracket_live  # 是否已有有效出場單 (前一收盤發出)


def run(df1m, p=None, intrabar_mode="ohlc", start=None, end=None):
    p = {**P, **(p or {})}
    b5 = prepare(df1m, p)
    n = len(b5)
    B = {c: b5[c].values for c in b5.columns}
    ts_open = b5["open_ts"].values
    ts_close = b5["close_ts"].values

    # 1min lookup for intrabar mode
    if intrabar_mode == "1min":
        df1m = df1m.sort_values("open_ts")
        m_open = df1m["open_ts"].values
        m_arr = df1m[["open", "high", "low", "close"]].values
        bar_start_idx = np.searchsorted(m_open, ts_open, side="left")
        bar_end_idx = np.searchsorted(m_open, ts_close, side="left")

    lots = []          # 現有部位 (同方向)
    direction = 0      # 1 多 / -1 空
    baseATR = addATR = gATR = np.nan
    pending = []       # 下一開盤執行的市價/進場單: (action, kind/comment)
    trades = []        # 每口一筆
    cooldown_until = None
    prev_cross_state = {}

    i0 = 1
    if start is not None:
        i0 = max(1, np.searchsorted(ts_open, np.datetime64(start)))
    i_end = n if end is None else np.searchsorted(ts_open, np.datetime64(end))

    def close_lot(lot, px, t, comment):
        nonlocal direction
        pnl = (px - lot.entry_px) * direction * POINT_VALUE - 2 * COMMISSION
        trades.append(dict(side="L" if direction > 0 else "S", kind=lot.kind,
                           entry_ts=lot.entry_ts, entry_px=lot.entry_px,
                           exit_ts=t, exit_px=px, exit_sig=comment, pnl=pnl))
        lots.remove(lot)
        if not lots:
            direction = 0

    warmup = 200
    for i in range(max(i0, warmup), min(i_end, n)):
        o, h, l, c = B["open"][i], B["high"][i], B["low"][i], B["close"][i]
        t_open, t_close = ts_open[i], ts_close[i]

        # ── 1) 開盤: 執行前一收盤掛出的市價單 ──
        if pending:
            for act, arg in pending:
                if act == "close_all":
                    for lot in lots[:]:
                        close_lot(lot, o, t_open, "Trend Rev")
                elif act == "close_kind":
                    kind, comment = arg
                    for lot in [x for x in lots if x.kind == kind]:
                        close_lot(lot, o, t_open, comment)
                elif act == "close_lot_ts":
                    ets, comment = arg
                    for lot in [x for x in lots if x.entry_ts == ets]:
                        close_lot(lot, o, t_open, comment)
                elif act == "entry":
                    kind, dir_ = arg
                    lots.append(Lot(kind, o, t_open, bracket_live=(len(lots) > 0)))
                    direction = dir_
            pending = []

        # ── 2) 盤中: stop / trail ──
        if lots:
            if intrabar_mode == "1min":
                s_, e_ = bar_start_idx[i], bar_end_idx[i]
                segs = []
                for k in range(s_, e_ + 1 if e_ < len(m_arr) else e_):
                    mo, mh, ml, mc = m_arr[k]
                    segs.extend(_segments(mo, mh, ml, mc))
            else:
                segs = _segments(o, h, l, c)

            first_px = segs[0][0] if segs else o
            for lot in lots[:]:
                if not lot.bracket_live:
                    continue
                # 開盤即已達 trail 啟動價 (跳空)
                if lot.trail_act is not None and not lot.trail_on and (first_px - lot.trail_act) * direction >= 0:
                    lot.trail_on = True
                    lot.peak = first_px
                # 開盤跳空穿越 stop
                eff = _eff_stop(lot, direction)
                if eff is not None and (first_px - eff) * direction <= 0:
                    close_lot(lot, first_px, t_open, _stop_name(lot, eff, direction))
            for p0, p1 in segs:
                if not lots:
                    break
                rising = p1 >= p0
                favorable = (rising and direction > 0) or (not rising and direction < 0)
                if favorable:
                    ext = p1
                    for lot in lots:
                        if not lot.bracket_live or lot.trail_act is None:
                            continue
                        if not lot.trail_on and (ext - lot.trail_act) * direction >= 0:
                            lot.trail_on = True
                            lot.peak = lot.trail_act
                        if lot.trail_on:
                            lot.peak = max(lot.peak, ext) if direction > 0 else min(lot.peak, ext)
                else:
                    for lot in lots[:]:
                        if not lot.bracket_live:
                            continue
                        eff = _eff_stop(lot, direction)
                        if eff is None:
                            continue
                        lo_, hi_ = (p1, p0) if direction > 0 else (p0, p1)
                        if lo_ <= eff <= hi_:
                            close_lot(lot, eff, t_close, _stop_name(lot, eff, direction))

        # ── 3) 收盤: 指標訊號 → 掛單 ──
        posSize = len(lots) * direction
        atr_i = B["atr"][i]
        if posSize == 0:
            baseATR = addATR = gATR = atr_i

        hr = B["hour"][i]
        isBaseToxic = (15 <= hr <= 20) or hr in (1, 2)
        if p["opt_block_h0"] and hr == 0:
            isBaseToxic = True
        if p["opt_block_open"] and hr == 8:
            isBaseToxic = True
        isLongToxic = isBaseToxic or hr == 4
        isShortToxic = isBaseToxic or hr == 21
        isDay = 8 <= hr <= 13
        g_trail = p["g_trailMultDay"] if isDay else p["g_trailMultNight"]

        def crossover(a_now, a_prev, b_now, b_prev):
            return a_now > b_now and a_prev <= b_prev

        c_prev = B["close"][i - 1]
        longTrigger = (crossover(B["ema10"][i], B["ema10"][i - 1], B["ema30"][i], B["ema30"][i - 1])
                       or crossover(c, c_prev, B["hh20_prev"][i], B["hh20_prev"][i - 1]))
        shortTrigger = crossover(B["ll20_prev"][i], B["ll20_prev"][i - 1], c, c_prev)  # crossunder(close, ll20)

        mtf_bull, mtf_bear = B["mtf_bull"][i], B["mtf_bear"][i]
        adx_ok = B["adx"][i] > p["adxThresh"]
        avgPrice = np.mean([x.entry_px for x in lots]) if lots else np.nan

        in_cooldown = cooldown_until is not None and t_close < cooldown_until

        # 進場
        if posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and longTrigger and adx_ok and not in_cooldown:
            pending.append(("entry", ("Cmd", 1)))
            baseATR = atr_i
        elif posSize == 0 and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger \
                and (adx_ok if p["opt_adx_short"] else True) and not in_cooldown:
            pending.append(("entry", ("Cmd", -1)))
            baseATR = atr_i
        elif 0 < posSize < 3 and not isLongToxic and mtf_bull and c > avgPrice + baseATR * p["l_pyramid_dist"]:
            pending.append(("entry", ("Add", 1)))
            addATR = atr_i
        elif posSize == 3 and not isLongToxic and c > avgPrice + baseATR * p["l_pyramid_dist"]:
            pending.append(("entry", ("G", 1)))
            gATR = atr_i
        elif -3 < posSize < 0 and not isShortToxic and mtf_bear and c < avgPrice - baseATR * p["s_pyramid_dist"]:
            pending.append(("entry", ("Add", -1)))
            addATR = atr_i
        elif posSize == -3 and not isShortToxic and c < avgPrice - baseATR * p["s_pyramid_dist"]:
            pending.append(("entry", ("G", -1)))
            gATR = atr_i

        # 出場單更新 (下一 bar 生效) + 市價平倉訊號
        if lots:
            eff_add = baseATR if np.isnan(addATR) else addATR
            eff_g = eff_add if np.isnan(gATR) else gATR
            first_lot_px = lots[0].entry_px
            profit = (c - first_lot_px) * direction
            be_armed_now = profit > baseATR * p["be_trigger"]

            for lot in lots:
                lot.bracket_live = True
                if direction > 0:
                    if lot.kind == "Cmd":
                        lot.trail_act = round(lot.entry_px + baseATR * p["l_trailBase"])
                        lot.loss_stop = round(lot.entry_px - baseATR * p["l_slMult"])
                        if be_armed_now:
                            lot.be_stop = first_lot_px
                    elif lot.kind == "Add":
                        lot.trail_act = round(lot.entry_px + eff_add * p["l_trailAdd"])
                        lot.loss_stop = round(lot.entry_px - eff_add * p["addLossL"])
                    else:
                        lot.trail_act = round(lot.entry_px + eff_g * g_trail)
                        lot.loss_stop = round(lot.entry_px - eff_g * p["g_slMult"])
                else:
                    if lot.kind == "Cmd":
                        lot.trail_act = round(lot.entry_px - baseATR * p["s_trailMult"])
                        lot.loss_stop = round(lot.entry_px + baseATR * p["s_slMult"])
                        if be_armed_now:
                            lot.be_stop = first_lot_px
                    elif lot.kind == "Add":
                        lot.trail_act = round(lot.entry_px - eff_add * p["s_trailMult"])
                        lot.loss_stop = round(lot.entry_px + eff_add * p["addLossS"])
                    else:
                        lot.trail_act = round(lot.entry_px - eff_g * g_trail)
                        lot.loss_stop = round(lot.entry_px + eff_g * p["g_slMult"])

            # 市價平倉 (訊號 bar 收盤 → 下一開盤成交)
            ef, ef_p = B["ema_fast"][i], B["ema_fast"][i - 1]
            cd_fast = p["opt_cooldown_min"] and p["opt_cooldown_scope"] == "both"
            cd_trev = p["opt_cooldown_min"] > 0
            if direction > 0:
                if crossover(ef, ef_p, c, c_prev) and any(x.kind == "G" for x in lots):  # crossunder(close, emaFast)
                    pending.append(("close_kind", ("G", "L_G_Cut")))
                if crossover(B["ema_cmd_l"][i], B["ema_cmd_l"][i - 1], c, c_prev) and any(x.kind == "Cmd" for x in lots):
                    pending.append(("close_kind", ("Cmd", "L_Cmd_Fast")))
                    if cd_fast:
                        cooldown_until = t_close + np.timedelta64(p["opt_cooldown_min"], "m")
                if crossover(B["ema_long"][i], B["ema_long"][i - 1], c, c_prev):
                    pending = [x for x in pending if x[0] != "entry"]
                    pending.append(("close_all", None))
                    if cd_trev:
                        cooldown_until = t_close + np.timedelta64(p["opt_cooldown_min"], "m")
            else:
                if crossover(c, c_prev, ef, ef_p) and any(x.kind == "G" for x in lots):
                    pending.append(("close_kind", ("G", "S_G_Cut")))
                if crossover(c, c_prev, B["ema_cmd_s"][i], B["ema_cmd_s"][i - 1]) and any(x.kind == "Cmd" for x in lots):
                    pending.append(("close_kind", ("Cmd", "S_Cmd_Fast")))
                    if cd_fast:
                        cooldown_until = t_close + np.timedelta64(p["opt_cooldown_min"], "m")
                if crossover(c, c_prev, B["ema_short"][i], B["ema_short"][i - 1]):
                    pending = [x for x in pending if x[0] != "entry"]
                    pending.append(("close_all", None))
                    if cd_trev:
                        cooldown_until = t_close + np.timedelta64(p["opt_cooldown_min"], "m")

            # 滯留單處理: 持倉 N 小時仍未獲利 → 平倉或改掛追蹤停損
            if p["opt_stale_hr"]:
                for lot in lots:
                    held_hr = (t_close - lot.entry_ts) / np.timedelta64(1, "h")
                    is_stale = held_hr >= p["opt_stale_hr"] and (c - lot.entry_px) * direction < 0
                    if p["opt_stale_mode"] == "close":
                        if is_stale:
                            pending.append(("close_lot_ts", (lot.entry_ts, "TimeStop")))
                    else:  # trail: 一旦觸發即持續棘輪收緊, 直到出場
                        if is_stale or lot.stale_stop is not None:
                            new_stop = round(c - direction * p["opt_stale_trail_atr"] * atr_i)
                            if lot.stale_stop is None:
                                lot.stale_stop = new_stop
                            else:
                                lot.stale_stop = max(lot.stale_stop, new_stop) if direction > 0 \
                                    else min(lot.stale_stop, new_stop)

    # 期末強制平倉
    for lot in lots[:]:
        close_lot(lot, B["close"][min(i_end, n) - 1], ts_close[min(i_end, n) - 1], "END")

    tr = pd.DataFrame(trades)
    if not tr.empty:
        tr = tr.sort_values("exit_ts").reset_index(drop=True)
    return tr


def _eff_stop(lot, direction):
    stops = [s for s in (lot.loss_stop, lot.be_stop, lot.stale_stop,
                         (lot.peak - 1 if direction > 0 else lot.peak + 1) if lot.trail_on else None)
             if s is not None]
    if not stops:
        return None
    return max(stops) if direction > 0 else min(stops)


def _stop_name(lot, eff, direction):
    trail_stop = (lot.peak - 1 if direction > 0 else lot.peak + 1) if lot.trail_on else None
    side = "L" if direction > 0 else "S"
    if trail_stop is not None and eff == trail_stop:
        return f"{side}_Exit" + ("_Add" if lot.kind == "Add" else "_G" if lot.kind == "G" else "")
    if lot.stale_stop is not None and eff == lot.stale_stop:
        return "TimeTrail"
    if lot.be_stop is not None and eff == lot.be_stop:
        return f"{side}_BE"
    return f"{side}_Exit" + ("_Add" if lot.kind == "Add" else "_G" if lot.kind == "G" else "") + "_SL"


def summary(tr, label=""):
    if tr.empty:
        return f"{label}: no trades"
    w = tr[tr.pnl > 0]
    lo = tr[tr.pnl <= 0]
    pf = w.pnl.sum() / abs(lo.pnl.sum()) if len(lo) and lo.pnl.sum() != 0 else np.inf
    cum = tr.pnl.cumsum()
    mdd = (cum - cum.cummax()).min()
    return (f"{label}: {len(tr)} trades, WR {len(w)/len(tr)*100:.1f}%, "
            f"net {tr.pnl.sum():+,.0f}, PF {pf:.2f}, MDD {mdd:+,.0f}")


if __name__ == "__main__":
    import sys
    df1m = load_1min(r"D:\stock\tmf-bot\backtest\mxf_1min.csv")
    mode = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if mode == "validate":
        tr = run(df1m, intrabar_mode="ohlc", start="2026-04-10")
        tr.to_csv(r"D:\stock\tmf-bot\backtest\strategy_v26\py_trades_validate.csv", index=False)
        print(summary(tr[tr.entry_ts >= "2026-04-16"], "py v26 ohlc (4/16+)"))
    elif mode == "validate1m":
        tr = run(df1m, intrabar_mode="1min", start="2026-04-10")
        tr.to_csv(r"D:\stock\tmf-bot\backtest\strategy_v26\py_trades_validate.csv", index=False)
        print(summary(tr[tr.entry_ts >= "2026-04-16"], "py v26 1min (4/16+)"))
    else:
        tr = run(df1m, intrabar_mode="1min")
        tr.to_csv(r"D:\stock\tmf-bot\backtest\strategy_v26\py_trades_full.csv", index=False)
        print(summary(tr, "py v26 full"))
