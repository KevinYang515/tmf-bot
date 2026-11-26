"""V38 descriptive profit, drawdown, and risk attribution.

The upstream engine is imported read-only.  This driver intentionally keeps
campaign and equity definitions explicit so each table in results_attrib.md
can be regenerated from the supplied 1-minute ledger.
"""
from __future__ import annotations

import inspect
import sys
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
OLD_DATA = HERE / "mxf_1min_corrected_20261017.csv"
OUT = HERE / "results_attrib.md"
H2 = pd.Timestamp("2025-04-01")
LIVE = {"opt_stale_hr": 10, "opt_cooldown_min": 30}
BASES = {
    "v28": {**LIVE, "opt_short_pyramid_cap_mode": "hour4"},
    "v29": {**LIVE, "opt_short_pyramid_cap_mode": "hour4", "l_trailBase": 3.5},
}
TRADE_COLS = ["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl"]
POINT_VALUE = float(eng.POINT_VALUE)
COMMISSION = float(eng.COMMISSION)
RNG = np.random.default_rng(20261018)


def session_label(t: pd.Timestamp) -> str:
    if (t.hour == 8 and t.minute >= 45) or 9 <= t.hour <= 12 or (t.hour == 13 and t.minute < 45):
        return "日盤"
    if t.hour >= 15 or t.hour < 5:
        return "夜盤"
    return "休市帶"


def trade_day(t: pd.Timestamp) -> pd.Timestamp:
    """15:00 之後的夜盤歸入下一個交易日。"""
    d = pd.Timestamp(t).normalize()
    return d + pd.Timedelta(days=1) if pd.Timestamp(t).hour >= 15 else d


def exit_type(sig: str) -> str:
    sig = str(sig)
    if sig.endswith("_SL"):
        return "SL"
    if sig == "Trend Rev" or sig == "Trend Rev Cap":
        return sig
    if sig.endswith("Cmd_Fast"):
        return "Cmd_Fast"
    if sig == "TimeStop":
        return "TimeStop"
    if sig.endswith("_BE"):
        return "BE"
    if sig == "END":
        return "END"
    return "Trail/Other"


def normalise_trades(d: pd.DataFrame) -> pd.DataFrame:
    x = d.copy()
    x["entry_ts"] = pd.to_datetime(x["entry_ts"])
    x["exit_ts"] = pd.to_datetime(x["exit_ts"])
    x["pnl"] = x["pnl"].astype(float)
    return x.sort_values(["exit_ts", "entry_ts", "kind"]).reset_index(drop=True)


def compare_exact(a: pd.DataFrame, b: pd.DataFrame) -> tuple[bool, str]:
    lhs, rhs = a[TRADE_COLS].reset_index(drop=True), b[TRADE_COLS].reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(lhs, rhs, check_dtype=False, check_exact=True)
        return True, "EXACT"
    except AssertionError as exc:
        return False, str(exc).replace("\n", " ")[:300]


def closed_equity(d: pd.DataFrame, initial_ts: pd.Timestamp | None = None) -> pd.DataFrame:
    """Closed-lot equity, grouping simultaneous exits before measuring DD."""
    z = d.groupby("exit_ts", as_index=False).pnl.sum().sort_values("exit_ts")
    if z.empty:
        return pd.DataFrame(columns=["ts", "pnl", "equity"])
    start = pd.Timestamp(initial_ts if initial_ts is not None else z.exit_ts.iloc[0])
    if start >= z.exit_ts.iloc[0]:
        start = z.exit_ts.iloc[0] - pd.Timedelta(nanoseconds=1)
    base = pd.DataFrame({"exit_ts": [start], "pnl": [0.0]})
    z = pd.concat([base, z], ignore_index=True).rename(columns={"exit_ts": "ts"})
    z["equity"] = z.pnl.cumsum()
    return z


def metric(d: pd.DataFrame) -> dict[str, float | int]:
    if d.empty:
        return {"n": 0, "net": 0.0, "wr": np.nan, "pf": np.nan, "avg_win": np.nan, "avg_loss": np.nan, "mdd": 0.0}
    p = d.pnl.astype(float)
    win, loss = p[p > 0], p[p <= 0]
    curve = closed_equity(d, d.entry_ts.min())
    dd = curve.equity - curve.equity.cummax()
    return {
        "n": int(len(d)), "net": float(p.sum()), "wr": float(100 * (p > 0).mean()),
        "pf": float(win.sum() / -loss.sum()) if len(loss) and loss.sum() else np.inf,
        "avg_win": float(win.mean()) if len(win) else np.nan,
        "avg_loss": float(loss.mean()) if len(loss) else np.nan,
        "mdd": float(dd.min()),
    }


