"""Pre-specified trader3a idea tests for task_3a_ideas.md.

The V38 engine is imported read-only.  A/B are standalone, session-bounded
one-minute simulations.  C keeps the recorded v28 engine path intact and
replaces only each Cmd lot's realised P/L with a two-half Cmd wrapper; Add/G
rows are copied without alteration.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
DATA = HERE / "mxf_1min_corrected_20261017b.csv"
V38_DAILY = HERE / "ext_v38_daily_costed.csv"
V28_LEDGER = HERE / "trades_v28.csv"
CUTOFF = pd.Timestamp("2026-10-17 03:58:00")
ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
import engine_v26_bbw as eng  # noqa: E402


POINT_VALUE = 50.0
BROKER = 20.0
TAX_RATE = 0.00002
SLIPPAGE_POINTS = 4.0
V28_RT_EXTRA = 440.0
YEARS = (2024, 2025, 2026)


def save(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(HERE / name, index=False, encoding="utf-8-sig")


def fmt_money(x: float) -> str:
    if not np.isfinite(x):
        return "—"
    return f"{x:,.0f}"


def fmt_num(x: float, digits: int = 2) -> str:
    if not np.isfinite(x):
        return "—"
    return f"{x:,.{digits}f}"


def markdown_table(frame: pd.DataFrame, columns: list[str], labels: dict[str, str]) -> str:
    if frame.empty:
        return "（無資料）"
    rows = [[labels.get(c, c) for c in columns], ["---"] * len(columns)]
    for row in frame[columns].itertuples(index=False, name=None):
        out: list[str] = []
        for value in row:
            if isinstance(value, (float, np.floating)):
                out.append("—" if not np.isfinite(value) else f"{value:,.3f}")
            elif isinstance(value, (pd.Timestamp, np.datetime64)):
                out.append(str(pd.Timestamp(value)))
            else:
                out.append(str(value))
        rows.append(out)
    return "\n".join("| " + " | ".join(x.replace("|", "\\|") for x in row) + " |" for row in rows)


def trade_day(values: pd.Series | pd.Timestamp) -> pd.Series | pd.Timestamp:
    """The night session belongs to the following trading date, as V38 daily does."""
    if isinstance(values, pd.Timestamp):
        return values.normalize() + pd.Timedelta(days=1) if values.hour >= 15 else values.normalize()
    z = pd.to_datetime(values)
    return z.dt.normalize() + pd.to_timedelta((z.dt.hour >= 15).astype(int), unit="D")


def sessionize(one: pd.DataFrame) -> pd.DataFrame:
    """Keep tradable tape minutes and attach a session ID/start/end without mixing sessions."""
    z = one.copy().sort_values("open_ts").reset_index(drop=True)
    clock = z.open_ts.dt.hour * 60 + z.open_ts.dt.minute
    is_day = (clock >= 8 * 60 + 45) & (clock < 13 * 60 + 45)
    is_night = (clock >= 15 * 60) | (clock < 5 * 60)
    z = z.loc[is_day | is_night].copy()
    clock = z.open_ts.dt.hour * 60 + z.open_ts.dt.minute
    z["session"] = np.where((clock >= 8 * 60 + 45) & (clock < 13 * 60 + 45), "day", "night")
    z["session_id"] = z.open_ts.dt.normalize()
    after_midnight = clock < 5 * 60
    z.loc[after_midnight, "session_id"] -= pd.Timedelta(days=1)
    z["session_start"] = np.where(
        z.session.eq("day"),
        z.session_id + pd.Timedelta(hours=8, minutes=45),
        z.session_id + pd.Timedelta(hours=15),
    )
    z["session_start"] = pd.to_datetime(z.session_start)
    z["session_end"] = np.where(
        z.session.eq("day"),
        z.session_id + pd.Timedelta(hours=13, minutes=45),
        z.session_id + pd.Timedelta(days=1, hours=5),
    )
    z["session_end"] = pd.to_datetime(z.session_end)
    z["session_minute"] = ((z.open_ts - z.session_start) / pd.Timedelta(minutes=1)).astype(int)
    return z.reset_index(drop=True)


def build_session_bars(one: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Aggregate only complete fixed-duration bars inside each assigned session."""
    z = one.copy()
    z["bar_no"] = z.session_minute // minutes
    z["bar_open"] = z.session_start + pd.to_timedelta(z.bar_no * minutes, unit="min")
    g = z.groupby(["session_id", "session", "bar_no", "bar_open"], sort=True, observed=True)
    bars = g.agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        close_ts=("ts", "max"), n_minutes=("ts", "size"), session_end=("session_end", "first"),
    ).reset_index()
    # A truncated source tail (and any source gap) cannot supply a signal bar.
    bars = bars.loc[bars.n_minutes.eq(minutes)].copy()
    bars = bars.rename(columns={"bar_open": "open_ts"}).sort_values("close_ts").reset_index(drop=True)
    return bars


def ema(values: pd.Series, span: int) -> pd.Series:
    return values.ewm(span=span, adjust=False).mean()


def rma(values: pd.Series, length: int) -> pd.Series:
    return values.ewm(alpha=1.0 / length, adjust=False).mean()


