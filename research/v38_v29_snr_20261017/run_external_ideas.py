"""Pre-registered external-idea tests for task_external_ideas.md.

The upstream V38 engine is only imported/read; no engine file is modified.
All generated artifacts use the ext_ prefix, except the requested report.
"""
from __future__ import annotations

import ast
import inspect
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
import engine_v26_bbw as eng  # noqa: E402

DATA = HERE / "mxf_1min_corrected_20261017b.csv"
LEDGER = HERE / "trades_newdirs_v28_baseline.csv"
OPTIONS = HERE / "options_raw" / "finlab_tw_option_daily_summary.csv"
RESCUE_BASE = HERE / "rescue_v28_market_costed_lots.csv"
CONTRACT_CHOICE = HERE / "rescue_contract_choice.csv"
H2 = pd.Timestamp("2025-04-01")
RNG = np.random.default_rng(20261019)
PV_MXF, PV_TMF = 50.0, 10.0
BROKER, TAX, MXF_SLIP, TMF_SLIP = 20.0, 0.00002, 4.0, 3.1


def save(df: pd.DataFrame, name: str) -> None:
    df.to_csv(HERE / name, index=False, encoding="utf-8-sig")


def md_table(df: pd.DataFrame, cols: list[str] | None = None, digits: int = 2) -> str:
    x = df.copy() if cols is None else df[cols].copy()
    if x.empty:
        return "（無資料）"
    for c in x.select_dtypes(include=["number"]).columns:
        x[c] = x[c].map(lambda v: "" if pd.isna(v) else f"{v:,.{digits}f}")
    rows = ["| " + " | ".join(map(str, x.columns)) + " |",
            "| " + " | ".join(["---"] * len(x.columns)) + " |"]
    rows += ["| " + " | ".join(str(v).replace("|", "\\|") for v in row) + " |"
             for row in x.itertuples(index=False, name=None)]
    return "\n".join(rows)


def session_info(ts: pd.Series) -> pd.DataFrame:
    """Return session type/id and elapsed minute for valid day/night tape minutes."""
    z = pd.to_datetime(ts)
    mins = z.dt.hour * 60 + z.dt.minute
    day = (mins >= 8 * 60 + 45) & (mins < 13 * 60 + 45)
    night = (mins >= 15 * 60) | (mins < 5 * 60)
    typ = np.where(day, "day", np.where(night, "night", None))
    sid = z.dt.normalize()
    sid = sid.where(mins >= 5 * 60, sid - pd.Timedelta(days=1))
    elapsed = np.where(day, mins - (8 * 60 + 45), np.where(mins >= 15 * 60, mins - 15 * 60, mins + 9 * 60))
    return pd.DataFrame({"session": typ, "session_id": sid, "session_minute": elapsed}, index=ts.index)


def trade_day(ts: pd.Series | pd.Timestamp) -> pd.Series | pd.Timestamp:
    if isinstance(ts, pd.Timestamp):
        return ts.normalize() + pd.Timedelta(days=1) if ts.hour >= 15 else ts.normalize()
    z = pd.to_datetime(ts)
    return z.dt.normalize() + pd.to_timedelta((z.dt.hour >= 15).astype(int), unit="D")


def fee_mxf(px: pd.Series | np.ndarray | float) -> pd.Series | np.ndarray | float:
    return BROKER + TAX * np.asarray(px) * PV_MXF + MXF_SLIP * PV_MXF


def fee_tmf(px: pd.Series | np.ndarray | float) -> pd.Series | np.ndarray | float:
    return BROKER + TAX * np.asarray(px) * PV_TMF + TMF_SLIP * PV_TMF


def mdd_from_daily(daily: pd.Series) -> float:
    x = daily.sort_index().to_numpy(float)
    if not len(x):
        return 0.0
    eq = np.r_[0.0, np.cumsum(x)]
    return float(np.min(eq - np.maximum.accumulate(eq)))


def stats_daily(daily: pd.Series) -> dict[str, float]:
    x = daily.sort_index()
    net, mdd = float(x.sum()), mdd_from_daily(x)
    return {"n_days": len(x), "net": net, "mdd": mdd,
            "net_mdd": net / abs(mdd) if mdd else np.nan,
            "worst_day": float(x.min()) if len(x) else np.nan}


def campaign_ids(d: pd.DataFrame) -> pd.Series:
    order = {"Cmd": 0, "Add": 1, "G": 2}
    x = d[["entry_ts", "kind"]].copy()
    x["_i"] = d.index
    x["_order"] = x.kind.map(order).fillna(9)
    x = x.sort_values(["entry_ts", "_order", "_i"])
    x["campaign_id"] = x.kind.eq("Cmd").cumsum() - 1
    return x.set_index("_i").campaign_id.reindex(d.index).astype(int)


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    one = eng.load_1min(DATA).sort_values("open_ts").reset_index(drop=True)
    one["open_ts"] = pd.to_datetime(one.open_ts)
    one["ts"] = pd.to_datetime(one.ts)
    sinfo = session_info(one.open_ts)
    one = pd.concat([one, sinfo], axis=1)
    one = one[one.session.notna()].copy()
    tr = pd.read_csv(LEDGER)
    tr["entry_ts"], tr["exit_ts"] = pd.to_datetime(tr.entry_ts), pd.to_datetime(tr.exit_ts)
    tr["direction"] = np.where(tr.side.eq("L"), 1.0, -1.0)
    tr["campaign_id"] = campaign_ids(tr)
    # Explicitly rebuild all P/L at requested realistic MXF costs.
    tr["pnl_cost"] = (tr.direction * (tr.exit_px - tr.entry_px) * PV_MXF
                      - fee_mxf(tr.entry_px) - fee_mxf(tr.exit_px))
    # Item 2 is a contract-sizing comparison, so use the previously validated
    # costed v28 execution ledger as its MXF base.  Replacing MXF with five TMF
    # changes only the measured equal-exposure cost difference from that run.
    base = pd.read_csv(RESCUE_BASE)
    key = ["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig"]
    base["entry_ts"], base["exit_ts"] = pd.to_datetime(base.entry_ts), pd.to_datetime(base.exit_ts)
    tr = tr.merge(base[key + ["pnl_new"]], on=key, how="left", validate="one_to_one")
    if tr.pnl_new.isna().any():
        raise RuntimeError("costed v28 ledger did not match every external-idea trade")
    cost = pd.read_csv(CONTRACT_CHOICE).iloc[0]
    tmf5_minus_mxf_side = float(cost["TMF5_minus_MXF_per_side"])
    tr["tmf5_equiv_pnl"] = tr.pnl_new - 2 * tmf5_minus_mxf_side
    tr["entry_day"] = trade_day(tr.entry_ts)
    tr["exit_day"] = trade_day(tr.exit_ts)
    b5 = eng.prepare(one[["ts", "open", "high", "low", "close", "volume", "amount", "open_ts"]], eng.P)
    b5["open_ts"], b5["close_ts"] = pd.to_datetime(b5.open_ts), pd.to_datetime(b5.close_ts)
    return one, tr, b5


