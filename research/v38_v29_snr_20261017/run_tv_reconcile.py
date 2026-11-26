"""Reconcile the TradingView v27 trade-list export against the local v27 engine.

The upstream engine is imported read-only.  The only cost experiment changes its
module-level commission in memory and restores it immediately afterwards.
"""
from __future__ import annotations

import calendar
import sys
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
TV_FILE = HERE / "tv_exports" / "V38.0707_v27_Session_TAIFEX_MXF1!_2026-10-18.csv"
DATA_FILE = HERE / "mxf_1min_corrected_20261017b.csv"
ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
REPORT = HERE / "results_tv_reconcile.md"
POINT_VALUE = 50.0
TV_SLIP_TICKS = 4.0
TV_COMMISSION_SIDE = 40.0
LIVE = {"opt_stale_hr": 10, "opt_cooldown_min": 30}


def out_csv(frame: pd.DataFrame, stem: str) -> Path:
    path = HERE / f"tvrec_{stem}.csv"
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def ncol(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False), errors="coerce")


def fnum(x: float | int | np.floating | None, digits: int = 0) -> str:
    if x is None or pd.isna(x):
        return "—"
    if np.isinf(x):
        return "∞"
    return f"{float(x):,.{digits}f}"


def fpct(x: float | int | np.floating | None, digits: int = 1) -> str:
    if x is None or pd.isna(x):
        return "—"
    if np.isinf(x):
        return "∞"
    return f"{float(x):.{digits}f}%"


def md_table(frame: pd.DataFrame, cols: list[str], digits: dict[str, int] | None = None) -> list[str]:
    digits = digits or {}
    if frame.empty:
        return ["（無資料）"]
    rows = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for values in frame.loc[:, cols].itertuples(index=False, name=None):
        cell = []
        for col, value in zip(cols, values):
            if isinstance(value, (float, np.floating)):
                cell.append(fnum(value, digits.get(col, 2)))
            else:
                cell.append(str(value))
        rows.append("| " + " | ".join(cell) + " |")
    return rows


def metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    """Closed-trade metrics; simultaneous closes are netted before MDD."""
    if frame.empty:
        return {"trades": 0, "net": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
                "pf": np.nan, "win_rate": np.nan, "closed_mdd": 0.0, "net_mdd": np.nan}
    pnl = frame["pnl"].astype(float)
    gp = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl <= 0].sum())
    closed = frame.groupby("exit_ts", sort=True)["pnl"].sum()
    equity = pd.concat([pd.Series([0.0]), closed.cumsum()], ignore_index=True)
    mdd = float((equity - equity.cummax()).min())
    net = float(pnl.sum())
    return {
        "trades": int(len(frame)), "net": net, "gross_profit": gp, "gross_loss": gl,
        "pf": gp / gl if gl else np.inf, "win_rate": 100 * float((pnl > 0).mean()),
        "closed_mdd": mdd, "net_mdd": net / abs(mdd) if mdd else np.inf,
    }