def add_atr(bars: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    z = bars.copy()
    prior = z.close.shift(1)
    tr = pd.concat([(z.high - z.low), (z.high - prior).abs(), (z.low - prior).abs()], axis=1).max(axis=1)
    z["atr14"] = rma(tr, length)
    return z


def add_stoch_macd(bars: pd.DataFrame) -> pd.DataFrame:
    z = bars.copy()
    lo = z.low.rolling(14).min()
    hi = z.high.rolling(14).max()
    raw_k = 100.0 * (z.close - lo) / (hi - lo).replace(0, np.nan)
    z["stoch_k"] = raw_k.rolling(3).mean()
    z["stoch_d"] = z.stoch_k.rolling(3).mean()
    macd = ema(z.close, 12) - ema(z.close, 26)
    z["macd_hist"] = macd - ema(macd, 9)
    return z


def add_60_trend(bars60: pd.DataFrame) -> pd.DataFrame:
    z = bars60.copy()
    z["ema50"] = ema(z.close, 50)
    z["trend_long"] = (z.close > z.ema50) & (z.ema50 > z.ema50.shift(3))
    z["trend_short"] = (z.close < z.ema50) & (z.ema50 < z.ema50.shift(3))
    return z


def attach_60(bars: pd.DataFrame, trend60: pd.DataFrame) -> pd.DataFrame:
    right = trend60[["close_ts", "ema50", "trend_long", "trend_short"]].sort_values("close_ts")
    return pd.merge_asof(bars.sort_values("close_ts"), right, on="close_ts", direction="backward")


def raw_exit_fill(raw_price: float, side: int) -> float:
    return float(raw_price - side * SLIPPAGE_POINTS)


def raw_entry_fill(raw_price: float, side: int) -> float:
    return float(raw_price + side * SLIPPAGE_POINTS)


def sleeve_fee(price: float) -> float:
    # Slippage is incorporated in the fill price, not charged a second time.
    return BROKER + TAX_RATE * float(price) * POINT_VALUE


def make_leg(pos: dict, exit_raw: float, exit_ts: pd.Timestamp, exit_sig: str, qty: float) -> dict:
    side = int(pos["side"])
    exit_fill = raw_exit_fill(float(exit_raw), side)
    entry_fill = float(pos["entry_fill"])
    gross = (exit_fill - entry_fill) * side * POINT_VALUE * qty
    fees = qty * (sleeve_fee(entry_fill) + sleeve_fee(exit_fill))
    return {
        "trade_id": pos["trade_id"], "variant": pos["variant"], "side": "L" if side > 0 else "S",
        "entry_ts": pos["entry_ts"], "entry_raw": pos["entry_raw"], "entry_px": entry_fill,
        "exit_ts": pd.Timestamp(exit_ts), "exit_raw": float(exit_raw), "exit_px": exit_fill,
        "exit_sig": exit_sig, "qty": qty, "gross": gross, "fees": fees, "pnl": gross - fees,
    }


def segments(o: float, h: float, l: float, c: float) -> list[tuple[float, float]]:
    return [(o, h), (h, l), (l, c)] if (h - o) < (o - l) else [(o, l), (l, h), (h, c)]


def stop_hit(pos: dict, o: float, h: float, l: float, c: float) -> tuple[bool, float]:
    side, stop = int(pos["side"]), float(pos["stop"])
    if (o - stop) * side <= 0:
        return True, float(o)  # a gap is filled at the minute open before fill slippage
    for p0, p1 in segments(o, h, l, c):
        if side > 0 and p1 < p0 and p1 <= stop <= p0:
            return True, stop
        if side < 0 and p1 > p0 and p0 <= stop <= p1:
            return True, stop
    return False, math.nan


def apply_a_intrabar(pos: dict, o: float, h: float, l: float, c: float, ts: pd.Timestamp, legs: list[dict]) -> bool:
    """Return True if the remaining A position is closed during this minute."""
    side = int(pos["side"])
    stop = float(pos["stop"])
    # A gap through the live stop has priority over any intraminute target.
    if (o - stop) * side <= 0:
        legs.append(make_leg(pos, float(o), ts, "Stop_gap", float(pos["qty"])))
        return True
    for p0, p1 in segments(o, h, l, c):
        if not pos["target_done"]:
            target = float(pos["target"])
            if side > 0 and p1 > p0 and p0 <= target <= p1:
                legs.append(make_leg(pos, target, ts, "1.5R_half", 0.5))
                pos["qty"] = 0.5
                pos["target_done"] = True
                pos["stop"] = max(float(pos["stop"]), float(pos["entry_raw"]))
                stop = float(pos["stop"])
            elif side < 0 and p1 < p0 and p1 <= target <= p0:
                legs.append(make_leg(pos, target, ts, "1.5R_half", 0.5))
                pos["qty"] = 0.5
                pos["target_done"] = True
                pos["stop"] = min(float(pos["stop"]), float(pos["entry_raw"]))
                stop = float(pos["stop"])
        if side > 0 and p1 < p0 and p1 <= stop <= p0:
            legs.append(make_leg(pos, stop, ts, "Stop" if not pos["target_done"] else "BE_stop", float(pos["qty"])))
            return True
        if side < 0 and p1 > p0 and p0 <= stop <= p1:
            legs.append(make_leg(pos, stop, ts, "Stop" if not pos["target_done"] else "BE_stop", float(pos["qty"])))
            return True
    return False


def to_ns(value: pd.Timestamp | np.datetime64) -> int:
    return int(pd.Timestamp(value).value)


def run_trend_pullback(
    name: str, one: pd.DataFrame, signals: pd.DataFrame, five: pd.DataFrame, scale_out: bool,
) -> pd.DataFrame:
    entry_map = {to_ns(r.close_ts): r for r in signals.itertuples(index=False)}
    exits = five[["close_ts", "exit_long", "exit_short"]].dropna(subset=["close_ts"])
    exit_map = {to_ns(r.close_ts): (bool(r.exit_long), bool(r.exit_short)) for r in exits.itertuples(index=False)}
    leg_rows: list[dict] = []
    pos: dict | None = None
    next_id = 1
    entries_per_session: dict[int, int] = {}
    arrays = one[["open_ts", "ts", "open", "high", "low", "close", "session_id", "session_end"]].to_numpy()
    last_ts = pd.Timestamp(one.ts.iloc[-1])
    for open_ts, close_ts, o, h, l, c, sid, send in arrays:
        key = to_ns(open_ts)
        close_time = pd.Timestamp(close_ts)
        if pos is not None:
            flag = exit_map.get(key)
            if flag is not None and (flag[0] if pos["side"] > 0 else flag[1]):
                leg_rows.append(make_leg(pos, float(o), pd.Timestamp(open_ts), "訊號出場", float(pos["qty"])))
                pos = None
        if pos is None:
            sig = entry_map.get(key)
            sid_key = to_ns(sid)
            if sig is not None and entries_per_session.get(sid_key, 0) < 4:
                side = int(sig.side)
                entry_raw = float(o)
                raw_stop = float(sig.raw_stop)
                atr5 = float(sig.atr5)
                stop = min(raw_stop, entry_raw - 0.5 * atr5) if side > 0 else max(raw_stop, entry_raw + 0.5 * atr5)
                r = abs(entry_raw - stop)
                pos = {
                    "trade_id": next_id, "variant": name, "side": side, "entry_ts": pd.Timestamp(open_ts),
                    "entry_raw": entry_raw, "entry_fill": raw_entry_fill(entry_raw, side), "stop": stop,
                    "qty": 1.0, "target_done": not scale_out,
                    "target": entry_raw + side * 1.5 * r if scale_out else math.nan,
                }
                next_id += 1
                entries_per_session[sid_key] = entries_per_session.get(sid_key, 0) + 1
        if pos is not None:
            if apply_a_intrabar(pos, float(o), float(h), float(l), float(c), close_time, leg_rows):
                pos = None
        if pos is not None and (close_time == pd.Timestamp(send) or close_time == last_ts):
            leg_rows.append(make_leg(pos, float(c), close_time, "Session_end" if close_time == pd.Timestamp(send) else "資料截止", float(pos["qty"])))
            pos = None
    return pd.DataFrame(leg_rows)


def run_bollinger(name: str, one: pd.DataFrame, signals: pd.DataFrame, bars15: pd.DataFrame) -> pd.DataFrame:
    entry_map = {to_ns(r.close_ts): r for r in signals.itertuples(index=False)}
    event_map = {
        to_ns(r.close_ts): (bool(r.wrong_long), bool(r.wrong_short), float(r.high), float(r.low), float(r.atr14))
        for r in bars15.itertuples(index=False)
    }
    leg_rows: list[dict] = []
    pos: dict | None = None
    next_id = 1
    arrays = one[["open_ts", "ts", "open", "high", "low", "close", "session_end"]].to_numpy()
    last_ts = pd.Timestamp(one.ts.iloc[-1])
    for open_ts, close_ts, o, h, l, c, send in arrays:
        key = to_ns(open_ts)
        if pos is not None and key in event_map:
            wrong_l, wrong_s, bh, bl, a = event_map[key]
            wrong = wrong_l if pos["side"] > 0 else wrong_s
            pos["wrong_count"] = pos["wrong_count"] + 1 if wrong else 0
            if pos["wrong_count"] >= 2:
                leg_rows.append(make_leg(pos, float(o), pd.Timestamp(open_ts), "中線反向兩根", 1.0))
                pos = None
            else:
                if pos["side"] > 0:
                    pos["peak"] = max(float(pos["peak"]), bh)
                    pos["trail"] = max(float(pos["trail"]), float(pos["peak"]) - 2.5 * a)
                    pos["stop"] = max(float(pos["band_stop"]), float(pos["trail"]))
                else:
                    pos["peak"] = min(float(pos["peak"]), bl)
                    pos["trail"] = min(float(pos["trail"]), float(pos["peak"]) + 2.5 * a)
                    pos["stop"] = min(float(pos["band_stop"]), float(pos["trail"]))
        if pos is None:
            sig = entry_map.get(key)
            if sig is not None:
                side = int(sig.side)
                entry_raw = float(o)
                pos = {
                    "trade_id": next_id, "variant": name, "side": side, "entry_ts": pd.Timestamp(open_ts),
                    "entry_raw": entry_raw, "entry_fill": raw_entry_fill(entry_raw, side),
                    "band_stop": float(sig.band_stop), "stop": float(sig.band_stop),
                    "peak": entry_raw, "trail": -np.inf if side > 0 else np.inf, "wrong_count": 0,
                }
                next_id += 1
        if pos is not None:
            hit, raw = stop_hit(pos, float(o), float(h), float(l), float(c))
            if hit:
                leg_rows.append(make_leg(pos, raw, pd.Timestamp(close_ts), "帶狀/ATR停損", 1.0))
                pos = None
        close_time = pd.Timestamp(close_ts)
        if pos is not None and (close_time == pd.Timestamp(send) or close_time == last_ts):
            leg_rows.append(make_leg(pos, float(c), close_time, "Session_end" if close_time == pd.Timestamp(send) else "資料截止", 1.0))
            pos = None
    return pd.DataFrame(leg_rows)


def legs_to_campaigns(legs: pd.DataFrame) -> pd.DataFrame:
    if legs.empty:
        return pd.DataFrame(columns=["trade_id", "variant", "entry_ts", "exit_ts", "pnl", "gross"])
    z = legs.copy()
    z["exit_day"] = trade_day(z.exit_ts)
    grouped = z.groupby(["trade_id", "variant"], as_index=False).agg(
        entry_ts=("entry_ts", "min"), exit_ts=("exit_ts", "max"), pnl=("pnl", "sum"), gross=("gross", "sum"),
        qty=("qty", "sum"),
    )
    grouped["exit_day"] = trade_day(grouped.exit_ts)
    return grouped


def daily_mdd(daily: pd.Series) -> float:
    if daily.empty:
        return 0.0
    equity = daily.sort_index().cumsum()
    return float((equity - equity.cummax()).min())


def sleeve_metrics(name: str, legs: pd.DataFrame, v38: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    campaigns = legs_to_campaigns(legs)
    if legs.empty:
        daily = pd.DataFrame(columns=["date", "variant", "pnl", "v38_pnl", "combined_pnl"])
        return pd.DataFrame(), daily, campaigns
    x = legs.copy()
    x["exit_day"] = trade_day(x.exit_ts)
    pnl_daily = x.groupby("exit_day").pnl.sum().sort_index()
    idx = pnl_daily.index.union(v38.index).sort_values()
    aligned = pd.DataFrame({"pnl": pnl_daily.reindex(idx, fill_value=0.0), "v38_pnl": v38.reindex(idx, fill_value=0.0)})
    daily = aligned.reset_index().rename(columns={"index": "date"})
    daily["variant"] = name
    daily["combined_pnl"] = daily.pnl + daily.v38_pnl
    rows: list[dict] = []
    for year in YEARS:
        start, end = pd.Timestamp(f"{year}-01-01"), pd.Timestamp(f"{year + 1}-01-01")
        d = aligned.loc[(aligned.index >= start) & (aligned.index < end)]
        c = campaigns.loc[(campaigns.exit_day >= start) & (campaigns.exit_day < end)]
        wins, losses = c.loc[c.pnl > 0, "pnl"], c.loc[c.pnl <= 0, "pnl"]
        net = float(d.pnl.sum())
        mdd = daily_mdd(d.pnl)
        rows.append({
            "idea": name, "year": year, "total": float(c.gross.sum()), "net": net, "daily_mdd": mdd,
            "net_mdd": net / abs(mdd) if mdd else np.nan, "trades": len(c),
            "win_rate": float((c.pnl > 0).mean()) if len(c) else np.nan,
            "avg_win": float(wins.mean()) if len(wins) else np.nan,
            "avg_loss": float(-losses.mean()) if len(losses) else np.nan,
            "avg_win_loss": float(wins.mean() / -losses.mean()) if len(wins) and len(losses) and losses.mean() != 0 else np.nan,
            "corr_v38": float(d.pnl.corr(d.v38_pnl)) if len(d) > 1 else np.nan,
        })
    return pd.DataFrame(rows), daily, campaigns


def make_a_signals(entry: pd.DataFrame, five: pd.DataFrame) -> pd.DataFrame:
    stop_ref = five[["close_ts", "low", "high", "atr14"]].rename(columns={"atr14": "atr5"}).copy()
    stop_ref["low6"] = stop_ref.low.rolling(6).min()
    stop_ref["high6"] = stop_ref.high.rolling(6).max()
    z = entry.copy()
    z["cross_up"] = (z.stoch_k > z.stoch_d) & (z.stoch_k.shift(1) <= z.stoch_d.shift(1))
    z["cross_down"] = (z.stoch_k < z.stoch_d) & (z.stoch_k.shift(1) >= z.stoch_d.shift(1))
    z["was_low"] = z.stoch_k.rolling(6).min() < 20
    z["was_high"] = z.stoch_k.rolling(6).max() > 80
    z["hist_up"] = z.macd_hist > z.macd_hist.shift(1)
    z["hist_down"] = z.macd_hist < z.macd_hist.shift(1)
    z = z.merge(stop_ref[["close_ts", "low6", "high6", "atr5"]], on="close_ts", how="left")
    long = z.trend_long & z.was_low & z.cross_up & z.hist_up
    short = z.trend_short & z.was_high & z.cross_down & z.hist_down
    out = pd.concat([
        z.loc[long, ["close_ts", "low6", "atr5"]].assign(side=1, raw_stop=lambda x: x.low6 - 0.2 * x.atr5),
        z.loc[short, ["close_ts", "high6", "atr5"]].assign(side=-1, raw_stop=lambda x: x.high6 + 0.2 * x.atr5),
    ], ignore_index=True)
    return out.sort_values("close_ts").reset_index(drop=True)


def build_sleeve_inputs(one: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    five = add_atr(build_session_bars(one, 5))
    five["ema20"] = ema(five.close, 20)
    five = add_stoch_macd(five)
    fifteen = add_atr(build_session_bars(one, 15))
    fifteen = add_stoch_macd(fifteen)
    sixty = add_60_trend(build_session_bars(one, 60))
    five = attach_60(five, sixty)
    fifteen = attach_60(fifteen, sixty)
    five["exit_long"] = (five.close >= five.ema20 + 2.0 * five.atr14) | ~five.trend_long.fillna(False)
    five["exit_short"] = (five.close <= five.ema20 - 2.0 * five.atr14) | ~five.trend_short.fillna(False)

    mid = fifteen.close.rolling(20).mean()
    std = fifteen.close.rolling(20).std(ddof=0)
    fifteen["bb_mid"] = mid
    fifteen["bb_up"] = mid + 2.0 * std
    fifteen["bb_down"] = mid - 2.0 * std
    fifteen["bb_width"] = (fifteen.bb_up - fifteen.bb_down) / mid
    fifteen["bb_width_pct"] = fifteen.bb_width.rolling(120).rank(pct=True) * 100.0
    low4 = np.ones(len(fifteen), dtype=bool)
    for shift in range(1, 5):
        low4 &= fifteen.bb_width_pct.shift(shift).lt(20).to_numpy()
    fifteen["squeeze_release"] = low4 & fifteen.bb_width.gt(fifteen.bb_width.shift(1)).to_numpy()
    fifteen["wrong_long"] = fifteen.close < fifteen.bb_mid
    fifteen["wrong_short"] = fifteen.close > fifteen.bb_mid
    return five, fifteen, sixty, one


def make_b_signals(fifteen: pd.DataFrame) -> pd.DataFrame:
    long = fifteen.squeeze_release & fifteen.trend_long & fifteen.bb_down.notna()
    short = fifteen.squeeze_release & fifteen.trend_short & fifteen.bb_up.notna()
    a = fifteen.loc[long, ["close_ts", "bb_down"]].assign(side=1, band_stop=lambda x: x.bb_down)
    b = fifteen.loc[short, ["close_ts", "bb_up"]].assign(side=-1, band_stop=lambda x: x.bb_up)
    return pd.concat([a, b], ignore_index=True).sort_values("close_ts").reset_index(drop=True)


def v28_params() -> dict:
    return {"opt_stale_hr": 10, "opt_cooldown_min": 30, "opt_short_pyramid_cap_mode": "hour4"}


def is_market_v28_exit(sig: str) -> bool:
    return sig in {"Trend Rev", "Trend Rev Cap", "TimeStop", "END", "L_Cmd_Fast", "S_Cmd_Fast"}


def cmd_stop_info(cmd: pd.DataFrame, b5: pd.DataFrame) -> pd.DataFrame:
    p = {**eng.P, **v28_params()}
    bars = b5[["close_ts", "atr", "hour"]].copy().sort_values("close_ts")
    # At a session boundary the engine can hold a next-bar order from the
    # prior session, so the causal signal is the last completed 5m bar rather
    # than necessarily a bar that closes at the eventual fill timestamp.
    z = pd.merge_asof(cmd.sort_values("entry_ts"), bars, left_on="entry_ts", right_on="close_ts", direction="backward")
    z = z.sort_values("source_id").reset_index(drop=True)
    if z.atr.isna().any():
        raise RuntimeError("a Cmd entry could not be matched to its causal 5m signal bar")
    is_day = z.hour.between(8, 13)
    mult = np.where(z.side.eq("L"), np.where(is_day, p["l_slMultDay"], p["l_slMultNight"]), p["s_slMult"])
    direction = np.where(z.side.eq("L"), 1.0, -1.0)
    z["direction"] = direction
    z["initial_stop"] = [round(px - d * a * m) for px, d, a, m in zip(z.entry_px, direction, z.atr, mult)]
    z["R"] = (z.entry_px - z.initial_stop).abs()
    z["session"] = np.where(z.entry_ts.dt.hour.between(8, 13), "day", "night")
    return z


def cmd_scale_path(row: pd.Series, one_arrays: tuple[np.ndarray, ...], x_r: float) -> dict:
    """Trace a Cmd half-lot only until its original v28 Cmd close.

    The full original Cmd remains the shadow position that produced the
    recorded Add/G path.  This exactly preserves Add/G, while the realised Cmd
    P/L follows target then a price-entry BE stop.
    """
    opens, closes, oo, hh, ll, cc = one_arrays
    entry_t, exit_t = np.datetime64(row.entry_ts), np.datetime64(row.exit_ts)
    side = int(row.direction)
    entry, stop, r = float(row.entry_px), float(row.initial_stop), float(row.R)
    target = entry + side * x_r * r
    market_exit = is_market_v28_exit(str(row.exit_sig))
    ix = int(np.searchsorted(opens, entry_t, side="left"))
    target_hit = False
    be_hit = False
    target_ts = pd.NaT
    be_ts = pd.NaT
    stopped_before_target = False
    while ix < len(opens):
        ot, ct = opens[ix], closes[ix]
        if market_exit and ot >= exit_t:
            break
        if not market_exit and ct > exit_t:
            break
        for p0, p1 in segments(float(oo[ix]), float(hh[ix]), float(ll[ix]), float(cc[ix])):
            # The first point of a later minute catches a gap before the path.
            if not target_hit:
                if (p0 - stop) * side <= 0:
                    stopped_before_target = True
                    break
                if (p0 - target) * side >= 0:
                    target_hit, target_ts = True, pd.Timestamp(ct)
            if target_hit and not be_hit and (p0 - entry) * side <= 0:
                be_hit, be_ts = True, pd.Timestamp(ct)
                break
            if not target_hit:
                if side > 0 and p1 < p0 and p1 <= stop <= p0:
                    stopped_before_target = True
                    break
                if side < 0 and p1 > p0 and p0 <= stop <= p1:
                    stopped_before_target = True
                    break
                if side > 0 and p1 > p0 and p0 <= target <= p1:
                    target_hit, target_ts = True, pd.Timestamp(ct)
                elif side < 0 and p1 < p0 and p1 <= target <= p0:
                    target_hit, target_ts = True, pd.Timestamp(ct)
            if target_hit and not be_hit:
                if side > 0 and p1 < p0 and p1 <= entry <= p0:
                    be_hit, be_ts = True, pd.Timestamp(ct)
                    break
                if side < 0 and p1 > p0 and p0 <= entry <= p1:
                    be_hit, be_ts = True, pd.Timestamp(ct)
                    break
        if stopped_before_target or be_hit:
            break
        ix += 1
    return {
        "target_hit": target_hit and not stopped_before_target, "be_hit": be_hit,
        "target": target, "target_ts": target_ts, "be_ts": be_ts,
    }


def engine_leg(source_id: int, row: pd.Series, qty: float, exit_px: float, exit_ts: pd.Timestamp, sig: str) -> dict:
    side = int(row.direction)
    pnl_engine = (float(exit_px) - float(row.entry_px)) * side * POINT_VALUE * qty - 2.0 * eng.COMMISSION * qty
    return {
        "trade_id": int(source_id), "source_id": int(source_id), "side": row["side"], "kind": row["kind"],
        "entry_ts": row.entry_ts, "entry_px": float(row.entry_px), "exit_ts": pd.Timestamp(exit_ts),
        "exit_px": float(exit_px), "exit_sig": sig, "qty": qty, "pnl_engine": pnl_engine,
        "pnl": pnl_engine - V28_RT_EXTRA * qty,
    }


def c_variant(name: str, ledger: pd.DataFrame, cmd_info: pd.DataFrame, one_arrays: tuple[np.ndarray, ...], x_r: float | None) -> pd.DataFrame:
    cmd_by_id = cmd_info.set_index("source_id")
    rows: list[dict] = []
    for source_id, row in ledger.iterrows():
        rid = int(source_id)
        if row["kind"] != "Cmd" or x_r is None:
            rows.append(engine_leg(rid, row, 1.0, float(row.exit_px), row.exit_ts, str(row.exit_sig)))
            continue
        info = cmd_by_id.loc[rid]
        path = cmd_scale_path(info, one_arrays, x_r)
        if not path["target_hit"]:
            rows.append(engine_leg(rid, info, 1.0, float(info.exit_px), info.exit_ts, str(info.exit_sig)))
        else:
            rows.append(engine_leg(rid, info, 0.5, float(path["target"]), path["target_ts"], f"Cmd_{x_r:g}R_half"))
            if path["be_hit"]:
                rows.append(engine_leg(rid, info, 0.5, float(info.entry_px), path["be_ts"], "Cmd_BE_half"))
            else:
                rows.append(engine_leg(rid, info, 0.5, float(info.exit_px), info.exit_ts, str(info.exit_sig)))
    out = pd.DataFrame(rows)
    out["variant"] = name
    out["exit_day"] = trade_day(out.exit_ts)
    return out


def c_metrics(name: str, legs: pd.DataFrame, v38: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    trades = legs.groupby(["trade_id", "variant"], as_index=False).agg(
        entry_ts=("entry_ts", "min"), exit_ts=("exit_ts", "max"), pnl=("pnl", "sum"),
        total=("pnl_engine", "sum"), qty=("qty", "sum"),
    )
    trades["exit_day"] = trade_day(trades.exit_ts)
    pnl_daily = legs.groupby("exit_day").pnl.sum().sort_index()
    idx = pnl_daily.index.union(v38.index).sort_values()
    aligned = pd.DataFrame({"pnl": pnl_daily.reindex(idx, fill_value=0.0), "v38_pnl": v38.reindex(idx, fill_value=0.0)})
    daily = aligned.reset_index().rename(columns={"index": "date"})
    daily["variant"] = name
    daily["combined_pnl"] = daily.pnl + daily.v38_pnl
    records: list[dict] = []
    for year in YEARS:
        start, end = pd.Timestamp(f"{year}-01-01"), pd.Timestamp(f"{year + 1}-01-01")
        d = aligned.loc[(aligned.index >= start) & (aligned.index < end)]
        t = trades.loc[(trades.exit_day >= start) & (trades.exit_day < end)]
        w, lo = t.loc[t.pnl > 0, "pnl"], t.loc[t.pnl <= 0, "pnl"]
        net, mdd = float(d.pnl.sum()), daily_mdd(d.pnl)
        records.append({
            "idea": name, "year": year, "total": float(t.total.sum()), "net": net, "daily_mdd": mdd,
            "net_mdd": net / abs(mdd) if mdd else np.nan, "trades": len(t),
            "win_rate": float((t.pnl > 0).mean()), "avg_win": float(w.mean()) if len(w) else np.nan,
            "avg_loss": float(-lo.mean()) if len(lo) else np.nan,
            "avg_win_loss": float(w.mean() / -lo.mean()) if len(w) and len(lo) and lo.mean() else np.nan,
            "corr_v38": float(d.pnl.corr(d.v38_pnl)),
        })
    return pd.DataFrame(records), daily, trades


def cmd_mfe_before_stop(row: pd.Series, one_arrays: tuple[np.ndarray, ...]) -> float:
    opens, closes, oo, hh, ll, cc = one_arrays
    entry_t, exit_t = np.datetime64(row.entry_ts), np.datetime64(row.exit_ts)
    side, entry, stop = int(row.direction), float(row.entry_px), float(row.initial_stop)
    market_exit = is_market_v28_exit(str(row.exit_sig))
    ix = int(np.searchsorted(opens, entry_t, side="left"))
    mfe = 0.0
    while ix < len(opens):
        ot, ct = opens[ix], closes[ix]
        if market_exit and ot >= exit_t:
            break
        if not market_exit and ct > exit_t:
            break
        for p0, p1 in segments(float(oo[ix]), float(hh[ix]), float(ll[ix]), float(cc[ix])):
            if (p0 - stop) * side <= 0:
                return mfe
            if side > 0:
                if p1 > p0:
                    mfe = max(mfe, p1 - entry)
                elif p1 <= stop <= p0:
                    return mfe
            else:
                if p1 < p0:
                    mfe = max(mfe, entry - p1)
                elif p0 <= stop <= p1:
                    return mfe
        ix += 1
    return mfe


def quality_table(cmd: pd.DataFrame, b5: pd.DataFrame, one_arrays: tuple[np.ndarray, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    z = cmd.copy()
    b = b5[["close_ts", "ema10", "ema30", "hh20_prev", "close", "ema_long", "ema_short", "atr"]].rename(columns={"atr": "entry_atr"}).copy()
    b["ema_cross"] = (b.ema10 > b.ema30) & (b.ema10.shift(1) <= b.ema30.shift(1))
    b["breakout20"] = (b.close > b.hh20_prev) & (b.close.shift(1) <= b.hh20_prev.shift(1))
    z = pd.merge_asof(z.sort_values("entry_ts"), b.sort_values("close_ts"), left_on="entry_ts", right_on="close_ts", direction="backward")
    z = z.sort_values("source_id").reset_index(drop=True)
    z["entry_type"] = np.where(z.side.eq("L") & z.ema_cross, "EMA交叉", "20-bar突破")
    trend_ema = np.where(z.side.eq("L"), z.ema_long, z.ema_short)
    z["ema_distance_atr"] = (z.close - trend_ema).abs() / z.entry_atr
    z["ema_distance_tercile"] = pd.qcut(z.ema_distance_atr, 3, labels=["近", "中", "遠"], duplicates="drop").astype(str)
    z["mfe_before_initial_stop"] = [cmd_mfe_before_stop(r, one_arrays) for _, r in z.iterrows()]
    for x in (0.5, 1.0, 2.0):
        z[f"hit_{str(x).replace('.', '_')}R"] = z.mfe_before_initial_stop >= x * z.R
    groups: list[tuple[str, str, pd.DataFrame]] = [("整體", "全部", z)]
    for col, label in [("side", "方向"), ("session", "session"), ("entry_type", "進場型態"), ("ema_distance_tercile", "EMA距離三分位")]:
        groups += [(label, str(key), g) for key, g in z.groupby(col, sort=True, dropna=False)]
    out: list[dict] = []
    for dimension, group, g in groups:
        p05, p1, p2 = (float(g[f"hit_{str(x).replace('.', '_')}R"].mean()) for x in (0.5, 1.0, 2.0))
        flags = []
        if p05 < .70:
            flags.append("0.5R<70%")
        if p1 < .50:
            flags.append("1R<50%")
        if p2 < .30:
            flags.append("2R<30%")
        out.append({"dimension": dimension, "group": group, "n": len(g), "p_0_5R": p05, "p_1R": p1, "p_2R": p2, "flag": "；".join(flags) if flags else "通過"})
    return pd.DataFrame(out), z


def present_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    x = metrics.copy()
    for col in ["total", "net", "daily_mdd", "avg_win", "avg_loss"]:
        x[col] = x[col].map(fmt_money)
    for col in ["net_mdd", "avg_win_loss", "corr_v38"]:
        x[col] = x[col].map(lambda v: fmt_num(v, 3))
    x["win_rate"] = x.win_rate.map(lambda v: "—" if not np.isfinite(v) else f"{100*v:.1f}%")
    return x


def write_report(metrics: pd.DataFrame, c_compare: pd.DataFrame, quality: pd.DataFrame, a_verdicts: dict[str, bool], b_ok: bool, c_verdicts: dict[str, bool]) -> None:
    show = present_metrics(metrics)
    show_c = c_compare.copy()
    for col in ["baseline_net", "variant_net", "delta"]:
        show_c[col] = show_c[col].map(fmt_money)
    show_c["beats_baseline"] = show_c.beats_baseline.map(lambda x: "是" if x else "否")
    q = quality.copy()
    for col in ["p_0_5R", "p_1R", "p_2R"]:
        q[col] = q[col].map(lambda v: f"{100*v:.1f}%")
    a_line = "；".join(f"{key}{'通過' if value else '不通過'}" for key, value in a_verdicts.items())
    c_line = "；".join(f"{key}{'通過' if value else '不通過'}" for key, value in c_verdicts.items())
    lines = [
        "# trader3a 想法：預先指定回測結果",
        "",
        "資料使用 `mxf_1min_corrected_20261017b.csv` 至 2026-10-17 03:58。A/B 的一口成本為券商 NT$20、交易稅 `0.00002 × 價格 × 50`，以及每邊 4 點滑價（滑價已放入成交價）；停損以一分 K 觸發，缺口以該分 K 開盤成交。C 沿用指定 v28 口徑：每個 engine lot 的淨利為 engine `pnl − NT$440`。夜盤損益歸到次一交易日，與 V38 日損益對齊。",
        "",
        "## 白話結論",
        "",
        f"- A 趨勢回檔：{a_line}；標準是四個預先指定版本各自 2024、2025、2026 都為正。",
        f"- B 布林擠壓：{'通過' if b_ok else '不通過'}；標準是三個年度都為正。",
        f"- C Cmd 70/30：{c_line}；標準是每年淨利都高於同口徑 v28 基準。Add/G 均直接保留原始 v28 列。",
        "- D Cmd 進場品質：見下表旗標；低於 70%／50%／30% 的群組不應據此套用 70/30 規則。",
        "",
        "## 年度績效",
        "",
        "`total` 是已含滑價的價格損益、未扣列示成本；`net` 是成本後損益。A/B 的交易數是完整部位（A2 的兩個出場 leg 合併為一筆），C 的交易數是原 v28 engine lot（Cmd 兩半合併回一個 lot）。",
        "",
        markdown_table(show, ["idea", "year", "total", "net", "daily_mdd", "net_mdd", "trades", "win_rate", "avg_win", "avg_loss", "avg_win_loss", "corr_v38"], {
            "idea": "版本", "year": "年", "total": "total", "net": "淨利", "daily_mdd": "日MDD", "net_mdd": "淨利/|MDD|",
            "trades": "交易", "win_rate": "勝率", "avg_win": "平均贏", "avg_loss": "平均輸", "avg_win_loss": "贏/輸", "corr_v38": "與V38日PnL相關",
        }),
        "",
        "## C：相對 v28 的年度淨利",
        "",
        markdown_table(show_c, ["variant", "year", "baseline_net", "variant_net", "delta", "beats_baseline"], {
            "variant": "Cmd版本", "year": "年", "baseline_net": "v28淨利", "variant_net": "版本淨利", "delta": "差額", "beats_baseline": "高於基準",
        }),
        "",
        "## D：v28 Cmd 的 70/50/30 品質診斷",
        "",
        "R 為 v28 Cmd 的起始損距；MFE 用一分 K 路徑量測，止損前到過門檻才算成功。EMA 距離採「訊號收盤與多/空趨勢 EMA 的絕對距離／進場 ATR」，以全 Cmd 三分位切分。EMA交叉優先標記；其餘（含空方）歸為 20-bar 突破。",
        "",
        markdown_table(q, ["dimension", "group", "n", "p_0_5R", "p_1R", "p_2R", "flag"], {
            "dimension": "分組", "group": "群組", "n": "Cmd數", "p_0_5R": "先到0.5R", "p_1R": "先到1R", "p_2R": "先到2R", "flag": "低於門檻",
        }),
        "",
        "## 實作註記",
        "",
        "A 的 KD 定義為 raw %K(14) 後 SMA(3)，%D 為 K 的 SMA(3)；15m A 只把 KD/MACD 的進場週期改為 15m，停損與偏離/趨勢出場仍照題意使用 5m。B 的擠壓為前四根 15m BB width 百分位都低於 20，下一根 width 上升；ATR trail 以進場後完成的 15m 高/低點棘輪。所有 A/B bars 都按日盤 08:45–13:45、夜盤 15:00–05:00 分開聚合，絕不跨 session，並在 session end 平倉。",
        "",
        "C 的 Cmd wrapper 以原 Cmd 作影子部位維持引擎的 Add/G 時序；達 X×R 時以目標價出半口，另半口若先碰 entry 價即以 entry 價出場，否則沿用原 Cmd 出場。這正是『只改初始 Cmd、Adds/G 不變』的可回放實作。",
        "",
        "## 產出檔案",
        "",
        "`t3a_metrics_yearly.csv`、`t3a_daily_*.csv`、`t3a_trades_*.csv`、`t3a_c_compare.csv`、`t3a_c_addg_unchanged.csv`、`t3a_cmd_quality.csv`、`t3a_cmd_quality_observations.csv`。",
    ]
    (HERE / "results_3a_ideas.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    print("load one-minute data", flush=True)
    one_raw = eng.load_1min(DATA)
    one_raw = one_raw.loc[one_raw.ts <= CUTOFF].copy()
    one = sessionize(one_raw)
    v38 = pd.read_csv(V38_DAILY, parse_dates=["date"]).set_index("date").v38_pnl.sort_index()
    print("build session-bounded A/B bars", flush=True)
    five, fifteen, _, one = build_sleeve_inputs(one)

    a_metrics: list[pd.DataFrame] = []
    all_daily: list[pd.DataFrame] = []
    a_verdicts: dict[str, bool] = {}
    for tf_name, entry in [("5m", five), ("15m", fifteen)]:
        sig = make_a_signals(entry, five)
        for suffix, scaled in [("A1偏離出場", False), ("A2_70_30", True)]:
            name = f"A_{tf_name}_{suffix}"
            print(f"run {name}", flush=True)
            legs = run_trend_pullback(name, one, sig, five, scaled)
            met, daily, campaigns = sleeve_metrics(name, legs, v38)
            save(legs, f"t3a_trades_{name}.csv")
            save(campaigns, f"t3a_campaigns_{name}.csv")
            save(daily, f"t3a_daily_{name}.csv")
            a_metrics.append(met); all_daily.append(daily)
            a_verdicts[name] = bool((met.net > 0).all())

    print("run B bollinger sleeve", flush=True)
    b_sig = make_b_signals(fifteen)
    b_name = "B_BB_squeeze_15m"
    b_legs = run_bollinger(b_name, one, b_sig, fifteen)
    b_met, b_daily, b_campaigns = sleeve_metrics(b_name, b_legs, v38)
    save(b_legs, f"t3a_trades_{b_name}.csv")
    save(b_campaigns, f"t3a_campaigns_{b_name}.csv")
    save(b_daily, f"t3a_daily_{b_name}.csv")
    all_daily.append(b_daily)
    b_ok = bool((b_met.net > 0).all())

    print("prepare V38 Cmd wrapper and quality diagnostic", flush=True)
    ledger = pd.read_csv(V28_LEDGER, parse_dates=["entry_ts", "exit_ts"])
    ledger["direction"] = np.where(ledger.side.eq("L"), 1, -1)
    ledger.index.name = "source_id"
    cmd = ledger.loc[ledger.kind.eq("Cmd")].copy().reset_index()
    b5_engine = eng.prepare(one_raw, {**eng.P, **v28_params()})
    cmd = cmd_stop_info(cmd, b5_engine)
    arrays = tuple(one_raw[c].to_numpy() for c in ["open_ts", "ts", "open", "high", "low", "close"])
    c_metrics_all: list[pd.DataFrame] = []
    c_compare_rows: list[dict] = []
    c_verdicts: dict[str, bool] = {}
    c_baseline_net: pd.Series | None = None
    addg_check_rows: list[dict] = []
    for name, x_r in [("C_v28_base", None), ("C_Cmd_1R_70_30", 1.0), ("C_Cmd_1_5R_70_30", 1.5)]:
        print(f"run {name}", flush=True)
        legs = c_variant(name, ledger, cmd, arrays, x_r)
        met, daily, trades = c_metrics(name, legs, v38)
        save(legs, f"t3a_trades_{name}.csv")
        save(trades, f"t3a_campaigns_{name}.csv")
        save(daily, f"t3a_daily_{name}.csv")
        c_metrics_all.append(met); all_daily.append(daily)
        net = met.set_index("year").net
        if x_r is None:
            c_baseline_net = net
        else:
            assert c_baseline_net is not None
            beats = net > c_baseline_net
            c_verdicts[name] = bool(beats.all())
            for year in YEARS:
                c_compare_rows.append({"variant": name, "year": year, "baseline_net": float(c_baseline_net.loc[year]), "variant_net": float(net.loc[year]), "delta": float(net.loc[year] - c_baseline_net.loc[year]), "beats_baseline": bool(beats.loc[year])})
            original_addg = ledger.loc[ledger.kind.ne("Cmd"), "pnl"]
            copied_addg = legs.loc[legs.kind.ne("Cmd")].groupby("source_id").pnl_engine.sum().reindex(original_addg.index)
            addg_check_rows.append({"variant": name, "addg_rows": len(copied_addg), "all_addg_pnl_unchanged": bool(np.allclose(copied_addg.to_numpy(float), original_addg.to_numpy(float))), "addg_engine_pnl": float(copied_addg.sum())})
    c_compare = pd.DataFrame(c_compare_rows)
    save(c_compare, "t3a_c_compare.csv")
    save(pd.DataFrame(addg_check_rows), "t3a_c_addg_unchanged.csv")

    print("run Cmd quality profile", flush=True)
    quality, observations = quality_table(cmd, b5_engine, arrays)
    save(quality, "t3a_cmd_quality.csv")
    save(observations, "t3a_cmd_quality_observations.csv")

    metrics = pd.concat(a_metrics + [b_met] + c_metrics_all, ignore_index=True)
    save(metrics, "t3a_metrics_yearly.csv")
    save(pd.concat(all_daily, ignore_index=True), "t3a_daily_all.csv")
    write_report(metrics, c_compare, quality, a_verdicts, b_ok, c_verdicts)
    print("wrote results_3a_ideas.md and t3a_*.csv", flush=True)


if __name__ == "__main__":
    main()