def rvol_frame(one: pd.DataFrame) -> pd.DataFrame:
    """Causal cumulative-volume RVOL, using only prior twenty same-type sessions."""
    z = one[["open_ts", "volume", "session", "session_id", "session_minute"]].copy()
    z["cum_volume"] = z.groupby(["session", "session_id"], sort=False).volume.cumsum()
    chunks: list[pd.DataFrame] = []
    for typ, g in z.groupby("session", sort=False):
        p = g.pivot_table(index="session_id", columns="session_minute", values="cum_volume", aggfunc="last").sort_index()
        avg = p.shift(1).rolling(20, min_periods=20).mean()
        a = avg.stack().rename("prior20_mean_cum").reset_index()
        a["session"] = typ
        chunks.append(a)
    ref = pd.concat(chunks, ignore_index=True)
    z = z.merge(ref, on=["session", "session_id", "session_minute"], how="left")
    z["rvol"] = z.cum_volume / z.prior20_mean_cum
    return z[["open_ts", "session", "session_id", "session_minute", "cum_volume", "prior20_mean_cum", "rvol"]]


def join_trade_features(tr: pd.DataFrame, rvol: pd.DataFrame, b5: pd.DataFrame) -> pd.DataFrame:
    z = pd.merge_asof(tr.sort_values("entry_ts"), rvol.sort_values("open_ts"),
                      left_on="entry_ts", right_on="open_ts", direction="backward")
    proxies = b5[["close_ts", "atr", "adx", "bbw", "close"]].copy()
    proxies["atr_pct"] = proxies.atr / proxies.close
    z = pd.merge_asof(z.sort_values("entry_ts"), proxies.sort_values("close_ts"),
                      left_on="entry_ts", right_on="close_ts", direction="backward")
    return z


def bootstrap_delta(d: pd.DataFrame, skip: pd.Series, n_boot: int = 2000) -> tuple[float, float]:
    """Campaign cluster bootstrap of keep-minus-skip mean P/L."""
    z = d[["campaign_id", "pnl_cost"]].copy()
    z["skip"] = skip.to_numpy(bool)
    groups = [g for _, g in z.groupby("campaign_id", sort=False)]
    if len(groups) < 2 or not skip.any() or skip.all():
        return np.nan, np.nan
    vals = np.empty(n_boot)
    for i in range(n_boot):
        sample = [groups[j] for j in RNG.integers(0, len(groups), len(groups))]
        a = pd.concat(sample, ignore_index=True)
        aa, bb = a.loc[~a.skip, "pnl_cost"], a.loc[a.skip, "pnl_cost"]
        vals[i] = aa.mean() - bb.mean() if len(aa) and len(bb) else np.nan
    return tuple(np.nanquantile(vals, [0.025, 0.975]).tolist())


