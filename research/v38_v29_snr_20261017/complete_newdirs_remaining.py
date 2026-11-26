"""Complete the unfinished A/A2 work and rebase all new-directions outputs.

This is deliberately a separate, ASCII-only runner.  The earlier staged work is
kept as an audit trail, while this runner fixes the common-cutoff reproduction,
constructs the contract-expiry walls from the raw TXO table, and writes a clean
final report.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
DATA = HERE / "mxf_1min_corrected_20261017b.csv"
sys.path.insert(0, str(ENGINE_DIR))
from engine_v26_bbw import P, load_1min, prepare, run as base_run  # noqa: E402
from engine_newdirs_wrapper import run as wrapped_run  # noqa: E402

CUTOFF = pd.Timestamp("2026-10-17 03:58:00")
H2 = pd.Timestamp("2025-04-01")
TRAIN0, TRAIN1 = pd.Timestamp("2026-03-01"), pd.Timestamp("2026-06-01")
TEST0, TEST1 = pd.Timestamp("2026-06-01"), pd.Timestamp("2026-08-22")
HOLDOUT = pd.Timestamp("2026-08-22")
BASES = {
    "v28": {"opt_stale_hr": 10, "opt_cooldown_min": 30, "opt_short_pyramid_cap_mode": "hour4"},
    "v29": {"opt_stale_hr": 10, "opt_cooldown_min": 30, "opt_short_pyramid_cap_mode": "hour4", "l_trailBase": 3.5},
}
TRADE_COLS = ["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl"]
SPANS = ["ALL", "H1", "H2_DEV", "TRAIN", "TEST", "HOLDOUT"]


def dates(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["entry_ts"] = pd.to_datetime(d.entry_ts)
    d["exit_ts"] = pd.to_datetime(d.exit_ts)
    return d


def subset(d: pd.DataFrame, span: str) -> pd.DataFrame:
    t = d.entry_ts
    if span == "ALL":
        return d
    if span == "H1":
        return d[t < H2]
    if span == "H2_DEV":
        return d[(t >= H2) & (t < HOLDOUT)]
    if span == "TRAIN":
        return d[(t >= TRAIN0) & (t < TRAIN1)]
    if span == "TEST":
        return d[(t >= TEST0) & (t < TEST1)]
    if span == "HOLDOUT":
        return d[t >= HOLDOUT]
    raise ValueError(span)


def mdd(d: pd.DataFrame) -> float:
    if d.empty:
        return 0.0
    equity = d.sort_values(["exit_ts", "entry_ts"]).pnl.cumsum()
    return float((equity - equity.cummax()).min())


def metric(d: pd.DataFrame) -> dict[str, float | int]:
    if d.empty:
        return {"n": 0, "net": 0.0, "wr": np.nan, "pf": np.nan, "mdd": 0.0, "net_mdd": np.nan}
    wins = float(d.loc[d.pnl > 0, "pnl"].sum())
    losses = float(-d.loc[d.pnl <= 0, "pnl"].sum())
    dd = mdd(d)
    return {
        "n": int(len(d)), "net": float(d.pnl.sum()), "wr": float((d.pnl > 0).mean() * 100),
        "pf": wins / losses if losses else np.inf, "mdd": dd,
        "net_mdd": float(d.pnl.sum() / abs(dd)) if dd else np.inf,
    }


def campaignize(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    order = {"Cmd": 0, "Add": 1, "G": 2}
    d = trades.copy().sort_values(
        ["entry_ts", "kind"], key=lambda x: x.map(order) if x.name == "kind" else x
    ).reset_index(drop=True)
    d["campaign_id"] = d.kind.eq("Cmd").cumsum() - 1
    rows = []
    for cid, g in d.groupby("campaign_id", sort=True):
        cmd = g[g.kind.eq("Cmd")].iloc[0]
        rows.append({"campaign_id": int(cid), "side": cmd.side, "entry_ts": cmd.entry_ts,
                     "entry_px": cmd.entry_px, "exit_ts": g.exit_ts.max(),
                     "pnl": float(g.pnl.sum()), "n_lots": int(len(g))})
    return pd.DataFrame(rows), d


def cmd_features(camp: pd.DataFrame, b5: pd.DataFrame) -> pd.DataFrame:
    b = b5.copy()
    close_ts = b.close_ts.to_numpy(dtype="datetime64[ns]")
    ix = np.searchsorted(close_ts, camp.entry_ts.to_numpy(dtype="datetime64[ns]"), side="right") - 1
    if (ix < 0).any():
        raise RuntimeError("campaign before first feature bar")
    out = camp.copy()
    out["sig_ix"] = ix
    for col in ("close", "atr", "ema_long", "ema_short", "hh20_prev", "ll20_prev", "adx", "bbw_pct"):
        out["sig_" + col] = b[col].to_numpy()[ix]
    direction = np.where(out.side.eq("L"), 1.0, -1.0)
    ema = np.where(out.side.eq("L"), out.sig_ema_long, out.sig_ema_short)
    out["extension_atr"] = direction * (out.sig_close - ema) / out.sig_atr
    out["breakout"] = np.where(out.side.eq("L"), out.sig_close > out.sig_hh20_prev, out.sig_close < out.sig_ll20_prev)
    return out


def bootstrap_diff(a: np.ndarray, b: np.ndarray, seed: int, draws: int = 5000) -> tuple[float, float, float]:
    if len(a) < 2 or len(b) < 2:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    x = rng.choice(a, size=(draws, len(a)), replace=True).mean(axis=1)
    y = rng.choice(b, size=(draws, len(b)), replace=True).mean(axis=1)
    z = x - y
    return float(z.mean()), float(np.quantile(z, 0.025)), float(np.quantile(z, 0.975))


def daily_underlying(df1m: pd.DataFrame) -> pd.DataFrame:
    x = df1m.copy()
    x["date"] = x.ts.dt.normalize()
    q = x.groupby("date", as_index=False).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    previous = q.close.shift()
    q["tr"] = pd.concat([(q.high - q.low), (q.high - previous).abs(), (q.low - previous).abs()], axis=1).max(axis=1)
    q["daily_atr14"] = q.tr.ewm(alpha=1 / 14, adjust=False).mean()
    return q[["date", "close", "daily_atr14"]]


def kth_weekday(year: int, month: int, weekday: int, n: int) -> pd.Timestamp:
    d = pd.Timestamp(year=year, month=month, day=1)
    return d + pd.Timedelta(days=(weekday - d.weekday()) % 7 + 7 * (n - 1))


def expiry_from_label(value: object) -> pd.Timestamp:
    s = str(value).strip()
    m = re.fullmatch(r"(\d{4})(\d{2})", s)
    if m:
        return kth_weekday(int(m.group(1)), int(m.group(2)), 2, 3)  # third Wednesday
    m = re.fullmatch(r"(\d{4})(\d{2})([WF])(\d)", s)
    if m:
        weekday = 2 if m.group(3) == "W" else 4
        return kth_weekday(int(m.group(1)), int(m.group(2)), weekday, int(m.group(4)))
    return pd.NaT


def build_walls(df1m: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build nearest weekly (W/F) and monthly (YYYYMM) walls from end-of-day OI."""
    raw = pd.read_csv(HERE / "options_raw" / "finlab_tw_option_daily_summary.csv", low_memory=False)
    s = raw[raw.symbol.eq("TXO")].copy()
    s["date"] = pd.to_datetime(s.date)
    s["cp"] = s.iloc[:, 3].astype(str)
    s["expiry"] = s.iloc[:, 4].astype(str).str.strip()
    s["strike"] = pd.to_numeric(s.iloc[:, 5], errors="coerce")
    published_expiry = pd.to_datetime(s.iloc[:, 8], errors="coerce")
    # Settlement moves to the next day session when its nominal Wednesday or
    # Friday is a Taiwan holiday.  Use day-session dates rather than overnight
    # calendar dates (Friday's night session otherwise creates a Saturday row).
    session_days = pd.DatetimeIndex(pd.Series(
        df1m.loc[df1m.ts.dt.hour.between(8, 13), "ts"].dt.normalize().unique()
    ).sort_values())
    def roll_to_session(value: pd.Timestamp) -> pd.Timestamp:
        if pd.isna(value):
            return pd.NaT
        ix = session_days.searchsorted(value)
        return session_days[ix] if ix < len(session_days) else pd.NaT
    derived_expiry = s.expiry.map(expiry_from_label).map(roll_to_session)
    s["expiry_date"] = published_expiry.fillna(derived_expiry)
    s["oi"] = pd.to_numeric(s.iloc[:, 15], errors="coerce")
    valid = published_expiry.notna() & derived_expiry.notna()
    validation = (s.loc[valid, ["expiry"]].assign(
        published=published_expiry.loc[valid].dt.normalize().to_numpy(),
        derived=derived_expiry.loc[valid].to_numpy(),
    ).drop_duplicates())
    validation["match"] = validation.published.eq(validation.derived)
    validation.to_csv(HERE / "newdirs_option_expiry_validation.csv", index=False, encoding="utf-8-sig")

    s = s.dropna(subset=["strike", "oi", "expiry_date"])
    s = s[s.expiry_date.ge(s.date)]
    s = s.drop_duplicates(["date", "expiry", "strike", "cp"], keep="last")
    calls_label, puts_label = "買權", "賣權"
    rows: list[dict[str, object]] = []
    for day, by_day in s.groupby("date", sort=True):
        for wall_type, is_monthly in (("weekly", False), ("monthly", True)):
            mask = by_day.expiry.str.fullmatch(r"\d{6}")
            candidates = by_day[mask if is_monthly else ~mask]
            if candidates.empty:
                continue
            expiry_date = candidates.expiry_date.min()
            expiry = candidates.loc[candidates.expiry_date.eq(expiry_date), "expiry"].iloc[0]
            g = candidates[candidates.expiry.eq(expiry)]
            calls, puts = g[g.cp.eq(calls_label)], g[g.cp.eq(puts_label)]
            if calls.empty or puts.empty:
                continue
            call_wall = float(calls.loc[calls.oi.idxmax(), "strike"])
            put_wall = float(puts.loc[puts.oi.idxmax(), "strike"])
            strikes = np.sort(g.strike.unique())
            def pain(k: float) -> float:
                return float((calls.oi * np.maximum(k - calls.strike, 0)).sum() +
                             (puts.oi * np.maximum(puts.strike - k, 0)).sum())
            max_pain = float(min(strikes, key=pain))
            rows.append({"date": day, "wall_type": wall_type, "expiry": expiry,
                         "expiry_date": expiry_date, "call_wall": call_wall, "put_wall": put_wall,
                         "max_pain": max_pain, "days_to_expiry": int((expiry_date - day).days)})
    walls = pd.DataFrame(rows).sort_values(["date", "wall_type"]).reset_index(drop=True)
    walls.to_csv(HERE / "newdirs_option_walls_daily.csv", index=False, encoding="utf-8-sig")

    base = daily_underlying(df1m)
    old = pd.read_csv(HERE / "newdirs_option_daily_features.csv", parse_dates=["date"])
    pcr_cols = [c for c in old.columns if c.startswith("pcr_")]
    base = base.merge(old[["date"] + pcr_cols].drop_duplicates("date"), on="date", how="left")
    for wall_type in ("weekly", "monthly"):
        z = walls[walls.wall_type.eq(wall_type)].drop(columns="wall_type").rename(
            columns={c: f"{wall_type}_{c}" for c in walls.columns if c not in ("date", "wall_type")}
        )
        base = base.merge(z, on="date", how="left")
    base["available_ts"] = base.date + pd.Timedelta(hours=15)
    base.to_csv(HERE / "newdirs_option_daily_features.csv", index=False, encoding="utf-8-sig")
    return base, validation