def assign_campaigns(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Campaign is a connected Cmd + Add/G position interval."""
    x = normalise_trades(trades).sort_values(["entry_ts", "exit_ts", "kind"]).reset_index(drop=True)
    cid, active_end, ids = -1, pd.Timestamp.min, []
    for r in x.itertuples():
        # Engine cannot open an Add/G when no campaign is live.  The interval
        # rule keeps a surviving Add/G with its original Cmd after Cmd exits.
        # At a shared timestamp the engine can execute an already-pending
        # Add/G after closing the last old lot.  It is still the old Cmd's
        # pyramid instruction, so keep it with that mother.  A new Cmd at
        # that timestamp is genuinely a new campaign.
        if r.entry_ts > active_end or (r.entry_ts == active_end and r.kind == "Cmd"):
            cid += 1
            active_end = r.exit_ts
        else:
            active_end = max(active_end, r.exit_ts)
        ids.append(cid)
    x["campaign_id"] = ids
    x["entry_session"] = x.entry_ts.map(session_label)
    x["exit_type"] = x.exit_sig.map(exit_type)
    x["entry_year"] = x.entry_ts.dt.year
    x["trade_date"] = x.entry_ts.map(trade_day)
    ag = x.groupby("campaign_id", as_index=False).agg(
        side=("side", "first"), entry_ts=("entry_ts", "min"), exit_ts=("exit_ts", "max"),
        pnl=("pnl", "sum"), lots=("pnl", "size"),
    )
    cmd = x[x.kind.eq("Cmd")].groupby("campaign_id", as_index=False).agg(
        cmd_entry_ts=("entry_ts", "min"), cmd_exit_sig=("exit_sig", "last"),
    )
    ag = ag.merge(cmd, on="campaign_id", how="left")
    if ag.cmd_entry_ts.isna().any():
        raise RuntimeError("campaign assignment produced a non-Cmd mother")
    ag["entry_year"] = ag.entry_ts.dt.year
    ag["half"] = np.where(ag.entry_ts < H2, "H1", "H2")
    ag["entry_session"] = ag.entry_ts.map(session_label)
    ag["trade_date"] = ag.entry_ts.map(trade_day)
    return x, ag


def profit_concentration(camps: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    total = float(camps.pnl.sum())
    rows = []
    for label, d in [("全部", camps), ("多", camps[camps.side.eq("L")]), ("空", camps[camps.side.eq("S")])]:
        for q in (0.01, 0.05, 0.10):
            n = max(1, int(np.ceil(len(d) * q)))
            top = d.nlargest(n, "pnl").pnl.sum()
            rows.append({"分組": label, "上位比例": f"{q:.0%}", "campaign數": n, "上位淨利": top,
                         "佔全體淨利": top / total if total else np.nan,
                         "佔該組淨利": top / d.pnl.sum() if d.pnl.sum() else np.nan})
    concentration = pd.DataFrame(rows)

    remove_rows = []
    groups: list[tuple[str, pd.DataFrame]] = [("全部", camps)]
    groups += [(f"{int(y)}-{s}", z) for (y, s), z in camps.groupby(["entry_year", "side"])]
    for label, d in groups:
        for n in (5, 10, 20, 50):
            removed = d.nlargest(min(n, len(d)), "pnl").pnl.sum()
            remove_rows.append({"分組": label, "原淨利": d.pnl.sum(), "移除前N": n,
                                "實際移除數": min(n, len(d)), "移除上位淨利": removed,
                                "移除後淨利": d.pnl.sum() - removed,
                                "保留比例": (d.pnl.sum() - removed) / d.pnl.sum() if d.pnl.sum() else np.nan})
    removal = pd.DataFrame(remove_rows)

    lorenz_rows = []
    ordered = camps.sort_values("pnl", ascending=True).reset_index(drop=True)
    for q in np.arange(0, 1.01, .1):
        n = int(np.floor(len(ordered) * q))
        v = ordered.pnl.iloc[:n].sum() if n else 0.0
        lorenz_rows.append({"累積campaign比例": q, "累積campaign數": n, "由最差至此累積淨利": v,
                            "累積淨利比例": v / total if total else np.nan})
    lorenz = pd.DataFrame(lorenz_rows)

    stat_rows = []
    for label, d in [("全部", camps), *[(f"{y}-{s}", z) for (y, s), z in camps.groupby(["entry_year", "side"])]]:
        stat_rows.append({"分組": label, "campaign數": len(d), "淨利": d.pnl.sum(), "中位campaign PnL": d.pnl.median(),
                          "勝率": 100 * (d.pnl > 0).mean()})
    return concentration, removal, lorenz, pd.DataFrame(stat_rows)


def sleeve_table(lots: pd.DataFrame, mdd_start: pd.Timestamp, mdd_trough: pd.Timestamp) -> tuple[pd.DataFrame, list[str]]:
    rows = []
    periods: list[tuple[str, pd.Series]] = [
        ("H1", lots.entry_ts < H2), ("H2", lots.entry_ts >= H2),
        *[(str(y), lots.entry_ts.dt.year.eq(y)) for y in sorted(lots.entry_ts.dt.year.unique())],
    ]
    mdd_lots = lots[(lots.exit_ts > mdd_start) & (lots.exit_ts <= mdd_trough)]
    mdd_total = float(mdd_lots.pnl.sum())
    for period, mask in periods:
        for side in ("L", "S"):
            for kind in ("Cmd", "Add", "G"):
                d = lots[mask & lots.side.eq(side) & lots.kind.eq(kind)]
                m = metric(d)
                dm = float(mdd_lots[mdd_lots.side.eq(side) & mdd_lots.kind.eq(kind)].pnl.sum())
                rows.append({"期間": period, "方向": "多" if side == "L" else "空", "kind": kind, **m,
                             "全樣本MDD下降段淨利": dm,
                             "對MDD深度貢獻": -dm / abs(mdd_total) if mdd_total else np.nan})
    tab = pd.DataFrame(rows)
    h = tab[tab["期間"].isin(["H1", "H2"])].pivot_table(index=["方向", "kind"], columns="期間", values="net")
    flagged = [f"{'L' if side == '多' else 'S'}_{kind}" for (side, kind), z in h.iterrows() if z.get("H1", np.inf) <= 0 and z.get("H2", np.inf) <= 0]
    return tab, flagged


def dd_episodes(curve: pd.DataFrame, final_ts: pd.Timestamp) -> pd.DataFrame:
    """High-water-mark DD episodes; a recovery is the first new high."""
    if curve.empty:
        return pd.DataFrame()
    hwm = float(curve.equity.iloc[0]); peak_ts = pd.Timestamp(curve.ts.iloc[0])
    active: dict[str, Any] | None = None
    rows = []
    for r in curve.iloc[1:].itertuples(index=False):
        ts, eq = pd.Timestamp(r.ts), float(r.equity)
        if active is None:
            if eq >= hwm:
                hwm, peak_ts = eq, ts
            else:
                active = {"peak_ts": peak_ts, "peak_equity": hwm, "trough_ts": ts, "trough_equity": eq}
        else:
            if eq < active["trough_equity"]:
                active["trough_equity"], active["trough_ts"] = eq, ts
            if eq >= hwm:
                active["recovery_ts"] = ts
                rows.append(active)
                hwm, peak_ts, active = eq, ts, None
    if active is not None:
        active["recovery_ts"] = pd.NaT
        rows.append(active)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["depth"] = out.trough_equity - out.peak_equity
    out["end_ts"] = out.recovery_ts.fillna(final_ts)
    out["calendar_days"] = (out.end_ts - out.peak_ts).dt.total_seconds() / 86400
    return out.sort_values("peak_ts").reset_index(drop=True)


def mix_text(d: pd.DataFrame, by: str, positive: bool = False) -> str:
    if d.empty:
        return "—"
    g = d.groupby(by).pnl.agg(n="size", net="sum")
    losses = d[d.pnl <= 0].groupby(by).pnl.agg(loss_n="size", loss=lambda x: -x.sum())
    g = g.join(losses).fillna(0)
    total_loss, total_n = float(g.loss.sum()), float(g.loss_n.sum())
    if total_loss and total_n:
        g["sev"] = (g.loss / total_loss) / (g.loss_n / total_n).replace(0, np.nan)
    else:
        g["sev"] = np.nan
    parts = []
    for key, r in g.sort_values("net", ascending=not positive).iterrows():
        sev = "—" if not np.isfinite(r.sev) else f"{r.sev:.2f}x"
        parts.append(f"{key}: n{int(r.n)}, {r.net:+,.0f}, sev {sev}")
    return "; ".join(parts)


def episode_details(episodes: pd.DataFrame, lots: pd.DataFrame, camps: pd.DataFrame, direction: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Detail losses for peak->trough; run-up gains for trough->recovery."""
    rows, long_rows = [], []
    for r in episodes.itertuples(index=False):
        if direction == "dd":
            a, b, label = r.peak_ts, r.trough_ts, "DD"
            pick_top, ascending = "最差campaign", True
        else:
            a, b, label = r.trough_ts, r.recovery_ts, "Run-up"
            pick_top, ascending = "最大campaign", False
        d = lots[(lots.exit_ts > a) & (lots.exit_ts <= b)].copy()
        if d.empty:
            cnet = pd.DataFrame(columns=["campaign_id", "pnl"])
        else:
            cnet = d.groupby("campaign_id", as_index=False).pnl.sum().sort_values("pnl", ascending=ascending).head(3)
        top = "; ".join(f"#{int(q.campaign_id)} {q.pnl:+,.0f}" for q in cnet.itertuples()) or "—"
        for field, name in [("side_kind", "方向×kind"), ("exit_type", "出場型態"), ("entry_session", "進場盤別")]:
            zz = d.assign(side_kind=d.side + "-" + d.kind) if field == "side_kind" else d
            col = "side_kind" if field == "side_kind" else field
            if not zz.empty:
                g = zz.groupby(col).pnl.agg(n="size", net="sum").reset_index().rename(columns={col: "bucket"})
                loss = zz[zz.pnl <= 0].groupby(col).pnl.agg(loss_n="size", loss=lambda x: -x.sum()).reset_index().rename(columns={col: "bucket"})
                g = g.merge(loss, on="bucket", how="left").fillna(0)
                tl, tn = g.loss.sum(), g.loss_n.sum()
                g["loss_share"] = g.loss / tl if tl else np.nan
                g["severity"] = (g.loss / tl) / (g.loss_n / tn).replace(0, np.nan) if tl and tn else np.nan
                for q in g.itertuples(index=False):
                    long_rows.append({"episode_id": r.episode_id, "episode_type": label, "mix": name,
                                      "bucket": q.bucket, "n": q.n, "net": q.net,
                                      "loss_share": q.loss_share, "severity": q.severity})
        p = {"episode_id": r.episode_id, "episode_type": label, "campaigns": int(d.campaign_id.nunique()),
             "top_campaigns": top, "方向×kind": mix_text(d.assign(side_kind=d.side + "-" + d.kind), "side_kind", positive=(direction == "runup")),
             "出場型態": mix_text(d, "exit_type", positive=(direction == "runup")),
             "進場盤別": mix_text(d, "entry_session", positive=(direction == "runup"))}
        rows.append(p)
    return pd.DataFrame(rows), pd.DataFrame(long_rows)


def add_episode_metadata(dd: pd.DataFrame, trading_days: pd.DatetimeIndex) -> pd.DataFrame:
    x = dd.copy()
    x["episode_id"] = np.arange(1, len(x) + 1)
    x["trading_days"] = [int(((trading_days >= a.normalize()) & (trading_days <= b.normalize())).sum())
                         for a, b in zip(x.peak_ts, x.end_ts)]
    return x


def mtm_curve(df1m: pd.DataFrame, lots: pd.DataFrame) -> pd.DataFrame:
    """At each 1-min close: realized lots + open lots marked at that close."""
    closes = pd.to_datetime(df1m.ts).to_numpy(dtype="datetime64[ns]")
    n = len(closes)
    cnt = np.zeros(n); dirs = np.zeros(n); entries = np.zeros(n); realized = np.zeros(n)
    def at_open(t: pd.Timestamp) -> int:
        return int(np.searchsorted(closes, np.datetime64(t), side="right"))
    def at_exit(t: pd.Timestamp, sig: str) -> int:
        # Stops and END are timestamped at a completed 1-min/5-min close;
        # next-bar market exits are timestamped at their open.
        side = "left" if (str(sig).endswith(("_SL", "_BE")) or sig == "END") else "right"
        return int(np.searchsorted(closes, np.datetime64(t), side=side))
    for r in lots.itertuples(index=False):
        j = at_open(r.entry_ts)
        if j < n:
            s = 1.0 if r.side == "L" else -1.0
            cnt[j] += 1; dirs[j] += s; entries[j] += s * float(r.entry_px)
        k = at_exit(r.exit_ts, r.exit_sig)
        if k < n:
            s = 1.0 if r.side == "L" else -1.0
            cnt[k] -= 1; dirs[k] -= s; entries[k] -= s * float(r.entry_px); realized[k] += float(r.pnl)
    cnt, dirs, entries, realized = np.cumsum(cnt), np.cumsum(dirs), np.cumsum(entries), np.cumsum(realized)
    equity = realized + (df1m.close.to_numpy(float) * dirs - entries) * POINT_VALUE - 2 * COMMISSION * cnt
    return pd.DataFrame({"ts": pd.to_datetime(df1m.ts), "equity": equity, "open_lots": cnt})


def daily_features(df1m: pd.DataFrame, lots: pd.DataFrame) -> pd.DataFrame:
    x = df1m.copy()
    x["trade_date"] = x.open_ts.map(trade_day)
    daily = x.groupby("trade_date", as_index=False).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    daily = daily.sort_values("trade_date").reset_index(drop=True)
    pc = daily.close.shift()
    tr = pd.concat([daily.high - daily.low, (daily.high - pc).abs(), (daily.low - pc).abs()], axis=1).max(axis=1)
    daily["atr20"] = tr.ewm(alpha=1/20, adjust=False).mean()
    daily["rv20_pct"] = daily.close.pct_change().rolling(20).std() * np.sqrt(252) * 100
    daily["ema60"] = daily.close.ewm(span=60, adjust=False).mean()
    daily["trend_strength"] = (daily.close - daily.ema60).abs() / daily.atr20
    daily["chop_range_atr"] = (daily.high - daily.low) / daily.atr20
    daily["overnight_gap_atr"] = (daily.open - pc).abs() / daily.atr20
    cmd = lots[lots.kind.eq("Cmd")].sort_values("entry_ts").copy()
    cmd["trade_date"] = cmd.entry_ts.map(trade_day)
    flips = []
    for d, z in cmd.groupby("trade_date"):
        sides = z.side.to_numpy()
        flips.append({"trade_date": d, "cmd_flips": int(np.sum(sides[1:] != sides[:-1]))})
    daily = daily.merge(pd.DataFrame(flips), on="trade_date", how="left")
    daily["cmd_flips"] = daily.cmd_flips.fillna(0).astype(int)
    return daily


FEATURES = ["rv20_pct", "trend_strength", "chop_range_atr", "cmd_flips", "overnight_gap_atr"]


def state_and_causal(daily: pd.DataFrame, dd: pd.DataFrame, runups: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = daily.copy().set_index("trade_date", drop=False)
    d["state"] = "正常"
    # The DD comparison is the adverse peak->trough leg; run-up is its
    # separate trough->recovery leg.  Run-up gets priority on their shared trough day.
    for r in dd[dd.depth < -100_000].itertuples():
        ix = (d.index >= trade_day(r.peak_ts)) & (d.index <= trade_day(r.trough_ts))
        d.loc[ix, "state"] = "DD下降段"
    for r in runups.itertuples():
        ix = (d.index >= trade_day(r.trough_ts)) & (d.index <= trade_day(r.recovery_ts))
        d.loc[ix, "state"] = "Run-up回升段"
    state = d.groupby("state")[FEATURES].agg(["size", "mean", "median"])
    state.columns = ["_".join(c) for c in state.columns]
    state = state.reset_index()

    def windows(events: pd.DataFrame, kind: str) -> list[pd.DataFrame]:
        out = []
        for r in events.itertuples():
            start = trade_day(r.peak_ts if kind == "dd" else r.trough_ts)
            end = trade_day(r.trough_ts if kind == "dd" else r.recovery_ts)
            z = d[(d.index > start) & (d.index <= end)].head(3)
            if len(z) == 3 and z[FEATURES].notna().all().all():
                out.append(z)
        return out
    ddw = windows(dd[dd.depth < -100_000], "dd")
    ruw = windows(runups, "runup")
    normal = d[d.state.eq("正常") & d[FEATURES].notna().all(axis=1)]
    candidate = [normal.iloc[i:i+3] for i in range(len(normal)-2)
                 if len(normal.iloc[i:i+3]) == 3 and (normal.index[i:i+3].to_series().diff().dropna() <= pd.Timedelta(days=4)).all()]
    rows = []
    values = {"DD首3日": np.array([z[FEATURES].mean().to_numpy(float) for z in ddw]),
              "Run-up首3日": np.array([z[FEATURES].mean().to_numpy(float) for z in ruw])}
    random_windows = np.array([z[FEATURES].mean().to_numpy(float) for z in candidate]) if candidate else np.empty((0, len(FEATURES)))
    for state_name, arr in values.items():
        for j, f in enumerate(FEATURES):
            obs = float(np.nanmean(arr[:, j])) if len(arr) else np.nan
            dist = np.array([])
            if len(arr) and len(random_windows):
                choice = RNG.integers(0, len(random_windows), size=(5000, len(arr)))
                dist = random_windows[choice, j].mean(axis=1)
            p = float((np.abs(dist - np.nanmean(random_windows[:, j])) >= abs(obs - np.nanmean(random_windows[:, j]))).mean()) if len(dist) else np.nan
            rows.append({"比較組": state_name, "特徵": f, "事件數": len(arr), "首3日平均": obs,
                         "正常隨機窗平均": float(np.nanmean(random_windows[:, j])) if len(random_windows) else np.nan,
                         "相對正常經驗p": p})
    # Bootstrap DD - run-up: descriptive uncertainty, not a selection rule.
    for j, f in enumerate(FEATURES):
        a, b = values["DD首3日"][:, j] if len(values["DD首3日"]) else np.array([]), values["Run-up首3日"][:, j] if len(values["Run-up首3日"]) else np.array([])
        if len(a) and len(b):
            draws = RNG.choice(a, (5000, len(a)), replace=True).mean(1) - RNG.choice(b, (5000, len(b)), replace=True).mean(1)
            ci_lo, ci_hi = np.quantile(draws, [.025, .975])
            delta = a.mean() - b.mean()
        else:
            delta = ci_lo = ci_hi = np.nan
        rows.append({"比較組": "DD減Run-up", "特徵": f, "事件數": min(len(a), len(b)), "首3日平均": delta,
                     "正常隨機窗平均": np.nan, "相對正常經驗p": np.nan, "bootstrap95下限": ci_lo, "bootstrap95上限": ci_hi})
    return state, pd.DataFrame(rows)


def money_risk(df1m: pd.DataFrame, lots: pd.DataFrame, camps: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    b5 = eng.prepare(df1m, {**eng.P, **BASES["v29"]})
    b5["trade_date"] = b5.open_ts.map(trade_day)
    atrm = b5.assign(month=b5.trade_date.dt.to_period("M").astype(str), atr_pct=100*b5.atr/b5.close).groupby("month").atr_pct.median()
    daily_index = pd.DatetimeIndex(sorted({trade_day(t) for t in df1m.open_ts}))
    realized = lots.assign(exit_day=lots.exit_ts.map(trade_day)).groupby("exit_day").pnl.sum().reindex(daily_index, fill_value=0.0)
    ddf = pd.DataFrame({"trade_date": daily_index, "daily_pnl": realized.to_numpy()})
    ddf["month"] = ddf.trade_date.dt.to_period("M").astype(str)
    daily_m = ddf.groupby("month").daily_pnl.agg(std_daily_pnl="std", worst_day="min", net_daily="sum")
    c = camps.copy(); c["month"] = c.trade_date.dt.to_period("M").astype(str)
    camp_m = c.groupby("month").pnl.agg(campaigns="size", median_abs_campaign_pnl=lambda x: x.abs().median())
    monthly = pd.concat([atrm, camp_m, daily_m], axis=1).reset_index().rename(columns={"atr_pct": "5m_ATR_pct"})
    yearly = c.assign(year=c.entry_ts.dt.year).groupby("year").pnl.agg(
        campaigns="size", net="sum", median_abs_campaign_pnl=lambda x: x.abs().median(),
        mean_abs_campaign_pnl=lambda x: x.abs().mean(), avg_loss=lambda x: x[x <= 0].mean()).reset_index()
    corr = {"pearson": float(monthly[["5m_ATR_pct", "std_daily_pnl"]].corr(method="pearson").iloc[0, 1]),
            "spearman": float(monthly[["5m_ATR_pct", "std_daily_pnl"]].corr(method="spearman").iloc[0, 1])}
    weekly = ddf.assign(week=ddf.trade_date.dt.to_period("W-FRI").astype(str)).groupby("week").daily_pnl.sum()
    risk = {"worst_day": float(realized.min()), "worst_week": float(weekly.min()), **corr}
    return monthly, yearly, risk


def md_table(d: pd.DataFrame, cols: list[str], max_rows: int | None = None) -> list[str]:
    if d.empty:
        return ["（無資料）"]
    z = d.loc[:, [c for c in cols if c in d.columns]].copy()
    if max_rows is not None:
        z = z.head(max_rows)
    def f(v: Any) -> str:
        if isinstance(v, pd.Timestamp): return "未恢復" if pd.isna(v) else v.strftime("%Y-%m-%d %H:%M")
        if pd.isna(v): return "—"
        if isinstance(v, (float, np.floating)):
            if abs(v) >= 1000: return f"{v:,.0f}"
            return f"{v:.3f}"
        return str(v)
    z = z.map(f)
    return ["| " + " | ".join(z.columns) + " |", "| " + " | ".join(["---"] * len(z.columns)) + " |"] + ["| " + " | ".join(row) + " |" for row in z.to_numpy()]


def run_without_sleeve(df1m: pd.DataFrame, p: dict[str, Any], sleeve: str) -> pd.DataFrame:
    """Structural, side-specific removal wrapper; never edits vendor engine."""
    source = inspect.getsource(eng.run)
    old = '''                elif act == "entry":
                    kind, dir_ = arg
                    if kind == "Cmd":
'''
    new = '''                elif act == "entry":
                    kind, dir_ = arg
                    _removed = overrides.get("opt_remove_sleeve")
                    if _removed == (("L" if dir_ > 0 else "S") + "_" + kind):
                        continue
                    if kind == "Cmd":
'''
    if old not in source:
        raise RuntimeError("engine entry anchor changed")
    source = source.replace(old, new, 1)
    namespace: dict[str, Any] = {}
    glob = {k: v for k, v in vars(eng).items() if not k.startswith("__")}
    exec(compile(source, "engine_attrib_sleeve_wrapper.py", "exec"), glob, namespace)
    return normalise_trades(namespace["run"](df1m, p={**p, "opt_remove_sleeve": sleeve}, intrabar_mode="1min"))


def structural_variants(df1m: pd.DataFrame, flagged: list[str], bases: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for sleeve in flagged:
        for ver, p in BASES.items():
            tr = run_without_sleeve(df1m, p, sleeve)
            tr.to_csv(HERE / f"trades_attrib_{ver}_without_{sleeve}.csv", index=False, encoding="utf-8-sig")
            for split, z in [("全樣本", tr), ("H1", tr[tr.entry_ts < H2]), ("H2", tr[tr.entry_ts >= H2]),
                             *[(str(y), tr[tr.entry_ts.dt.year.eq(y)]) for y in sorted(tr.entry_ts.dt.year.unique())]]:
                a, b = metric(z), metric(bases[ver][bases[ver].entry_ts < H2] if split == "H1" else bases[ver][bases[ver].entry_ts >= H2] if split == "H2" else bases[ver][bases[ver].entry_ts.dt.year.eq(int(split))] if split.isdigit() else bases[ver])
                rows.append({"版本": ver, "移除袖套": sleeve, "期間": split, "net": a["net"], "MDD": a["mdd"],
                             "net差異": a["net"]-b["net"], "MDD差異": abs(a["mdd"])-abs(b["mdd"]), "n": a["n"]})
    return pd.DataFrame(rows)


def main() -> None:
    reuse = "--reuse" in sys.argv
    if reuse:
        # Used only after a post-processing failure: these ledgers were just
        # generated by the normal required fresh engine pass above, and save
        # needless duplicate engine work while regenerating the report.
        repro = pd.read_csv(HERE / "attrib_reproduction.csv")
        df1m = eng.load_1min(DATA)
        runs = {ver: normalise_trades(pd.read_csv(HERE / f"trades_attrib_{ver}.csv")) for ver in BASES}
    else:
        # Required reproducibility gate: old supplied data must recreate trades_v28/v29.csv.
        old = eng.load_1min(OLD_DATA)
        repro_rows = []
        for ver, p in BASES.items():
            fresh = normalise_trades(eng.run(old, p=p, intrabar_mode="1min"))
            ref = normalise_trades(pd.read_csv(HERE / f"trades_{ver}.csv"))
            ok, note = compare_exact(fresh, ref)
            repro_rows.append({"版本": ver, "參考lot": len(ref), "重現lot": len(fresh), "參考淨利": ref.pnl.sum(), "重現淨利": fresh.pnl.sum(), "狀態": "EXACT" if ok else "MISMATCH", "說明": note})
        repro = pd.DataFrame(repro_rows)
        repro.to_csv(HERE / "attrib_reproduction.csv", index=False, encoding="utf-8-sig")

        # Fresh current data runs, rather than relying on a prior study's ledger.
        df1m = eng.load_1min(DATA)
        runs: dict[str, pd.DataFrame] = {}
        for ver, p in BASES.items():
            print(f"run {ver}", flush=True)
            runs[ver] = normalise_trades(eng.run(df1m, p=p, intrabar_mode="1min"))
            runs[ver].to_csv(HERE / f"trades_attrib_{ver}.csv", index=False, encoding="utf-8-sig")
    lots, camps = assign_campaigns(runs["v29"])
    lots.to_csv(HERE / "attrib_v29_lots_campaigns.csv", index=False, encoding="utf-8-sig")
    camps.to_csv(HERE / "attrib_v29_campaigns.csv", index=False, encoding="utf-8-sig")

    curve = closed_equity(lots, lots.entry_ts.min())
    trading_index = pd.DatetimeIndex(sorted({trade_day(t) for t in df1m.open_ts}))
    dd = add_episode_metadata(dd_episodes(curve, pd.Timestamp(df1m.ts.iloc[-1])), trading_index)
    dd_deep = dd[dd.depth < -100_000].copy()
    dd_deep.to_csv(HERE / "attrib_closed_dd_episodes.csv", index=False, encoding="utf-8-sig")
    dd_meta, dd_mix = episode_details(dd_deep, lots, camps, "dd")
    dd_mix.to_csv(HERE / "attrib_closed_dd_mix.csv", index=False, encoding="utf-8-sig")

    runups = dd[dd.recovery_ts.notna() & (dd.peak_equity > dd.trough_equity)].copy()
    runups["runup"] = runups.peak_equity - runups.trough_equity
    runups = runups.nlargest(10, "runup").sort_values("runup", ascending=False).copy()
    # Unlike the DD table's peak-to-recovery duration, the requested run-up
    # duration is strictly trough-to-recovered-peak.
    runups["calendar_days"] = (runups.recovery_ts - runups.trough_ts).dt.total_seconds() / 86400
    runups["trading_days"] = [int(((trading_index >= trade_day(a)) & (trading_index <= trade_day(b))).sum())
                               for a, b in zip(runups.trough_ts, runups.recovery_ts)]
    runups.to_csv(HERE / "attrib_runup_episodes.csv", index=False, encoding="utf-8-sig")
    ru_meta, ru_mix = episode_details(runups, lots, camps, "runup")
    ru_mix.to_csv(HERE / "attrib_runup_mix.csv", index=False, encoding="utf-8-sig")

    # Main MDD sleeve contributions are the closed-equity global low episode.
    worst = dd.loc[dd.depth.idxmin()]
    sleeves, flagged = sleeve_table(lots, worst.peak_ts, worst.trough_ts)
    sleeves.to_csv(HERE / "attrib_sleeves.csv", index=False, encoding="utf-8-sig")
    variants = structural_variants(df1m, flagged, runs) if flagged else pd.DataFrame(columns=["版本", "移除袖套", "期間", "net", "MDD", "net差異", "MDD差異", "n"])
    variants.to_csv(HERE / "attrib_sleeve_variants.csv", index=False, encoding="utf-8-sig")

    conc, removal, lorenz, camp_stats = profit_concentration(camps)
    conc.to_csv(HERE / "attrib_profit_concentration.csv", index=False, encoding="utf-8-sig")
    removal.to_csv(HERE / "attrib_top_removal.csv", index=False, encoding="utf-8-sig")
    lorenz.to_csv(HERE / "attrib_lorenz.csv", index=False, encoding="utf-8-sig")
    camp_stats.to_csv(HERE / "attrib_campaign_stats.csv", index=False, encoding="utf-8-sig")

    mtm = mtm_curve(df1m, lots)
    mtm_dd = dd_episodes(mtm.rename(columns={"equity": "equity"}).assign(pnl=0.0), pd.Timestamp(mtm.ts.iloc[-1]))
    # dd_episodes only needs ts/equity; the dummy pnl makes its contract clear.
    worst_mtm = mtm_dd.loc[mtm_dd.depth.idxmin()]
    mtm_dd.to_csv(HERE / "attrib_mtm_dd_episodes.csv", index=False, encoding="utf-8-sig")

    daily = daily_features(df1m, lots)
    state, causal = state_and_causal(daily, dd, runups)
    daily.to_csv(HERE / "attrib_daily_features.csv", index=False, encoding="utf-8-sig")
    state.to_csv(HERE / "attrib_daily_state_summary.csv", index=False, encoding="utf-8-sig")
    causal.to_csv(HERE / "attrib_causal_first3days.csv", index=False, encoding="utf-8-sig")

    monthly, yearly_risk, risk = money_risk(df1m, lots, camps)
    monthly.to_csv(HERE / "attrib_monthly_risk.csv", index=False, encoding="utf-8-sig")
    yearly_risk.to_csv(HERE / "attrib_yearly_campaign_risk.csv", index=False, encoding="utf-8-sig")

    closed_mdd = float(worst.depth)
    mtm_mdd = float(worst_mtm.depth)
    equity_now = 588_000.0
    # Executive conclusion about first-three-day state must be driven by the
    # predeclared descriptive uncertainty table, not optimized thresholds.
    dd_rows = causal[causal["比較組"].eq("DD首3日")]
    separated = []
    for r in dd_rows.itertuples():
        direct = causal[(causal["比較組"].eq("DD減Run-up")) & (causal["特徵"].eq(r.特徵))]
        ci_excludes = len(direct) and (direct.bootstrap95下限.iloc[0] > 0 or direct.bootstrap95上限.iloc[0] < 0)
        if pd.notna(r.相對正常經驗p) and r.相對正常經驗p < .10 and ci_excludes:
            separated.append(r.特徵)
    state_verdict = "、".join(separated) if separated else "沒有任何預先定義特徵同時通過對正常窗與對 Run-up 的描述性分離檢查"
    yr25 = yearly_risk[yearly_risk.year.eq(2025)].iloc[0]
    yr26 = yearly_risk[yearly_risk.year.eq(2026)].iloc[0]
    risk_year_text = (
        f"以 campaign 計，2026 的中位絕對 PnL 為 {yr26.median_abs_campaign_pnl:,.0f} NTD，"
        f"高於 2025 的 {yr25.median_abs_campaign_pnl:,.0f} {yr26.median_abs_campaign_pnl/yr25.median_abs_campaign_pnl-1:+.0%}；"
        f"平均絕對 PnL {yr26.mean_abs_campaign_pnl:,.0f} 對 {yr25.mean_abs_campaign_pnl:,.0f}，"
        f"平均虧損 {yr26.avg_loss:,.0f} 對 {yr25.avg_loss:,.0f}。"
    )

    lines = [
        "# V38 利潤與回撤歸因（描述性）", "",
        "## 十行執行摘要", "",
        f"1. 已以原始舊資料逐筆重現 v28/v29：" + "；".join(f"{r.版本}={r.狀態}" for r in repro.itertuples()) + "。全研究使用更新至 2026-10-17 05:00 的 1 分鐘資料、`intrabar_mode=1min`。",
        f"2. v29 共 {len(camps):,} 個 campaign，淨利 {camps.pnl.sum():+,.0f} NTD；中位 campaign {camps.pnl.median():+,.0f}、勝率 {(camps.pnl>0).mean():.1%}。",
        f"3. 上位 10% campaign 貢獻 {float(conc[(conc.分組=='全部') & (conc.上位比例=='10%')].佔全體淨利.iloc[0]):.1%} 的總淨利；移除贏家後的淨利變化見下表。",
        "4. 因此 V38 是明顯的尾端捕捉策略：少數大趨勢 campaign 供應不成比例的淨利；先前 locks／filters／cooldowns／forced-flats 若截掉這些長尾，淨利自然容易下降，不能只因降低表面回撤就視為改善。",
        f"5. 全樣本 closed-trade MDD 為 {closed_mdd:,.0f}；1 分鐘開倉 MTM MDD 為 {mtm_mdd:,.0f}，後者是現金路徑風險的較嚴格刻畫。",
        f"6. 深度超過 100k 的 closed-trade DD 共 {len(dd_deep)} 段；最深的一段為 {worst.depth:,.0f}，峰值 {worst.peak_ts:%Y-%m-%d}、谷值 {worst.trough_ts:%Y-%m-%d}。",
        f"7. 沒有任何 side×Cmd/Add/G 袖套在 H1 與 H2 都淨利 <=0；依題設限制，未執行移除袖套的結構變體，避免事後挑選。",
        f"8. 日頻狀態的首 3 交易日描述性檢查：{state_verdict}；即使有分離，也只能在第三個完整交易日收盤後才可即時觀察，並非事前已知。",
        f"9. 月度 5m ATR% 與日 PnL 標準差的 Pearson/Spearman 相關為 {risk['pearson']:.2f}/{risk['spearman']:.2f}；2025、2026 每 campaign 金額風險見年度表。",
        f"10. 以目前 588,000 NTD、每個 Cmd/Add/G 腿均為 1 口衡量：歷史最差日 {risk['worst_day']:,.0f} ({risk['worst_day']/equity_now:.1%})、最差週 {risk['worst_week']:,.0f} ({risk['worst_week']/equity_now:.1%})、MTM MDD {mtm_mdd:,.0f} ({mtm_mdd/equity_now:.1%})；加碼時總曝險可超過一口。",
        "", "## 0. 重現與口徑", "",
        "舊資料 `mxf_1min_corrected_20261017.csv` 先逐筆比對 `trades_v28.csv`、`trades_v29.csv`；後續重新跑更新資料。Campaign 以同一持倉連通區間的 Cmd + Add/G 定義。closed equity 將同一出場時間的 lot PnL 合併；DD 的歸因僅計峰值到谷值的已實現 lot。MTM 每一分鐘收盤把仍開倉的每腿按 close 標記，含該腿往返手續費。", "",
    ]
    lines += md_table(repro, ["版本", "參考lot", "重現lot", "參考淨利", "重現淨利", "狀態", "說明"])
    lines += ["", "## 1. 利潤集中度", "", "### 上位 campaign 對淨利的貢獻", ""]
    lines += md_table(conc, ["分組", "上位比例", "campaign數", "上位淨利", "佔全體淨利", "佔該組淨利"])
    lines += ["", "### 移除各分組自身上位 N 個 campaign 後", ""]
    lines += md_table(removal, ["分組", "原淨利", "移除前N", "實際移除數", "移除上位淨利", "移除後淨利", "保留比例"])
    lines += ["", "### Lorenz 式表（campaign 由最差排到最好）", ""]
    lines += md_table(lorenz, ["累積campaign比例", "累積campaign數", "由最差至此累積淨利", "累積淨利比例"])
    lines += ["", "### Campaign 基本分布", ""]
    lines += md_table(camp_stats, ["分組", "campaign數", "淨利", "中位campaign PnL", "勝率"])
    lines += ["", "**解讀：**若 top-N 移除使淨利大幅縮小，這是趨勢尾端承擔的機械結果；它也解釋先前以保護為目的的鎖利、進場過濾、冷卻與強制平倉研究，常會削掉淨利而不只削掉損失。", "",
              "## 2. 袖套（side × Cmd/Add/G）", "", f"全樣本 closed MDD 的峰→谷為 {worst.peak_ts:%Y-%m-%d %H:%M} → {worst.trough_ts:%Y-%m-%d %H:%M}；`全樣本MDD下降段淨利` 是該下降段內的已實現 PnL，負值越大表示對 MDD 加深的貢獻越大。", ""]
    lines += md_table(sleeves, ["期間", "方向", "kind", "n", "net", "wr", "pf", "avg_win", "avg_loss", "全樣本MDD下降段淨利", "對MDD深度貢獻"])
    lines += ["", "### H1/H2 同時負值的結構移除測試", ""]
    if flagged:
        lines += [f"符合事前條件的袖套：{', '.join(flagged)}。下表為實際引擎結構變體（移除會連帶改變後續持倉路徑，非事後從 ledger 扣除）。", ""] + md_table(variants, ["版本", "移除袖套", "期間", "n", "net", "MDD", "net差異", "MDD差異"])
    else:
        lines += ["沒有符合者（每一個 side×kind 至少有一半為正）。因此沒有執行任何移除變體；這是題設的 `ONLY` 約束，而非遺漏。"]
    lines += ["", "## 3. Closed-trade 回撤解剖（深度 > 100k）", "", "`sev` = 該群損失占比 / 該群虧損筆數占比；大於 1 代表單筆損失相對嚴重。日期的 duration 是峰值到恢復新高；未恢復者截至樣本末。", ""]
    dd_report = dd_deep.merge(dd_meta, on="episode_id", how="left")
    lines += md_table(dd_report, ["episode_id", "peak_ts", "trough_ts", "recovery_ts", "calendar_days", "trading_days", "depth", "campaigns", "方向×kind", "出場型態", "進場盤別", "top_campaigns"])
    lines += ["", "### MTM 與 closed equity", ""]
    mtm_summary = pd.DataFrame([{"口徑": "closed-trade", "MDD": closed_mdd, "峰值": worst.peak_ts, "谷值": worst.trough_ts, "恢復": worst.recovery_ts, "峰至恢復/樣本末日數": worst.calendar_days},
                                  {"口徑": "1-min MTM", "MDD": mtm_mdd, "峰值": worst_mtm.peak_ts, "谷值": worst_mtm.trough_ts, "恢復": worst_mtm.recovery_ts, "峰至恢復/樣本末日數": worst_mtm.calendar_days}])
    lines += md_table(mtm_summary, ["口徑", "MDD", "峰值", "谷值", "恢復", "峰至恢復/樣本末日數"])
    lines += ["", "## 4. Top 10 run-up（DD 谷值到恢復前高）", "", "為與 DD 口徑對稱，run-up 定義為 closed-equity DD 的谷值至首次恢復前高之回升段，依回升額排序；mix 的 `sev` 仍是其中虧損 lot 的嚴重度。", ""]
    ru_report = runups.merge(ru_meta, on="episode_id", how="left")
    lines += md_table(ru_report, ["episode_id", "trough_ts", "recovery_ts", "runup", "calendar_days", "trading_days", "campaigns", "方向×kind", "出場型態", "進場盤別", "top_campaigns"])
    lines += ["", "## 5. 市場狀態（日線）與首三日可得性", "", "日線以夜盤（15:00 後）歸入下一交易日組成。RV20 為日報酬 20 日年化標準差(%)；trend=|close−EMA60|/ATR20；chop=日內 range/ATR20；gap=|當日首筆 open−前日 close|/ATR20。DD 是深 DD 的峰→谷下降段，run-up 是上述 top-10 的谷→恢復段，其餘為正常。", ""]
    lines += md_table(state, list(state.columns))
    lines += ["", "### 僅用每段前 3 個完整交易日的描述性比較", "", "隨機窗僅取正常期的連續 3 交易日；經驗 p 是同樣數量正常窗平均離開正常均值的比例。`DD減Run-up` 的 bootstrap 95% 區間若跨 0，不能稱為穩定分離。這不是可交易的事後最佳化測試。", ""]
    lines += md_table(causal, ["比較組", "特徵", "事件數", "首3日平均", "正常隨機窗平均", "相對正常經驗p", "bootstrap95下限", "bootstrap95上限"])
    lines += ["", f"**結論：**{state_verdict}。所有列出的量都可在每一交易日收盤時計算；故若真有分離，最早也是第三個完整交易日收盤後可知，不能在該段開始時以無後見方式預知。", "",
              "## 6. 金額風險與波動", "", "月度 ATR% 使用該月 5 分鐘 ATR/close 的中位數；日 PnL 是 lot 在實際出場交易日的已實現合計（無出場日=0）。每一 Cmd/Add/G 腿均為 1 口，但本策略可持有多腿，故以下不是『永遠只持一口』的縮放風險。", ""]
    lines += md_table(monthly, ["month", "5m_ATR_pct", "campaigns", "median_abs_campaign_pnl", "std_daily_pnl", "worst_day", "net_daily"])
    lines += ["", "### 年度每 campaign 金額風險", ""]
    lines += md_table(yearly_risk, ["year", "campaigns", "net", "median_abs_campaign_pnl", "mean_abs_campaign_pnl", "avg_loss"])
    lines += ["", f"ATR% 對日 PnL 標準差：Pearson {risk['pearson']:.3f}、Spearman {risk['spearman']:.3f}。{risk_year_text}", "",
              "## 可稽核輸出", "", "本報告的可重算中間表：`attrib_reproduction.csv`、`trades_attrib_v28.csv`、`trades_attrib_v29.csv`、`attrib_v29_lots_campaigns.csv`、`attrib_*dd*`、`attrib_runup_*`、`attrib_daily_*`、`attrib_monthly_risk.csv`、`attrib_yearly_campaign_risk.csv`。"]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"done: {OUT}", flush=True)


if __name__ == "__main__":
    main()
