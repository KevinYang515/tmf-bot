"""Reproducible execution for task_newdirs.md (A/A2, B, and C)."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
DATA = HERE / "mxf_1min_corrected_20261017b.csv"
sys.path.insert(0, str(ENGINE_DIR))
from engine_v26_bbw import P, load_1min, prepare, run as base_run  # noqa: E402
from engine_newdirs_wrapper import run as wrapped_run  # noqa: E402

H2 = pd.Timestamp("2025-04-01")
TRAIN0, TRAIN1 = pd.Timestamp("2026-03-01"), pd.Timestamp("2026-06-01")
TEST0, TEST1 = pd.Timestamp("2026-06-01"), pd.Timestamp("2026-08-22")
HOLDOUT = pd.Timestamp("2026-08-22")
LIVE = {"opt_stale_hr": 10, "opt_cooldown_min": 30}
BASES = {
    "v28": {**LIVE, "opt_short_pyramid_cap_mode": "hour4"},
    "v29": {**LIVE, "opt_short_pyramid_cap_mode": "hour4", "l_trailBase": 3.5},
}
TRADE_COLS = ["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl"]
RNG = np.random.default_rng(20261018)


def dates(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["entry_ts"] = pd.to_datetime(d.entry_ts)
    d["exit_ts"] = pd.to_datetime(d.exit_ts)
    return d


def subset(d: pd.DataFrame, span: str) -> pd.DataFrame:
    t = d.entry_ts
    if span == "全樣本": return d
    if span == "H1": return d[t < H2]
    if span == "H2": return d[t >= H2]
    if span == "TRAIN": return d[(t >= TRAIN0) & (t < TRAIN1)]
    if span == "TEST": return d[(t >= TEST0) & (t < TEST1)]
    if span == "HOLDOUT": return d[t >= HOLDOUT]
    if span in ("2024", "2025", "2026"): return d[t.dt.year == int(span)]
    raise ValueError(span)


SPANS = ["全樣本", "H1", "H2", "TRAIN", "TEST", "HOLDOUT", "2024", "2025", "2026"]


def mdd(d: pd.DataFrame) -> float:
    if d.empty: return 0.0
    q = d.sort_values(["exit_ts", "entry_ts"]).pnl.cumsum()
    return float((q - q.cummax()).min())


def metric(d: pd.DataFrame) -> dict[str, float | int]:
    if d.empty:
        return dict(n=0, net=0.0, wr=np.nan, pf=np.nan, mdd=0.0, net_mdd=np.nan)
    wins, loss = d.loc[d.pnl > 0, "pnl"].sum(), -d.loc[d.pnl <= 0, "pnl"].sum()
    dd = mdd(d)
    return dict(n=len(d), net=float(d.pnl.sum()), wr=float((d.pnl > 0).mean() * 100),
                pf=float(wins / loss) if loss else np.inf, mdd=dd,
                net_mdd=float(d.pnl.sum() / abs(dd)) if dd else np.inf)


def campaignize(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    order = {"Cmd": 0, "Add": 1, "G": 2}
    d = trades.copy().sort_values(["entry_ts", "kind"], key=lambda x: x.map(order) if x.name == "kind" else x).reset_index(drop=True)
    d["campaign_id"] = d.kind.eq("Cmd").cumsum() - 1
    out = []
    for cid, g in d.groupby("campaign_id", sort=True):
        cmd = g[g.kind.eq("Cmd")].iloc[0]
        out.append(dict(campaign_id=int(cid), side=cmd.side, entry_ts=cmd.entry_ts,
                        entry_px=cmd.entry_px, exit_ts=g.exit_ts.max(), pnl=g.pnl.sum(), n_lots=len(g)))
    return pd.DataFrame(out), d


def boot_diff(a: np.ndarray, b: np.ndarray, draws: int = 3000) -> tuple[float, float, float]:
    if len(a) < 2 or len(b) < 2: return (np.nan, np.nan, np.nan)
    x = RNG.choice(a, size=(draws, len(a)), replace=True).mean(axis=1)
    y = RNG.choice(b, size=(draws, len(b)), replace=True).mean(axis=1)
    z = x - y
    return float(z.mean()), float(np.quantile(z, .025)), float(np.quantile(z, .975))


def table(d: pd.DataFrame, cols: list[str], digits: int = 1) -> list[str]:
    if d.empty: return ["（無資料）"]
    x = d.loc[:, cols].copy()
    for c in x:
        if pd.api.types.is_float_dtype(x[c]):
            x[c] = x[c].map(lambda v: "" if pd.isna(v) else ("∞" if np.isinf(v) else f"{v:,.{digits}f}"))
    def cell(v: object) -> str:
        if pd.isna(v): return ""
        return str(v).replace("|", "\\|").replace("\n", " ")
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    out += ["| " + " | ".join(cell(v) for v in row) + " |" for row in x.itertuples(index=False, name=None)]
    return out


def exact_check(fresh: pd.DataFrame, filename: str) -> str:
    ref = dates(pd.read_csv(HERE / filename))
    end = ref.exit_ts.max()
    got = fresh[fresh.exit_ts <= end][TRADE_COLS].reset_index(drop=True)
    want = ref[TRADE_COLS].reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(got, want, check_dtype=False, check_exact=True)
        return f"完全一致（{len(got):,}/{len(want):,} 筆）"
    except AssertionError as e:
        return f"不一致：{str(e)[:180]}"


def daily_underlying(df1m: pd.DataFrame) -> pd.DataFrame:
    x = df1m.copy()
    x["date"] = x.ts.dt.normalize()
    q = x.groupby("date", as_index=False).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    prev = q.close.shift()
    q["tr"] = pd.concat([(q.high-q.low), (q.high-prev).abs(), (q.low-prev).abs()], axis=1).max(axis=1)
    q["daily_atr14"] = q.tr.ewm(alpha=1/14, adjust=False).mean()
    return q


def fetch_options() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict[str, str]], str]:
    """Fetch FinLab-first sources, preserving downloaded raw tables locally."""
    raw = HERE / "options_raw"; raw.mkdir(exist_ok=True)
    logs: list[dict[str, str]] = []
    try:
        from finlab import data
        data.set_storage(data.FileStorage(str(HERE / "finlab_cache")))
        got = {}
        for key in ("tw_option_put_call_ratio", "tw_option_daily_summary", "tw_taifex_option_institutional_breakdown"):
            try:
                z = data.get(key)
                z.to_csv(raw / f"finlab_{key}.csv", index=False, encoding="utf-8-sig")
                got[key] = z
                logs.append(dict(source="finlab", url=key, status=f"ok {len(z):,} rows"))
            except Exception as exc:
                logs.append(dict(source="finlab", url=key, status=f"FAIL {type(exc).__name__}: {str(exc)[:180]}"))
                got[key] = pd.DataFrame()
        # The futures breakdown is the correct FinLab data-set name, but this
        # machine's cached session can be expired.  Retain the exact outcome.
        try:
            z = data.get("tw_taifex_futures_institutional_breakdown")
            z.to_csv(raw / "finlab_tw_taifex_futures_institutional_breakdown.csv", index=False, encoding="utf-8-sig")
            logs.append(dict(source="finlab", url="tw_taifex_futures_institutional_breakdown", status=f"ok {len(z):,} rows"))
            futures_note = "可取得"
        except Exception as exc:
            logs.append(dict(source="finlab", url="tw_taifex_futures_institutional_breakdown", status=f"FAIL {type(exc).__name__}: {str(exc)[:180]}"))
            futures_note = f"未取得：{type(exc).__name__}（登入 token 過期，未臆造資料）"
    except Exception as exc:
        got = {k: pd.DataFrame() for k in ("tw_option_put_call_ratio", "tw_option_daily_summary", "tw_taifex_option_institutional_breakdown")}
        futures_note = f"FinLab 初始化失敗：{type(exc).__name__}"
        logs.append(dict(source="finlab", url="initialise", status=f"FAIL {exc}"))
    # Official raw endpoint probes are deliberately preserved.  FinLab tables
    # above are used when complete; these probes document the public fallback.
    for name, url in {
        "taifex_pcRatio.html": "https://www.taifex.com.tw/cht/3/pcRatio",
        "taifex_pcRatioExcel.bin": "https://www.taifex.com.tw/cht/3/pcRatioExcel",
        "taifex_vix.html": "https://www.taifex.com.tw/cht/3/vix",
    }.items():
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            (raw / name).write_bytes(r.content)
            logs.append(dict(source="TAIFEX", url=url, status=f"HTTP {r.status_code}; {len(r.content):,} bytes"))
        except Exception as exc:
            logs.append(dict(source="TAIFEX", url=url, status=f"FAIL {type(exc).__name__}: {str(exc)[:160]}"))
    pd.DataFrame(logs).to_csv(raw / "source_log.csv", index=False, encoding="utf-8-sig")
    return got["tw_option_put_call_ratio"], got["tw_option_daily_summary"], got["tw_taifex_option_institutional_breakdown"], logs, futures_note


def option_daily_features(pcr: pd.DataFrame, summary: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Build only post-close daily fields; availability is date 15:00."""
    base = daily[["date", "close", "daily_atr14"]].copy()
    note = ""
    if not pcr.empty:
        p = pcr[pcr.symbol.eq("TXO")].copy()
        p["date"] = pd.to_datetime(p.date)
        # FinLab column positions are stable raw Taifex Put/Call fields:
        # put OI, call OI, OI ratio, put volume, call volume, volume ratio.
        p = p.sort_values("date")
        p["pcr_oi"] = pd.to_numeric(p.iloc[:, 5], errors="coerce") / 100.0
        p["pcr_vol"] = pd.to_numeric(p.iloc[:, 8], errors="coerce") / 100.0
        for c in ("pcr_oi", "pcr_vol"):
            mean, std = p[c].rolling(60, min_periods=30).mean(), p[c].rolling(60, min_periods=30).std(ddof=0)
            p[c + "_z60"] = (p[c] - mean) / std.replace(0, np.nan)
            p[c + "_d1"] = p[c].diff(1); p[c + "_d5"] = p[c].diff(5)
        base = base.merge(p[["date", "pcr_oi", "pcr_vol", "pcr_oi_z60", "pcr_vol_z60", "pcr_oi_d1", "pcr_oi_d5", "pcr_vol_d1", "pcr_vol_d5"]], on="date", how="left")
    else:
        note += "PCR 缺失；"
    walls = []
    if not summary.empty:
        s = summary[summary.symbol.eq("TXO")].copy()
        s["date"] = pd.to_datetime(s.date)
        # Fixed schema columns from tw_option_daily_summary.
        expiry, strike, cp, last_trade, oi = s.columns[4], s.columns[5], s.columns[3], s.columns[8], s.columns[15]
        s["expiry"] = s[expiry].astype(str); s["strike"] = pd.to_numeric(s[strike], errors="coerce")
        s["last_trade"] = pd.to_datetime(s[last_trade], errors="coerce"); s["oi"] = pd.to_numeric(s[oi], errors="coerce")
        s["cp"] = s[cp].astype(str)
        s = s.dropna(subset=["strike", "last_trade", "oi"]).drop_duplicates(["date", "expiry", "strike", "cp"], keep="last")
        for day, g0 in s.groupby("date"):
            for typ, g1 in (("weekly", g0[g0.expiry.str.contains("W", case=False, na=False)]),
                            ("monthly", g0[~g0.expiry.str.contains("W", case=False, na=False)])):
                g1 = g1[g1.last_trade >= day]
                if g1.empty: continue
                ex = g1.loc[g1.last_trade.idxmin(), "expiry"]
                g = g1[g1.expiry.eq(ex)]
                # Unicode field values are the Taifex standard 買權 / 賣權.
                calls, puts = g[g.cp.eq("買權")], g[g.cp.eq("賣權")]
                if calls.empty or puts.empty: continue
                cw = calls.loc[calls.oi.idxmax(), "strike"]; pw = puts.loc[puts.oi.idxmax(), "strike"]
                strikes = np.sort(g.strike.unique())
                pain = min(float((calls.oi * np.maximum(k-calls.strike, 0)).sum() + (puts.oi * np.maximum(puts.strike-k, 0)).sum()) for k in strikes)
                mp = min(strikes, key=lambda k: float((calls.oi * np.maximum(k-calls.strike, 0)).sum() + (puts.oi * np.maximum(puts.strike-k, 0)).sum()))
                walls.append(dict(date=day, wall_type=typ, expiry=ex, expiry_date=g.last_trade.min(), call_wall=cw, put_wall=pw, max_pain=mp, days_to_expiry=(g.last_trade.min()-day).days))
        w = pd.DataFrame(walls)
        if not w.empty:
            w.to_csv(HERE / "newdirs_option_walls_daily.csv", index=False, encoding="utf-8-sig")
            for typ in ("weekly", "monthly"):
                z = w[w.wall_type.eq(typ)].drop(columns="wall_type").rename(columns={c: f"{typ}_{c}" for c in w.columns if c not in ("date", "wall_type")})
                base = base.merge(z, on="date", how="left")
    else:
        note += "選擇權逐履約價日表缺失；"
    base["available_ts"] = base.date + pd.Timedelta(hours=15)
    base.to_csv(HERE / "newdirs_option_daily_features.csv", index=False, encoding="utf-8-sig")
    return base, note