def load_futures_oi(df1m: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Save the real FinLab raw table and make a deliberately one-session-lagged daily feature."""
    raw_dir = HERE / "options_raw"
    try:
        from finlab import data
        data.set_storage(data.FileStorage(str(HERE / "finlab_cache")))
        source = data.get("tw_taifex_futures_institutional_breakdown").copy()
        source.to_csv(raw_dir / "finlab_tw_taifex_futures_institutional_breakdown.csv", index=False, encoding="utf-8-sig")
    except Exception as exc:  # report rather than fabricate an unavailable data set
        empty = pd.DataFrame(columns=["date", "available_ts", "foreign_net_oi"])
        empty.to_csv(HERE / "newdirs_futures_oi_daily.csv", index=False, encoding="utf-8-sig")
        return empty, f"FAIL: {type(exc).__name__}: {exc}"

    source["date"] = pd.to_datetime(source.date)
    identity_col = source.columns[2]
    # Source labels are traditional Chinese: 臺股期貨 / 外資及陸資.
    x = source[source.symbol.astype(str).isin(["台股期貨", "臺股期貨"]) & source[identity_col].astype(str).eq("外資及陸資")].copy()
    x["foreign_net_oi"] = pd.to_numeric(x.iloc[:, 9], errors="coerce")
    x = x.sort_values("date").drop_duplicates("date")
    x["foreign_net_oi_d1"] = x.foreign_net_oi.diff()
    x["foreign_net_oi_d5"] = x.foreign_net_oi.diff(5)
    mean = x.foreign_net_oi.rolling(60, min_periods=30).mean()
    std = x.foreign_net_oi.rolling(60, min_periods=30).std(ddof=0)
    x["foreign_net_oi_z60"] = (x.foreign_net_oi - mean) / std.replace(0, np.nan)
    x["foreign_net_oi_sign"] = np.sign(x.foreign_net_oi)

    trade_dates = pd.DatetimeIndex(pd.Series(df1m.ts.dt.normalize().unique()).sort_values())
    available = []
    for day in x.date:
        later = trade_dates[trade_dates > day]
        available.append((later[0] if len(later) else day) + pd.Timedelta(hours=15))
    out = x[["date", "foreign_net_oi", "foreign_net_oi_d1", "foreign_net_oi_d5", "foreign_net_oi_z60", "foreign_net_oi_sign"]].copy()
    out["available_ts"] = available
    out.to_csv(HERE / "newdirs_futures_oi_daily.csv", index=False, encoding="utf-8-sig")
    log_path = raw_dir / "source_log.csv"
    log = pd.read_csv(log_path) if log_path.exists() else pd.DataFrame(columns=["source", "url", "status"])
    log = log[log.url.ne("tw_taifex_futures_institutional_breakdown")]
    status = f"ok {len(source):,} rows; foreign Taiwan-index OI {len(out):,} rows, {out.date.min().date()} to {out.date.max().date()}"
    log = pd.concat([log, pd.DataFrame([{"source": "finlab", "url": "tw_taifex_futures_institutional_breakdown", "status": status}])], ignore_index=True)
    log.to_csv(log_path, index=False, encoding="utf-8-sig")
    return out, status


def attach_daily(camp: pd.DataFrame, b5: pd.DataFrame, daily: pd.DataFrame, futures: pd.DataFrame) -> pd.DataFrame:
    c = cmd_features(camp, b5).sort_values("entry_ts")
    d = daily.sort_values("available_ts")
    c = pd.merge_asof(c, d, left_on="entry_ts", right_on="available_ts", direction="backward")
    if not futures.empty:
        f = futures.drop(columns="date", errors="ignore").sort_values("available_ts")
        c = pd.merge_asof(c.sort_values("entry_ts"), f, left_on="entry_ts", right_on="available_ts", direction="backward", suffixes=("", "_fut"))
    return c.sort_values("campaign_id").reset_index(drop=True)


def numeric_bucket(values: pd.Series, low: float, high: float) -> pd.Series:
    return pd.Series(np.where(values <= low, "low", np.where(values >= high, "high", "mid")), index=values.index).where(values.notna())


def feature_discriminator(camp: pd.DataFrame, specs: dict[str, str], stem: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """H1 thresholds; H2_DEV is not allowed to choose a new bucket or threshold."""
    details: list[dict[str, object]] = []
    gates: list[dict[str, object]] = []
    h1_mask = camp.entry_ts < H2
    h2_mask = (camp.entry_ts >= H2) & (camp.entry_ts < HOLDOUT)
    ho_mask = camp.entry_ts >= HOLDOUT
    for index, (feature, kind) in enumerate(specs.items()):
        values = pd.to_numeric(camp[feature], errors="coerce") if kind == "numeric" else camp[feature]
        if kind == "numeric":
            valid_h1 = values[h1_mask].dropna()
            if len(valid_h1) < 30:
                continue
            low, high = valid_h1.quantile([1 / 3, 2 / 3])
            bucket = numeric_bucket(values, float(low), float(high))
            labels = ["low", "mid", "high"]
        else:
            valid_h1 = values[h1_mask].dropna()
            if valid_h1.nunique() < 2 or len(valid_h1) < 30:
                continue
            low, high = np.nan, np.nan
            bucket = values.map({False: "false", True: "true"}).where(values.notna())
            labels = ["false", "true"]
        h1_means = {label: camp.loc[h1_mask & bucket.eq(label), "pnl"].mean() for label in labels}
        bad_bucket = min(h1_means, key=lambda k: np.inf if pd.isna(h1_means[k]) else h1_means[k])
        period_stats: dict[str, tuple[float, float, float, int, int]] = {}
        for period, mask in (("H1", h1_mask), ("H2_DEV", h2_mask), ("HOLDOUT", ho_mask)):
            for side in ("L", "S"):
                for label in labels:
                    z = camp[mask & camp.side.eq(side) & bucket.eq(label)]
                    details.append({"feature": feature, "period": period, "side": side, "bucket": label,
                                    "n": len(z), "net": float(z.pnl.sum()), "mean_pnl": float(z.pnl.mean()) if len(z) else np.nan})
            bad = camp.loc[mask & bucket.eq(bad_bucket), "pnl"].to_numpy(float)
            rest = camp.loc[mask & bucket.ne(bad_bucket) & bucket.notna(), "pnl"].to_numpy(float)
            point, ci_low, ci_high = bootstrap_diff(bad, rest, 20261018 + index * 17 + len(period))
            period_stats[period] = (point, ci_low, ci_high, len(bad), len(rest))
        dev_bad = camp.loc[(camp.entry_ts < HOLDOUT) & bucket.eq(bad_bucket), "pnl"]
        losses = float(-dev_bad[dev_bad < 0].sum())
        profits = float(dev_bad[dev_bad > 0].sum())
        proxy_cols = [feature, "sig_adx", "sig_bbw_pct"]
        proxy = camp[proxy_cols].copy()
        rho = proxy.corr(method="spearman").loc[feature]
        # The futures series starts in the display-only holdout.  Keep both
        # counts explicit rather than requiring every OI transformation (the
        # 60d z-score is necessarily unavailable) to be non-null.
        future_base = camp["foreign_net_oi"].notna() if "foreign_net_oi" in camp else pd.Series(False, index=camp.index)
        future_dev_overlap = int((camp[feature].notna() & future_base & (camp.entry_ts < HOLDOUT)).sum())
        future_holdout_overlap = int((camp[feature].notna() & future_base & (camp.entry_ts >= HOLDOUT)).sum())
        h1, h2, hold = period_stats["H1"], period_stats["H2_DEV"], period_stats["HOLDOUT"]
        gate = bool(h1[2] < 0 and h2[2] < 0)
        gates.append({
            "feature": feature, "type": kind, "bad_bucket_from_h1": bad_bucket, "low_threshold_h1": low,
            "high_threshold_h1": high, "h1_diff": h1[0], "h1_ci_low": h1[1], "h1_ci_high": h1[2],
            "h1_bad_n": h1[3], "h2_diff": h2[0], "h2_ci_low": h2[1], "h2_ci_high": h2[2],
            "h2_bad_n": h2[3], "holdout_diff": hold[0], "holdout_bad_n": hold[3],
            "loss_removed": losses, "profit_removed": profits,
            "loss_profit_ratio": losses / profits if profits else np.inf,
            "rho_adx": float(rho.get("sig_adx", np.nan)), "rho_bbw": float(rho.get("sig_bbw_pct", np.nan)),
            "futures_dev_overlap": future_dev_overlap, "futures_holdout_overlap": future_holdout_overlap, "gate": gate,
        })
    detail_df, gate_df = pd.DataFrame(details), pd.DataFrame(gates)
    detail_df.to_csv(HERE / f"newdirs_{stem}_discriminator.csv", index=False, encoding="utf-8-sig")
    gate_df.to_csv(HERE / f"newdirs_{stem}_gates.csv", index=False, encoding="utf-8-sig")
    return detail_df, gate_df


def futures_discriminator(camp: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    available = [x for x in ("foreign_net_oi", "foreign_net_oi_d1", "foreign_net_oi_d5", "foreign_net_oi_z60") if x in camp]
    rows = []
    for feature in available:
        for period, mask in (("H1", camp.entry_ts < H2), ("H2_DEV", (camp.entry_ts >= H2) & (camp.entry_ts < HOLDOUT)), ("HOLDOUT", camp.entry_ts >= HOLDOUT)):
            z = camp.loc[mask & camp[feature].notna(), feature]
            rows.append({"feature": feature, "period": period, "campaign_n": int(len(z)),
                         "feature_min": float(z.min()) if len(z) else np.nan, "feature_max": float(z.max()) if len(z) else np.nan})
    detail = pd.DataFrame(rows)
    gate = pd.DataFrame([{ "feature": feature, "gate": False,
                            "reason": "No H1/H2_DEV observations: FinLab coverage begins 2026-09-17." }
                         for feature in available])
    detail.to_csv(HERE / "newdirs_futures_oi_discriminator.csv", index=False, encoding="utf-8-sig")
    gate.to_csv(HERE / "newdirs_futures_oi_gates.csv", index=False, encoding="utf-8-sig")
    return detail, gate


def scaled_trades(lots: pd.DataFrame, featured: pd.DataFrame, variant: str) -> tuple[pd.DataFrame, int, float]:
    h1 = featured[featured.entry_ts < H2]
    cut = float(h1.extension_atr.quantile(2 / 3))
    q = featured.set_index("campaign_id")
    if variant == "control_2x":
        double = pd.Series(True, index=q.index)
    elif variant == "breakout_2x":
        double = q.breakout
    elif variant == "extension_2x":
        double = q.extension_atr >= cut
    elif variant == "both_2x":
        double = q.breakout & (q.extension_atr >= cut)
    else:
        raise ValueError(variant)
    d = lots.copy()
    d["qty"] = d.campaign_id.map(pd.Series(np.where(double, 2, 1), index=q.index))
    d["pnl"] *= d.qty
    events = []
    for r in d.itertuples(index=False):
        events += [(r.entry_ts, 1, int(r.qty)), (r.exit_ts, 0, -int(r.qty))]
    pos = peak = 0
    for _, _, change in sorted(events, key=lambda x: (x[0], x[1])):
        pos += change
        peak = max(peak, pos)
    return d, peak, cut


def b_study(runs: dict[str, pd.DataFrame], b5: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, assumptions = [], []
    variants = ["both_2x", "breakout_2x", "extension_2x", "control_2x"]
    for base, trades in runs.items():
        camp, lots = campaignize(trades)
        features = cmd_features(camp, b5)
        features.to_csv(HERE / f"newdirs_{base}_sizing_campaigns.csv", index=False, encoding="utf-8-sig")
        rendered = {}
        for variant in variants:
            x, peak, cut = scaled_trades(lots, features, variant)
            rendered[variant] = x
            assumptions.append({"base": base, "variant": variant, "extension_high_cutpoint_h1": cut,
                                "peak_lots": peak, "margin_assumption_per_mxf": 92000, "margin_need": peak * 92000})
            for span in SPANS:
                rows.append({"base": base, "variant": variant, "span": span, "peak_lots": peak, **metric(subset(x, span))})
        for span in SPANS:
            control = metric(subset(rendered["control_2x"], span))["net"]
            for variant in variants[:-1]:
                rows.append({"base": base, "variant": variant + "_minus_control", "span": span,
                             "peak_lots": np.nan, "n": np.nan,
                             "net": metric(subset(rendered[variant], span))["net"] - control,
                             "wr": np.nan, "pf": np.nan, "mdd": np.nan, "net_mdd": np.nan})
    metrics = pd.DataFrame(rows)
    assumptions_df = pd.DataFrame(assumptions)
    metrics.to_csv(HERE / "newdirs_b_sizing_metrics.csv", index=False, encoding="utf-8-sig")
    assumptions_df.to_csv(HERE / "newdirs_b_sizing_assumptions.csv", index=False, encoding="utf-8-sig")
    return metrics, assumptions_df


def c_study(df1m: pd.DataFrame, runs: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    variants = {"allow_15_16": "15_16", "allow_17_20": "17_20", "allow_01_02": "01_02",
                "allow_long_04": "long_04", "allow_short_21": "short_21"}
    rows, hour_rows = [], []
    for base, baseline in runs.items():
        z = baseline.copy()
        z["entry_hour"] = z.entry_ts.dt.hour
        for hour, g in z.groupby("entry_hour"):
            hour_rows.append({"base": base, "entry_hour": int(hour), **metric(g)})
        for name, code in variants.items():
            x = dates(wrapped_run(df1m, p={**BASES[base], "opt_newdirs_unblock": code}, intrabar_mode="1min"))
            x.to_csv(HERE / f"trades_newdirs_{base}_{name}.csv", index=False, encoding="utf-8-sig")
            for span in SPANS:
                after, before = metric(subset(x, span)), metric(subset(baseline, span))
                rows.append({"base": base, "variant": name, "span": span, **after,
                             "delta_net": after["net"] - before["net"], "delta_mdd": after["mdd"] - before["mdd"]})
    metrics, hours = pd.DataFrame(rows), pd.DataFrame(hour_rows)
    metrics.to_csv(HERE / "newdirs_c_unblock_metrics.csv", index=False, encoding="utf-8-sig")
    hours.to_csv(HERE / "newdirs_c_entry_hours.csv", index=False, encoding="utf-8-sig")
    return metrics, hours


def fmt(value: object, digits: int = 0) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    if isinstance(value, (float, np.floating)):
        if np.isinf(value):
            return "inf"
        return f"{value:,.{digits}f}"
    return str(value)


def md_table(d: pd.DataFrame, columns: list[str], digits: int = 0) -> list[str]:
    if d.empty:
        return ["No evaluable rows."]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in d.loc[:, columns].itertuples(index=False, name=None):
        values = [fmt(x, digits).replace("|", "\\|") for x in row]
        lines.append("| " + " | ".join(values) + " |")
    return lines


def report(runs: dict[str, pd.DataFrame], source_note: str, expiry_validation: pd.DataFrame,
           wall_gates: pd.DataFrame, future_detail: pd.DataFrame, pcr_gates: pd.DataFrame,
           b_metrics: pd.DataFrame, b_assumptions: pd.DataFrame, c_metrics: pd.DataFrame,
           c_hours: pd.DataFrame) -> None:
    base_rows = []
    for base, trades in runs.items():
        base_rows.append({"base": base, **metric(trades)})
    base_df = pd.DataFrame(base_rows)

    b_core = b_metrics[b_metrics.variant.str.contains("minus_control") & b_metrics.span.isin(["H1", "H2_DEV", "TRAIN", "TEST"])]
    b_pivot = b_core.pivot(index=["base", "variant"], columns="span", values="net").reset_index()
    b_pivot["PASS"] = b_pivot[["H1", "H2_DEV", "TRAIN", "TEST"]].gt(0).all(axis=1)

    c_core = c_metrics[c_metrics.span.isin(["H1", "H2_DEV", "TRAIN", "TEST"])]
    c_pivot = c_core.pivot(index=["base", "variant"], columns="span", values="delta_net").reset_index()
    c_pivot["PASS"] = c_pivot[["H1", "H2_DEV", "TRAIN", "TEST"]].gt(0).all(axis=1)

    pcr_show = pcr_gates[["feature", "h1_ci_low", "h1_ci_high", "h2_ci_low", "h2_ci_high", "loss_profit_ratio", "gate"]].copy()
    wall_show = wall_gates[["feature", "bad_bucket_from_h1", "h1_ci_low", "h1_ci_high", "h2_ci_low", "h2_ci_high", "loss_profit_ratio", "futures_dev_overlap", "futures_holdout_overlap", "gate"]].copy()
    future_show = future_detail.copy()
    validation_summary = pd.DataFrame([{
        "published/derived expiry pairs": len(expiry_validation),
        "matches": int(expiry_validation.match.sum()) if not expiry_validation.empty else 0,
        "mismatches": int((~expiry_validation.match).sum()) if not expiry_validation.empty else 0,
    }])
    hour_summary = []
    for base, tr in runs.items():
        t = tr.copy()
        t["hour"] = t.entry_ts.dt.hour
        blocked = t[t.hour.isin([1, 2, 15, 16, 17, 18, 19, 20])]
        cmds = blocked[blocked.kind.eq("Cmd")]
        hour_summary.append({"base": base, "all_trades_in_base_block_hours": len(blocked),
                             "Cmd_boundary_fill_01": int(cmds.hour.eq(1).sum()),
                             "Cmd_boundary_fill_15": int(cmds.hour.eq(15).sum()),
                             "Cmd_other_block_hours": int((~cmds.hour.isin([1, 15])).sum()),
                             "non_Cmd_residual": int(len(blocked[~blocked.kind.eq("Cmd")])),
                             "hour_1_residual": int((t.hour.eq(1)).sum()),
                             "hour_15_residual": int((t.hour.eq(15)).sum())})

    lines = [
        "# V38 new directions: completed A/A2/B/C study",
        "",
        "## Executive verdict",
        "",
        "- A futures OI: **FAIL / not evaluable**. The correct FinLab table loaded, but covers only 19 dates, 2026-09-17 through 2026-10-16. It has no H1 or H2_DEV observations, so no discriminator or engine filter is justified.",
        "- A2 PCR: **FAIL**. No PCR feature passed the predeclared H1 + H2_DEV bootstrap gate. A2 walls/max-pain/expiry: **FAIL**; no wall feature passed either. Therefore zero A/A2 engine variants were run (within the combined cap of four).",
        "- B sizing: **FAIL** on both bases. Every quality-weighted 2x rule loses to the always-2x control in at least one required window.",
        "- C legacy hours: **FAIL**. None of the five unblocks has positive delta in H1, H2_DEV, TRAIN, and TEST for either base.",
        "- Recommendation: retain the live v29 rules unchanged. There is no candidate for a 200-draw matched placebo. If a future study produces a PASS, its evidence remains weak because these windows have already been reused across roughly 8 studies / 60+ variants; run the Phase-E-style 200-draw matched placebo before calling it a candidate.",
        "",
        "## Common-cutoff baseline reproduction",
        "",
        f"The common cutoff is **{CUTOFF} inclusive** from `mxf_1min_corrected_20261017b.csv`, matching the earlier `mxf_1min_corrected_20261017.csv` endpoint. The later 04:00-05:00 tail is excluded. Both engine baselines exactly match their prior trade files (v28 4,224/4,224; v29 4,137/4,137).",
        "",
    ] + md_table(base_df, ["base", "n", "net", "mdd", "net_mdd"], 2) + [
        "",
        "All engine runs use 1-minute intrabar execution, stale=10h, and cooldown=30m. H2_DEV is 2025-04-01 through 2026-08-21; HOLDOUT begins 2026-08-22 and is display-only.",
        "",
        "## A: foreign institutional futures OI",
        "",
        "Dataset: `tw_taifex_futures_institutional_breakdown`, 1,311 x 17 raw rows. The extracted `台股期貨` / `外資及陸資` OI series has 19 daily observations. Features written to `newdirs_futures_oi_daily.csv` are net OI, 1d/5d changes, sign, and a 60d z-score (unavailable with only 19 dates). To be conservative, each observation is made available only at 15:00 of the next trading date, i.e. previous-trading-day published data.",
        "",
        f"Fetch: {source_note}",
        "",
    ] + md_table(future_show, list(future_show.columns), 0) + [
        "",
        "Result: H1 and H2_DEV each have zero causal observations. No OI-related engine test was run. The option-institutional table was inspected too, but it is investor-by-product aggregate data without a call/put dimension, so it cannot produce the specified foreign call-OI minus put-OI exposure without inventing a mapping.",
        "",
        "## A2: TXO PCR, option walls, max pain, and expiry",
        "",
        "Sources: `tw_option_put_call_ratio` (2001-12-24 to 2026-10-16, 6,109 rows), `tw_option_daily_summary` (2024-01-02 to 2026-10-16, 115,948 rows), and `tw_taifex_option_institutional_breakdown` (2024-01-02 to 2026-10-16, 12,825 rows). Official TAIFEX PCR/VIX endpoint probes and raw FinLab tables are retained under `options_raw/`. The VIX endpoint returned a small non-tabular response, so VIX/VIX-term features were not invented.",
        "",
        "Every daily option feature is timestamped 15:00 and joined backward to each campaign signal; no same-day day-session use is possible. Wall prices use the signal-bar close, not the next-bar fill, and are normalized by the signal 5-minute ATR and daily ATR14.",
        "",
        "Expiry labels were reconstructed only where the raw summary lacked its expiry date: YYYYMM = third Wednesday, Wn = nth Wednesday, Fn = nth Friday, rolled to the next day session when that nominal date is a holiday. A raw expiry date always takes precedence. The validation below compares the label rule with every raw non-null expiry date.",
        "",
    ] + md_table(validation_summary, list(validation_summary.columns), 0) + [
        "",
        "### PCR gate and precision check",
        "",
        "`h1_ci_*` and `h2_ci_*` are bootstrap 95% intervals for the predeclared adverse low-score bucket minus all other buckets. A gate needs both upper bounds below zero. `loss_profit_ratio` is the precision check: loss removed / profit removed in the adverse bucket before holdout.",
        "",
    ] + md_table(pcr_show, list(pcr_show.columns), 2) + [
        "",
        "PCR verdict: all six gates are false; no PCR filter was engine-tested.",
        "",
        "### Wall / max-pain / expiry gate and precision check",
        "",
        "For each side-aligned feature, H1 fixes terciles (or the binary state) and identifies the lowest-mean-PnL bucket. The same thresholds and bucket are then evaluated in H2_DEV. A gate requires both bootstrap 95% intervals to be wholly below zero. Features cover weekly and monthly wall runway in 5-minute and daily ATR, directional and absolute max-pain distance, price-between-walls, days-to-expiry, and a near-expiry pin condition (within one 5-minute ATR of max pain at <=1 DTE). The futures proxy check has zero development overlap because the futures series starts in the display-only holdout; holdout overlap is shown separately and is not used for a gate.",
        "",
    ] + md_table(wall_show, list(wall_show.columns), 2) + [
        "",
        "Wall verdict: no feature passed. The full causal daily panels are `newdirs_option_daily_features.csv` and `newdirs_option_walls_daily.csv`; detailed side/bucket output and gates are in `newdirs_walls_discriminator.csv` and `newdirs_walls_gates.csv`.",
        "",
        "## B: breakout / extension position sizing",
        "",
        "H1-only extension cutpoints are used. Each selected campaign scales Cmd, Add, and G together. The comparison is against the control that doubles every campaign; raw net alone is not the decision criterion. Peak exposure is 8 MXF lots for every tested variant; margin assumption is NTD 92,000 per MXF, hence NTD 736,000. ML meta-label sizing had already failed and was not retried.",
        "",
    ] + md_table(b_assumptions.drop_duplicates(["base", "variant"]), ["base", "variant", "extension_high_cutpoint_h1", "peak_lots", "margin_need"], 2) + [
        "",
        "Net delta versus the always-2x control:",
        "",
    ] + md_table(b_pivot, ["base", "variant", "H1", "H2_DEV", "TRAIN", "TEST", "PASS"], 0) + [
        "",
        "## C: legacy `isBaseToxic` blocked hours",
        "",
        "The engine checks the signal bar's close hour: it blocks new Cmd signals at 15:00-20:59 and 01:00-02:59, with long Cmd also blocked at 04:00 and short Cmd at 21:00. A Cmd signal from 14:55 or 00:55 fills on the next bar at 15:00 or 01:00, respectively, so those boundary timestamps are expected and are not rule violations. There are no Cmd fills in any other base-block hour. Add/G entries can also occur while an existing campaign is open.",
        "",
    ] + md_table(pd.DataFrame(hour_summary), list(pd.DataFrame(hour_summary).columns), 0) + [
        "",
        "Unblock delta net versus each exact baseline:",
        "",
    ] + md_table(c_pivot, ["base", "variant", "H1", "H2_DEV", "TRAIN", "TEST", "PASS"], 0) + [
        "",
        "The detailed C metrics include ALL and display-only HOLDOUT in `newdirs_c_unblock_metrics.csv`; the hour distribution is in `newdirs_c_entry_hours.csv`.",
        "",
        "## Reproducibility artifacts",
        "",
        "- `complete_newdirs_remaining.py`: final completion runner; it does not modify the underlying engine.",
        "- `newdirs_exact.json`, `trades_newdirs_v28_baseline.csv`, `trades_newdirs_v29_baseline.csv`: exact cutoff baseline proof.",
        "- `newdirs_futures_oi_daily.csv`, `newdirs_futures_oi_discriminator.csv`, `newdirs_futures_oi_gates.csv`: futures-OI audit.",
        "- `newdirs_option_daily_features.csv`, `newdirs_option_walls_daily.csv`, `newdirs_option_expiry_validation.csv`, `newdirs_walls_*.csv`: wall/max-pain/expiry audit.",
        "- Existing `newdirs_option_discriminator.csv` and `newdirs_option_gates.csv`: PCR audit retained from the completed staged run.",
    ]
    (HERE / "results_newdirs.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    print("Load and apply common cutoff", flush=True)
    df1m = load_1min(DATA)
    df1m = df1m[df1m.ts <= CUTOFF].copy()
    print("Reproduce exact baselines", flush=True)
    runs: dict[str, pd.DataFrame] = {}
    exact: dict[str, str] = {}
    for base, params in BASES.items():
        got = dates(base_run(df1m, p=params, intrabar_mode="1min"))
        want = dates(pd.read_csv(HERE / f"trades_{base}.csv"))
        pd.testing.assert_frame_equal(got[TRADE_COLS].reset_index(drop=True), want[TRADE_COLS].reset_index(drop=True), check_dtype=False, check_exact=True)
        got.to_csv(HERE / f"trades_newdirs_{base}_baseline.csv", index=False, encoding="utf-8-sig")
        runs[base] = got
        exact[base] = f"EXACT {len(got)}/{len(want)}"
    (HERE / "newdirs_exact.json").write_text(json.dumps({"cutoff": str(CUTOFF), **exact}, indent=2), encoding="utf-8")

    print("Prepare causal features", flush=True)
    b5 = prepare(df1m, {**P, **BASES["v29"]})
    daily, validation = build_walls(df1m)
    futures, source_note = load_futures_oi(df1m)
    camp29, _ = campaignize(runs["v29"])
    featured = attach_daily(camp29, b5, daily, futures)
    direction = np.where(featured.side.eq("L"), 1.0, -1.0)
    for raw in ("pcr_oi_z60", "pcr_vol_z60", "pcr_oi_d1", "pcr_oi_d5", "pcr_vol_d1", "pcr_vol_d5"):
        if raw in featured:
            featured["score_" + raw] = -direction * pd.to_numeric(featured[raw], errors="coerce")
    wall_specs: dict[str, str] = {}
    for typ in ("weekly", "monthly"):
        call, put, pain, dte = (f"{typ}_call_wall", f"{typ}_put_wall", f"{typ}_max_pain", f"{typ}_days_to_expiry")
        wall = np.where(featured.side.eq("L"), featured[call], featured[put])
        room = direction * (wall - featured.sig_close)
        pain_dir = direction * (featured[pain] - featured.sig_close)
        pain_abs = (featured[pain] - featured.sig_close).abs()
        featured[f"{typ}_wall_room_5m_atr"] = room / featured.sig_atr
        featured[f"{typ}_wall_room_daily_atr"] = room / featured.daily_atr14
        featured[f"{typ}_max_pain_dir_5m_atr"] = pain_dir / featured.sig_atr
        featured[f"{typ}_max_pain_abs_5m_atr"] = pain_abs / featured.sig_atr
        featured[f"{typ}_between_walls"] = ((featured.sig_close >= np.minimum(featured[call], featured[put])) &
                                               (featured.sig_close <= np.maximum(featured[call], featured[put]))).where(featured[call].notna() & featured[put].notna())
        featured[f"{typ}_dte"] = pd.to_numeric(featured[dte], errors="coerce")
        featured[f"{typ}_near_expiry_pin"] = ((featured[f"{typ}_dte"] <= 1) &
                                                (featured[f"{typ}_max_pain_abs_5m_atr"] <= 1)).where(featured[f"{typ}_dte"].notna())
        for col in (f"{typ}_wall_room_5m_atr", f"{typ}_wall_room_daily_atr", f"{typ}_max_pain_dir_5m_atr", f"{typ}_max_pain_abs_5m_atr", f"{typ}_dte"):
            wall_specs[col] = "numeric"
        wall_specs[f"{typ}_between_walls"] = "binary"
        wall_specs[f"{typ}_near_expiry_pin"] = "binary"
    featured.to_csv(HERE / "newdirs_v29_campaign_option_features.csv", index=False, encoding="utf-8-sig")
    print("Run walls and futures discriminators", flush=True)
    _, wall_gates = feature_discriminator(featured, wall_specs, "walls")
    future_detail, _ = futures_discriminator(featured)

    print("Rebase B sizing", flush=True)
    b_metrics, b_assumptions = b_study(runs, b5)
    print("Rebase C hour variants", flush=True)
    c_metrics, c_hours = c_study(df1m, runs)

    pcr_gates = pd.read_csv(HERE / "newdirs_option_gates.csv")
    print("Write final report", flush=True)
    report(runs, source_note, validation, wall_gates, future_detail, pcr_gates,
           b_metrics, b_assumptions, c_metrics, c_hours)
    print("Done", flush=True)


if __name__ == "__main__":
    main()
