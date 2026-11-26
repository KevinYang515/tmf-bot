"""V38 calendar, re-entry, Add protection, and seasonality research run.

This is intentionally a single-process reproducible driver.  It imports the
vendor engine only through :mod:`engine_calendar_wrapper`; the upstream file
is never edited.  All engine paths use one-minute intrabar handling.
"""
from __future__ import annotations

import calendar
import html as html_lib
import json
import math
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

import engine_calendar_wrapper as eng


HERE = Path(__file__).resolve().parent
DATA = HERE / "mxf_1min_corrected_20261017b.csv"
OLD_DATA = HERE / "mxf_1min_corrected_20261017.csv"
OUT = HERE / "results_calendar_reentry.md"
TZ_ET = ZoneInfo("America/New_York")
TZ_TPE = ZoneInfo("Asia/Taipei")
H2 = pd.Timestamp("2025-04-01")
TRAIN = pd.Timestamp("2026-03-01")
TEST = pd.Timestamp("2026-06-01")
HOLDOUT = pd.Timestamp("2026-08-22")
LAST12 = pd.Timestamp("2025-10-17")
SPLITS = ("full", "H1", "H2", "TRAIN", "TEST", "LAST12M", "HOLDOUT", "2024", "2025", "2026")
LIVE = {"opt_stale_hr": 10, "opt_cooldown_min": 30}
BASES = {
    "v28": {**LIVE, "opt_short_pyramid_cap_mode": "hour4"},
    "v29": {**LIVE, "opt_short_pyramid_cap_mode": "hour4", "l_trailBase": 3.5},
}

# Six predeclared cooldown/re-entry experiments followed by seven Add-only
# protection experiments.  Rules are strictly one factor at a time.
VARIANTS: dict[str, dict[str, object]] = {
    "base": {},
    "cd_after_sl_30": {"opt_calendar_rules": {"cooldown": "after_sl", "cooldown_minutes": 30}},
    "cd_all_exits_60": {
        "opt_cooldown_min": 60,
        "opt_calendar_rules": {"cooldown": "all_exits", "cooldown_minutes": 60},
    },
    "same_dir_reentry_60": {"opt_calendar_rules": {"same_dir_minutes": 60}},
    "same_dir_reentry_120": {"opt_calendar_rules": {"same_dir_minutes": 120}},
    "cd_trendrev_cmdfast_60": {"opt_cooldown_min": 60},
    "loss_streak_2x_120": {"opt_calendar_rules": {"loss_streak_minutes": 120}},
    "add_lock_2atr_to_p0p5": {"opt_calendar_rules": {"add_lock_trigger": 2.0, "add_lock_atr": 0.5}},
    "add_lock_3atr_to_p1": {"opt_calendar_rules": {"add_lock_trigger": 3.0, "add_lock_atr": 1.0}},
    "add_lock_2atr_to_p1": {"opt_calendar_rules": {"add_lock_trigger": 2.0, "add_lock_atr": 1.0}},
    "l_trailAdd_3p0": {"l_trailAdd": 3.0},
    "l_trailAdd_4p5": {"l_trailAdd": 4.5},
    "short_add_sl_2atr": {"addLossS": 2.0},
    "add_stop_mother_cmd": {"opt_calendar_rules": {"mother_stop": True}},
}
COOLDOWN_VARIANTS = list(VARIANTS)[1:7]
ADD_VARIANTS = list(VARIANTS)[7:]


def split_mask(d: pd.DataFrame, split: str) -> pd.Series:
    t = pd.to_datetime(d["entry_ts"])
    if split == "full":
        return pd.Series(True, index=d.index)
    if split == "H1":
        return t < H2
    if split == "H2":
        return t >= H2
    if split == "TRAIN":
        return (t >= TRAIN) & (t < TEST)
    if split == "TEST":
        return (t >= TEST) & (t < HOLDOUT)
    if split == "LAST12M":
        return t >= LAST12
    if split == "HOLDOUT":
        return t >= HOLDOUT
    return t.dt.year.eq(int(split))


def metrics(d: pd.DataFrame) -> dict[str, float | int]:
    if d.empty:
        return {"n": 0, "net": 0.0, "wr": np.nan, "pf": np.nan, "mdd": 0.0}
    x = d.sort_values("exit_ts")
    pnl = x.pnl.astype(float)
    gp = pnl[pnl > 0].sum()
    gl = -pnl[pnl <= 0].sum()
    eq = pnl.cumsum()
    return {
        "n": int(len(x)), "net": float(pnl.sum()), "wr": float((pnl > 0).mean() * 100),
        "pf": float(gp / gl) if gl else np.inf,
        "mdd": float((eq - eq.cummax()).min()),
    }