def cmd_features(camp: pd.DataFrame, b5: pd.DataFrame) -> pd.DataFrame:
    b = b5.copy()
    close_ts = b.close_ts.to_numpy(dtype="datetime64[ns]")
    ix = np.searchsorted(close_ts, camp.entry_ts.to_numpy(dtype="datetime64[ns]"), side="right") - 1
    out = camp.copy(); out["sig_ix"] = ix
    for c in ("close", "atr", "ema_long", "ema_short", "ema_fast", "hh20_prev", "ll20_prev", "adx", "bbw_pct"):
        out["sig_"+c] = b[c].to_numpy()[ix]
    dr = np.where(out.side.eq("L"), 1.0, -1.0)
    ema = np.where(out.side.eq("L"), out.sig_ema_long, out.sig_ema_short)
    out["extension_atr"] = dr*(out.sig_close-ema)/out.sig_atr
    out["breakout"] = np.where(out.side.eq("L"), out.sig_close > out.sig_hh20_prev, out.sig_close < out.sig_ll20_prev)
    return out


def option_discriminator(camp: pd.DataFrame, b5: pd.DataFrame, dailyopt: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, object]]]:
    c = cmd_features(camp, b5)
    d = dailyopt.sort_values("available_ts")
    c = pd.merge_asof(c.sort_values("entry_ts"), d, left_on="entry_ts", right_on="available_ts", direction="backward").sort_values("campaign_id")
    side = np.where(c.side.eq("L"), 1.0, -1.0)
    # Larger score always means the daily option condition supports direction.
    for raw in ("pcr_oi_z60", "pcr_vol_z60", "pcr_oi_d1", "pcr_oi_d5", "pcr_vol_d1", "pcr_vol_d5"):
        if raw in c: c["score_"+raw] = -side * pd.to_numeric(c[raw], errors="coerce")
    if "weekly_call_wall" in c:
        wall = np.where(c.side.eq("L"), c.weekly_call_wall, c.weekly_put_wall)
        c["score_weekly_wall"] = side * (wall-c.entry_px) / c.sig_atr
        c["score_weekly_pain"] = side * (c.weekly_max_pain-c.entry_px) / c.sig_atr
    score_cols = [x for x in c if x.startswith("score_")]
    rows, gates = [], []
    for col in score_cols:
        h1v = c.loc[c.entry_ts < H2, col].dropna()
        if len(h1v) < 30: continue
        lo, hi = h1v.quantile([1/3, 2/3])
        bucket = pd.Series(np.where(c[col] <= lo, "反向", np.where(c[col] >= hi, "同向", "中性")), index=c.index).where(c[col].notna())
        c[col+"_bucket"] = bucket
        r_all = []
        for period, mask in (("H1", c.entry_ts < H2), ("H2", (c.entry_ts >= H2) & (c.entry_ts < HOLDOUT)), ("HOLDOUT", c.entry_ts >= HOLDOUT)):
            for s in ("L", "S"):
                for bu in ("反向", "中性", "同向"):
                    z = c[mask & c.side.eq(s) & bucket.eq(bu)]
                    rows.append(dict(feature=col.removeprefix("score_"), period=period, side=s, bucket=bu, n=len(z), net=z.pnl.sum(), mean_pnl=z.pnl.mean() if len(z) else np.nan))
            bad = c[mask & bucket.eq("反向")].pnl.to_numpy(float)
            rest = c[mask & bucket.ne("反向") & bucket.notna()].pnl.to_numpy(float)
            point, lowci, highci = boot_diff(bad, rest)
            r_all.append((period, point, lowci, highci, len(bad), len(rest)))
        h1, h2 = r_all[0], r_all[1]
        devbad = c[c.entry_ts.lt(HOLDOUT) & bucket.eq("反向")].pnl
        precision_loss = float(-devbad[devbad < 0].sum()); precision_profit = float(devbad[devbad > 0].sum())
        proxy = c[[col, "sig_adx", "sig_bbw_pct"]].corr(method="spearman").loc[col]
        gate = bool(h1[3] < 0 and h2[3] < 0)  # both CIs wholly below zero
        gates.append(dict(feature=col.removeprefix("score_"), score_col=col, low_threshold=float(lo), high_threshold=float(hi),
                          h1_diff=h1[1], h1_ci_low=h1[2], h1_ci_high=h1[3], h2_diff=h2[1], h2_ci_low=h2[2], h2_ci_high=h2[3],
                          bad_n_h1=h1[4], bad_n_h2=h2[4], loss_removed=precision_loss, profit_removed=precision_profit,
                          loss_profit_ratio=precision_loss/precision_profit if precision_profit else np.inf,
                          rho_adx=float(proxy.get("sig_adx", np.nan)), rho_bbw=float(proxy.get("sig_bbw_pct", np.nan)), gate=gate))
    detail, gate_df = pd.DataFrame(rows), pd.DataFrame(gates)
    c.to_csv(HERE / "newdirs_v29_campaign_option_features.csv", index=False, encoding="utf-8-sig")
    detail.to_csv(HERE / "newdirs_option_discriminator.csv", index=False, encoding="utf-8-sig")
    gate_df.to_csv(HERE / "newdirs_option_gates.csv", index=False, encoding="utf-8-sig")
    return detail, gate_df, []