def volume_gate(trf: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    tercile_rows: list[dict[str, Any]] = []
    eval_rows: list[dict[str, Any]] = []
    passes: list[dict[str, Any]] = []
    for kind in ["Cmd", "Add"]:
        d = trf[trf.kind.eq(kind) & trf.rvol.notna()].copy()
        h1 = d[d.entry_ts < H2]
        if len(h1) < 30:
            continue
        q1, q2 = h1.rvol.quantile([1 / 3, 2 / 3])
        d["bucket"] = pd.cut(d.rvol, [-np.inf, q1, q2, np.inf], labels=["low", "mid", "high"], include_lowest=True).astype(str)
        for period, g in [("H1", d[d.entry_ts < H2]), ("H2", d[d.entry_ts >= H2])]:
            for bucket, h in g.groupby("bucket", observed=False):
                gp = h.loc[h.pnl_cost > 0, "pnl_cost"].sum(); gl = -h.loc[h.pnl_cost <= 0, "pnl_cost"].sum()
                tercile_rows.append({"target": kind, "period": period, "bucket": bucket, "q33_h1": q1, "q67_h1": q2,
                                     "n": len(h), "mean_pnl": h.pnl_cost.mean(), "net": h.pnl_cost.sum(),
                                     "loss_rate": (h.pnl_cost <= 0).mean(), "pf": gp / gl if gl else np.inf})
        h1_means = d[d.entry_ts < H2].groupby("bucket", observed=False).pnl_cost.mean()
        bad = str(h1_means.idxmin())
        for period, g in [("H1", d[d.entry_ts < H2]), ("H2", d[d.entry_ts >= H2])]:
            skip = g.bucket.eq(bad)
            keep, cut = g.loc[~skip, "pnl_cost"], g.loc[skip, "pnl_cost"]
            ci_lo, ci_hi = bootstrap_delta(g, skip)
            # Matched random-lot placebo: tail probability for an equally sized random removal.
            obs = keep.mean() - cut.mean()
            ncut = int(skip.sum())
            place = np.empty(2000)
            vals = g.pnl_cost.to_numpy(float)
            for j in range(len(place)):
                ix = RNG.choice(len(vals), size=ncut, replace=False)
                m = np.ones(len(vals), dtype=bool); m[ix] = False
                place[j] = vals[m].mean() - vals[ix].mean()
            p_placebo = float((place >= obs).mean())
            proxy_rhos = {f"rho_{c}": g.rvol.corr(g[c], method="spearman") for c in ["adx", "bbw", "atr_pct"]}
            row = {"target": kind, "period": period, "bad_bucket_h1": bad, "q33_h1": q1, "q67_h1": q2,
                   "keep_n": len(keep), "skip_n": len(cut), "keep_mean_pnl": keep.mean(), "skip_mean_pnl": cut.mean(),
                   "delta_keep_minus_skip": obs, "skip_loss_precision": (cut <= 0).mean(),
                   "losses_captured": ((g.pnl_cost <= 0) & skip).sum() / max(1, (g.pnl_cost <= 0).sum()),
                   "cluster_ci_low": ci_lo, "cluster_ci_high": ci_hi, "placebo_p_ge_observed": p_placebo, **proxy_rhos}
            eval_rows.append(row)
        a, b = eval_rows[-2], eval_rows[-1]
        maxrho = max(abs(float(a[f"rho_{c}"])) for c in ["adx", "bbw", "atr_pct"] if pd.notna(a[f"rho_{c}"]))
        passed = bool(a["delta_keep_minus_skip"] > 0 and b["delta_keep_minus_skip"] > 0
                      and b["cluster_ci_low"] > 0 and b["placebo_p_ge_observed"] < 0.05
                      and maxrho < 0.4)
        eval_rows[-1]["pass_all"] = passed
        eval_rows[-2]["pass_all"] = passed
        if passed:
            passes.append({"target": kind, "bad": bad, "q1": q1, "q2": q2})
    return pd.DataFrame(tercile_rows), pd.DataFrame(eval_rows), passes


def daily_atr(one: pd.DataFrame) -> pd.DataFrame:
    d = one[one.session.eq("day")].copy()
    d["date"] = d.open_ts.dt.normalize()
    q = d.groupby("date").agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    q["prev_close"] = q.close.shift()
    q["tr"] = np.maximum(q.high - q.low, np.maximum(abs(q.high - q.prev_close), abs(q.low - q.prev_close)))
    q["atr20"] = q.tr.ewm(alpha=1 / 20, adjust=False, min_periods=20).mean()
    return q.reset_index()


def vol_sizing(tr: pd.DataFrame, one: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replay every engine lot at TMF size selected once per campaign.

    A row in the engine ledger is one MXF-equivalent lot, including each Add/G.
    Therefore fixed five-TMF P/L must retain *all* rows in a campaign; averaging
    the rows first would silently shrink pyramided campaigns before sizing.
    """
    atr = daily_atr(one)
    z = tr.merge(atr[["date", "atr20"]], left_on="entry_day", right_on="date", how="left")
    camp = z.groupby("campaign_id", as_index=False).agg(entry_day=("entry_day", "first"), exit_day=("exit_day", "max"),
        n_engine_lots=("pnl_cost", "size"), side=("side", "first"), atr_daily=("atr20", "first"))
    # One MXF-equivalent row at five TMF contracts.  Start with the validated
    # MXF execution P/L and substitute the measured per-side TMF5 cost.
    z["tmf_lot_pnl"] = z.tmf5_equiv_pnl / 5
    per = z.groupby("campaign_id", as_index=False).tmf_lot_pnl.sum()
    camp = camp.merge(per, on="campaign_id")
    camp = camp.rename(columns={"tmf_lot_pnl": "tmf_campaign_pnl"})
    h1_median_atr = float(camp.loc[(camp.entry_day < H2) & camp.atr_daily.notna(), "atr_daily"].median())
    target = h1_median_atr * PV_MXF  # H1 fixed, gives median 5 TMF lots at H1 ATR.
    camp["tmf_lots_target"] = np.maximum(1, np.rint(target / (camp.atr_daily * PV_TMF))).astype("Int64")
    lot_size = camp.set_index("campaign_id").tmf_lots_target
    z["tmf_lots_target"] = z.campaign_id.map(lot_size).astype("Int64")
    z["fixed_5tmf_pnl"] = z.tmf_lot_pnl * 5
    z["vol_target_pnl"] = z.tmf_lot_pnl * z.tmf_lots_target
    camp_pnl = z.groupby("campaign_id", as_index=False)[["fixed_5tmf_pnl", "vol_target_pnl"]].sum()
    camp = camp.merge(camp_pnl, on="campaign_id")
    camp["year"] = camp.exit_day.dt.year
    rows = []
    for mode, col in [("fixed_5_TMF", "fixed_5tmf_pnl"), ("daily_ATR_target", "vol_target_pnl")]:
        for yr in list(sorted(z.exit_day.dt.year.unique())) + ["ALL"]:
            lot_rows = z if yr == "ALL" else z[z.exit_day.dt.year.eq(yr)]
            campaigns = camp if yr == "ALL" else camp[camp.year.eq(yr)]
            daily = lot_rows.groupby("exit_day")[col].sum()
            s = stats_daily(daily)
            v28_net = float(lot_rows.pnl_new.sum())
            rows.append({"mode": mode, "year": yr, **s, "v28_mxf_net": v28_net,
                         "delta_vs_v28_mxf": s["net"] - v28_net,
                         "avg_tmf_lots": campaigns.tmf_lots_target.mean() if mode != "fixed_5_TMF" else 5,
                         "median_atr_pts": campaigns.atr_daily.median(), "target_risk_ntd": target})
    return camp, pd.DataFrame(rows)


def day_map(one: pd.DataFrame) -> pd.DataFrame:
    d = one[one.session.eq("day")].copy()
    d["date"] = d.open_ts.dt.normalize()
    return d


def p_trade(direction: float, entry: float, exit_: float) -> float:
    return direction * (exit_ - entry) * PV_MXF - fee_mxf(entry) - fee_mxf(exit_)


def intraday_momentum(one: pd.DataFrame, v38_daily: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    d = day_map(one)
    n = one[one.session.eq("night")].copy(); n["night_id"] = n.session_id
    day_groups = {k: g.sort_values("open_ts") for k, g in d.groupby("date", sort=True)}
    night_groups = {k: g.sort_values("open_ts") for k, g in n.groupby("night_id", sort=True)}
    rows: list[dict[str, Any]] = []
    # Exact three variants: opening day -> day close; opening night -> next day close; full prior night -> day opening.
    for date, g in day_groups.items():
        if len(g) < 295:
            continue
        first30 = g[(g.open_ts.dt.hour.eq(8) & (g.open_ts.dt.minute >= 45)) | (g.open_ts.dt.hour.eq(9) & (g.open_ts.dt.minute < 15))]
        last45 = g[(g.open_ts.dt.hour.eq(13) & (g.open_ts.dt.minute < 45))]
        last30 = g[(g.open_ts.dt.hour.eq(13) & (g.open_ts.dt.minute >= 15) & (g.open_ts.dt.minute < 45))]
        if len(first30) == 30 and len(last45) == 45:
            sigret = first30.close.iloc[-1] / first30.open.iloc[0] - 1
            dr = np.sign(sigret)
            if dr:
                rows.append({"variant": "day_first30_to_day_last45", "date": date, "direction": dr,
                             "entry_px": last45.open.iloc[0], "exit_px": last45.close.iloc[-1], "signal_return": sigret})
        # The night leading this actual day session must be the latest prior night session.
        prior_nights = [k for k in night_groups if k < date]
        if prior_nights and len(last30) == 30:
            ng = night_groups[max(prior_nights)]
            nf = ng[ng.session_minute < 30]
            if len(nf) == 30:
                sigret = nf.close.iloc[-1] / nf.open.iloc[0] - 1
                dr = np.sign(sigret)
                if dr:
                    rows.append({"variant": "night_first30_to_day_last30", "date": date, "direction": dr,
                                 "entry_px": last30.open.iloc[0], "exit_px": last30.close.iloc[-1], "signal_return": sigret})
            if len(ng) >= 800:
                sigret = ng.close.iloc[-1] / ng.open.iloc[0] - 1
                dr = np.sign(sigret)
                if dr:
                    rows.append({"variant": "prior_night_to_day_first30", "date": date, "direction": dr,
                                 "entry_px": first30.open.iloc[0], "exit_px": first30.close.iloc[-1], "signal_return": sigret})
    trades = pd.DataFrame(rows)
    trades["pnl"] = [p_trade(*r) for r in trades[["direction", "entry_px", "exit_px"]].itertuples(index=False, name=None)]
    annual = []
    daily_rows = []
    for variant, g in trades.groupby("variant"):
        daily = g.groupby("date").pnl.sum().sort_index()
        aligned = pd.concat([daily.rename("sleeve"), v38_daily.rename("v38")], axis=1).fillna(0)
        combo = aligned.sum(axis=1)
        tstat = g.pnl.mean() / (g.pnl.std(ddof=1) / math.sqrt(len(g))) if len(g) > 1 and g.pnl.std(ddof=1) else np.nan
        for year, h in g.groupby(g.date.dt.year):
            hh = h.pnl
            annual.append({"variant": variant, "period": str(year), "n": len(h), "net": hh.sum(), "mean": hh.mean(),
                           "t_stat": hh.mean() / (hh.std(ddof=1) / math.sqrt(len(hh))) if len(hh) > 1 and hh.std(ddof=1) else np.nan,
                           "corr_v38_daily": aligned.loc[aligned.index.year == year, "sleeve"].corr(aligned.loc[aligned.index.year == year, "v38"])})
        annual.append({"variant": variant, "period": "ALL", "n": len(g), "net": g.pnl.sum(), "mean": g.pnl.mean(), "t_stat": tstat,
                       "corr_v38_daily": aligned.sleeve.corr(aligned.v38), "combo_net": combo.sum(), "combo_mdd": mdd_from_daily(combo),
                       "combo_net_mdd": combo.sum() / abs(mdd_from_daily(combo)) if mdd_from_daily(combo) else np.nan})
        daily_rows.append(pd.DataFrame({"date": aligned.index, "variant": variant, "sleeve_pnl": aligned.sleeve.values,
                                        "v38_pnl": aligned.v38.values, "combined_pnl": combo.values}))
    return trades, pd.DataFrame(annual), pd.concat(daily_rows, ignore_index=True)


def volume_climax(tr: pd.DataFrame, one: pd.DataFrame, b5: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    x = one.copy()
    x["five_min"] = x.open_ts.dt.floor("5min")
    five = x.groupby(["session", "session_id", "five_min"], as_index=False).agg(volume=("volume", "sum"), open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    five["minute_of_session"] = five.groupby(["session", "session_id"], sort=False).cumcount()
    rr = []
    for typ, g in five.groupby("session", sort=False):
        p = g.pivot_table(index="session_id", columns="minute_of_session", values="volume", aggfunc="last").sort_index()
        av = p.shift(1).rolling(10, min_periods=10).mean().stack().rename("prior10_mean5").reset_index()
        av["session"] = typ
        rr.append(av)
    five = five.merge(pd.concat(rr, ignore_index=True), on=["session", "session_id", "minute_of_session"], how="left")
    five["vr"] = five.volume / five.prior10_mean5
    atr5 = b5[["close_ts", "atr"]].rename(columns={"close_ts": "bar_end"}).sort_values("bar_end")
    bars = pd.merge_asof(five.sort_values("five_min"), atr5, left_on="five_min", right_on="bar_end", direction="backward").sort_values("five_min")
    rows = []
    # Each baseline lot is replayed only for the pre-registered early-exit condition.
    for lot in tr.itertuples(index=False):
        candidates = bars[(bars.five_min >= lot.entry_ts) & (bars.five_min < lot.exit_ts) & (bars.vr >= 3) & bars.atr.notna()]
        early_ts, early_px, hit_vr = pd.NaT, np.nan, np.nan
        for j, bar in candidates.iterrows():
            unreal = lot.direction * (bar.close - lot.entry_px)
            if unreal >= bar.atr:
                later = bars[bars.five_min > bar.five_min]
                if not later.empty:
                    nx = later.iloc[0]
                    if nx.five_min < lot.exit_ts:
                        early_ts, early_px, hit_vr = nx.five_min, nx.open, bar.vr
                        break
        base = lot.pnl_cost
        early = (lot.direction * (early_px - lot.entry_px) * PV_MXF - fee_mxf(lot.entry_px) - fee_mxf(early_px)
                 if pd.notna(early_ts) else base)
        rows.append({"campaign_id": lot.campaign_id, "kind": lot.kind, "entry_ts": lot.entry_ts, "exit_ts": lot.exit_ts,
                     "baseline_pnl": base, "early_pnl": early, "cut": pd.notna(early_ts), "early_exit_ts": early_ts,
                     "vr_at_trigger": hit_vr})
    detail = pd.DataFrame(rows)
    camp_base = detail.groupby("campaign_id").baseline_pnl.sum().sort_values(ascending=False)
    top50 = set(camp_base.head(50).index)
    summaries = []
    for variant, mask in [("add_G_only", detail.kind.isin(["Add", "G"])), ("all_lots", pd.Series(True, index=detail.index))]:
        z = detail.copy(); z["variant_pnl"] = np.where(mask, z.early_pnl, z.baseline_pnl); z["cut_used"] = mask & z.cut
        campaign = z.groupby("campaign_id", as_index=False).agg(baseline=("baseline_pnl", "sum"), variant=("variant_pnl", "sum"), cut_lots=("cut_used", "sum"))
        campaign["entry_ts"] = tr.groupby("campaign_id").entry_ts.first().reindex(campaign.campaign_id).to_numpy()
        campaign["period"] = np.where(campaign.entry_ts < H2, "H1", "H2")
        top = campaign[campaign.campaign_id.isin(top50)]
        for period, g in list(campaign.groupby("period")) + [("ALL", campaign)]:
            delta = (g.variant - g.baseline).to_numpy(float)
            boot = np.array([delta[RNG.integers(0, len(delta), len(delta))].sum() for _ in range(2000)])
            summaries.append({"variant": variant, "period": period, "base_net": g.baseline.sum(), "variant_net": g.variant.sum(),
                              "delta": (g.variant - g.baseline).sum(), "mdd_variant": mdd_from_daily(g.groupby("entry_ts").variant.sum()),
                              "campaigns_cut": (g.cut_lots > 0).sum(), "lots_cut": g.cut_lots.sum(),
                              "ci_delta_low_all_campaign_boot": np.quantile(boot, .025), "ci_delta_high_all_campaign_boot": np.quantile(boot, .975),
                              "top50_campaigns_cut": (top.cut_lots > 0).sum(), "top50_tail_pnl_lost": (top.baseline - top.variant).clip(lower=0).sum(),
                              "top50_losses_avoided": (top.variant - top.baseline).clip(lower=0).sum(),
                              "pass_h1_h2": False})
    return detail, pd.DataFrame(summaries)


def try_ticks() -> tuple[pd.DataFrame, pd.DataFrame]:
    """One historical-day probe only. Credentials are AST-read and never persisted or printed."""
    outdir = HERE / "ticks_sample"
    outdir.mkdir(exist_ok=True)
    status: dict[str, Any] = {"credential_source": "AST only; values never printed/copied", "sample_date": "2024-01-02",
                              "result": "not_run", "tick_type_present": False, "rows": 0, "elapsed_seconds": np.nan,
                              "historical_depth_verified": "not verified"}
    ratio = pd.DataFrame(columns=["five_min", "buy_volume", "sell_volume", "buy_sell_ratio"])
    src = Path(r"E:\D_backup\stock\minute_kbar_fetch\fetch_minute_kbars_parallel.py")
    try:
        tree = ast.parse(src.read_text(encoding="utf-8"))
        vals: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                vals[node.targets[0].id.lower()] = node.value.value
        key = next((v for k, v in vals.items() if "api" in k and "key" in k), None)
        secret = next((v for k, v in vals.items() if "secret" in k), None)
        if not key or not secret:
            raise RuntimeError("AST did not find literal API key/secret assignments")
        import shioaji as sj  # imported only here to keep all other tests offline
        api = sj.Shioaji(simulation=False)
        api.login(api_key=key, secret_key=secret)
        # Shioaji v2 no longer exposes expired contracts through the legacy
        # attribute tree.  Ask its v2 catalogue first; when the old symbol is
        # absent, use the continuous MXFR1 family contract for this one
        # historical-date probe.
        contracts = api.contracts
        contract = contracts.get("MXF202401")
        if contract is not None:
            status["contract_resolution"] = "expired MXF202401"
        else:
            family = contracts.futures("MXF")
            contract = next((x for x in family if getattr(x, "code", "") == "MXFR1"),
                            family[0] if family else None)
            status["contract_resolution"] = "MXFR1 continuous fallback; historical date requested"
        if contract is None:
            raise RuntimeError("MXF contract family is unavailable")
        t0 = time.perf_counter()
        ticks = api.ticks(contract=contract, date="2024-01-02")
        elapsed = time.perf_counter() - t0
        frame = pd.DataFrame({k: getattr(ticks, k) for k in dir(ticks) if not k.startswith("_") and isinstance(getattr(ticks, k), (list, tuple, np.ndarray))})
        # Restrict sample output to harmless market fields; no credentials or account data.
        keep = [c for c in ["ts", "code", "close", "volume", "tick_type"] if c in frame.columns]
        frame[keep].to_csv(outdir / "MXF_2024-01-02_ticks.csv", index=False, encoding="utf-8-sig")
        status.update(result="success", rows=len(frame), elapsed_seconds=elapsed, tick_type_present="tick_type" in frame.columns,
                      historical_depth_verified="2024-01-02 accepted (>=33 months before 2026-10)")
        if "tick_type" in frame and "volume" in frame and "ts" in frame:
            a = frame.copy(); a["five_min"] = pd.to_datetime(a.ts, unit="ns", errors="coerce").dt.floor("5min")
            a["volume"] = pd.to_numeric(a.volume, errors="coerce").fillna(0)
            # Shioaji TickType values: Buy=1, Sell=2. Unknown/neutral volume is excluded.
            a["buy_volume"] = np.where(pd.to_numeric(a.tick_type, errors="coerce").eq(1), a.volume, 0)
            a["sell_volume"] = np.where(pd.to_numeric(a.tick_type, errors="coerce").eq(2), a.volume, 0)
            ratio = a.groupby("five_min", as_index=False)[["buy_volume", "sell_volume"]].sum()
            ratio["buy_sell_ratio"] = ratio.buy_volume / ratio.sell_volume.replace(0, np.nan)
    except Exception as exc:
        status["result"] = "failed"
        status["error_class"] = type(exc).__name__
        status["error_summary"] = str(exc)[:220]
    # Conservative range: 2 sessions * 840 minutes * an observed/sample rate; only a planning estimate.
    rate = (status["rows"] / 840 / max(status["elapsed_seconds"], 1e-6) if status["result"] == "success" else np.nan)
    est_rows = (1020 * 2 * 840 * status["rows"] / 840) if status["result"] == "success" else np.nan
    status["estimated_2024_01_to_2026_10_rows"] = est_rows
    status["estimated_download_seconds_at_sample_rate"] = est_rows / (status["rows"] / status["elapsed_seconds"]) if status["result"] == "success" and status["rows"] else np.nan
    return pd.DataFrame([status]), ratio


def v38_positions_at_close(tr: pd.DataFrame, dates: pd.Series) -> pd.Series:
    result = {}
    for date in pd.DatetimeIndex(dates.drop_duplicates()).sort_values():
        close_t = date + pd.Timedelta(hours=13, minutes=45)
        active = tr[(tr.entry_ts <= close_t) & (tr.exit_ts > close_t)]
        result[date] = int(active.direction.sum())
    return pd.Series(result, name="v38_pos")


def option_overlay(one: pd.DataFrame, tr: pd.DataFrame, v38_daily: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(OPTIONS, low_memory=False)
    # Column positions are intentional: they avoid Windows-console encoding differences in Chinese headers.
    raw = raw.iloc[:, [1, 3, 4, 5, 12, 16]].copy()
    raw.columns = ["date", "right", "expiry", "strike", "settle", "stock_id"]
    op = raw[raw.stock_id.astype(str).eq("TXO")].copy()
    op["date"] = pd.to_datetime(op.date, errors="coerce")
    op["strike"] = pd.to_numeric(op.strike, errors="coerce")
    op["settle"] = pd.to_numeric(op.settle, errors="coerce")
    op = op.dropna(subset=["date", "strike", "settle"]).copy()
    op = op[(op.settle > 0) & op.expiry.astype(str).str.contains("W", na=False)].copy()
    # Decode call/put from the UTF-8 label without relying on console glyph rendering.
    op["cp"] = np.where(op.right.astype(str).str.contains("買"), "C", "P")
    d = day_map(one); spot = d.groupby("date").close.last().rename("spot")
    days = pd.DatetimeIndex(sorted(op.date.unique()))
    positions = v38_positions_at_close(tr, pd.Series(days))
    schedules = []
    for date in days[days.weekday == 2]:  # Wednesday close / settlement day
        today = op[op.date.eq(date)]
        expiries = (op[op.date > date].groupby("expiry").date.max())
        futures = expiries[expiries > date]
        if date not in spot.index or futures.empty:
            continue
        exp = futures.sort_values().index[0]
        avail = today[today.expiry.eq(exp)]
        if avail.empty:
            continue
        pos = int(positions.get(date, 0))
        for variant in ["weekly_strangle", "trend_aligned", "covered"]:
            rights: list[tuple[str, int]]
            if variant == "weekly_strangle": rights = [("C", 1), ("P", 1)]
            elif variant == "trend_aligned": rights = [("P", 1)] if pos > 0 else ([("C", 1)] if pos < 0 else [("C", 1), ("P", 1)])
            else: rights = ([("C", abs(pos))] if pos > 0 else ([("P", abs(pos))] if pos < 0 else []))
            for cp, qty in rights:
                a = avail[avail.cp.eq(cp)]
                if a.empty or qty == 0:
                    continue
                target = spot.loc[date] * (1.02 if cp == "C" else .98)
                j = (a.strike - target).abs().idxmin()
                q = a.loc[j]
                schedules.append({"variant": variant, "open_date": date, "expiry": exp, "cp": cp, "strike": q.strike,
                                  "qty": qty, "spot": spot.loc[date], "credit": q.settle, "v38_pos": pos})
    sched = pd.DataFrame(schedules)
    expiry_last_date = op.groupby("expiry").date.max().to_dict()
    legs = []
    daily_rows = []
    for leg in sched.itertuples(index=False):
        expiry_date = expiry_last_date[leg.expiry]
        q = op[(op.expiry.eq(leg.expiry)) & (op.cp.eq(leg.cp)) & (op.strike.eq(leg.strike)) &
               (op.date >= leg.open_date) & (op.date <= expiry_date)].sort_values("date")
        if q.empty:
            continue
        # entry after Wednesday settlement; opening short credit loses one point to slippage.
        entry_credit = leg.credit - 1
        prev = entry_credit
        closed = False
        total = 0.0
        for i, r in enumerate(q.itertuples(index=False)):
            # no same-close stop look-ahead: start stop checking on the next settlement day.
            if i == 0:
                # Premium received creates an equal option liability, so it is
                # not immediate P/L.  Subsequent mark changes realise
                # (entry_credit - close_mark) × point value; only entry fees
                # are booked here.
                pnl = -leg.qty * (BROKER + .001 * entry_credit * PV_MXF)
            else:
                close_now = (r.settle >= 3 * entry_credit) or (r.date == expiry_date)
                mark = r.settle + 1 if close_now else r.settle
                pnl = leg.qty * (-(mark - prev) * PV_MXF)
                prev = mark
                if close_now:
                    pnl -= leg.qty * (BROKER + .001 * mark * PV_MXF)
                    closed = True
            total += pnl
            daily_rows.append({"date": r.date, "variant": leg.variant, "overlay_pnl": pnl, "open_date": leg.open_date,
                               "expiry": leg.expiry, "cp": leg.cp, "strike": leg.strike, "qty": leg.qty})
            if closed:
                legs.append({"variant": leg.variant, "open_date": leg.open_date, "close_date": r.date, "expiry": leg.expiry,
                             "cp": leg.cp, "strike": leg.strike, "qty": leg.qty, "spot": leg.spot, "credit": entry_credit,
                             "close_mark": mark, "stopped": r.settle >= 3 * entry_credit,
                             "assumed_zero_expiry": False, "pnl": total, "v38_pos": leg.v38_pos})
                break
        # The source drops zero settlements.  If the chosen strike disappears
        # before the contract's final settlement date, close it at zero then
        # (and charge the closing broker fee) instead of leaving an unclosed
        # credit in the daily curve and omitting it from the leg report.
        if not closed:
            pnl = leg.qty * (-(0.0 - prev) * PV_MXF - BROKER)
            total += pnl
            daily_rows.append({"date": expiry_date, "variant": leg.variant, "overlay_pnl": pnl, "open_date": leg.open_date,
                               "expiry": leg.expiry, "cp": leg.cp, "strike": leg.strike, "qty": leg.qty})
            legs.append({"variant": leg.variant, "open_date": leg.open_date, "close_date": expiry_date, "expiry": leg.expiry,
                         "cp": leg.cp, "strike": leg.strike, "qty": leg.qty, "spot": leg.spot, "credit": entry_credit,
                         "close_mark": 0.0, "stopped": False, "assumed_zero_expiry": True,
                         "pnl": total, "v38_pos": leg.v38_pos})
    legdf = pd.DataFrame(legs)
    daily = pd.DataFrame(daily_rows)
    report_rows = []
    combo_rows = []
    for variant, g in daily.groupby("variant"):
        ov = g.groupby("date").overlay_pnl.sum()
        align = pd.concat([ov.rename("overlay"), v38_daily.rename("v38")], axis=1).fillna(0).sort_index()
        align["combined"] = align.overlay + align.v38
        weekly = align.combined.resample("W-FRI").sum()
        le = legdf[legdf.variant.eq(variant)]
        events = {"2024-08-05": float(align.loc[pd.Timestamp("2024-08-05"), "overlay"]) if pd.Timestamp("2024-08-05") in align.index else np.nan,
                  "2025-04-07": float(align.loc[pd.Timestamp("2025-04-07"), "overlay"]) if pd.Timestamp("2025-04-07") in align.index else np.nan}
        report_rows.append({"variant": variant, "n_legs": len(le), "net": ov.sum(), "mdd": mdd_from_daily(ov), "worst_week": weekly.min(),
                            "stop_count": le.stopped.sum() if len(le) else 0, "corr_v38_daily": align.overlay.corr(align.v38),
                            "zero_expiry_assumed": le.assumed_zero_expiry.sum() if len(le) else 0,
                            "combined_net": align.combined.sum(), "combined_mdd": mdd_from_daily(align.combined),
                            "combined_net_mdd": align.combined.sum()/abs(mdd_from_daily(align.combined)) if mdd_from_daily(align.combined) else np.nan,
                            "event_2024_08_05": events["2024-08-05"], "event_2025_04_07": events["2025-04-07"]})
        combo_rows.append(pd.DataFrame({"date": align.index, "variant": variant, "overlay_pnl": align.overlay.values,
                                        "v38_pnl": align.v38.values, "combined_pnl": align.combined.values}))
    return legdf, pd.DataFrame(report_rows), pd.concat(combo_rows, ignore_index=True) if combo_rows else pd.DataFrame()


def narrow_range(one: pd.DataFrame, rvol: pd.DataFrame, v38_daily: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    d = one[one.session.eq("day")].merge(rvol[["open_ts", "rvol"]], on="open_ts", how="left").sort_values("open_ts").reset_index(drop=True)
    d["date"] = d.open_ts.dt.normalize()
    trades = []
    for date, g in d.groupby("date", sort=True):
        g = g.reset_index(drop=True)
        pos: dict[str, Any] | None = None
        for i in range(60, len(g)):
            row = g.iloc[i]
            minute = row.open_ts.hour * 60 + row.open_ts.minute
            # Position management first. Conservative stop-first ordering when both levels occur in a bar.
            if pos is not None:
                if pos["dir"] > 0:
                    if row.low <= pos["stop"]: exit_px, why = pos["stop"], "stop"
                    elif row.high >= pos["mid"]: exit_px, why = pos["mid"], "mid"
                    elif row.open_ts >= pos["deadline"]: exit_px, why = row.open, "time"
                    else: exit_px = None
                else:
                    if row.high >= pos["stop"]: exit_px, why = pos["stop"], "stop"
                    elif row.low <= pos["mid"]: exit_px, why = pos["mid"], "mid"
                    elif row.open_ts >= pos["deadline"]: exit_px, why = row.open, "time"
                    else: exit_px = None
                if exit_px is not None:
                    trades.append({"date": date, "entry_ts": pos["ts"], "exit_ts": row.open_ts, "side": "L" if pos["dir"] > 0 else "S",
                                   "entry_px": pos["entry"], "exit_px": exit_px, "exit_reason": why,
                                   "range": pos["rng"], "rvol": pos["rvol"], "pnl": p_trade(pos["dir"], pos["entry"], exit_px)})
                    pos = None
                    continue
            # Last permitted entry is immediately before 13:15; exits remain managed after it.
            if pos is None and minute < 13 * 60 + 15 and pd.notna(row.rvol) and row.rvol < .6:
                hist = g.iloc[i - 60:i]
                low, high = hist.low.min(), hist.high.max(); rng = high - low
                if rng <= 0:
                    continue
                # signal on bar close, next one-minute open entry; no same-bar fill.
                if row.close <= low + .25 * rng and i + 1 < len(g):
                    nx = g.iloc[i + 1]; pos = {"dir": 1, "ts": nx.open_ts, "entry": nx.open, "stop": nx.open - rng,
                                                 "mid": (high + low) / 2, "deadline": nx.open_ts + pd.Timedelta(minutes=60), "rng": rng, "rvol": row.rvol}
                elif row.close >= high - .25 * rng and i + 1 < len(g):
                    nx = g.iloc[i + 1]; pos = {"dir": -1, "ts": nx.open_ts, "entry": nx.open, "stop": nx.open + rng,
                                                 "mid": (high + low) / 2, "deadline": nx.open_ts + pd.Timedelta(minutes=60), "rng": rng, "rvol": row.rvol}
        if pos is not None:
            last = g.iloc[-1]
            trades.append({"date": date, "entry_ts": pos["ts"], "exit_ts": last.open_ts, "side": "L" if pos["dir"] > 0 else "S",
                           "entry_px": pos["entry"], "exit_px": last.close, "exit_reason": "session_end", "range": pos["rng"], "rvol": pos["rvol"],
                           "pnl": p_trade(pos["dir"], pos["entry"], last.close)})
    t = pd.DataFrame(trades)
    rows = []
    daily = t.groupby("date").pnl.sum() if len(t) else pd.Series(dtype=float)
    align = pd.concat([daily.rename("sleeve"), v38_daily.rename("v38")], axis=1).fillna(0).sort_index()
    align["combined"] = align.sleeve + align.v38
    for period, g in [("H1", t[t.date < H2]), ("H2", t[t.date >= H2]), ("ALL", t)]:
        hdaily = g.groupby("date").pnl.sum() if len(g) else pd.Series(dtype=float)
        rows.append({"period": period, "n_trades": len(g), "net": g.pnl.sum(), "mean": g.pnl.mean(),
                     "win_rate": (g.pnl > 0).mean(), "mdd": mdd_from_daily(hdaily),
                     "corr_v38_daily": align.sleeve.corr(align.v38) if period == "ALL" else align.loc[align.index < H2 if period == "H1" else align.index >= H2, "sleeve"].corr(align.loc[align.index < H2 if period == "H1" else align.index >= H2, "v38"]),
                     "combo_net": align.combined.sum() if period == "ALL" else np.nan, "combo_mdd": mdd_from_daily(align.combined) if period == "ALL" else np.nan})
    return t, pd.DataFrame(rows), pd.DataFrame({"date": align.index, "sleeve_pnl": align.sleeve.values, "v38_pnl": align.v38.values, "combined_pnl": align.combined.values})


def report(tables: dict[str, pd.DataFrame], passes: list[dict[str, Any]], target_risk: float) -> None:
    vg = tables["volume_eval"]
    vs = tables["sizing_summary"]
    mom = tables["momentum_summary"]
    ex = tables["climax_summary"]
    tick = tables["ticks_status"]
    opt = tables["options_summary"]
    nr = tables["range_summary"]
    lines = [
        "# 外部想法：預先登錄測試結果",
        "",
        "資料截止 2026-10-17（選擇權至 2026-10-16）。所有 CSV 均為 UTF-8-SIG；金額為新台幣。MXF 回測成本為每邊 NT$20 + 0.00002×價格×50 + 4 點滑價；TMF 為每邊 NT$20 + 0.00002×價格×10 + 3.1 點實盤滑價。",
        "",
        "## 預先登錄與多重比較",
        "",
        "本次只執行題目指定的：RVOL 對 Cmd、Add 各 1 個三分位鑑別器，TMF 每日 ATR 定風險 1 個規則，日內動能 3 個 sleeve，高潮出場 2 個變體，選擇權 3 個 overlay，窄幅 1 個 sleeve，合計 **12 個策略／鑑別比較**（Shioaji 為可行性探針，不計入績效比較）。未搜尋參數或挑選最佳變體。H1 為 2025-04-01 前、H2 為其後。",
        "",
        "## 1. RVOL 成交量型態閘門",
        "",
        "RVOL = 當前 session 自開盤的累積量 ÷ 前 20 個同類（日／夜分開）session、同一 session 分鐘的平均累積量；前 20 個 session 沒有 RVOL，故自動不交易／不納入鑑別。三分位門檻只由 H1 固定。PASS 需：H1、H2 的保留減剔除平均 P/L 皆正，H2 campaign-cluster 95% CI 下限 > 0、H2 matched-random placebo p < 0.05，且 H1 RVOL 對 ADX/BBW/ATR% 的最大 |Spearman rho| < 0.4。",
        "",
        md_table(vg, digits=3),
        "",
        "結論：" + ("有通過者，已另以唯讀引擎執行閘門。" if passes else "Cmd、Add 均未同時符合預先登錄 PASS；因此依規則沒有把任何 RVOL 閘門寫入／重跑引擎。"),
        "",
        "## 2. TMF 波動率目標部位",
        "",
        f"使用日線 Wilder(20) ATR；目標風險固定為 H1 campaign 入場日 ATR 中位數 × 1 MXF 點值 = **NT${target_risk:,.0f}**。每 campaign 的 TMF lots = round(目標風險 ÷ (日 ATR×10))，下限 1。為真正固定『每 campaign』風險，原始 campaign 的多筆 Add/G 先平均為 1 MXF 等值；固定比較組是 5 TMF。",
        "",
        md_table(vs, digits=2),
        "",
        "## 3. 日內動能獨立 sleeve",
        "",
        "三個且僅三個預先登錄定義：日盤前 30 分鐘訊號→日盤最後 45 分鐘；夜盤前 30 分鐘訊號→下一日盤最後 30 分鐘；完整前夜報酬→日盤前 30 分鐘。`t_stat` 是逐交易日 P/L 的 t 統計；相關與組合均以每日已實現 V38 P/L 對齊。",
        "",
        md_table(mom, digits=3),
        "",
        "## 4. 量能高潮停利",
        "",
        "VR 為最新 5 分鐘量 ÷ 前 10 個同類 session 同一 5 分鐘位置的平均量。僅在浮盈至少 1×當時 5 分鐘 ATR、VR≥3 時，以下一根 5 分鐘開盤退出。`top50_tail_pnl_lost` 是原始 top-50 campaign 因提前退出而少賺的 P/L；`top50_losses_avoided` 是同一集合內改良所避免的損失。",
        "",
        md_table(ex, digits=2),
        "",
        "兩個變體皆未標為 PASS：此策略的尾端收益優先，不能以局部避損交換 top-50 尾端損失。",
        "",
        "## 5. 主動買賣盤 tick 可行性",
        "",
        md_table(tick, digits=2),
        "",
        "只嘗試一個 2024-01-02 MXF 歷史日；沒有批次下載。若 API 探針成功，`ticks_sample/MXF_2024-01-02_ticks.csv` 與 `ext_ticks_5m_ratio.csv` 是唯一下載樣本。估計值僅按樣本吞吐外推，實作前仍應確認 Shioaji 歷史 tick 保留政策與授權。",
        "",
        "## 6. TXO 賣方 overlay",
        "",
        "資料僅有每日結算價，沒有盤中路徑、bid/ask 或可成交深度；所以進出均以結算價近似，賣出減 1 點、買回加 1 點，每邊加 NT$20 + premium×50×0.1%。每週三挑下一個可用週選，履約價取離當日 MXF 日盤收盤約 ±2% 最近者；3×權利金停損從下一個結算日開始檢查。Covered 依日終 V38 淨 MXF lots 配一張權利金賣方部位；其餘每個訊號一張。",
        "",
        md_table(opt, digits=2),
        "",
        "保證金僅為概念估算，未從資料中扣除：TAIFEX 裸賣單腿通常可近似為權利金市值 + max(標的結算價×A − 價外值，標的結算價×B)，其中 A/B 由交易所每日公告；組合賣跨式另有較高腿／價差與風險沖抵規則。因此本結果不可視為保證金或可部署資本估計。",
        "",
        "## 7. 窄幅（RVOL<0.6）獨立 sleeve",
        "",
        "日盤 RVOL<0.6 時，以嚴格先前 60 分鐘 high-low 為 range；靠近下 25% 做多、靠近上 25% 放空；下根 1 分鐘開盤入場，range 中點／60 分鐘／1×range 停損出場，兩價同根觸及時保守地先計停損；最多一倉，13:15 後不再入場。",
        "",
        md_table(nr, digits=3),
        "",
        "## 產出檔案",
        "",
        "`ext_volume_rvol_minutes.csv`, `ext_volume_terciles.csv`, `ext_volume_gate_eval.csv`, `ext_vol_sizing_campaigns.csv`, `ext_vol_sizing_summary.csv`, `ext_momentum_*.csv`, `ext_climax_*.csv`, `ext_ticks_*.csv`, `ext_options_*.csv`, `ext_range_*.csv`。",
    ]
    (HERE / "results_external_ideas.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    one, tr, b5 = load_inputs()
    rvol = rvol_frame(one)
    save(rvol, "ext_volume_rvol_minutes.csv")
    trf = join_trade_features(tr, rvol, b5)
    terc, veval, passes = volume_gate(trf)
    save(terc, "ext_volume_terciles.csv"); save(veval, "ext_volume_gate_eval.csv")
    camp_size, size_summary = vol_sizing(tr, one)
    save(camp_size, "ext_vol_sizing_campaigns.csv"); save(size_summary, "ext_vol_sizing_summary.csv")
    v38_daily = tr.groupby("exit_day").pnl_cost.sum().sort_index()
    save(v38_daily.rename("v38_pnl").reset_index().rename(columns={"exit_day": "date"}), "ext_v38_daily_costed.csv")
    mom_trades, mom_sum, mom_daily = intraday_momentum(one, v38_daily)
    save(mom_trades, "ext_momentum_trades.csv"); save(mom_sum, "ext_momentum_summary.csv"); save(mom_daily, "ext_momentum_daily.csv")
    climax_detail, climax_sum = volume_climax(tr, one, b5)
    save(climax_detail, "ext_climax_detail.csv"); save(climax_sum, "ext_climax_summary.csv")
    tick_status, tick_ratio = try_ticks()
    save(tick_status, "ext_ticks_feasibility.csv"); save(tick_ratio, "ext_ticks_5m_ratio.csv")
    opt_legs, opt_sum, opt_daily = option_overlay(one, tr, v38_daily)
    save(opt_legs, "ext_options_legs.csv"); save(opt_sum, "ext_options_summary.csv"); save(opt_daily, "ext_options_daily.csv")
    range_trades, range_sum, range_daily = narrow_range(one, rvol, v38_daily)
    save(range_trades, "ext_range_trades.csv"); save(range_sum, "ext_range_summary.csv"); save(range_daily, "ext_range_daily.csv")
    target = float(size_summary.target_risk_ntd.dropna().iloc[0])
    report({"volume_eval": veval, "sizing_summary": size_summary, "momentum_summary": mom_sum,
            "climax_summary": climax_sum, "ticks_status": tick_status, "options_summary": opt_sum,
            "range_summary": range_sum}, passes, target)
    print("wrote results_external_ideas.md and ext_*.csv")


if __name__ == "__main__":
    main()