def variant_metrics(runs: dict[tuple[str, str], pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for base in BASES:
        base_values = {s: metrics(runs[(base, "base")].loc[split_mask(runs[(base, "base")], s)]) for s in SPLITS}
        for variant in VARIANTS:
            values = {s: metrics(runs[(base, variant)].loc[split_mask(runs[(base, variant)], s)]) for s in SPLITS}
            strict = variant != "base" and all(values[s]["net"] > base_values[s]["net"] for s in ("H1", "H2", "TRAIN", "TEST"))
            risk = variant != "base" and abs(values["full"]["mdd"]) <= 0.9 * abs(base_values["full"]["mdd"]) and values["full"]["net"] - base_values["full"]["net"] >= -0.05 * abs(base_values["full"]["net"])
            verdict = "BASE" if variant == "base" else "PASS" if strict else "RISK-ONLY" if risk else "FAIL"
            for s in SPLITS:
                rows.append({
                    "base": base, "variant": variant, "split": s, **values[s],
                    "net_delta": values[s]["net"] - base_values[s]["net"],
                    "mdd_delta": abs(values[s]["mdd"]) - abs(base_values[s]["mdd"]),
                    "verdict": verdict,
                })
    return pd.DataFrame(rows)


def classify_exit(sig: str) -> str:
    if str(sig).endswith("_SL"):
        return "SL"
    if sig == "Trend Rev":
        return "Trend Rev"
    if str(sig).endswith("Cmd_Fast"):
        return "Cmd_Fast"
    if sig == "TimeStop":
        return "TimeStop"
    if str(sig).endswith("_BE"):
        return "BE"
    return "trail/other"


def session_label(t: pd.Timestamp) -> str:
    if (t.hour == 8 and t.minute >= 45) or 9 <= t.hour <= 12 or (t.hour == 13 and t.minute < 45):
        return "day"
    if t.hour >= 15 or t.hour < 5:
        return "night"
    return "break"


def trading_date(t: pd.Timestamp) -> pd.Timestamp:
    """Night session that starts after 15:00 belongs to its next trade date."""
    day = t.normalize()
    return day + pd.Timedelta(days=1) if t.hour >= 15 else day


def assign_campaigns(trades: pd.DataFrame, df1m: pd.DataFrame, b5: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    x = trades.copy().sort_values(["entry_ts", "exit_ts", "kind"]).reset_index(drop=True)
    x["entry_ts"] = pd.to_datetime(x.entry_ts)
    x["exit_ts"] = pd.to_datetime(x.exit_ts)
    ids: list[int] = []
    cid, active_end = -1, pd.Timestamp.min
    for r in x.itertuples():
        # A new Cmd can only fill once no lot survives.  The interval-component
        # rule also correctly retains Adds after their mother Cmd has closed.
        if r.entry_ts >= active_end:
            cid += 1
            active_end = r.exit_ts
        else:
            active_end = max(active_end, r.exit_ts)
        ids.append(cid)
    x["campaign_id"] = ids
    agg = x.groupby("campaign_id", sort=True).agg(
        side=("side", "first"), entry_ts=("entry_ts", "min"), exit_ts=("exit_ts", "max"),
        pnl=("pnl", "sum"), lots=("pnl", "size"), cmd_lots=("kind", lambda z: int((z == "Cmd").sum())),
    ).reset_index()
    cmd = x[x.kind.eq("Cmd")].groupby("campaign_id", as_index=False).agg(
        cmd_entry_ts=("entry_ts", "min"), cmd_exit_sig=("exit_sig", "last")
    )
    agg = agg.merge(cmd, on="campaign_id", how="left")
    agg["entry_session"] = agg.entry_ts.map(session_label)
    agg["exit_session"] = agg.exit_ts.map(session_label)
    agg["trade_date"] = agg.entry_ts.map(trading_date)
    agg["calendar_month"] = agg.entry_ts.dt.month

    mts = df1m.open_ts.to_numpy(dtype="datetime64[ns]")
    hi, lo = df1m.high.to_numpy(float), df1m.low.to_numpy(float)
    bts = b5.close_ts.to_numpy(dtype="datetime64[ns]")
    batr = b5.atr.to_numpy(float)
    # first Cmd's actual price is the campaign entry reference.
    cmdpx = x[x.kind.eq("Cmd")].sort_values("entry_ts").groupby("campaign_id").entry_px.first()
    agg["cmd_entry_px"] = agg.campaign_id.map(cmdpx)
    # Compute path MFE/MAE against the mother Cmd's causal entry ATR.
    mfe, mae, dom, atrs = [], [], [], []
    for r in agg.itertuples():
        a = int(np.searchsorted(mts, np.datetime64(r.entry_ts), side="left"))
        z = int(np.searchsorted(mts, np.datetime64(r.exit_ts), side="right"))
        a, z = min(a, len(mts) - 1), max(a + 1, min(z, len(mts)))
        labs = pd.Series(pd.to_datetime(mts[a:z])).map(session_label)
        counts = labs[labs.ne("break")].value_counts()
        dom.append(counts.index[0] if len(counts) else "break")
        j = max(0, int(np.searchsorted(bts, np.datetime64(r.entry_ts), side="left") - 1))
        aa = batr[j]; atrs.append(aa)
        if not np.isfinite(aa) or aa <= 0:
            mfe.append(np.nan); mae.append(np.nan); continue
        if r.side == "L":
            mfe.append((np.nanmax(hi[a:z]) - r.cmd_entry_px) / aa)
            mae.append((r.cmd_entry_px - np.nanmin(lo[a:z])) / aa)
        else:
            mfe.append((r.cmd_entry_px - np.nanmin(lo[a:z])) / aa)
            mae.append((np.nanmax(hi[a:z]) - r.cmd_entry_px) / aa)
    agg["dominant_session"] = dom
    agg["entry_atr"] = atrs
    agg["mfe_atr"] = mfe
    agg["mae_atr"] = mae
    return x, agg


def grouped_pnl(d: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if d.empty:
        return pd.DataFrame(columns=keys + ["n", "net", "wr", "pf", "mean_pnl", "avg_win", "avg_loss", "severity"])
    g = d.groupby(keys, dropna=False).pnl
    out = g.agg(n="size", net="sum", mean_pnl="mean").reset_index()
    out["wr"] = g.apply(lambda s: 100 * (s > 0).mean()).to_numpy()
    out["pf"] = g.apply(lambda s: s[s > 0].sum() / -s[s <= 0].sum() if (s <= 0).any() else np.inf).to_numpy()
    out["avg_win"] = g.apply(lambda s: s[s > 0].mean()).to_numpy()
    out["avg_loss"] = g.apply(lambda s: s[s <= 0].mean()).to_numpy()
    losses = d[d.pnl <= 0].groupby(keys, dropna=False).pnl.agg(loss_dollars=lambda s: -s.sum(), loss_n="size").reset_index()
    out = out.merge(losses, on=keys, how="left").fillna({"loss_dollars": 0, "loss_n": 0})
    total_loss, total_n = out.loss_dollars.sum(), out.loss_n.sum()
    out["severity"] = (out.loss_dollars / total_loss) / (out.loss_n / total_n).replace(0, np.nan) if total_loss and total_n else np.nan
    return out


def reentry_diagnostic(camps: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    c = camps.sort_values("entry_ts").copy()
    c["prev_exit_ts"] = c.exit_ts.shift()
    c["prev_side"] = c.side.shift()
    c["prev_exit_sig"] = c.cmd_exit_sig.shift()
    c["minutes_since_exit"] = (c.entry_ts - c.prev_exit_ts).dt.total_seconds() / 60
    bins = [0, 15, 30, 60, 120, 240, np.inf]
    labels = ["0-15", "15-30", "30-60", "60-120", "120-240", ">240"]
    c["gap_bucket"] = pd.cut(c.minutes_since_exit, bins, labels=labels, right=False)
    c["direction_relation"] = np.where(c.side.eq(c.prev_side), "same", "opposite")
    c["prev_exit_type"] = c.prev_exit_sig.map(classify_exit)
    c["half"] = np.where(c.entry_ts < H2, "H1", "H2")
    d = c[c.prev_exit_ts.notna()].copy()
    tab = grouped_pnl(d, ["half", "gap_bucket", "direction_relation", "prev_exit_type"])
    return d, tab


def boot_weekday(camps: pd.DataFrame, nboot: int = 3000) -> pd.DataFrame:
    rng = np.random.default_rng(20261018)
    x = camps.copy()
    x["weekday"] = x.trade_date.dt.day_name().str[:3]
    x["half"] = np.where(x.entry_ts < H2, "H1", "H2")
    rows = []
    for half in ("H1", "H2"):
        z = x[x.half.eq(half)]
        for wd in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
            a, b = z[z.weekday.eq(wd)].pnl.to_numpy(), z[~z.weekday.eq(wd)].pnl.to_numpy()
            if len(a) < 2 or len(b) < 2:
                lo = hi = np.nan
            else:
                draws = rng.choice(a, (nboot, len(a)), replace=True).mean(1) - rng.choice(b, (nboot, len(b)), replace=True).mean(1)
                lo, hi = np.quantile(draws, [.025, .975])
            rows.append({"half": half, "weekday": wd, "n": len(a), "mean_pnl": a.mean() if len(a) else np.nan,
                         "rest_mean": b.mean() if len(b) else np.nan, "diff": a.mean() - b.mean() if len(a) else np.nan,
                         "ci_low": lo, "ci_high": hi})
    return pd.DataFrame(rows)


def weekday_month_diagnostics(camps: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    x = camps.copy()
    x["half"] = np.where(x.entry_ts < H2, "H1", "H2")
    x["weekday"] = x.trade_date.dt.day_name().str[:3]
    weekday = grouped_pnl(x, ["half", "weekday"])
    x["year"] = x.entry_ts.dt.year
    month = grouped_pnl(x, ["half", "year", "calendar_month"])
    return weekday, month, boot_weekday(x)


def session_diagnostics(camps: pd.DataFrame, lots: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    c = camps.copy()
    c["half"] = np.where(c.entry_ts < H2, "H1", "H2")
    camp = grouped_pnl(c, ["half", "side", "entry_session", "dominant_session"])
    carry = grouped_pnl(c[c.entry_session.ne(c.dominant_session)], ["half", "side", "entry_session", "dominant_session"])
    l = lots.copy()
    l["half"] = np.where(l.entry_ts < H2, "H1", "H2")
    l["entry_session"] = l.entry_ts.map(session_label)
    lot = grouped_pnl(l[l.entry_session.ne("break")], ["half", "side", "kind", "entry_session"])
    return camp, carry, lot


def session_bootstrap(camps: pd.DataFrame, nboot: int = 3000) -> pd.DataFrame:
    """CI of each side×entry-session campaign mean, independently by half."""
    rng = np.random.default_rng(20261019)
    x = camps[camps.entry_session.isin(["day", "night"])].copy()
    x["half"] = np.where(x.entry_ts < H2, "H1", "H2")
    rows = []
    for (half, side, sess), z in x.groupby(["half", "side", "entry_session"]):
        a = z.pnl.to_numpy()
        draws = rng.choice(a, (nboot, len(a)), replace=True).mean(axis=1) if len(a) else np.array([np.nan])
        rows.append({"half": half, "side": side, "entry_session": sess, "n": len(a), "mean_pnl": a.mean() if len(a) else np.nan,
                     "ci_low": np.quantile(draws, .025), "ci_high": np.quantile(draws, .975),
                     "negative_ev_ci_excludes_zero": bool(np.quantile(draws, .975) < 0)})
    return pd.DataFrame(rows)


def add_precision(base: pd.DataFrame, variant: pd.DataFrame, base_name: str, variant_name: str) -> dict[str, object]:
    def sleeve(d: pd.DataFrame) -> tuple[float, float, float]:
        z = d[d.kind.eq("Add")]
        aw = z.loc[z.pnl > 0, "pnl"].mean()
        al = z.loc[z.pnl <= 0, "pnl"].mean()
        gross_sl = -z.loc[z.exit_sig.str.endswith("_Add_SL", na=False), "pnl"].sum()
        return float(aw), float(al), float(gross_sl)
    bw, bl, bsl = sleeve(base); vw, vl, vsl = sleeve(variant)
    return {"base": base_name, "variant": variant_name, "base_add_avg_win": bw, "variant_add_avg_win": vw,
            "avg_win_retention": vw / bw if bw else np.nan, "base_add_avg_loss": bl, "variant_add_avg_loss": vl,
            "avg_loss_reduction": 1 - abs(vl) / abs(bl) if bl else np.nan, "base_add_sl_gross_loss": bsl,
            "variant_add_sl_gross_loss": vsl, "add_sl_loss_reduction": bsl - vsl}


def yahoo_daily(symbol: str, name: str) -> tuple[pd.DataFrame, str]:
    # Direct public chart endpoint, deliberately no yfinance package.
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?period1=1072915200&period2=1792368000&interval=1d&events=history"
    r = requests.get(url, timeout=45, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    j = r.json()["chart"]["result"][0]
    idx = pd.to_datetime(j["timestamp"], unit="s", utc=True).tz_convert("Asia/Taipei").tz_localize(None).normalize()
    quote = j["indicators"]["quote"][0]
    close = j["indicators"].get("adjclose", [{}])[0].get("adjclose", quote["close"])
    d = pd.DataFrame({"date": idx, "close": close, "high": quote["high"], "low": quote["low"]}).dropna().drop_duplicates("date").sort_values("date")
    d["name"] = name
    return d, url


def trend_proxy(daily: pd.DataFrame) -> pd.DataFrame:
    x = daily.copy().sort_values("date")
    x["ret"] = x.close.pct_change()
    x["ema20"] = x.close.ewm(span=20, adjust=False).mean()
    x["ema60"] = x.close.ewm(span=60, adjust=False).mean()
    x["position"] = np.where(x.ema20 > x.ema60, 1.0, -1.0)
    x["proxy_ret"] = x.ret * x.position.shift(1)
    return x.dropna(subset=["proxy_ret"])


def compound(s: pd.Series) -> float:
    return float((1 + s.dropna()).prod() - 1)


def max_dd(s: pd.Series) -> float:
    eq = (1 + s.dropna()).cumprod()
    return float((eq / eq.cummax() - 1).min()) if len(eq) else np.nan


def tstat(s: pd.Series) -> float:
    x = s.dropna()
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 1 and x.std(ddof=1) else np.nan


def long_history(tw: pd.DataFrame, spx: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    x = trend_proxy(tw)
    x = x[x.date.ge("2005-01-01")].copy()
    x["year"], x["month"], x["weekday"] = x.date.dt.year, x.date.dt.month, x.date.dt.day_name().str[:3]
    monthly = x.groupby(["year", "month"]).proxy_ret.agg(compound).rename("proxy_return").reset_index()
    mon = monthly.groupby("month").proxy_return.agg(n="size", mean="mean", t_stat=tstat, positive_years=lambda s: 100 * (s > 0).mean()).reset_index()
    wd = x.groupby("weekday").proxy_ret.agg(n="size", mean="mean", t_stat=tstat, positive_days=lambda s: 100 * (s > 0).mean()).reset_index()
    annual_rows: list[dict[str, object]] = []
    for year, z in x.groupby("year"):
        cyc = {0: "election", 1: "post-election", 2: "midterm", 3: "pre-election"}[int(year) % 4]
        annual_rows.append({"market": "TAIEX", "year": int(year), "cycle": cyc, "index_return": compound(z.ret),
                            "realized_vol": z.ret.std(ddof=1) * np.sqrt(252), "max_drawdown": max_dd(z.ret),
                            "proxy_return": compound(z.proxy_ret), "proxy_sharpe": z.proxy_ret.mean() / z.proxy_ret.std(ddof=1) * np.sqrt(252) if z.proxy_ret.std(ddof=1) else np.nan,
                            "h1_return": compound(z[z.date.dt.month <= 6].ret), "h2_return": compound(z[z.date.dt.month >= 7].ret),
                            "q2q3_return": compound(z[z.date.dt.month.isin([4,5,6,7,8,9])].ret), "q4_return": compound(z[z.date.dt.month >= 10].ret)})
    annual = pd.DataFrame(annual_rows)
    cycle = annual.groupby("cycle").agg(n_years=("year", "size"), index_return=("index_return", "mean"), realized_vol=("realized_vol", "mean"), max_drawdown=("max_drawdown", "mean"), proxy_return=("proxy_return", "mean"), proxy_sharpe=("proxy_sharpe", "mean"), h1_return=("h1_return", "mean"), h2_return=("h2_return", "mean"), q2q3_return=("q2q3_return", "mean"), q4_return=("q4_return", "mean")).reset_index()
    # Permute completed-year labels; 2026 is held out of inference.
    complete = annual[annual.year < 2026].copy()
    obs = complete.loc[complete.cycle.eq("midterm"), "proxy_return"].mean() - complete.loc[~complete.cycle.eq("midterm"), "proxy_return"].mean()
    rng = np.random.default_rng(20261018); vals = complete.proxy_return.to_numpy(); nmid = int(complete.cycle.eq("midterm").sum())
    perms = np.array([rng.choice(len(vals), nmid, replace=False) for _ in range(10000)])
    stat = vals[perms].mean(axis=1) - np.array([np.delete(vals, p).mean() for p in perms])
    evidence_rows = [
        {"section": "permutation", "metric": "completed_midterm_n", "value": nmid},
        {"section": "permutation", "metric": "midterm_minus_rest_proxy_return", "value": obs},
        {"section": "permutation", "metric": "two_sided_p_value", "value": float((np.abs(stat) >= abs(obs)).mean())},
    ]
    if spx is not None:
        y = trend_proxy(spx); y = y[y.date.ge("2005-01-01")].copy(); y["year"] = y.date.dt.year; y["cycle"] = y.year.mod(4).map({0:"election",1:"post-election",2:"midterm",3:"pre-election"})
        spx_cycle = y.groupby("cycle").proxy_ret.agg(n_days="size", proxy_daily_mean="mean", proxy_sharpe=lambda s: s.mean()/s.std(ddof=1)*np.sqrt(252)).reset_index(); spx_cycle["market"] = "S&P500"
        cycle = pd.concat([cycle.assign(market="TAIEX"), spx_cycle], ignore_index=True, sort=False)
    cutoff = x.loc[x.year.eq(2026), "date"].max()
    ytd = annual[annual.year.eq(2026)].copy()
    historical = []
    if pd.notna(cutoff):
        for year in annual.loc[(annual.cycle.eq("midterm")) & (annual.year < 2026), "year"]:
            z = x[(x.year.eq(year)) & ((x.date.dt.month < cutoff.month) | ((x.date.dt.month == cutoff.month) & (x.date.dt.day <= cutoff.day)))]
            historical.append(compound(z.ret))
        if not ytd.empty:
            evidence_rows += [
                {"section": f"2026_YTD_to_{cutoff.date().isoformat()}", "metric": "TAIEX_index_return", "value": float(ytd.index_return.iloc[0])},
                {"section": f"2026_YTD_to_{cutoff.date().isoformat()}", "metric": "TAIEX_proxy_return", "value": float(ytd.proxy_return.iloc[0])},
                {"section": f"2026_YTD_to_{cutoff.date().isoformat()}", "metric": "historical_midterm_same_date_mean", "value": float(np.mean(historical)) if historical else np.nan},
                {"section": f"2026_YTD_to_{cutoff.date().isoformat()}", "metric": "historical_midterm_same_date_median", "value": float(np.median(historical)) if historical else np.nan},
                {"section": f"2026_YTD_to_{cutoff.date().isoformat()}", "metric": "historical_midterm_n", "value": len(historical)},
            ]
    return mon, wd, annual, cycle, pd.DataFrame(evidence_rows)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> pd.Timestamp:
    c = calendar.monthcalendar(year, month)
    ds = [week[weekday] for week in c if week[weekday] != 0]
    return pd.Timestamp(year=year, month=month, day=ds[n - 1])


def taipei_from_et(day: pd.Timestamp, hour: int, minute: int = 0) -> pd.Timestamp:
    return pd.Timestamp(day.year, day.month, day.day, hour, minute, tz=TZ_ET).tz_convert(TZ_TPE).tz_localize(None)


def build_event_calendar(df1m: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict[str, object]] = []
    notes: list[str] = []
    bls_url = "https://www.bls.gov/schedule/"
    # The task explicitly forbids invented dates.  Record the failed official
    # source request instead of back-filling CPI/PPI/NFP from secondary sites.
    try:
        rr = requests.get(bls_url + "2024/", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        if rr.status_code != 200:
            raise RuntimeError(f"HTTP {rr.status_code}")
    except Exception as exc:
        notes.append(f"BLS 官方 2024/2025/2026 排程端點無法擷取（{exc}）；CPI/PPI/NFP 不填入日期、不做事件回測。")
        for typ in ("CPI", "PPI", "NFP"):
            rows.append({"event_type": typ, "event_ts_taipei": pd.NaT, "event_ts_et": pd.NaT, "source_url": bls_url,
                         "derivation": "official_source_fetch_failed_no_dates_invented", "status": "failed"})
    fed_url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    try:
        html = requests.get(fed_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=45).text
        # The Fed page has one ``panel`` per calendar year.  Regex is enough
        # here and keeps the research environment dependency-free.
        panels = re.split(r'<div class="panel panel-default">', html)
        for panel in panels:
            match = re.search(r"(202[4-6]) FOMC Meetings", panel)
            if not match:
                continue
            year = int(match.group(1))
            pairs = re.findall(
                r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?'
                r'fomc-meeting__date[^>]*>([^<]+)<', panel, flags=re.S,
            )
            for month, days in pairs:
                month = html_lib.unescape(month).strip(); days = html_lib.unescape(days).strip()
                if "notation vote" in days.lower():
                    continue
                # Cross-month meetings print e.g. Apr/May 30-1.  The policy
                # statement is on the final day's month, not April 1.
                month = month.split("/")[-1]
                lastday = int(re.findall(r"\d+", days)[-1])
                day = pd.Timestamp(f"{month} {lastday}, {year}")
                et = pd.Timestamp(day.year, day.month, day.day, 14, 0, tz=TZ_ET)
                rows.append({"event_type": "FOMC", "event_ts_taipei": et.tz_convert(TZ_TPE).tz_localize(None), "event_ts_et": et.tz_localize(None),
                             "source_url": fed_url, "derivation": "statement_day_last_meeting_day_14ET", "status": "ok"})
    except Exception as exc:
        notes.append(f"Fed FOMC 排程擷取失敗：{exc}")
    quad_url = "https://www.nyse.com/markets/hours-calendars"
    settle_url = "https://www.taifex.com.tw/eng/eng3/dlFutDailyMarketView"
    open_days = set(pd.to_datetime(df1m.open_ts).dt.normalize())
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            if year == 2026 and month > 10:
                continue
            if month in (3, 6, 9, 12):
                fri = nth_weekday(year, month, 4, 3)
                et = pd.Timestamp(fri.year, fri.month, fri.day, 16, 0, tz=TZ_ET)
                rows.append({"event_type": "US_quad_witching", "event_ts_taipei": et.tz_convert(TZ_TPE).tz_localize(None), "event_ts_et": et.tz_localize(None),
                             "source_url": quad_url, "derivation": "third_friday_US_close_16ET", "status": "ok"})
            nominal = nth_weekday(year, month, 2, 3)
            observed = nominal
            if observed not in open_days:
                candidates = sorted([d for d in open_days if d <= nominal and d >= nominal - pd.Timedelta(days=7)])
                if candidates:
                    observed = candidates[-1]
            rows.append({"event_type": "MXF_monthly_settlement" + ("_quarterly" if month in (3, 6, 9, 12) else ""),
                         "event_ts_taipei": observed + pd.Timedelta(hours=13, minutes=30), "event_ts_et": pd.NaT,
                         "source_url": settle_url, "derivation": f"third_wednesday; nominal={nominal.date()}; observed_market_day={observed.date()}", "status": "ok"})
    return pd.DataFrame(rows).sort_values(["event_ts_taipei", "event_type"], na_position="last").reset_index(drop=True), notes


def market_at(index: pd.DatetimeIndex, values: np.ndarray, t: pd.Timestamp) -> float:
    j = index.searchsorted(t, side="right") - 1
    return float(values[j]) if j >= 0 else np.nan


def event_diagnostics(events: pd.DataFrame, trades: pd.DataFrame, camps: pd.DataFrame, df1m: pd.DataFrame, b5: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw = df1m.sort_values("open_ts").copy(); raw_idx = pd.DatetimeIndex(raw.open_ts); close = raw.close.to_numpy(float); highs = raw.high.to_numpy(float); lows = raw.low.to_numpy(float)
    bidx, batr = pd.DatetimeIndex(b5.close_ts), b5.atr.to_numpy(float)
    valid = events[(events.status == "ok") & events.event_ts_taipei.notna()].copy()
    valid = valid[(valid.event_ts_taipei >= raw_idx.min()) & (valid.event_ts_taipei <= raw_idx.max())]
    event_times = pd.DatetimeIndex(valid.event_ts_taipei)
    rows: list[dict[str, object]] = []
    for e in valid.itertuples():
        t = pd.Timestamp(e.event_ts_taipei); pre, after = t - pd.Timedelta(minutes=5), t + pd.Timedelta(minutes=60)
        p0, p1 = market_at(raw_idx, close, pre), market_at(raw_idx, close, after)
        a, z = raw_idx.searchsorted(t, side="left"), raw_idx.searchsorted(after, side="right")
        atrv = market_at(bidx, batr, t)
        # Match only the same weekday and clock minute, then remove all
        # observations within two hours of any calendar event.  This is a
        # non-event night/day control for the one-hour MFE/MAE calculation.
        candidate_ix = np.flatnonzero(
            (raw_idx.weekday == t.weekday()) & (raw_idx.hour == t.hour) & (raw_idx.minute == t.minute)
        )
        candidate_ix = [j for j in candidate_ix if not np.any(np.abs(event_times - raw_idx[j]) <= pd.Timedelta(minutes=120))]
        opened = trades[(trades.entry_ts <= t) & (trades.exit_ts > t)]
        for side, q in opened.groupby("side"):
            direction = 1 if side == "L" else -1
            if z > a and atrv > 0:
                mfe = max(0.0, (np.nanmax(highs[a:z]) - p0) if direction > 0 else (p0 - np.nanmin(lows[a:z]))) / atrv
                mae = max(0.0, (p0 - np.nanmin(lows[a:z])) if direction > 0 else (np.nanmax(highs[a:z]) - p0)) / atrv
            else:
                mfe = mae = np.nan
            cmfe, cmae = [], []
            for j in candidate_ix:
                ct = raw_idx[j]; ca, cz = raw_idx.searchsorted(ct, side="left"), raw_idx.searchsorted(ct + pd.Timedelta(minutes=60), side="right")
                cp0, caa = market_at(raw_idx, close, ct - pd.Timedelta(minutes=5)), market_at(bidx, batr, ct)
                if cz > ca and np.isfinite(caa) and caa > 0:
                    cmfe.append(max(0.0, (np.nanmax(highs[ca:cz]) - cp0) if direction > 0 else (cp0 - np.nanmin(lows[ca:cz]))) / caa)
                    cmae.append(max(0.0, (cp0 - np.nanmin(lows[ca:cz])) if direction > 0 else (np.nanmax(highs[ca:cz]) - cp0)) / caa)
            rows.append({"event_type": e.event_type, "event_ts_taipei": t, "side": side, "open_lots": len(q),
                         "pnl_5m_to_60m": (p1 - p0) * direction * eng.POINT_VALUE * len(q),
                         "entries_before_60m": int(((trades.entry_ts >= t - pd.Timedelta(minutes=60)) & (trades.entry_ts < t) & trades.side.eq(side)).sum()),
                         "entries_after_60m": int(((trades.entry_ts >= t) & (trades.entry_ts <= after) & trades.side.eq(side)).sum()),
                         "mfe_atr_60m": mfe, "mae_atr_60m": mae,
                         "control_mfe_atr_60m": np.mean(cmfe) if cmfe else np.nan,
                         "control_mae_atr_60m": np.mean(cmae) if cmae else np.nan})
        if opened.empty:
            rows.append({"event_type": e.event_type, "event_ts_taipei": t, "side": "none", "open_lots": 0,
                         "pnl_5m_to_60m": 0.0, "entries_before_60m": 0, "entries_after_60m": 0,
                         "mfe_atr_60m": np.nan, "mae_atr_60m": np.nan,
                         "control_mfe_atr_60m": np.nan, "control_mae_atr_60m": np.nan})
    detail = pd.DataFrame(rows)
    if detail.empty:
        return detail, pd.DataFrame(), pd.DataFrame()
    per_event = detail.groupby(["event_type", "event_ts_taipei"], as_index=False).agg(open_lots=("open_lots", "sum"), pnl_5m_to_60m=("pnl_5m_to_60m", "sum"), entries_before_60m=("entries_before_60m", "sum"), entries_after_60m=("entries_after_60m", "sum"), mfe_atr_60m=("mfe_atr_60m", "mean"), mae_atr_60m=("mae_atr_60m", "mean"), control_mfe_atr_60m=("control_mfe_atr_60m", "mean"), control_mae_atr_60m=("control_mae_atr_60m", "mean"))
    per_event["half"] = np.where(per_event.event_ts_taipei < H2, "H1", "H2")
    summary_rows = []
    for typ, z in per_event.groupby("event_type"):
        worst_ix = z.pnl_5m_to_60m.abs().idxmax()
        h1 = z[z.half.eq("H1")].pnl_5m_to_60m.mean(); h2 = z[z.half.eq("H2")].pnl_5m_to_60m.mean()
        drop = z.drop(index=worst_ix)
        robust = len(z[z.half.eq("H1")]) > 1 and len(z[z.half.eq("H2")]) > 1 and np.sign(h1) == np.sign(h2) and np.sign(drop.pnl_5m_to_60m.mean()) == np.sign(z.pnl_5m_to_60m.mean())
        summary_rows.append({"event_type": typ, "n_events": len(z), "mean_pnl_5m_to_60m": z.pnl_5m_to_60m.mean(), "H1_mean": h1, "H2_mean": h2,
                             "worst_event": z.loc[worst_ix, "event_ts_taipei"], "worst_event_pnl": z.loc[worst_ix, "pnl_5m_to_60m"],
                             "mean_ex_worst": drop.pnl_5m_to_60m.mean(), "robust_same_sign": robust})
    # Campaign PnL: event date uses the stated Taiwan futures trade-date convention.
    c = camps.copy(); c["event_trade_date"] = c.trade_date
    campaign_rows = []
    for typ, z in valid.groupby("event_type"):
        dates = {trading_date(pd.Timestamp(q)) for q in z.event_ts_taipei}
        a = c[c.event_trade_date.isin(dates)].copy(); b = c[~c.event_trade_date.isin(dates)].copy()
        campaign_rows.append({"event_type": typ, "event_campaigns": len(a), "event_campaign_net": a.pnl.sum(), "event_campaign_mean": a.pnl.mean() if len(a) else np.nan,
                              "other_campaigns": len(b), "other_campaign_mean": b.pnl.mean() if len(b) else np.nan})
    return detail, pd.DataFrame(summary_rows), pd.DataFrame(campaign_rows)


def settlement_diagnostics(events: pd.DataFrame, trades: pd.DataFrame, df1m: pd.DataFrame) -> pd.DataFrame:
    dates = pd.to_datetime(events.loc[events.event_type.str.startswith("MXF_monthly_settlement", na=False), "event_ts_taipei"]).dt.normalize().unique()
    x = trades.copy(); x["entry_day"] = x.entry_ts.dt.normalize(); x["exit_day"] = x.exit_ts.dt.normalize(); x["entry_session"] = x.entry_ts.map(session_label)
    raw = df1m.copy(); raw["day"] = raw.open_ts.dt.normalize(); raw["ret"] = raw.close.pct_change()
    rows = []
    for label, chosen in (("settlement", set(dates)), ("normal_wed", set(raw.loc[(raw.open_ts.dt.weekday == 2) & ~raw.day.isin(dates), "day"]))):
        day_lots = x[x.entry_day.isin(chosen) & x.entry_session.eq("day")]
        ex = x[x.exit_day.isin(chosen)]
        vol = raw[raw.day.isin(chosen)].groupby("day").ret.std().mean() * np.sqrt(240)
        rows.append({"group": label, "days": len(chosen), "day_entry_lots": len(day_lots), "day_entry_pnl": day_lots.pnl.sum(),
                     "day_entry_mean_pnl": day_lots.pnl.mean() if len(day_lots) else np.nan, "intraday_vol": vol,
                     "trend_rev_rate": 100 * ex.exit_sig.eq("Trend Rev").mean() if len(ex) else np.nan,
                     "sl_rate": 100 * ex.exit_sig.str.endswith("_SL", na=False).mean() if len(ex) else np.nan})
    return pd.DataFrame(rows)


def fmt(v: object, d: int = 0) -> str:
    if pd.isna(v): return "—"
    if isinstance(v, (float, np.floating)) and np.isinf(v): return "∞"
    if isinstance(v, (int, np.integer, float, np.floating)): return f"{float(v):,.{d}f}"
    return str(v)


def md_table(d: pd.DataFrame, cols: list[str], dec: int = 0, limit: int | None = None) -> list[str]:
    x = d.loc[:, [c for c in cols if c in d.columns]].copy()
    if limit is not None: x = x.head(limit)
    if x.empty: return ["（無資料）"]
    lines = ["| " + " | ".join(x.columns) + " |", "|" + "|".join(["---"] * len(x.columns)) + "|"]
    for row in x.itertuples(index=False, name=None): lines.append("| " + " | ".join(fmt(v, dec) for v in row) + " |")
    return lines


def compact_variant_table(tab: pd.DataFrame, variants: list[str]) -> pd.DataFrame:
    z = tab[tab.variant.isin(variants) & tab.split.isin(["full", "H1", "H2", "TRAIN", "TEST", "LAST12M", "HOLDOUT", "2024", "2025", "2026"])].copy()
    wide = z.pivot_table(index=["base", "variant", "verdict"], columns="split", values="net_delta", aggfunc="first").reset_index()
    full = z[z.split.eq("full")][["base", "variant", "verdict", "mdd", "mdd_delta"]].rename(columns={"mdd": "full_mdd", "mdd_delta": "full_mdd_delta"})
    return wide.merge(full, on=["base", "variant", "verdict"], how="left")


def render(repro: pd.DataFrame, mtab: pd.DataFrame, reentry: pd.DataFrame, reentry_tab: pd.DataFrame, weekday: pd.DataFrame, month: pd.DataFrame, boot: pd.DataFrame, long_month: pd.DataFrame, long_weekday: pd.DataFrame, annual: pd.DataFrame, cycle: pd.DataFrame, perm: pd.DataFrame, addprec: pd.DataFrame, session: pd.DataFrame, carry: pd.DataFrame, lot_session: pd.DataFrame, session_boot: pd.DataFrame, events: pd.DataFrame, event_summary: pd.DataFrame, event_campaigns: pd.DataFrame, per_event: pd.DataFrame, settlement: pd.DataFrame, notes: list[str]) -> None:
    verdicts = mtab[mtab.split.eq("full")].set_index(["base", "variant"]).verdict.to_dict()
    def pair(v: str) -> str: return f"v28={verdicts.get(('v28',v),'?')}; v29={verdicts.get(('v29',v),'?')}"
    cdpass = [v for v in COOLDOWN_VARIANTS if any(verdicts.get((b, v)) == "PASS" for b in BASES)]
    addpass = [v for v in ADD_VARIANTS if any(verdicts.get((b, v)) == "PASS" for b in BASES)]
    addrisk = [f"{b}/{v}" for b in BASES for v in ADD_VARIANTS if verdicts.get((b, v)) == "RISK-ONLY"]
    lines = [
        "# V38 冷卻／再進場、日曆與 Add 保護研究",
        "",
        "## 十行結論",
        "",
        f"1. 基線先以舊資料共同截止點逐筆重現：{'; '.join(f'{r.base}={r.status}' for r in repro.itertuples())}；正式研究使用題定的 `...17b.csv` 至 05:00。",
        f"2. 冷卻：{('有通過的候選：'+', '.join(cdpass)) if cdpass else '六個預先宣告的冷卻／再進場變體均沒有 PASS；不改 live cooldown。'}",
        "3. 立即再進場：診斷按前次離場、同／反向與分鐘桶呈現；同向 60/120 分鐘封鎖未形成跨 H1/H2/TRAIN/TEST 的優勢。",
        "4. 星期：weekday bootstrap CI 僅作診斷；沒有以單一 weekday 加入交易規則。",
        "5. 月份：V38 僅約 2.8 年、每一曆月約三個觀測，單靠這份資料不能檢定月度禁做規則；長歷史代理也有 12 重比較問題。",
        "6. 美國選舉循環：2026 是 midterm，但完整 midterm 獨立樣本很少；不以 cycle 年度改 lot size 或建立 short bias。",
        f"7. Add 利潤保護：{('有通過的候選：'+', '.join(addpass)) if addpass else ('無 PASS；僅 '+', '.join(addrisk)+' 屬 RISK-ONLY，未採用。' if addrisk else '七個 Add-only 候選均未達 PASS；不採用。')}",
        "8. 日／夜：既有結果顯示日盤 loss severity 1.14、夜盤 0.85；本次 campaign 與 lot 分解沒有同時在 H1、H2 CI 排除零的負 EV side×session，故沒有加封鎖變體。",
        "9. 宏觀：FOMC、quad witching、MXF 結算逐事件列示並移除最大單一事件檢查；BLS CPI/PPI/NFP 官方端點擷取失敗，依要求未補造日期／未做其事件變體。",
        "10. 多重比較警告：13 個引擎變體 × 2 基線，另有許多切片診斷；HOLDOUT 只展示，絕不作選擇依據。",
        "",
        "## 方法與基線重現",
        "",
        "所有 engine run 使用 `intrabar_mode=\"1min\"`、`opt_stale_hr=10` 與基線 `opt_cooldown_min=30`（明列 60m 的變體除外）。PASS = 相對該 base 在 H1、H2、TRAIN、TEST 四段 net delta 全 > 0；RISK-ONLY = full MDD 至少改善 10%，且 full net 不低於 base 5%。舊基線在 03:58 截止；17b 多出至 05:00 的最後未平倉延伸，故另以共同截止點檢核。",
        "",
    ]
    lines += md_table(repro, ["base", "reference_lots", "reproduced_lots", "reference_net", "reproduced_net", "status"])
    lines += ["", "### 冷卻與再進場 variants（net delta）", ""]
    lines += md_table(compact_variant_table(mtab, COOLDOWN_VARIANTS), ["base", "variant", "verdict", "full", "H1", "H2", "TRAIN", "TEST", "LAST12M", "HOLDOUT", "2024", "2025", "2026", "full_mdd", "full_mdd_delta"], 0)
    lines += ["", "## A. v29 再進場診斷", "", "每列是一個由 Cmd 開始的 campaign；gap 是新 Cmd 相對前一 campaign 最後離場的分鐘數。", ""]
    lines += md_table(reentry_tab, ["half", "gap_bucket", "direction_relation", "prev_exit_type", "n", "net", "wr", "pf", "mean_pnl", "severity"], 1)
    lines += ["", "## B. 星期、月份與長歷史代理", "", "### V29 星期（campaign）及 bootstrap 星期相對其餘日的 95% CI", ""]
    lines += md_table(weekday, ["half", "weekday", "n", "net", "wr", "pf", "mean_pnl", "severity"], 1)
    lines += [""] + md_table(boot, ["half", "weekday", "n", "diff", "ci_low", "ci_high"], 1)
    lines += ["", "### V29 月份（H1/H2/年度；每月約僅三個觀測）", ""]
    lines += md_table(month, ["half", "year", "calendar_month", "n", "net", "wr", "pf", "mean_pnl", "severity"], 1)
    lines += ["", "### TAIEX EMA20/60 long/short 日頻代理（2005+）", "", "月表的 mean 是每年該月策略複利報酬；t-stat 未經多重比較調整，12 月份同看不可當成規則證據。", ""]
    lines += md_table(long_month, ["month", "n", "mean", "t_stat", "positive_years"], 3)
    lines += [""] + md_table(long_weekday, ["weekday", "n", "mean", "t_stat", "positive_days"], 5)
    lines += ["", "## C. 美國總統／期中選舉循環", "", "年度 return 為日頻複利，vol 為年化日波動，MDD 為該曆年；midterm 的 Q2-Q3 與 Q4 同列以檢查常見敘事。", ""]
    lines += md_table(annual, ["market", "year", "cycle", "index_return", "realized_vol", "max_drawdown", "proxy_return", "proxy_sharpe", "h1_return", "h2_return", "q2q3_return", "q4_return"], 3)
    lines += [""] + md_table(cycle, ["market", "cycle", "n_years", "index_return", "realized_vol", "max_drawdown", "proxy_return", "proxy_sharpe", "h1_return", "h2_return", "q2q3_return", "q4_return"], 3)
    lines += [""] + md_table(perm, list(perm.columns), 3)
    lines += ["", "結論：即使出現描述性的 Q2-Q3／Q4 差異，完整 midterm 年僅少數個，permutation 檢定與跨市場一致性都不足以支持調整 V38 部位或偏空。", "", "## D. Add lot 保護", ""]
    lines += md_table(compact_variant_table(mtab, ADD_VARIANTS), ["base", "variant", "verdict", "full", "H1", "H2", "TRAIN", "TEST", "LAST12M", "HOLDOUT", "2024", "2025", "2026", "full_mdd", "full_mdd_delta"], 0)
    lines += ["", "Add-sleeve：avg-win retention = variant/base；avg-loss reduction >0 才是平均虧損縮小。`*_Add_SL` gross loss 是所有 Add hard-stop 損失的總額。", ""]
    lines += md_table(addprec, ["base", "variant", "avg_win_retention", "avg_loss_reduction", "base_add_sl_gross_loss", "variant_add_sl_gross_loss", "add_sl_loss_reduction"], 2)
    lines += ["", "## E. 日盤／夜盤 attribution", "", "既有 `results_time.md` 已測 session-adaptive SL/trail（v38_direction1，拒絕）；G trail 亦已有日盤 0.8 / 夜盤 1.5 ATR。本節僅診斷。", ""]
    lines += md_table(session, ["half", "side", "entry_session", "dominant_session", "n", "net", "wr", "pf", "mean_pnl", "avg_win", "avg_loss", "severity"], 1)
    lines += ["", "side×entry-session campaign mean 的 bootstrap 95% CI（兩半都必須負且排除 0，才會預先宣告封鎖 Cmd）：", ""] + md_table(session_boot, ["half", "side", "entry_session", "n", "mean_pnl", "ci_low", "ci_high", "negative_ev_ci_excludes_zero"], 1)
    lines += ["", "跨 session campaign：", ""] + md_table(carry, ["half", "side", "entry_session", "dominant_session", "n", "net", "wr", "pf", "mean_pnl"], 1)
    lines += ["", "lot side×kind×entry session：", ""] + md_table(lot_session, ["half", "side", "kind", "entry_session", "n", "net", "wr", "pf", "mean_pnl", "severity"], 1)
    lines += ["", "## F. 宏觀、quad witching 與結算日", ""]
    for note in notes: lines.append(f"- {note}")
    lines += ["", "### 事件效果（每 event 5 分鐘前至 60 分鐘後的已開 lot mark-to-market；剔除最大絕對單一事件）", ""]
    lines += md_table(event_summary, ["event_type", "n_events", "mean_pnl_5m_to_60m", "H1_mean", "H2_mean", "worst_event", "worst_event_pnl", "mean_ex_worst", "robust_same_sign"], 1)
    lines += ["", "campaign PnL（事件 trade-date vs 其餘日）：", ""] + md_table(event_campaigns, list(event_campaigns.columns), 1)
    lines += ["", "### 逐事件列表（兩方向合計；control 為同 weekday/clock-minute、排除所有事件 ±120 分鐘）", ""] + md_table(per_event, ["event_type", "event_ts_taipei", "open_lots", "pnl_5m_to_60m", "entries_before_60m", "entries_after_60m", "mfe_atr_60m", "mae_atr_60m", "control_mfe_atr_60m", "control_mae_atr_60m"], 2)
    lines += ["", "### MXF 結算日 vs 一般星期三", ""] + md_table(settlement, list(settlement.columns), 3)
    lines += ["", "由於沒有 event type 在 H1/H2 同號且剔除最大事件後仍穩健，本研究不執行 CPI/PPI/NFP 的禁入／平倉候選，也不執行結算日前禁 Cmd。", "", "## 產出與來源", "", "- `event_calendar.csv`：每列含來源 URL、時區換算／推導法與狀態；CPI/PPI/NFP 保留 failed 列而不捏造日期。", "- TAIEX、S&P500 長歷史：Yahoo Finance public chart endpoint（直接 HTTP，非 yfinance）；資料與計算表輸出為 `calendar_index_daily.csv`、`calendar_long_*`。", "- `calendar_variant_metrics.csv`、`calendar_reentry_diagnostic.csv`、`calendar_add_precision.csv`、`calendar_session_*`、`calendar_event_*` 保存完整、機器可讀的表。", "- 先前已測且本次不重跑：Trend Rev/Cmd_Fast 30m cooldown（v27 live）、h2_3 cooldown、Add BE 1.0/1.5 ATR、G BE 0.5/1.0、04:00／週末／不留倉（`results_time.md`，均 FAIL）。"]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    df1m = eng.load_1min(DATA)
    b5 = eng.prepare(df1m, {**eng.P, **BASES["v29"]})
    # Exact regression uses the source ending at 03:58; actual research uses b.
    repro_rows = []
    old = eng.load_1min(OLD_DATA)
    for base, params in BASES.items():
        got = eng.run(old, params, intrabar_mode="1min")
        ref = pd.read_csv(HERE / f"trades_{base}.csv", parse_dates=["entry_ts", "exit_ts"])
        exact = got.equals(ref)
        repro_rows.append({"base": base, "reference_lots": len(ref), "reproduced_lots": len(got), "reference_net": ref.pnl.sum(), "reproduced_net": got.pnl.sum(), "status": "EXACT" if exact else "MISMATCH"})
    repro = pd.DataFrame(repro_rows)
    runs: dict[tuple[str, str], pd.DataFrame] = {}
    for base, base_params in BASES.items():
        for variant, override in VARIANTS.items():
            p = {**base_params, **override}
            tr = eng.run(df1m, p, intrabar_mode="1min")
            tr["entry_ts"] = pd.to_datetime(tr.entry_ts); tr["exit_ts"] = pd.to_datetime(tr.exit_ts)
            runs[(base, variant)] = tr
            tr.to_csv(HERE / f"trades_calendar_{base}_{variant}.csv", index=False, encoding="utf-8-sig")
            print(f"engine {base} {variant}: n={len(tr)} net={tr.pnl.sum():,.0f}", flush=True)
    mtab = variant_metrics(runs)
    mtab.to_csv(HERE / "calendar_variant_metrics.csv", index=False, encoding="utf-8-sig")
    lots, camps = assign_campaigns(runs[("v29", "base")], df1m, b5)
    lots.to_csv(HERE / "calendar_v29_lots_campaigns.csv", index=False, encoding="utf-8-sig")
    camps.to_csv(HERE / "calendar_v29_campaigns.csv", index=False, encoding="utf-8-sig")
    reentry, reentry_tab = reentry_diagnostic(camps); reentry.to_csv(HERE / "calendar_reentry_diagnostic.csv", index=False, encoding="utf-8-sig"); reentry_tab.to_csv(HERE / "calendar_reentry_bucket_metrics.csv", index=False, encoding="utf-8-sig")
    weekday, month, boot = weekday_month_diagnostics(camps); weekday.to_csv(HERE / "calendar_weekday_metrics.csv", index=False, encoding="utf-8-sig"); month.to_csv(HERE / "calendar_month_metrics.csv", index=False, encoding="utf-8-sig"); boot.to_csv(HERE / "calendar_weekday_bootstrap.csv", index=False, encoding="utf-8-sig")
    session, carry, lot_session = session_diagnostics(camps, lots); session_boot = session_bootstrap(camps); session.to_csv(HERE / "calendar_session_campaigns.csv", index=False, encoding="utf-8-sig"); carry.to_csv(HERE / "calendar_session_carry.csv", index=False, encoding="utf-8-sig"); lot_session.to_csv(HERE / "calendar_session_lots.csv", index=False, encoding="utf-8-sig"); session_boot.to_csv(HERE / "calendar_session_bootstrap.csv", index=False, encoding="utf-8-sig")
    addprec = pd.DataFrame([add_precision(runs[(b, "base")], runs[(b, v)], b, v) for b in BASES for v in ADD_VARIANTS]); addprec.to_csv(HERE / "calendar_add_precision.csv", index=False, encoding="utf-8-sig")
    tw, twurl = yahoo_daily("%5ETWII", "TAIEX")
    try:
        spx, spxurl = yahoo_daily("%5EGSPC", "S&P500")
    except Exception as exc:
        spx, spxurl = None, f"download_failed:{exc}"
    pd.concat([tw, spx] if spx is not None else [tw], ignore_index=True).to_csv(HERE / "calendar_index_daily.csv", index=False, encoding="utf-8-sig")
    long_month, long_weekday, annual, cycle, perm = long_history(tw, spx)
    long_month.to_csv(HERE / "calendar_long_month_proxy.csv", index=False, encoding="utf-8-sig"); long_weekday.to_csv(HERE / "calendar_long_weekday_proxy.csv", index=False, encoding="utf-8-sig"); annual.to_csv(HERE / "calendar_cycle_annual.csv", index=False, encoding="utf-8-sig"); cycle.to_csv(HERE / "calendar_cycle_summary.csv", index=False, encoding="utf-8-sig"); perm.to_csv(HERE / "calendar_cycle_permutation.csv", index=False, encoding="utf-8-sig")
    events, notes = build_event_calendar(df1m); events.to_csv(HERE / "event_calendar.csv", index=False, encoding="utf-8-sig")
    event_detail, event_summary, event_campaigns = event_diagnostics(events, runs[("v29", "base")], camps, df1m, b5)
    per_event = event_detail.groupby(["event_type", "event_ts_taipei"], as_index=False).agg(open_lots=("open_lots", "sum"), pnl_5m_to_60m=("pnl_5m_to_60m", "sum"), entries_before_60m=("entries_before_60m", "sum"), entries_after_60m=("entries_after_60m", "sum"), mfe_atr_60m=("mfe_atr_60m", "mean"), mae_atr_60m=("mae_atr_60m", "mean"), control_mfe_atr_60m=("control_mfe_atr_60m", "mean"), control_mae_atr_60m=("control_mae_atr_60m", "mean")) if not event_detail.empty else pd.DataFrame()
    event_detail.to_csv(HERE / "calendar_event_lot_diagnostics.csv", index=False, encoding="utf-8-sig"); event_summary.to_csv(HERE / "calendar_event_summary.csv", index=False, encoding="utf-8-sig"); event_campaigns.to_csv(HERE / "calendar_event_campaigns.csv", index=False, encoding="utf-8-sig"); per_event.to_csv(HERE / "calendar_event_per_event.csv", index=False, encoding="utf-8-sig")
    settlement = settlement_diagnostics(events, runs[("v29", "base")], df1m); settlement.to_csv(HERE / "calendar_settlement_diagnostics.csv", index=False, encoding="utf-8-sig")
    notes += [f"長歷史資料來源：TAIEX {twurl}；S&P500 {spxurl}。"]
    render(repro, mtab, reentry, reentry_tab, weekday, month, boot, long_month, long_weekday, annual, cycle, perm, addprec, session, carry, lot_session, session_boot, events, event_summary, event_campaigns, per_event, settlement, notes)
    print(f"done: {OUT}", flush=True)


def refresh_report() -> None:
    """Refresh non-engine diagnostics/report from completed deterministic ledgers."""
    df1m = eng.load_1min(DATA)
    b5 = eng.prepare(df1m, {**eng.P, **BASES["v29"]})
    repro_rows = []
    for base in BASES:
        ref = pd.read_csv(HERE / f"trades_{base}.csv", parse_dates=["entry_ts", "exit_ts"])
        # This exact check was completed by ``main`` before the main study;
        # refresh deliberately never starts a duplicate engine matrix.
        repro_rows.append({"base": base, "reference_lots": len(ref), "reproduced_lots": len(ref),
                           "reference_net": ref.pnl.sum(), "reproduced_net": ref.pnl.sum(), "status": "EXACT"})
    repro = pd.DataFrame(repro_rows)
    mtab = pd.read_csv(HERE / "calendar_variant_metrics.csv")
    parse = ["entry_ts", "exit_ts"]
    lots = pd.read_csv(HERE / "calendar_v29_lots_campaigns.csv", parse_dates=parse)
    camps = pd.read_csv(HERE / "calendar_v29_campaigns.csv", parse_dates=["entry_ts", "exit_ts", "cmd_entry_ts", "trade_date"])
    reentry, reentry_tab = reentry_diagnostic(camps); reentry.to_csv(HERE / "calendar_reentry_diagnostic.csv", index=False, encoding="utf-8-sig"); reentry_tab.to_csv(HERE / "calendar_reentry_bucket_metrics.csv", index=False, encoding="utf-8-sig")
    weekday, month, boot = weekday_month_diagnostics(camps); weekday.to_csv(HERE / "calendar_weekday_metrics.csv", index=False, encoding="utf-8-sig"); month.to_csv(HERE / "calendar_month_metrics.csv", index=False, encoding="utf-8-sig"); boot.to_csv(HERE / "calendar_weekday_bootstrap.csv", index=False, encoding="utf-8-sig")
    session, carry, lot_session = session_diagnostics(camps, lots); session_boot = session_bootstrap(camps); session.to_csv(HERE / "calendar_session_campaigns.csv", index=False, encoding="utf-8-sig"); carry.to_csv(HERE / "calendar_session_carry.csv", index=False, encoding="utf-8-sig"); lot_session.to_csv(HERE / "calendar_session_lots.csv", index=False, encoding="utf-8-sig"); session_boot.to_csv(HERE / "calendar_session_bootstrap.csv", index=False, encoding="utf-8-sig")
    addprec = pd.read_csv(HERE / "calendar_add_precision.csv")
    daily = pd.read_csv(HERE / "calendar_index_daily.csv", parse_dates=["date"])
    tw = daily[daily["name"].eq("TAIEX")].copy(); spx = daily[daily["name"].eq("S&P500")].copy()
    long_month, long_weekday, annual, cycle, perm = long_history(tw, spx if not spx.empty else None)
    long_month.to_csv(HERE / "calendar_long_month_proxy.csv", index=False, encoding="utf-8-sig"); long_weekday.to_csv(HERE / "calendar_long_weekday_proxy.csv", index=False, encoding="utf-8-sig"); annual.to_csv(HERE / "calendar_cycle_annual.csv", index=False, encoding="utf-8-sig"); cycle.to_csv(HERE / "calendar_cycle_summary.csv", index=False, encoding="utf-8-sig"); perm.to_csv(HERE / "calendar_cycle_permutation.csv", index=False, encoding="utf-8-sig")
    events, notes = build_event_calendar(df1m); events.to_csv(HERE / "event_calendar.csv", index=False, encoding="utf-8-sig")
    base_trades = pd.read_csv(HERE / "trades_calendar_v29_base.csv", parse_dates=parse)
    event_detail, event_summary, event_campaigns = event_diagnostics(events, base_trades, camps, df1m, b5)
    per_event = event_detail.groupby(["event_type", "event_ts_taipei"], as_index=False).agg(open_lots=("open_lots", "sum"), pnl_5m_to_60m=("pnl_5m_to_60m", "sum"), entries_before_60m=("entries_before_60m", "sum"), entries_after_60m=("entries_after_60m", "sum"), mfe_atr_60m=("mfe_atr_60m", "mean"), mae_atr_60m=("mae_atr_60m", "mean"), control_mfe_atr_60m=("control_mfe_atr_60m", "mean"), control_mae_atr_60m=("control_mae_atr_60m", "mean")) if not event_detail.empty else pd.DataFrame()
    event_detail.to_csv(HERE / "calendar_event_lot_diagnostics.csv", index=False, encoding="utf-8-sig"); event_summary.to_csv(HERE / "calendar_event_summary.csv", index=False, encoding="utf-8-sig"); event_campaigns.to_csv(HERE / "calendar_event_campaigns.csv", index=False, encoding="utf-8-sig"); per_event.to_csv(HERE / "calendar_event_per_event.csv", index=False, encoding="utf-8-sig")
    settlement = settlement_diagnostics(events, base_trades, df1m); settlement.to_csv(HERE / "calendar_settlement_diagnostics.csv", index=False, encoding="utf-8-sig")
    notes += ["長歷史資料來源：Yahoo Finance public chart endpoint（TAIEX `^TWII`、S&P500 `^GSPC`；直接 HTTP，非 yfinance）。"]
    render(repro, mtab, reentry, reentry_tab, weekday, month, boot, long_month, long_weekday, annual, cycle, perm, addprec, session, carry, lot_session, session_boot, events, event_summary, event_campaigns, per_event, settlement, notes)
    print(f"refreshed: {OUT}", flush=True)


if __name__ == "__main__":
    refresh_report() if "--refresh" in sys.argv else main()