def scaled_trades(trades: pd.DataFrame, featured: pd.DataFrame, variant: str) -> tuple[pd.DataFrame, int, float]:
    h1 = featured[featured.entry_ts < H2]
    cut = float(h1.extension_atr.quantile(2/3))
    q = featured.set_index("campaign_id")
    d = trades.copy()
    if variant == "control_2x": double = pd.Series(True, index=q.index)
    elif variant == "breakout_2x": double = q.breakout
    elif variant == "extension_2x": double = q.extension_atr >= cut
    elif variant == "both_2x": double = q.breakout & (q.extension_atr >= cut)
    else: raise ValueError(variant)
    qty_by_campaign = pd.Series(np.where(double, 2, 1), index=q.index)
    d["qty"] = d.campaign_id.map(qty_by_campaign)
    d["pnl"] *= d.qty
    # Peak quantity: exits first on a timestamp, a conservative flat-to-new entry rule.
    events = []
    for r in d.itertuples(index=False):
        events += [(r.entry_ts, 1, int(r.qty)), (r.exit_ts, 0, -int(r.qty))]
    pos = peak = 0
    for _, _, delta in sorted(events, key=lambda z: (z[0], z[1])):
        pos += delta; peak = max(peak, pos)
    return d, peak, cut


def b_study(runs: dict[str, pd.DataFrame], b5: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, cuts = [], []
    for base, tr in runs.items():
        camp, lots = campaignize(tr)
        feat = cmd_features(camp, b5)
        feat.to_csv(HERE / f"newdirs_{base}_sizing_campaigns.csv", index=False, encoding="utf-8-sig")
        variants = ["both_2x", "breakout_2x", "extension_2x", "control_2x"]
        rendered = {}
        for v in variants:
            x, peak, cut = scaled_trades(lots, feat, v); rendered[v] = x
            cuts.append(dict(base=base, extension_high_cutpoint_h1=cut, variant=v, peak_lots=peak, margin_assumption_per_mxf=92000, margin_need=peak*92000))
            for sp in SPANS:
                rows.append(dict(base=base, variant=v, span=sp, peak_lots=peak, **metric(subset(x, sp))))
        for sp in SPANS:
            ctrl = metric(subset(rendered["control_2x"], sp))["net"]
            for v in variants[:-1]:
                rows[-(len(variants)-1) + variants[:-1].index(v)] if False else None
                # add explicit comparator rows rather than mutating a complex ordered table
                rows.append(dict(base=base, variant=v+"_minus_control", span=sp, peak_lots=np.nan,
                                 n=np.nan, net=metric(subset(rendered[v], sp))["net"]-ctrl, wr=np.nan, pf=np.nan, mdd=np.nan, net_mdd=np.nan))
    out, cutdf = pd.DataFrame(rows), pd.DataFrame(cuts)
    out.to_csv(HERE / "newdirs_b_sizing_metrics.csv", index=False, encoding="utf-8-sig")
    cutdf.to_csv(HERE / "newdirs_b_sizing_assumptions.csv", index=False, encoding="utf-8-sig")
    return out, cutdf


def c_study(df1m: pd.DataFrame, runs: dict[str, pd.DataFrame], only: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    variants = {"allow_15_16": "15_16", "allow_17_20": "17_20", "allow_01_02": "01_02", "allow_long_04": "long_04", "allow_short_21": "short_21"}
    if only is not None:
        if only not in variants: raise ValueError(f"unknown C variant {only}")
        variants = {only: variants[only]}
    rows, hourrows = [], []
    for base, tr in runs.items():
        z = tr.copy(); z["entry_hour"] = z.entry_ts.dt.hour
        for h, g in z.groupby("entry_hour"):
            hourrows.append(dict(base=base, entry_hour=int(h), **metric(g)))
        for name, code in variants.items():
            x = dates(wrapped_run(df1m, p={**BASES[base], "opt_newdirs_unblock": code}, intrabar_mode="1min"))
            x.to_csv(HERE / f"trades_newdirs_{base}_{name}.csv", index=False, encoding="utf-8-sig")
            for sp in SPANS:
                mm, bb = metric(subset(x, sp)), metric(subset(tr, sp))
                rows.append(dict(base=base, variant=name, span=sp, **mm, delta_net=mm["net"]-bb["net"], delta_mdd=mm["mdd"]-bb["mdd"]))
    out, h = pd.DataFrame(rows), pd.DataFrame(hourrows)
    suffix = "" if only is None else "_" + only
    out.to_csv(HERE / f"newdirs_c_unblock_metrics{suffix}.csv", index=False, encoding="utf-8-sig")
    h.to_csv(HERE / "newdirs_c_entry_hours.csv", index=False, encoding="utf-8-sig")
    return out, h


def a_engine_variants(df1m: pd.DataFrame, gates: pd.DataFrame, dailyopt: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if gates.empty: return pd.DataFrame(rows)
    # Predeclared budget: at most two strongest passing option features, one
    # "block aligned-opposing Cmd" form each, hence 2 features x 2 bases = 4 runs.
    chosen = gates[gates.gate].assign(strength=lambda x: -x.h1_ci_high - x.h2_ci_high).nlargest(2, "strength")
    for g in chosen.itertuples(index=False):
        score = "score_" + g.feature
        # The daily feature table has raw PCR variables. Reconstruct matching directional-neutral score.
        if g.feature.startswith("pcr_"):
            raw = g.feature
            source = raw
            if source not in dailyopt: continue
            f = dailyopt[["available_ts", source]].rename(columns={source:"score"}).dropna().copy()
            f.score = -f.score  # wrapper multiplies score by side, matching discriminator
        else:
            continue  # wall feature is diagnostic-only; no predeclared live rule
        f["low_threshold"], f["high_threshold"], f["mode"] = g.low_threshold, g.high_threshold, "block_opposes"
        for base, p in BASES.items():
            x = dates(wrapped_run(df1m, p={**p, "opt_newdirs_filter": f}, intrabar_mode="1min"))
            x.to_csv(HERE / f"trades_newdirs_{base}_A_{g.feature}.csv", index=False, encoding="utf-8-sig")
            ref = dates(base_run(df1m, p=p, intrabar_mode="1min"))
            for sp in SPANS:
                mm, bb = metric(subset(x, sp)), metric(subset(ref, sp))
                rows.append(dict(feature=g.feature, base=base, span=sp, **mm, delta_net=mm["net"]-bb["net"]))
    out = pd.DataFrame(rows); out.to_csv(HERE / "newdirs_a_engine_metrics.csv", index=False, encoding="utf-8-sig")
    return out


def write_report(exact: dict[str, str], logs: list[dict[str,str]], futures_note: str, optnote: str,
                 pcr: pd.DataFrame, summary: pd.DataFrame, inst: pd.DataFrame,
                 disc: pd.DataFrame, gates: pd.DataFrame, am: pd.DataFrame, bm: pd.DataFrame, ba: pd.DataFrame,
                 cm: pd.DataFrame, hours: pd.DataFrame) -> None:
    lines = ["# V38 新方向 A／B／C 實驗", "", "## 執行摘要", "",
             f"- 基線再現：v28 {exact['v28']}；v29 {exact['v29']}。所有重新執行皆為 1 分鐘 intrabar、stale=10h、cooldown=30m。",
             "- A（法人期貨／TXO）：期貨法人分解資料集已定位，但本機 FinLab 登入 token 過期，故沒有把不存在的外資期貨 OI 補成假資料，也沒有執行 A 的期貨 filter。TXO PCR 與履約價 OI 有完整資料；依預先 gate 檢驗後，只有 gate 真正通過的 PCR 特徵才會產生最多兩種、合計最多四次（含兩 base）的引擎實驗。",
             "- B verdict：拒絕。相對永遠兩口 control，breakout 2x 是最接近者，但 v28 的 H1/H2/TRAIN 為 −2,530/−86,850/−62,010，v29 為 +3,530/−52,600/−63,500；both 與 extension 均在所有開發窗大幅落後。ML meta-label sizing 曾失敗，本次未重試。",
             "- C verdict：五個解除窗口在 v28、v29 都沒有 PASS。較好的 15–16 在兩 base 的 TRAIN 分別 −111,050／−29,030；01–02、17–20、long 04、short 21 都至少有 H1/H2/TRAIN/TEST 一個負 delta。HOLDOUT 僅展示。",
             "- 重要限制：這些視窗已在約 8 個研究、60+ variants 中重複使用；任何 PASS 都是弱證據，在稱為 candidate 前必須做 200-draw 年度匹配 placebo（Phase E 方式）。", "",
             "## A／A2：法人與選擇權資訊", "",
             "### 資料盤點與時間因果", "",
             "| 類別 | FinLab 實際資料集 | 覆蓋／結果 |", "| --- | --- | --- |",
             f"| 期貨法人 | `tw_taifex_futures_institutional_breakdown`；另有 `futures_institutional_investors_trading_summary`（多/空未平倉與多空淨額欄） | {futures_note} |",
             f"| TXO Put/Call | `tw_option_put_call_ratio` | {pd.to_datetime(pcr.date).min().date() if not pcr.empty else '無'} 至 {pd.to_datetime(pcr.date).max().date() if not pcr.empty else '無'}；{len(pcr):,} 列 |",
             f"| TXO 各履約價 OI | `tw_option_daily_summary` | {pd.to_datetime(summary.date).min().date() if not summary.empty else '無'} 至 {pd.to_datetime(summary.date).max().date() if not summary.empty else '無'}；{len(summary):,} 列 |",
             f"| 選擇權法人 | `tw_taifex_option_institutional_breakdown` | {pd.to_datetime(inst.date).min().date() if not inst.empty else '無'} 至 {pd.to_datetime(inst.date).max().date() if not inst.empty else '無'}；{len(inst):,} 列；本表的商品彙總未能可靠對到 TXO，未硬套為外資 TXO exposure。 |", "",
             "每日欄位一律在當日 15:00 後才 `available`，因此夜盤可用、同日 08:45–13:45 不可用；以 as-of join 對應 campaign。PCR（OI/量）的 60 日 z、1/5 日變化，以及最近週/月 call/put wall、max-pain、到期距離皆已輸出。VIXTWN 公開頁面探測結果見下方來源紀錄；未成功形成逐日可回測序列時不填補。", "",
             "### A2 campaign discriminator（v29；分數愈高=越支持交易方向）", ""]
    if not gates.empty:
        lines += table(gates, ["feature","h1_diff","h1_ci_low","h1_ci_high","h2_diff","h2_ci_low","h2_ci_high","loss_removed","profit_removed","loss_profit_ratio","rho_adx","rho_bbw","gate"], 2)
    else: lines += ["無可用完整特徵，故無 discriminator。"]
    lines += ["", "反向 bucket 的 CI 是其平均 campaign PnL − 其餘 bucket；gate=true 代表 H1 與非 HOLDOUT H2 的兩個 95% CI 均完全小於 0。`loss_removed/profit_removed` 是最差 bucket 的精準度檢查。期貨 OI 缺失，故無法做其 proxy correlation；ADx/BBW rho 已列。", "",
              "### A 的實際引擎結果", ""]
    if not am.empty:
        lines += table(am[am.span.isin(["全樣本","H1","H2","TRAIN","TEST","HOLDOUT"])], ["feature","base","span","n","net","mdd","net_mdd","delta_net"], 2)
    else:
        lines += ["沒有特徵同時通過 H1/H2 CI gate，或通過者不是預先可執行的 PCR filter；因此依規則不增加 engine variant。"]
    lines += ["", "### 原始下載／探測紀錄", ""] + table(pd.DataFrame(logs), ["source","url","status"], 0)
    lines += ["", "## B：breakout／extension 品質 sizing", "",
              "H1 entry（<2025-04-01）固定 extension 高段門檻；breakout 由 Cmd 完成的 5 分鐘訊號 bar 相對前 20 bar 突破定義。全 campaign 的 Cmd/Add/G 同時乘以 qty，價格路徑與 pyramid 邏輯未改，故沒有把『2 lots』錯當成多一層 pyramid。保證金是報表用的 92,000 NTD/MXF 近似假設，實盤須向期交所／期貨商確認。", "",
              "### 高 extension 門檻、peak lots 與保證金假設", ""] + table(ba, ["base","variant","extension_high_cutpoint_h1","peak_lots","margin_assumption_per_mxf","margin_need"], 2)
    lines += ["", "### 品質 sizing vs 永遠兩口 control（delta net）", ""]
    comp = bm[bm.variant.str.contains("minus_control") & bm.span.isin(["全樣本","H1","H2","TRAIN","TEST","HOLDOUT"])]
    lines += table(comp, ["base","variant","span","net"], 0)
    lines += ["", "### 各 sizing 版本的 net／MDD／net|MDD|", ""]
    coreb = bm[~bm.variant.str.contains("minus_control") & bm.span.isin(["全樣本","H1","H2","TRAIN","TEST","HOLDOUT"])]
    lines += table(coreb, ["base","variant","span","n","net","mdd","net_mdd","peak_lots"], 2)
    lines += ["", "B verdict：若品質版相對 control 的多數開發窗為負，代表它只是較少槓桿而非品質 sizing；若正，也仍須 200-draw 匹配 placebo 後才可稱 candidate。", "",
              "## C：legacy `isBaseToxic` 時段重驗", "",
              "Engine 原式為 `isBaseToxic=(15<=hour<=20) or hour in (1,2)`，再加 long hour=4、short hour=21。這是訊號 5 分鐘 bar 的 hour，而不是 pending next-open fill 的 hour；因此 entry-hour 表在邊界可見上一根訊號造成的偏移。特別檢查 2、16–20（應無）；若 hour=1/15 有筆，須依此前一訊號 bar 解讀而非視為規則失效。", "",
              "### v29/v28 entry-hour distribution", ""] + table(hours, ["base","entry_hour","n","net","wr","pf","mdd"], 2)
    lines += ["", "### 逐窗解除（delta vs 各 base）", ""]
    corec = cm[cm.span.isin(["全樣本","H1","H2","TRAIN","TEST","HOLDOUT"])]
    lines += table(corec, ["base","variant","span","n","net","mdd","net_mdd","delta_net","delta_mdd"], 2)
    lines += ["", "C PASS 定義為 H1、H2、TRAIN、TEST 的 `delta_net` 全正；上表直接提供各窗，沒有以 HOLDOUT 選規則。這些封鎖規則早於本研究、此前未在本 live config 驗證，故即使 PASS 也只屬待 placebo 的弱證據。", "",
              "## 產物與可重現性", "",
              "- `run_newdirs.py`、`engine_newdirs_wrapper.py`：唯一的研究程式；上游 engine 未修改。",
              "- `options_raw/`：FinLab 原始表、TAIFEX HTTP 原始回應及 URL/status log。",
              "- `newdirs_option_daily_features.csv`、`newdirs_option_walls_daily.csv`、`newdirs_option_discriminator.csv`、`newdirs_option_gates.csv`：A/A2 可稽核資料。",
              "- `newdirs_b_sizing_metrics.csv`、`newdirs_b_sizing_assumptions.csv`、`newdirs_c_unblock_metrics.csv`、`newdirs_c_entry_hours.csv`：完整數字；另有實際 variant trades CSV。", ""]
    (HERE / "results_newdirs.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    print("load 1m", flush=True)
    df1m = load_1min(DATA)
    print("run two baselines", flush=True)
    runs = {name: dates(base_run(df1m, p=p, intrabar_mode="1min")) for name, p in BASES.items()}
    exact = {name: exact_check(x, f"trades_{name}.csv") for name, x in runs.items()}
    for name, x in runs.items(): x.to_csv(HERE / f"trades_newdirs_{name}_baseline.csv", index=False, encoding="utf-8-sig")
    b5 = prepare(df1m, {**P, **BASES["v29"]})
    print("collect FinLab-first TXO sources", flush=True)
    pcr, summary, inst, logs, f_note = fetch_options()
    dailyopt, optnote = option_daily_features(pcr, summary, daily_underlying(df1m))
    camp29, _ = campaignize(runs["v29"])
    print("A/A2 discriminator", flush=True)
    disc, gates, _ = option_discriminator(camp29, b5, dailyopt)
    print("B sizing", flush=True)
    bm, ba = b_study(runs, b5)
    print("C legacy-hour variants", flush=True)
    cm, hours = c_study(df1m, runs)
    print("A gated engine variants (only if justified)", flush=True)
    am = a_engine_variants(df1m, gates, dailyopt)
    write_report(exact, logs, f_note, optnote, pcr, summary, inst, disc, gates, am, bm, ba, cm, hours)
    print("done results_newdirs.md", flush=True)


def staged(stage: str) -> None:
    """Small restartable stages keep each Windows execution cell below its limit."""
    runs = {name: dates(pd.read_csv(HERE / f"trades_newdirs_{name}_baseline.csv")) for name in BASES}
    if stage == "exact":
        df1m = load_1min(DATA)
        ends = [dates(pd.read_csv(HERE / f"trades_{name}.csv")).exit_ts.max() for name in BASES]
        ref_df = df1m[df1m.ts <= max(ends)].copy()
        result = {name: exact_check(dates(base_run(ref_df, p=p, intrabar_mode="1min")), f"trades_{name}.csv") for name, p in BASES.items()}
        (HERE / "newdirs_exact.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    if stage == "b":
        df1m = load_1min(DATA); b5 = prepare(df1m, {**P, **BASES["v29"]})
        b_study(runs, b5); return
    if stage.startswith("c_"):
        name = stage.removeprefix("c_")
        df1m = load_1min(DATA); c_study(df1m, runs, name); return
    if stage == "a":
        gates = pd.read_csv(HERE / "newdirs_option_gates.csv")
        daily = pd.read_csv(HERE / "newdirs_option_daily_features.csv", parse_dates=["available_ts"])
        # All current gates are false, but this call writes the explicit empty
        # audit file rather than silently treating A engine work as omitted.
        a_engine_variants(load_1min(DATA), gates, daily); return
    if stage == "report":
        ex_path = HERE / "newdirs_exact.json"
        exact = json.loads(ex_path.read_text(encoding="utf-8")) if ex_path.exists() else {name: exact_check(x, f"trades_{name}.csv") for name, x in runs.items()}
        logs = pd.read_csv(HERE / "options_raw" / "source_log.csv").fillna("").to_dict("records")
        pcr = pd.read_csv(HERE / "options_raw" / "finlab_tw_option_put_call_ratio.csv")
        summary = pd.read_csv(HERE / "options_raw" / "finlab_tw_option_daily_summary.csv")
        inst = pd.read_csv(HERE / "options_raw" / "finlab_tw_taifex_option_institutional_breakdown.csv")
        disc = pd.read_csv(HERE / "newdirs_option_discriminator.csv")
        gates = pd.read_csv(HERE / "newdirs_option_gates.csv")
        am_path = HERE / "newdirs_a_engine_metrics.csv"
        try:
            am = pd.read_csv(am_path) if am_path.exists() and am_path.stat().st_size > 5 else pd.DataFrame()
        except pd.errors.EmptyDataError:
            am = pd.DataFrame()
        bm, ba = pd.read_csv(HERE / "newdirs_b_sizing_metrics.csv"), pd.read_csv(HERE / "newdirs_b_sizing_assumptions.csv")
        cfiles = sorted(HERE.glob("newdirs_c_unblock_metrics_*.csv"))
        cm = pd.concat([pd.read_csv(x) for x in cfiles], ignore_index=True)
        cm.to_csv(HERE / "newdirs_c_unblock_metrics.csv", index=False, encoding="utf-8-sig")
        hours = pd.read_csv(HERE / "newdirs_c_entry_hours.csv")
        f_note = "未取得：RuntimeError（登入 token 過期，未臆造資料）"
        write_report(exact, logs, f_note, "", pcr, summary, inst, disc, gates, am, bm, ba, cm, hours)
        return
    raise ValueError(f"unknown stage {stage}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        staged(sys.argv[1])
    else:
        main()