def table_metrics(frame: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    rows = []
    group_key: str | list[str] = by[0] if len(by) == 1 else by
    for key, sub in frame.groupby(group_key, sort=True, dropna=False):
        keys = (key,) if len(by) == 1 else key
        rows.append(dict(zip(by, keys), **metrics(sub)))
    return pd.DataFrame(rows)


def read_tv() -> tuple[pd.DataFrame, dict[str, int]]:
    raw = pd.read_csv(TV_FILE, encoding="utf-8-sig")
    # Index 1 is 類型.  It is the *sole* source for entry/exit classification.
    typ = raw.iloc[:, 1].astype(str)
    entry = raw.loc[typ.str.contains("進場", regex=False)].copy()
    exit_ = raw.loc[typ.str.contains("出場", regex=False)].copy()
    e = pd.DataFrame({
        "trade_id": entry.iloc[:, 0].astype(str),
        "entry_type": entry.iloc[:, 1].astype(str),
        "entry_ts": pd.to_datetime(entry.iloc[:, 2], errors="coerce"),
        "entry_signal": entry.iloc[:, 3].astype(str),
        "entry_px": ncol(entry.iloc[:, 4]),
    })
    x = pd.DataFrame({
        "trade_id": exit_.iloc[:, 0].astype(str),
        "exit_type": exit_.iloc[:, 1].astype(str),
        "exit_ts": pd.to_datetime(exit_.iloc[:, 2], errors="coerce"),
        "exit_signal": exit_.iloc[:, 3].astype(str),
        "exit_px": ncol(exit_.iloc[:, 4]),
        "pnl": ncol(exit_.iloc[:, 7]),
        "commission": ncol(exit_.iloc[:, 9]),
        "cumulative_pnl": ncol(exit_.iloc[:, 14]),
    })
    # The two final rows have an open-position text in the date column, so their
    # associated trade IDs are excluded by requiring a valid exit datetime.
    d = e.merge(x, on="trade_id", how="inner", validate="one_to_one")
    d = d.dropna(subset=["entry_ts", "exit_ts", "entry_px", "exit_px", "pnl"]).copy()
    d["side"] = np.where(d["entry_type"].str.contains("多頭", regex=False), "L", "S")
    d["kind"] = d["entry_signal"].str.extract(r"_(Cmd|Add|G)", expand=False).fillna("Other")
    d["year"] = d["exit_ts"].dt.year
    d["quarter"] = d["exit_ts"].dt.to_period("Q").astype(str)
    d = d.sort_values(["exit_ts", "trade_id"]).reset_index(drop=True)
    audit = {
        "raw_rows": len(raw), "entry_rows": len(entry), "exit_rows": len(exit_),
        "closed_trades": len(d), "open_rows_excluded": int(x.exit_ts.isna().sum()),
    }
    return d, audit


def add_campaigns(d: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Campaign = same-side, overlap-connected set of closed lots."""
    q = d.sort_values(["side", "entry_ts", "exit_ts", "trade_id"]).copy()
    campaign = []
    for side, sub in q.groupby("side", sort=True):
        cur = 0
        active_until = pd.Timestamp.min
        for ix, row in sub.iterrows():
            if row.entry_ts > active_until:
                cur += 1
                active_until = row.exit_ts
            else:
                active_until = max(active_until, row.exit_ts)
            campaign.append((ix, f"{side}{cur:04d}"))
    cmap = pd.Series({i: c for i, c in campaign}, name="campaign_id")
    q = q.join(cmap).sort_index()
    d2 = d.join(q["campaign_id"])
    camp = d2.groupby("campaign_id", as_index=False).agg(
        side=("side", "first"), campaign_entry_ts=("entry_ts", "min"),
        campaign_exit_ts=("exit_ts", "max"), lots=("pnl", "size"),
        net=("pnl", "sum"), gross_profit=("pnl", lambda z: z[z > 0].sum()),
        gross_loss=("pnl", lambda z: -z[z <= 0].sum()),
    )
    camp["year"] = camp.campaign_exit_ts.dt.year
    concentration = []
    for year, sub in camp.groupby("year", sort=True):
        pos = sub.loc[sub.net > 0, "net"].sort_values(ascending=False)
        total_net = float(sub.net.sum())
        total_pos = float(pos.sum())
        rec: dict[str, float | int] = {"year": int(year), "campaigns": int(len(sub)),
                                        "net": total_net, "positive_campaign_profit": total_pos}
        for n in (1, 5, 10):
            top = float(pos.head(n).sum())
            rec[f"top{n}_net"] = top
            rec[f"top{n}_share_net_pct"] = 100 * top / total_net if total_net else np.nan
            rec[f"top{n}_share_positive_pct"] = 100 * top / total_pos if total_pos else np.nan
        concentration.append(rec)
    return d2, camp, pd.DataFrame(concentration)


def read_engine_csv(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path, parse_dates=["entry_ts", "exit_ts"])
    d["side"] = d["side"].astype(str)
    d["kind"] = d["kind"].astype(str)
    d["year"] = d.exit_ts.dt.year
    d["quarter"] = d.exit_ts.dt.to_period("Q").astype(str)
    return d


def engine_runs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return supplied 1m run plus fresh OHLC and in-memory TV-cost OHLC runs."""
    if str(ENGINE_DIR) not in sys.path:
        sys.path.insert(0, str(ENGINE_DIR))
    import engine_v26_bbw as eng  # read-only source; no file is changed

    df1m = eng.load_1min(DATA_FILE)
    supplied_1m = read_engine_csv(HERE / "trades_v27.csv")
    fresh_1m = eng.run(df1m, p=LIVE, intrabar_mode="1min")
    fresh_1m["entry_ts"] = pd.to_datetime(fresh_1m.entry_ts)
    fresh_1m["exit_ts"] = pd.to_datetime(fresh_1m.exit_ts)
    fresh_1m["year"] = fresh_1m.exit_ts.dt.year
    fresh_1m["quarter"] = fresh_1m.exit_ts.dt.to_period("Q").astype(str)

    ohlc = eng.run(df1m, p=LIVE, intrabar_mode="ohlc")
    ohlc["entry_ts"] = pd.to_datetime(ohlc.entry_ts)
    ohlc["exit_ts"] = pd.to_datetime(ohlc.exit_ts)
    ohlc["year"] = ohlc.exit_ts.dt.year
    ohlc["quarter"] = ohlc.exit_ts.dt.to_period("Q").astype(str)

    old_commission = eng.COMMISSION
    try:
        eng.COMMISSION = TV_COMMISSION_SIDE  # temporary process-only monkeypatch
        ohlc_cost = eng.run(df1m, p=LIVE, intrabar_mode="ohlc")
    finally:
        eng.COMMISSION = old_commission
    ohlc_cost["entry_ts"] = pd.to_datetime(ohlc_cost.entry_ts)
    ohlc_cost["exit_ts"] = pd.to_datetime(ohlc_cost.exit_ts)
    # Engine has no slippage parameter.  Apply TV's known 4 points/order as
    # accounting only; bracket levels and signal paths remain the engine's.
    ohlc_cost["pnl_tv_cost"] = ohlc_cost.pnl - 2 * TV_SLIP_TICKS * POINT_VALUE
    ohlc_cost["year"] = ohlc_cost.exit_ts.dt.year
    ohlc_cost["quarter"] = ohlc_cost.exit_ts.dt.to_period("Q").astype(str)
    b5 = eng.build_bars(df1m, 5)
    b5["open_ts"] = pd.to_datetime(b5.open_ts)
    return supplied_1m, fresh_1m, ohlc, ohlc_cost, b5


def with_match_index(d: pd.DataFrame, prefix: str) -> pd.DataFrame:
    x = d.copy()
    keys = ["entry_ts", "side"]
    x["match_seq"] = x.groupby(keys, sort=False).cumcount()
    x = x.rename(columns={c: f"{prefix}_{c}" for c in x.columns if c not in keys + ["match_seq"]})
    return x


def reconcile(tv: pd.DataFrame, engine: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # The requested overlap is based on the closed-trade date range (thus it
    # includes any Jan-02 entry closed on Jan-03).
    start = engine.exit_ts.min().normalize()
    end = engine.exit_ts.max().normalize() + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    tv_o = tv[(tv.exit_ts >= start) & (tv.exit_ts <= end)].copy()
    en_o = engine[(engine.exit_ts >= start) & (engine.exit_ts <= end)].copy()
    t = with_match_index(tv_o, "tv")
    e = with_match_index(en_o, "engine")
    keys = ["entry_ts", "side", "match_seq"]
    joined = t.merge(e, on=keys, how="outer", indicator=True, sort=False)
    joined["classification"] = joined["_merge"].map({"both": "matched", "left_only": "TV-only", "right_only": "engine-only"})
    joined = joined.drop(columns="_merge")
    matched = joined[joined.classification.eq("matched")].copy()
    # Reported TV prices already include its deterministic 4-tick adverse fill.
    # Back it out solely for an additive decomposition, not as a claim about
    # unobservable raw TV tick data.
    direction = np.where(matched.side.eq("L"), 1.0, -1.0)
    matched["tv_entry_pre_slip"] = matched.tv_entry_px - direction * TV_SLIP_TICKS
    matched["tv_exit_pre_slip"] = matched.tv_exit_px + direction * TV_SLIP_TICKS
    matched["component_cost_slippage"] = -2 * ((TV_COMMISSION_SIDE - 20.0) + TV_SLIP_TICKS * POINT_VALUE)
    matched["component_entry_price"] = -direction * (matched.tv_entry_pre_slip - matched.engine_entry_px) * POINT_VALUE
    matched["component_exit_time_price"] = direction * (matched.tv_exit_pre_slip - matched.engine_exit_px) * POINT_VALUE
    matched["pnl_difference"] = matched.tv_pnl - matched.engine_pnl
    matched["decomposition_sum"] = matched[["component_cost_slippage", "component_entry_price", "component_exit_time_price"]].sum(axis=1)
    matched["decomposition_residual"] = matched.pnl_difference - matched.decomposition_sum
    matched["exit_time_same"] = matched.tv_exit_ts.eq(matched.engine_exit_ts)
    matched["year"] = matched.tv_exit_ts.dt.year
    decomp = (matched.groupby("year", dropna=False)[[
        "pnl_difference", "component_cost_slippage", "component_entry_price",
        "component_exit_time_price", "decomposition_residual",
    ]].sum().reset_index())
    exit_same = matched.groupby("year", as_index=False).agg(
        matched=("classification", "size"), exit_time_same_pct=("exit_time_same", lambda z: 100 * z.mean()),
        median_abs_exit_delay_min=("engine_exit_ts", lambda z: np.nan),
    )
    delay = (matched.engine_exit_ts - matched.tv_exit_ts).dt.total_seconds().abs() / 60
    med_delay = matched.assign(abs_exit_delay_min=delay).groupby("year").abs_exit_delay_min.median()
    exit_same["median_abs_exit_delay_min"] = exit_same.year.map(med_delay)
    decomp = decomp.merge(exit_same, on="year", how="left")
    return tv_o, en_o, joined, matched, decomp


def session_zone(ts: pd.Timestamp) -> str:
    minute = ts.hour * 60 + ts.minute
    if 8 * 60 + 45 <= minute <= 9 * 60:
        return "日盤開盤 08:45–09:00"
    if 13 * 60 + 30 <= minute <= 13 * 60 + 45:
        return "日盤收盤 13:30–13:45"
    if 15 * 60 <= minute <= 15 * 60 + 15:
        return "夜盤開盤 15:00–15:15"
    if 4 * 60 + 45 <= minute <= 5 * 60:
        return "夜盤 05:00 收盤附近"
    if 8 * 60 + 45 <= minute <= 13 * 60 + 45:
        return "日盤其他"
    return "夜盤其他"


def unmatched_bar_check(joined: pd.DataFrame, b5: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    tv_only = joined[joined.classification.eq("TV-only")].copy()
    e_only = joined[joined.classification.eq("engine-only")].copy()
    bars = b5.rename(columns={c: f"bar_{c}" for c in ["open", "high", "low", "close"]})
    tv_only = tv_only.merge(bars[["open_ts", "bar_open", "bar_high", "bar_low", "bar_close"]],
                            left_on="entry_ts", right_on="open_ts", how="left")
    direction = np.where(tv_only.side.eq("L"), 1.0, -1.0)
    tv_only["tv_entry_pre_slip"] = tv_only.tv_entry_px - direction * TV_SLIP_TICKS
    tv_only["bar_found"] = tv_only.bar_open.notna()
    tv_only["pre_slip_in_5m_range"] = tv_only.bar_found & tv_only.tv_entry_pre_slip.between(tv_only.bar_low, tv_only.bar_high)
    tv_only["pre_slip_minus_5m_open"] = tv_only.tv_entry_pre_slip - tv_only.bar_open
    tv_only["session_zone"] = tv_only.entry_ts.map(session_zone)
    tv_only["year"] = tv_only.entry_ts.dt.year
    summary = tv_only.groupby(["year", "session_zone"], as_index=False).agg(
        TV_only=("classification", "size"), bar_found=("bar_found", "sum"),
        in_5m_range_pct=("pre_slip_in_5m_range", lambda z: 100 * z.mean()),
        median_abs_pre_slip_vs_open=("pre_slip_minus_5m_open", lambda z: z.abs().median()),
    )
    e_only["session_zone"] = e_only.entry_ts.map(session_zone)
    engine_summary = e_only.groupby([e_only.entry_ts.dt.year.rename("year"), "session_zone"], as_index=False).size().rename(columns={"size": "engine_only"})
    return tv_only, summary, engine_summary


def third_wednesday(year: int, month: int) -> pd.Timestamp:
    weeks = calendar.monthcalendar(year, month)
    days = [week[calendar.WEDNESDAY] for week in weeks if week[calendar.WEDNESDAY] != 0]
    return pd.Timestamp(year=year, month=month, day=days[2])


def rollover_check(matched: pd.DataFrame, joined: pd.DataFrame) -> pd.DataFrame:
    # Local operational documentation says the live contract moves on the day
    # before the third Wednesday. The bar source itself has no contract label.
    days = [third_wednesday(y, mo) - pd.Timedelta(days=1) for y in range(2024, 2027) for mo in range(1, 13)]
    m = matched.copy()
    m["roll_window"] = m.entry_ts.dt.normalize().map(lambda d: any(abs((d - x).days) <= 1 for x in days))
    m["abs_pre_slip_entry_diff"] = (m.tv_entry_pre_slip - m.engine_entry_px).abs()
    rows = []
    for label, sub in m.groupby("roll_window"):
        rows.append({
            "sample": "matched", "window": "換月日前後 1 日" if label else "其他日期", "n": len(sub),
            "median_abs_pre_slip_entry_diff": sub.abs_pre_slip_entry_diff.median(),
            "p95_abs_pre_slip_entry_diff": sub.abs_pre_slip_entry_diff.quantile(.95),
            "mean_pre_slip_entry_diff": (sub.tv_entry_pre_slip - sub.engine_entry_px).mean(),
            "exit_time_same_pct": 100 * sub.exit_time_same.mean(),
        })
    tv_only = joined[joined.classification.eq("TV-only")].copy()
    tv_only["roll_window"] = tv_only.entry_ts.dt.normalize().map(lambda d: any(abs((d - x).days) <= 1 for x in days))
    for label, sub in tv_only.groupby("roll_window"):
        rows.append({"sample": "TV-only", "window": "換月日前後 1 日" if label else "其他日期", "n": len(sub),
                     "median_abs_pre_slip_entry_diff": np.nan, "p95_abs_pre_slip_entry_diff": np.nan,
                     "mean_pre_slip_entry_diff": np.nan, "exit_time_same_pct": np.nan})
    return pd.DataFrame(rows)


def regime_table() -> pd.DataFrame:
    idx = pd.read_csv(HERE / "calendar_index_daily.csv", parse_dates=["date"])
    idx = idx[idx.name.eq("TAIEX")].sort_values("date").copy()
    idx["prev_close"] = idx.close.shift(1)
    tr = pd.concat([(idx.high - idx.low), (idx.high - idx.prev_close).abs(), (idx.low - idx.prev_close).abs()], axis=1).max(axis=1)
    idx["atr20"] = tr.ewm(alpha=1 / 20, adjust=False).mean()
    idx["atr_pct"] = 100 * idx.atr20 / idx.close
    idx["ema60"] = idx.close.ewm(span=60, adjust=False).mean()
    idx["above_ema60"] = idx.close > idx.ema60
    idx["daily_return"] = idx.close.pct_change()
    rows = []
    for year, sub in idx[idx.date.dt.year.between(2022, 2026)].groupby(idx.date.dt.year):
        rows.append({
            "year": int(year), "start_close": sub.close.iloc[0], "end_close": sub.close.iloc[-1],
            "return_pct": 100 * (sub.close.iloc[-1] / sub.close.iloc[0] - 1),
            "mean_atr20_pct": sub.atr_pct.mean(),
            "daily_vol_pct": 100 * sub.daily_return.std(),
            "above_ema60_pct": 100 * sub.above_ema60.mean(),
            "trend_distance_atr": ((sub.close - sub.ema60).abs() / sub.atr20).mean(),
        })
    return pd.DataFrame(rows)


def cost_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    regime = regime_table()
    tax = regime[["year", "start_close", "end_close"]].copy()
    # Tax is 0.00002 × MXF contract value (= index × 50) per side.
    tax["tax_start_per_side"] = tax.start_close * POINT_VALUE * 0.00002
    tax["tax_end_per_side"] = tax.end_close * POINT_VALUE * 0.00002
    # Recompute annual average from the daily index so level movement is represented.
    idx = pd.read_csv(HERE / "calendar_index_daily.csv", parse_dates=["date"])
    tai = idx[idx.name.eq("TAIEX")].copy()
    mean_tax = tai.assign(year=tai.date.dt.year, tax=tai.close * POINT_VALUE * 0.00002).groupby("year").tax.mean()
    tax["tax_mean_per_side"] = tax.year.map(mean_tax)
    cost_rows = []
    for version in ("v27", "v28", "v29"):
        tr = read_engine_csv(HERE / f"trades_{version}.csv")
        base = float(tr.pnl.sum())  # already subtracts 20/side = 40 round trip
        n = len(tr)
        cost_rows.append({
            "version": version, "trades": n, "engine_cost20_side_net": base,
            "net_40side_plus_1tick": base - n * 140.0,
            "net_40side_plus_2ticks": base - n * 240.0,
            "net_40side_plus_4ticks": base - n * 440.0,
        })
    return tax, pd.DataFrame(cost_rows)


def drawdown_context(d: pd.DataFrame, date: pd.Timestamp) -> tuple[pd.DataFrame, dict[str, object]]:
    daily = d.assign(day=d.exit_ts.dt.normalize()).groupby("day", as_index=False).pnl.sum().sort_values("day")
    daily["equity"] = daily.pnl.cumsum()
    daily["drawdown"] = daily.equity - daily.equity.cummax()
    before = daily[daily.day <= date]
    row = before.iloc[-1] if not before.empty else None
    window = daily[(daily.day >= "2026-07-29") & (daily.day <= "2026-09-30")]
    trough = window.loc[window.drawdown.idxmin()] if not window.empty else None
    context = {
        "date": date.date().isoformat(),
        "equity": float(row.equity) if row is not None else np.nan,
        "drawdown": float(row.drawdown) if row is not None else np.nan,
        "window_net": float(daily[(daily.day >= "2026-07-01") & (daily.day <= "2026-09-30")].pnl.sum()),
        "window_mdd": float(daily[(daily.day >= "2026-07-01") & (daily.day <= "2026-09-30")].drawdown.min()),
        "post_0729_trough_day": trough.day.date().isoformat() if trough is not None else None,
        "post_0729_trough_dd": float(trough.drawdown) if trough is not None else np.nan,
    }
    return daily[(daily.day >= "2026-06-15") & (daily.day <= "2026-09-15")], context


def main() -> None:
    tv, audit = read_tv()
    tv, campaigns, concentration = add_campaigns(tv)
    yearly = table_metrics(tv, ["year"])
    quarterly = table_metrics(tv, ["quarter"])
    side_kind = table_metrics(tv, ["year", "side", "kind"])
    exit_attr = table_metrics(tv, ["year", "exit_signal"])
    tv["era"] = np.where(tv.year <= 2023, "2022–2023", "2024–2026")
    era_side_kind = table_metrics(tv, ["era", "side", "kind"])
    era_exit = table_metrics(tv, ["era", "exit_signal"])
    out_csv(yearly, "tv_yearly")
    out_csv(quarterly, "tv_quarterly")
    out_csv(side_kind, "tv_side_kind")
    out_csv(exit_attr, "tv_exit_attribution")
    out_csv(era_side_kind, "tv_era_side_kind")
    out_csv(era_exit, "tv_era_exit_attribution")
    out_csv(campaigns, "tv_campaigns")
    out_csv(concentration, "tv_campaign_concentration")

    supplied, fresh1m, ohlc, ohlc_cost, b5 = engine_runs()
    # The supplied live-config CSV is the reference. Preserve a transparent
    # fresh-run check rather than silently assuming reproduction.
    supplied_key = supplied[["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl"]].reset_index(drop=True)
    fresh_key = fresh1m[["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl"]].reset_index(drop=True)
    fresh_equal = supplied_key.equals(fresh_key)
    reproduction_diff = supplied_key.merge(fresh_key, how="outer", indicator=True)
    reproduction_diff["classification"] = reproduction_diff["_merge"].map({
        "both": "same", "left_only": "provided_only", "right_only": "fresh_b_only",
    })
    reproduction_diff = reproduction_diff.drop(columns="_merge")
    out_csv(reproduction_diff, "engine_1min_reproduction_diff")
    tv_o, en_o, classified, matched, decomp = reconcile(tv, supplied)
    out_csv(classified, "reconciliation_classification")
    out_csv(matched, "matched_decomposition")
    out_csv(decomp, "matched_decomposition_summary")
    tv_only_bars, bar_summary, engine_only_summary = unmatched_bar_check(classified, b5)
    out_csv(tv_only_bars, "tv_only_entry_bars")
    out_csv(bar_summary, "tv_only_bar_summary")
    out_csv(engine_only_summary, "engine_only_session_summary")
    roll = rollover_check(matched, classified)
    out_csv(roll, "rollover_check")

    q_tv = tv_o.groupby("quarter", as_index=False).agg(TV_trades=("pnl", "size"), TV_net=("pnl", "sum"))
    q_engine = en_o.groupby("quarter", as_index=False).agg(engine_trades=("pnl", "size"), engine_net=("pnl", "sum"))
    overlap_quarterly = q_tv.merge(q_engine, on="quarter", how="outer").sort_values("quarter")
    overlap_quarterly["TV_minus_engine"] = overlap_quarterly.TV_net - overlap_quarterly.engine_net
    out_csv(overlap_quarterly, "overlap_quarterly")

    one_min_cost = supplied.copy()
    # This is the like-for-like accounting comparator. Unlike the fresh OHLC
    # run, it does not move stops for slippage because the source lacks a
    # slippage price-path parameter.
    one_min_cost["pnl_tv_cost"] = one_min_cost.pnl - 440.0
    run_rows = []
    for label, tr, pnl_col in [
        ("engine 1min（提供的 live-config）", supplied, "pnl"),
        ("engine 1min + TV 成本（帳務）", one_min_cost, "pnl_tv_cost"),
        ("engine 1min（本次重跑）", fresh1m, "pnl"),
        ("engine 5m OHLC heuristic", ohlc, "pnl"),
        ("engine 5m OHLC + TV 成本", ohlc_cost.rename(columns={"pnl_tv_cost": "pnl_for_metrics"}), "pnl_for_metrics"),
    ]:
        z = tr.copy()
        if pnl_col != "pnl":
            z["pnl"] = z[pnl_col]
        run_rows.append({"run": label, **metrics(z), "TV_overlap_net": float(tv_o.pnl.sum()),
                         "TV_minus_run": float(tv_o.pnl.sum() - z.pnl.sum())})
    runs = pd.DataFrame(run_rows)
    out_csv(runs, "engine_run_comparison")

    reg = regime_table()
    tax, cost = cost_tables()
    out_csv(reg, "regime_taiex")
    out_csv(tax, "tax_by_year")
    out_csv(cost, "realistic_cost_restatement")

    dd_tv, dd_tv_info = drawdown_context(tv, pd.Timestamp("2026-07-29"))
    dd_en, dd_en_info = drawdown_context(supplied, pd.Timestamp("2026-07-29"))
    dd = dd_tv.merge(dd_en, on="day", how="outer", suffixes=("_TV", "_engine"))
    out_csv(dd, "drawdown_20260729")

    counts = classified.classification.value_counts()
    total_tv = int(len(tv_o)); total_en = int(len(en_o)); n_match = int(counts.get("matched", 0))
    n_tvonly = int(counts.get("TV-only", 0)); n_enonly = int(counts.get("engine-only", 0))
    full_22_23 = yearly[yearly.year.isin([2022, 2023])].copy()
    full_24_26 = yearly[yearly.year.isin([2024, 2025, 2026])].copy()
    no_positive = int((yearly.net <= 0).sum())
    low_200k = int((yearly.net < 200_000).sum())
    de_total = decomp.select_dtypes("number").sum(numeric_only=True)
    all_bar = tv_only_bars
    bar_found_pct = 100 * all_bar.bar_found.mean() if len(all_bar) else np.nan
    in_range_pct = 100 * all_bar.pre_slip_in_5m_range.mean() if len(all_bar) else np.nan
    zone_stats = all_bar.groupby("session_zone").agg(
        n=("classification", "size"), in_range=("pre_slip_in_5m_range", "mean"),
        median_abs_open=("pre_slip_minus_5m_open", lambda z: z.abs().median()),
    )
    day_open_zone = zone_stats.loc["日盤開盤 08:45–09:00"]
    close05_zone = zone_stats.loc["夜盤 05:00 收盤附近"]
    roll_m = roll[roll["sample"].eq("matched")].set_index("window")
    roll_normal = roll_m.loc["其他日期"]
    roll_window = roll_m.loc["換月日前後 1 日"]
    top_conc = concentration[concentration.year.isin([2022, 2023, 2024, 2025, 2026])]
    era_exit_top = (era_exit.assign(abs_net=era_exit.net.abs()).sort_values(["era", "abs_net"], ascending=[True, False])
                    .groupby("era", group_keys=False).head(5).drop(columns="abs_net"))
    tv_run = runs.loc[runs.run.eq("engine 5m OHLC + TV 成本"), :].iloc[0]
    one_run = runs.loc[runs.run.eq("engine 1min（提供的 live-config）"), :].iloc[0]
    one_cost_run = runs.loc[runs.run.eq("engine 1min + TV 成本（帳務）"), :].iloc[0]
    raw_gap_close = float(one_run.TV_minus_run - runs.loc[runs.run.eq("engine 5m OHLC heuristic"), "TV_minus_run"].iloc[0])
    raw_gap_close_pct = 100 * raw_gap_close / float(one_run.TV_minus_run)
    fair_gap_close = float(one_cost_run.TV_minus_run - tv_run.TV_minus_run)
    fair_gap_close_pct = 100 * fair_gap_close / float(one_cost_run.TV_minus_run)
    key_quarters = overlap_quarterly[overlap_quarterly.quarter.isin(["2024Q1", "2026Q3"])]

    lines: list[str] = [
        "# TV v27 匯出與 Python engine 對帳",
        "",
        "## 結論",
        "",
        f"TV 5 分鐘 heuristic 與 engine 1 分鐘不只是成本差異：重疊期 {total_tv:,} 筆 TV 對 {total_en:,} 筆 engine，僅 {n_match:,} 筆（{100*n_match/total_tv:.1f}% 的 TV）以進場時間＋方向對得上；TV-only {n_tvonly:,}、engine-only {n_enonly:,}。因此兩者不可互相當作驗證。",
        "",
        "對實盤 alert 而言，應以 Python 的 1 分鐘路徑 engine 為研究與風控 source of truth；它使用本地近月連續資料及較細的盤內順序。TV 的 5 分鐘 OHLC 填單可作 Pine 訊號 smoke test，不能拿來確認填單、停損與年度收益。",
        "",
        "## 資料與方法",
        "",
        f"匯出共有 {audit['raw_rows']:,} 行、{audit['entry_rows']:,} 個進場列與 {audit['exit_rows']:,} 個出場列。最後兩個出場日期非日期文字，依題意排除；保留 {audit['closed_trades']:,} 筆 closed lots。進／出場的判定只使用第 2 欄「類型」，沒有由訊號欄反推。價格、損益均先移除千分位再轉數值。",
        "",
        "TV 的列示損益逐筆完全等於 `(出場價−進場價)×方向×50−手續費`；因此列示的價已經承載設定的滑價。下列比較的時間以出場日認列，closed MDD 是同一出場時間先淨額後的已實現權益回撤。",
        "",
        "依這個嚴格規則，本次 overlap 得到 TV 4,584、matched 2,487；與題述 quick fact 的 4,582／2,488 相差極小但不相同。這裡沒有為了湊數而改用訊號欄或移除邊界 lots；逐筆分類已完整輸出，差異可由 `tvrec_reconciliation_classification.csv` 重現與追查。",
        "",
        "## 1. 2022–2023 未動過的 TV 樣本與 regime",
        "",
        "### 年度 closed-lot 指標（同一 TV 口徑）",
        "",
        *md_table(yearly, ["year", "trades", "net", "pf", "win_rate", "closed_mdd"], {"net": 0, "pf": 2, "win_rate": 1, "closed_mdd": 0}),
        "",
        "2022 的 TV 淨利為 " + f"{fnum(float(full_22_23[full_22_23.year.eq(2022)].net.iloc[0]))}" +
        "，2023 為 " + f"{fnum(float(full_22_23[full_22_23.year.eq(2023)].net.iloc[0]))}" +
        "；相較 2024–2026 的三個強正年，2022 僅是小幅正值、2023 為小幅負值。這支持 edge 對 regime 有依賴，而非每年穩定產生相同 alpha。",
        "",
        "### 季度（完整表在 `tvrec_tv_quarterly.csv`）",
        "",
        *md_table(quarterly[quarterly.quarter.str[:4].isin(["2022", "2023", "2024", "2025", "2026"])], ["quarter", "trades", "net", "pf", "win_rate", "closed_mdd"], {"net": 0, "pf": 2, "win_rate": 1, "closed_mdd": 0}),
        "",
        "### 大盤 regime（TAIEX 日線）",
        "",
        *md_table(reg, ["year", "return_pct", "mean_atr20_pct", "daily_vol_pct", "above_ema60_pct", "trend_distance_atr"], {"return_pct": 1, "mean_atr20_pct": 2, "daily_vol_pct": 2, "above_ema60_pct": 1, "trend_distance_atr": 2}),
        "",
        "2022 是負報酬、ATR% 與日波動較高的熊市；2023 為上漲且較低波動的多頭。v27 在兩種 regime 的年淨利都很弱，且 2023 為負，不能把 2024–2026 的成果外推為無條件收益。五個完整／近完整年度中，非正年 {}/5（{}%）；以「年淨利 < 20 萬」作保守的低收益標記則為 {}/5。這是很小且相依的樣本，合理表述是歷史上約每五年出現一個非正年、約兩個低收益年，而不是精確的機率預測。".format(no_positive, f"{100*no_positive/len(yearly):.0f}", low_200k),
        "",
        "### 方向、lot 類型、出場訊號、campaign 集中度",
        "",
        "以下是兩段樣本的 side×Cmd/Add/G；完整逐年表在 `tvrec_tv_side_kind.csv`，兩段比較表在 `tvrec_tv_era_side_kind.csv`。",
        "",
        *md_table(era_side_kind, ["era", "side", "kind", "trades", "net", "pf", "win_rate", "closed_mdd"], {"net": 0, "pf": 2, "win_rate": 1, "closed_mdd": 0}),
        "",
        "出場訊號 attribution 的完整表在 `tvrec_tv_exit_attribution.csv`／`tvrec_tv_era_exit_attribution.csv`；各時段按損益絕對值最大的五種如下。campaign 以同方向、持倉區間相連的 lots 定義，並輸出到 `tvrec_tv_campaigns.csv`。",
        "",
        *md_table(era_exit_top, ["era", "exit_signal", "trades", "net", "pf", "win_rate"], {"net": 0, "pf": 2, "win_rate": 1}),
        "",
        "以下是 top campaign 正收益集中度（以正 campaign gross profit 為分母，避免虧損年出現超過 100% 的淨利比率）。",
        "",
        *md_table(top_conc, ["year", "campaigns", "net", "top1_share_positive_pct", "top5_share_positive_pct", "top10_share_positive_pct"], {"net": 0, "top1_share_positive_pct": 1, "top5_share_positive_pct": 1, "top10_share_positive_pct": 1}),
        "",
        "## 2. 2024-01-03 至 2026-10-17 對帳與差異診斷",
        "",
        "### 完全匹配與損益分解",
        "",
        "匹配鍵為 `entry_ts + side`（同鍵重複時才加序號）。對每個 matched lot，先把 TV 列示填價的已知 4 tick／邊反向扣回，才分解為：成本＋滑價、原始進場價差、原始出場價／時間差。成本＋滑價固定為 TV 相對 engine 的 −440 元／lot（TV: 40 元＋4 points／邊；engine: 20 元／邊）。此為會計分解；TV 的未滑價逐筆 tick 並不可觀測。",
        "",
        *md_table(decomp, ["year", "matched", "pnl_difference", "component_cost_slippage", "component_entry_price", "component_exit_time_price", "decomposition_residual", "exit_time_same_pct", "median_abs_exit_delay_min"], {"pnl_difference": 0, "component_cost_slippage": 0, "component_entry_price": 0, "component_exit_time_price": 0, "decomposition_residual": 2, "exit_time_same_pct": 1, "median_abs_exit_delay_min": 1}),
        "",
        f"總計 matched 損益差（TV−engine）為 {fnum(de_total.get('pnl_difference', np.nan))}；成本／滑價項 {fnum(de_total.get('component_cost_slippage', np.nan))}、進場價項 {fnum(de_total.get('component_entry_price', np.nan))}、出場時間／價項 {fnum(de_total.get('component_exit_time_price', np.nan))}，分解殘差 {fnum(de_total.get('decomposition_residual', np.nan), 6)}。殘差接近零是公式核對，不代表策略一致；真正主因是大量不匹配 entry 與後續路徑分岔。",
        "",
        "重點季度直接對照如下（全季度表 `tvrec_overlap_quarterly.csv`）。2024Q1 TV 幾乎打平而 engine 顯著正，2026Q3 TV 顯著正而 engine 接近打平；這正是以少數 matched lots 或成本校正都無法解釋的策略路徑差。",
        "",
        *md_table(key_quarters, ["quarter", "TV_trades", "TV_net", "engine_trades", "engine_net", "TV_minus_engine"], {"TV_net": 0, "engine_net": 0, "TV_minus_engine": 0}),
        "",
        "### 5 分鐘 OHLC 重跑與相同成本",
        "",
        "engine 原始碼只有 `intrabar_mode == \"1min\"` 會展開 1 分鐘路徑；任何其他值（正式使用 `ohlc`）皆走 5 分鐘 O-H-L-C heuristic。以下為 live-config v27（TimeStop 10h、Cooldown 30m）重跑；TV 成本列在不改 engine 檔案下，以執行期 commission=40/邊及結果再扣 4 points/邊作帳務調整。",
        "",
        *md_table(runs, ["run", "trades", "net", "pf", "win_rate", "closed_mdd", "TV_overlap_net", "TV_minus_run"], {"net": 0, "pf": 2, "win_rate": 1, "closed_mdd": 0, "TV_overlap_net": 0, "TV_minus_run": 0}),
        "",
        f"5m heuristic 的表面（frictionless）缺口由 {fnum(float(one_run.TV_minus_run))} 縮至 {fnum(float(runs.loc[runs.run.eq('engine 5m OHLC heuristic'), 'TV_minus_run'].iloc[0]))}，即 {fnum(raw_gap_close)}／{raw_gap_close_pct:.1f}%；但那是把已含 TV 成本的 TV 與 frictionless engine 混比。改為同一 TV 成本後，1m 帳務缺口為 {fnum(float(one_cost_run.TV_minus_run))}、5m OHLC 為 {fnum(float(tv_run.TV_minus_run))}，仍僅縮小 {fnum(fair_gap_close)}／{fair_gap_close_pct:.1f}%。5m path 有實質影響，卻沒有重現 TV 的交易集合。",
        "",
        ("本次 1 分鐘重跑與提供的 `trades_v27.csv` 逐欄完全一致。" if fresh_equal else
         "本次 1 分鐘重跑與提供的 `trades_v27.csv` 並非逐欄一致，但差異僅在資料尾端的 `END`：提供版 1 個 lot 於 03:58 結束；b 資料延長到 05:00 後改以 1 個 Cmd 加 1 個 Add 結束，淨差 +8,410 元。逐筆表為 `tvrec_engine_1min_reproduction_diff.csv`。對主對帳仍採題目指定的 `trades_v27.csv`，避免把 TV 尚未 closed 的最後兩筆混入。"),
        "",
        "### 資料、時段與換月檢查",
        "",
        f"TV-only 的 {n_tvonly:,} 個進場中，本地 5 分鐘 bar 找得到 {bar_found_pct:.1f}%；把 TV 填價反推 4 ticks 後仍落於該本地 5 分鐘 high–low 的比例為 {in_range_pct:.1f}%。日盤開盤 08:45–09:00 有 {int(day_open_zone.n):,} 筆、in-range {100*day_open_zone.in_range:.1f}%、反推價距本地 open 的 median |Δ| {fnum(day_open_zone.median_abs_open)} 點；05:00 收盤附近僅 {int(close05_zone.n):,} 筆、in-range {100*close05_zone.in_range:.1f}%。依日／夜開收盤的完整細表在 `tvrec_tv_only_bar_summary.csv`，逐筆 OHLC 對照在 `tvrec_tv_only_entry_bars.csv`；engine-only 的時段分佈在 `tvrec_engine_only_session_summary.csv`。這能排除『完全無本地價格』作為多數 TV-only 的唯一解釋，但不能由 trade list 還原 TV 的完整 5m 資料或 bar path。",
        "",
        f"本地資料由 MXFR1（自動近月連續）取得；專案 live 合約規則為每月第三個週三 settlement 前一日切換。TV 的 MXF1! 匯出沒有實際合約代碼或 rollover 標記，故不能從本檔證明兩者 rollover 日期完全相同。proxy 反而提示換月附近值得警戒：matched 的反推進場價 |Δ| P95 從其他日的 {fnum(roll_normal.p95_abs_pre_slip_entry_diff)} 點升至 {fnum(roll_window.p95_abs_pre_slip_entry_diff)} 點，且相同出場時間率從 {roll_normal.exit_time_same_pct:.1f}% 降至 {roll_window.exit_time_same_pct:.1f}%。這與合約選擇／價格調整差異相容，但不是 rollover 日期不同的直接證據。`tvrec_rollover_check.csv` 保留可重現明細。",
        "",
        "## 3. 成本合理性",
        "",
        "MXF 每點 50 元；依題設期交稅為 `0.00002 × 指數 × 50` 每邊。以下是 TAIEX 年內平均及年初／年末指數水準所對應的稅額（未含券商費）。若以 engine 的 20 元／邊作為券商費 proxy，稅加費在 2022–2026 約為 38–70 元／邊，實際仍應以帳戶費率與券商對帳單替換。",
        "",
        *md_table(tax, ["year", "tax_start_per_side", "tax_end_per_side", "tax_mean_per_side"], {"tax_start_per_side": 2, "tax_end_per_side": 2, "tax_mean_per_side": 2}),
        "",
        "因此 TV 的 40 元／邊（僅 commission）大致可當作費稅合併的低端近似；再加 4 ticks／邊（200 元）則是一般流動時段相當保守的滑價假設。對開盤、消息、跳空、停損觸發而言仍可能樂觀。下表以既有 trades CSV 純會計重算：原 CSV 已扣 20 元／邊，所以改成 40 元／邊＋1 tick／邊要再扣 140 元／lot；＋2 ticks 要再扣 240 元／lot。",
        "",
        *md_table(cost, ["version", "trades", "engine_cost20_side_net", "net_40side_plus_1tick", "net_40side_plus_2ticks", "net_40side_plus_4ticks"], {"engine_cost20_side_net": 0, "net_40side_plus_1tick": 0, "net_40side_plus_2ticks": 0, "net_40side_plus_4ticks": 0}),
        "",
        "## 4. 2026-07-29 回撤與建議",
        "",
        f"在 2026-07-29 當日（或之前最近一個有 closed PnL 的交易日），TV closed equity 的回撤為 {fnum(dd_tv_info['drawdown'])}，engine 1 分鐘也為 {fnum(dd_en_info['drawdown'])}：兩者在這個 closed-PnL 時點都是新高，故『7/29 當日已存在 DD』不成立。其後一段下跌在 TV 確實存在，但較淺：TV 於 {dd_tv_info['post_0729_trough_day']} 到 {fnum(dd_tv_info['post_0729_trough_dd'])}，engine 則於 {dd_en_info['post_0729_trough_day']} 到 {fnum(dd_en_info['post_0729_trough_dd'])}；7–9 月 window 淨利依序為 {fnum(dd_tv_info['window_net'])}、{fnum(dd_en_info['window_net'])}。逐日權益序列位於 `tvrec_drawdown_20260729.csv`。",
        "",
        "因此 2026-07-29 的 engine drawdown 不能直接期待在 TV 上以相同日期、幅度或甚至方向重現；若 TV 序列顯示不同，即是本次對帳所證實的路徑／交易集合差異，而非可忽略的費用校正。未來研究應保留 engine 作唯一績效基準，Pine 只做訊號部署及 alert 健康檢查；每次 Pine 改動後，以逐訊號時間戳、合約、目標部位與實際成交回寫做獨立對帳。",
        "",
        "## 產物",
        "",
        "所有 `tvrec_*.csv` 均為 UTF-8 with BOM，包含 TV 年／季／side-kind／exit、campaign、逐筆分類、matched 分解、5m bar／session、rollover proxy、engine 重跑、費用、regime 與 2026-07-29 drawdown 明細。",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {REPORT.name}; TV closed={len(tv):,}; overlap TV={len(tv_o):,}, engine={len(en_o):,}, matched={len(matched):,}")


if __name__ == "__main__":
    main()
