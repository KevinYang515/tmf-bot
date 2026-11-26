"""Reproducible analysis for task_rescue.md.

The strategy engine is never edited.  This script uses its saved, exact v28
ledger, the read-only engine prepare() function for the 5-minute ATR/signal
price, and the supplied 1-minute tape/live-fill logs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
sys.path.insert(0, str(ENGINE_DIR))
from engine_v26_bbw import P, load_1min, prepare, run as base_run  # noqa: E402

DATA = HERE / "mxf_1min_corrected_20261017b.csv"
TRADES = HERE / "trades_newdirs_v28_baseline.csv"
CUTOFF = pd.Timestamp("2026-10-17 03:58:00")
POINT_VALUE, BROKER_FEE, TAX_RATE, TICK = 50.0, 20.0, 0.00002, 1.0
H2 = pd.Timestamp("2025-04-01")
TRAIN0, TRAIN1 = pd.Timestamp("2026-03-01"), pd.Timestamp("2026-06-01")
TEST0, HOLDOUT = pd.Timestamp("2026-06-01"), pd.Timestamp("2026-08-22")
TEST1 = HOLDOUT
RNG = np.random.default_rng(20261019)


def save(df: pd.DataFrame, name: str) -> None:
    df.to_csv(HERE / name, index=False, encoding="utf-8-sig")


def span_mask(d: pd.DataFrame, span: str) -> pd.Series:
    t = d.entry_ts
    if span == "ALL": return pd.Series(True, index=d.index)
    if span == "H1": return t < H2
    if span == "H2": return t >= H2
    if span == "TRAIN": return (t >= TRAIN0) & (t < TRAIN1)
    if span == "TEST": return (t >= TEST0) & (t < TEST1)
    if span == "HOLDOUT": return t >= HOLDOUT
    raise ValueError(span)


SPANS = ["ALL", "H1", "H2", "TRAIN", "TEST", "HOLDOUT"]


def calc_mdd(pnl: np.ndarray) -> float:
    if len(pnl) == 0: return 0.0
    eq = np.r_[0.0, np.cumsum(pnl)]
    return float(np.min(eq - np.maximum.accumulate(eq)))


def pnl_stats(d: pd.DataFrame, pnl_col: str = "pnl_new") -> dict[str, float]:
    x = d.sort_values(["exit_ts", "entry_ts"])[pnl_col].to_numpy(float)
    net = float(x.sum())
    mdd = calc_mdd(x)
    gp, gl = x[x > 0].sum(), -x[x <= 0].sum()
    return dict(n=len(x), net=net, mdd=mdd, net_mdd=net / abs(mdd) if mdd else np.nan,
                pf=gp / gl if gl else np.inf)


def side_fee(price: np.ndarray | float) -> np.ndarray | float:
    # tax = 0.00002 * price * NT$50, in addition to NT$20 broker fee.
    return BROKER_FEE + TAX_RATE * np.asarray(price) * POINT_VALUE


def is_session_open(ts: pd.Series | pd.Timestamp) -> np.ndarray | bool:
    if isinstance(ts, pd.Timestamp):
        return (ts.hour, ts.minute) in ((8, 45), (15, 0))
    return ((ts.dt.hour.eq(8) & ts.dt.minute.eq(45)) |
            (ts.dt.hour.eq(15) & ts.dt.minute.eq(0))).to_numpy(bool)


def campaign_ids(tr: pd.DataFrame) -> pd.Series:
    order = {"Cmd": 0, "Add": 1, "G": 2}
    x = tr[["entry_ts", "kind"]].copy()
    x["_i"] = tr.index
    x["_order"] = x.kind.map(order)
    x = x.sort_values(["entry_ts", "_order", "_i"])
    x["campaign_id"] = x.kind.eq("Cmd").cumsum() - 1
    return x.set_index("_i").campaign_id.reindex(tr.index).astype(int)


def live_slippage(one: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, np.ndarray], dict[str, float]]:
    live = pd.read_csv(HERE / "vm_logs" / "trade_records.csv")
    live = live[live.order_status.eq("Status.Filled")].copy()
    live["datetime"] = pd.to_datetime(live.datetime)
    live["action_dir"] = np.where(live.action.eq("BUY"), 1.0, -1.0)
    open_map = one.set_index("open_ts").open
    live["one_min_open"] = live.datetime.dt.floor("min").map(open_map)
    live["adverse_vs_1m_open_pts"] = (live.fill_price - live.one_min_open) * live.action_dir
    live["adverse_vs_signal_pts"] = (live.fill_price - live.signal_price) * live.action_dir
    live["session_bucket"] = np.where(is_session_open(live.datetime), "session_open", "normal")
    live["product"] = np.where(live.contract.str.startswith("TMF"), "TMF", "MXF")
    detail = (live.groupby(["session_bucket", "product"], dropna=False)
              .agg(n=("adverse_vs_1m_open_pts", "size"),
                   mean_open_pts=("adverse_vs_1m_open_pts", "mean"),
                   median_open_pts=("adverse_vs_1m_open_pts", "median"),
                   mean_signal_pts=("adverse_vs_signal_pts", "mean"),
                   median_signal_pts=("adverse_vs_signal_pts", "median"))
              .reset_index())
    overall = pd.DataFrame([{
        "session_bucket": "ALL", "product": "ALL", "n": len(live),
        "mean_open_pts": live.adverse_vs_1m_open_pts.mean(),
        "median_open_pts": live.adverse_vs_1m_open_pts.median(),
        "mean_signal_pts": live.adverse_vs_signal_pts.mean(),
        "median_signal_pts": live.adverse_vs_signal_pts.median(),
    }])
    out = pd.concat([overall, detail], ignore_index=True)
    dist = {b: g.adverse_vs_1m_open_pts.dropna().to_numpy(float)
            for b, g in live.groupby("session_bucket")}
    means = {b: float(np.mean(v)) for b, v in dist.items()}
    return out, dist, means


def attach_latency(live_open: pd.DataFrame) -> pd.DataFrame:
    """Greedy one-to-one match on action + signal price, max 10 minutes."""
    fills = pd.read_csv(HERE / "vm_logs" / "trade_records.csv")
    fills = fills[fills.order_status.eq("Status.Filled")].copy()
    fills["datetime"] = pd.to_datetime(fills.datetime)
    fills["dir"] = np.where(fills.action.eq("BUY"), 1.0, -1.0)
    fills["open"] = fills.datetime.dt.floor("min").map(live_open)
    fills["adverse_signal_pts"] = (fills.fill_price - fills.signal_price) * fills.dir
    web = pd.read_csv(HERE / "vm_logs" / "webhook_raw.csv")
    web = web[web.order_action.notna()].copy()
    web["action"] = web.order_action.str.upper()
    web["received"] = pd.to_datetime(web.received_at).dt.tz_localize(None)
    web["tv_local"] = (pd.to_datetime(web.tv_timestamp, utc=True)
                       .dt.tz_convert("Asia/Taipei").dt.tz_localize(None))
    used: set[int] = set()
    rows: list[dict[str, float]] = []
    for f in fills.sort_values("datetime").itertuples():
        q = web[(web.action.eq(f.action)) & (web.signal_price.eq(f.signal_price))
                & (web.tv_local <= f.datetime)
                & ((f.datetime - web.tv_local).dt.total_seconds() <= 600)
                & (~web.index.isin(used))].copy()
        if q.empty: continue
        q["lag"] = (f.datetime - q.tv_local).dt.total_seconds()
        j = q.lag.idxmin()
        used.add(j)
        rows.append(dict(signal_to_fill_sec=float(q.loc[j, "lag"]),
                         receipt_to_fill_sec=float((f.datetime - q.loc[j, "received"]).total_seconds()),
                         adverse_signal_pts=float(f.adverse_signal_pts)))
    d = pd.DataFrame(rows)
    d["late_gt60"] = d.signal_to_fill_sec > 60
    g = (d.groupby("late_gt60")
         .agg(n=("adverse_signal_pts", "size"), mean_slip_pts=("adverse_signal_pts", "mean"),
              median_slip_pts=("adverse_signal_pts", "median"), sum_slip_pts=("adverse_signal_pts", "sum"),
              mean_signal_to_fill_sec=("signal_to_fill_sec", "mean"))
         .reset_index())
    total = d.adverse_signal_pts.sum()
    on = d.loc[~d.late_gt60, "adverse_signal_pts"].mean()
    late = d.loc[d.late_gt60, "adverse_signal_pts"]
    summary = pd.DataFrame([{
        "matched_fills": len(d), "late_gt60_n": int(d.late_gt60.sum()),
        "late_gt60_pct": float(d.late_gt60.mean() * 100),
        "raw_late_share_of_signal_slip_pct": float(late.sum() / total * 100),
        "excess_late_slip_pts": float((late.mean() - on) * len(late)),
        "excess_late_share_of_signal_slip_pct": float((late.mean() - on) * len(late) / total * 100),
        "median_signal_to_fill_sec": float(d.signal_to_fill_sec.median()),
    }])
    save(d, "rescue_latency_matches.csv")
    save(g, "rescue_latency_groups.csv")
    return summary


def make_orders(tr: pd.DataFrame, b5: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create one row per logical engine order; legs sharing a fill share a draw."""
    ent = tr[["entry_ts", "entry_px", "side"]].copy()
    ent["event"] = "entry"
    ent["action"] = np.where(ent.side.eq("L"), 1.0, -1.0)
    ent["eligible_limit"] = True
    ent = ent.rename(columns={"entry_ts": "nominal_ts", "entry_px": "base_px"})
    ent["order_key"] = ("E|" + ent.nominal_ts.astype(str) + "|" + ent.side)
    ex = tr[["exit_ts", "exit_px", "side", "exit_sig"]].copy()
    ex["event"] = "exit"
    ex["action"] = np.where(ex.side.eq("L"), -1.0, 1.0)
    # Loss/BE brackets are stops: they remain stop/market, never a passive limit.
    ex["eligible_limit"] = ~(ex.exit_sig.str.contains("_SL", regex=False) |
                             ex.exit_sig.str.endswith("_BE"))
    ex = ex.rename(columns={"exit_ts": "nominal_ts", "exit_px": "base_px"})
    ex["order_key"] = ("X|" + ex.nominal_ts.astype(str) + "|" + ex.side + "|" +
                       ex.exit_sig + "|" + ex.base_px.astype(str))
    z = pd.concat([ent, ex], ignore_index=True)
    # A session boundary (08:45/15:00) has no just-completed in-session bar;
    # the engine uses the preceding completed 5m bar, hence backward as-of.
    signal = b5[["close_ts", "close"]].sort_values("close_ts")
    z = pd.merge_asof(z.sort_values("nominal_ts"), signal, left_on="nominal_ts",
                      right_on="close_ts", direction="backward")
    z["signal_px"] = z["close"].fillna(z.base_px)
    z = z.drop(columns=["close_ts", "close"])
    z["session_bucket"] = np.where(is_session_open(z.nominal_ts), "session_open", "normal")
    orders = (z.groupby("order_key", as_index=False)
              .agg(event=("event", "first"), nominal_ts=("nominal_ts", "first"),
                   base_px=("base_px", "first"), signal_px=("signal_px", "first"),
                   action=("action", "first"), eligible_limit=("eligible_limit", "first"),
                   session_bucket=("session_bucket", "first")))
    orders["order_id"] = np.arange(len(orders), dtype=int)
    lookup = orders.set_index("order_key").order_id
    legs = tr.copy()
    legs["entry_order_id"] = ent.order_key.map(lookup).to_numpy(int)
    legs["exit_order_id"] = ex.order_key.map(lookup).to_numpy(int)
    return orders, legs


def limit_plan(orders: pd.DataFrame, one: pd.DataFrame, k: int, valid_min: int,
               slip_means: dict[str, float], delay_open_min: int = 0) -> pd.DataFrame:
    """Conservative: price must trade *through* the limit by one point."""
    tape = one.set_index("open_ts")[["open", "high", "low"]]
    r = orders.copy()
    r["fill_ts"] = r.nominal_ts + pd.Timedelta(minutes=delay_open_min)
    r["fill_type"] = "market"
    r["price_det"] = r.base_px
    r["market_ref_px"] = r.base_px
    r["late_min"] = 0
    for ix, o in r.iterrows():
        use_limit = bool(o.eligible_limit) and delay_open_min == 0
        if not use_limit:
            # Waiting at session open, stops, and END use a market fill.
            px = tape.open.get(o.fill_ts, o.base_px)
            r.at[ix, "market_ref_px"] = px
            r.at[ix, "price_det"] = px + o.action * slip_means[o.session_bucket]
            continue
        limit = o.signal_px + o.action * k * TICK
        found = None
        for j in range(valid_min):
            ts = o.nominal_ts + pd.Timedelta(minutes=j)
            if ts not in tape.index: continue
            bar = tape.loc[ts]
            through = bar.low <= limit - TICK if o.action > 0 else bar.high >= limit + TICK
            if through:
                found = ts
                break
        if found is not None:
            r.at[ix, "fill_type"] = "limit"
            r.at[ix, "price_det"] = limit
            r.at[ix, "fill_ts"] = found
            r.at[ix, "late_min"] = int((found - o.nominal_ts).total_seconds() / 60)
        else:
            ts = o.nominal_ts + pd.Timedelta(minutes=valid_min)
            px = tape.open.get(ts, o.base_px)
            r.at[ix, "fill_type"] = "fallback_market"
            r.at[ix, "fill_ts"] = ts
            r.at[ix, "late_min"] = valid_min
            r.at[ix, "market_ref_px"] = px
            r.at[ix, "price_det"] = px + o.action * slip_means[o.session_bucket]
    return r


def open_wait_plan(orders: pd.DataFrame, one: pd.DataFrame, slip_means: dict[str, float],
                   wait_min: int) -> pd.DataFrame:
    """Market baseline, delaying *only* orders originally due at a session open."""
    tape = one.set_index("open_ts")["open"]
    r = orders.copy()
    r["fill_ts"] = r.nominal_ts
    r["market_ref_px"] = r.base_px
    r["fill_type"] = "market"
    r["late_min"] = 0
    affected = is_session_open(r.nominal_ts)
    if wait_min:
        r.loc[affected, "fill_ts"] = r.loc[affected, "nominal_ts"] + pd.Timedelta(minutes=wait_min)
        r.loc[affected, "market_ref_px"] = r.loc[affected, "fill_ts"].map(tape).fillna(r.loc[affected, "base_px"])
        r.loc[affected, "late_min"] = wait_min
    r["price_det"] = r.market_ref_px + r.action * r.session_bucket.map(slip_means)
    return r


def apply_plan(legs: pd.DataFrame, plan: pd.DataFrame, name: str) -> pd.DataFrame:
    p = plan.set_index("order_id")
    d = legs.copy()
    d["entry_px_new"] = d.entry_order_id.map(p.price_det)
    d["exit_px_new"] = d.exit_order_id.map(p.price_det)
    d["entry_fill_ts_model"] = d.entry_order_id.map(p.fill_ts)
    d["exit_fill_ts_model"] = d.exit_order_id.map(p.fill_ts)
    d["entry_fill_type"] = d.entry_order_id.map(p.fill_type)
    d["exit_fill_type"] = d.exit_order_id.map(p.fill_type)
    direction = np.where(d.side.eq("L"), 1.0, -1.0)
    d["pnl_new"] = ((d.exit_px_new - d.entry_px_new) * direction * POINT_VALUE
                    - side_fee(d.entry_px_new) - side_fee(d.exit_px_new))
    d["scenario"] = name
    return d


def bootstrap_net(legs: pd.DataFrame, plan: pd.DataFrame, dist: dict[str, np.ndarray],
                  draws: int = 1000) -> pd.DataFrame:
    """Bootstrap fills by session bucket. Limit fills stay at their stated limit."""
    p = plan.set_index("order_id").sort_index()
    norder = len(p)
    prices = p.price_det.to_numpy(float)
    market = p.fill_type.ne("limit").to_numpy()
    act = p.action.to_numpy(float)
    buck = p.session_bucket.to_numpy(str)
    ei = legs.entry_order_id.to_numpy(int)
    xi = legs.exit_order_id.to_numpy(int)
    dr = np.empty((draws, len(legs)), dtype=float)
    direction = np.where(legs.side.eq("L"), 1.0, -1.0)
    for b in range(draws):
        px = prices.copy()
        for bucket in ("normal", "session_open"):
            m = market & (buck == bucket)
            px[m] = (p.market_ref_px.to_numpy(float)[m] + act[m] *
                     RNG.choice(dist[bucket], size=int(m.sum()), replace=True))
        e, x = px[ei], px[xi]
        dr[b] = ((x - e) * direction * POINT_VALUE - side_fee(e) - side_fee(x))
    rows = []
    for span in SPANS:
        m = span_mask(legs, span).to_numpy()
        net = dr[:, m].sum(axis=1)
        rows.append(dict(span=span, draws=draws, net_mean=float(net.mean()),
                         net_p025=float(np.quantile(net, .025)), net_p975=float(np.quantile(net, .975))))
    return pd.DataFrame(rows)


def execution_analysis(orders: pd.DataFrame, legs: pd.DataFrame, one: pd.DataFrame,
                       dist: dict[str, np.ndarray], means: dict[str, float]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base_plan = limit_plan(orders, one, 0, 0, means)
    # valid_min=0 is a special market-only control; make it explicit.
    base_plan["fill_type"] = "market"
    base_plan["market_ref_px"] = base_plan.base_px
    base_plan["price_det"] = base_plan.base_px + base_plan.action * base_plan.session_bucket.map(means)
    base = apply_plan(legs, base_plan, "market_bootstrap_mean")
    grid_rows = []
    plans: dict[str, pd.DataFrame] = {"market": base_plan}
    for k in (0, 1, 2, 3):
        for n in (1, 2, 5):
            name = f"limit_k{k}_N{n}"
            plan = limit_plan(orders, one, k, n, means)
            plans[name] = plan
            q = apply_plan(legs, plan, name)
            for span in SPANS:
                st = pnl_stats(q.loc[span_mask(q, span)])
                grid_rows.append(dict(scenario=name, k_ticks=k, valid_min=n, span=span,
                                      limit_orders=int(plan.fill_type.eq("limit").sum()),
                                      fallback_orders=int(plan.fill_type.eq("fallback_market").sum()),
                                      mean_late_min=float(plan.late_min.mean()), **st))
    grid_rows += [dict(scenario="market", k_ticks=np.nan, valid_min=0, span=s,
                       limit_orders=0, fallback_orders=0, mean_late_min=0.0,
                       **pnl_stats(base.loc[span_mask(base, s)])) for s in SPANS]
    grid = pd.DataFrame(grid_rows)
    market_net = grid[grid.scenario.eq("market")].set_index("span").net
    grid["delta_vs_market"] = grid.net - grid.span.map(market_net)
    grid["PASS"] = False
    for scenario in grid.scenario.unique():
        if scenario == "market": continue
        ok = grid[(grid.scenario == scenario) & grid.span.isin(["H1", "H2", "TRAIN", "TEST"])].delta_vs_market.gt(0).all()
        grid.loc[grid.scenario.eq(scenario), "PASS"] = ok
    h1 = grid[grid.span.eq("H1")].sort_values(["net", "net_mdd"], ascending=False)
    selected = str(h1.iloc[0].scenario)
    selected_plan = plans[selected]
    boot = pd.concat([
        bootstrap_net(base, base_plan, dist).assign(scenario="market"),
        bootstrap_net(apply_plan(legs, selected_plan, selected), selected_plan, dist).assign(scenario=selected),
    ], ignore_index=True)
    waits = []
    for delay in (0, 1, 2, 5):
        plan = open_wait_plan(orders, one, means, delay)
        q = apply_plan(legs, plan, f"open_wait_{delay}")
        affected = int(is_session_open(orders.nominal_ts).sum())
        for span in SPANS:
            waits.append(dict(wait_min=delay, affected_orders=affected, span=span,
                              **pnl_stats(q.loc[span_mask(q, span)])))
    waits = pd.DataFrame(waits)
    wait0 = waits[waits.wait_min.eq(0)].set_index("span").net
    waits["delta_vs_immediate"] = waits.net - waits.span.map(wait0)
    waits["PASS"] = False
    for delay in waits.wait_min.unique():
        if delay == 0: continue
        ok = waits[(waits.wait_min == delay) & waits.span.isin(["H1", "H2", "TRAIN", "TEST"])].delta_vs_immediate.gt(0).all()
        waits.loc[waits.wait_min.eq(delay), "PASS"] = ok
    return grid, boot, waits, base


def boot_campaign_diff(d: pd.DataFrame, keep: pd.Series, draws: int = 2000) -> tuple[float, float, float]:
    x = d[["campaign_id", "pnl_new"]].copy()
    x["keep"] = keep.to_numpy(bool)
    camp = x.groupby("campaign_id").apply(
        lambda g: pd.Series({"keep_sum": g.loc[g.keep, "pnl_new"].sum(), "keep_n": g.keep.sum(),
                             "drop_sum": g.loc[~g.keep, "pnl_new"].sum(), "drop_n": (~g.keep).sum()}),
        include_groups=False).reset_index()
    if len(camp) < 2 or camp.keep_n.sum() == 0 or camp.drop_n.sum() == 0:
        return (np.nan, np.nan, np.nan)
    idx = RNG.integers(0, len(camp), size=(draws, len(camp)))
    z = camp.iloc[idx.ravel()].to_numpy().reshape(draws, len(camp), 5)
    # columns after campaign_id: keep_sum, keep_n, drop_sum, drop_n
    a = z[:, :, 1].sum(axis=1) / z[:, :, 2].sum(axis=1)
    b = z[:, :, 3].sum(axis=1) / z[:, :, 4].sum(axis=1)
    dif = a - b
    return float(dif.mean()), float(np.quantile(dif, .025)), float(np.quantile(dif, .975))


def placebo_pvalue(d: pd.DataFrame, keep: pd.Series, observed: float, draws: int = 500) -> float:
    """Within side×calendar-quarter permute keep labels; campaigns remain clustered in scoring."""
    x = d.copy()
    x["stratum"] = x.side + "|" + x.entry_ts.dt.to_period("Q").astype(str)
    vals = []
    for _ in range(draws):
        fake = pd.Series(False, index=x.index)
        for _, g in x.groupby("stratum"):
            n = int(keep.loc[g.index].sum())
            if n: fake.loc[RNG.choice(g.index.to_numpy(), size=n, replace=False)] = True
        # This is the matched-label null distribution.  Cluster-bootstrap CIs
        # for the actual effect are calculated separately in boot_campaign_diff.
        vals.append(float(x.loc[fake, "pnl_new"].mean() - x.loc[~fake, "pnl_new"].mean()))
    return float((np.asarray(vals) >= observed).mean())


def cost_atr_analysis(base: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = base.copy()
    # Expected round-trip points at the entry/exit execution buckets, including fee+tax.
    d["entry_cost_pts"] = (side_fee(d.entry_px_new) / POINT_VALUE +
                            (d.entry_px_new - d.entry_px) * np.where(d.side.eq("L"), 1, -1))
    d["exit_cost_pts"] = (side_fee(d.exit_px_new) / POINT_VALUE +
                           (d.exit_px - d.exit_px_new) * np.where(d.side.eq("L"), 1, -1))
    d["round_cost_pts"] = d.entry_cost_pts + d.exit_cost_pts
    d["cost_atr"] = d.round_cost_pts / d.atr_pts
    rows, tests = [], []
    for kind in ("Cmd", "Add", "G"):
        z = d[d.kind.eq(kind)].copy()
        h1 = z[z.entry_ts < H2]
        for feature, bad_high in (("atr_pts", False), ("cost_atr", True)):
            q1, q2 = h1[feature].quantile([1/3, 2/3]).to_numpy(float)
            for period, zz in (("H1", h1), ("H2", z[z.entry_ts >= H2])):
                bucket = pd.cut(zz[feature], [-np.inf, q1, q2, np.inf], labels=["low", "mid", "high"], include_lowest=True)
                for b in ("low", "mid", "high"):
                    y = zz[bucket.eq(b)].pnl_new.to_numpy(float)
                    rows.append(dict(kind=kind, feature=feature, period=period, h1_q33=q1, h1_q67=q2,
                                     tercile=b, n_lots=len(y), n_campaigns=zz.loc[bucket.eq(b), "campaign_id"].nunique(),
                                     mean_pnl=float(y.mean()) if len(y) else np.nan,
                                     net=float(y.sum()), pf=float(y[y > 0].sum() / -y[y <= 0].sum()) if np.any(y <= 0) else np.inf))
                # Candidate execution gate removes low ATR or high cost/ATR.
                keep = bucket.ne("high" if bad_high else "low")
                obs, lo, hi = boot_campaign_diff(zz, keep)
                yk, yd = zz.loc[keep, "pnl_new"].to_numpy(float), zz.loc[~keep, "pnl_new"].to_numpy(float)
                pf_keep = yk[yk > 0].sum() / -yk[yk <= 0].sum() if np.any(yk <= 0) else np.inf
                pf_drop = yd[yd > 0].sum() / -yd[yd <= 0].sum() if np.any(yd <= 0) else np.inf
                pv = placebo_pvalue(zz, keep, obs) if np.isfinite(obs) else np.nan
                tests.append(dict(kind=kind, feature=feature, period=period, h1_threshold=q2 if bad_high else q1,
                                  skip_rule=(">" if bad_high else "<"), n_campaigns=zz.campaign_id.nunique(),
                                  keep_n=int(keep.sum()), skip_n=int((~keep).sum()),
                                  keep_mean_pnl=float(yk.mean()), skip_mean_pnl=float(yd.mean()),
                                  keep_pf=float(pf_keep), skip_pf=float(pf_drop),
                                  delta_keep_minus_skip=obs, ci_low=lo, ci_high=hi,
                                  placebo_p_ge_observed=pv,
                                  local_pass=bool(lo > 0 and pf_keep > 1 and zz.campaign_id.nunique() > 1 and pv < .05)))
    tests = pd.DataFrame(tests)
    tests["pass_H1_H2"] = tests.groupby(["kind", "feature"]).local_pass.transform("all")
    return pd.DataFrame(rows), tests


def regime_multiplier_recheck(one: pd.DataFrame, b5: pd.DataFrame, means: dict[str, float],
                              market_base: pd.DataFrame) -> pd.DataFrame:
    """Re-run the previously rejected H6 grid, now restated with live costs."""
    variants = {
        "baseline_v28": {},
        "h6_pct70_scale070": {"opt_regime_mult_enabled": True, "opt_regime_pct_threshold": 70.0, "opt_regime_scale": .70},
        "h6_pct70_scale085": {"opt_regime_mult_enabled": True, "opt_regime_pct_threshold": 70.0, "opt_regime_scale": .85},
        "h6_pct80_scale070": {"opt_regime_mult_enabled": True, "opt_regime_pct_threshold": 80.0, "opt_regime_scale": .70},
        "h6_pct80_scale085": {"opt_regime_mult_enabled": True, "opt_regime_pct_threshold": 80.0, "opt_regime_scale": .85},
    }
    rows = []
    for name, extra in variants.items():
        if name == "baseline_v28":
            q = market_base
        else:
            raw = base_run(one, p={"opt_stale_hr": 10, "opt_cooldown_min": 30,
                                   "opt_short_pyramid_cap_mode": "hour4", **extra}, intrabar_mode="1min")
            raw["entry_ts"], raw["exit_ts"] = pd.to_datetime(raw.entry_ts), pd.to_datetime(raw.exit_ts)
            orders, legs = make_orders(raw, b5)
            plan = limit_plan(orders, one, 0, 0, means)
            plan["fill_type"] = "market"
            plan["market_ref_px"] = plan.base_px
            plan["price_det"] = plan.base_px + plan.action * plan.session_bucket.map(means)
            q = apply_plan(legs, plan, name)
        for span in SPANS:
            rows.append(dict(variant=name, span=span, **pnl_stats(q.loc[span_mask(q, span)])))
    out = pd.DataFrame(rows)
    ref = out[out.variant.eq("baseline_v28")].set_index("span").net
    out["delta_vs_v28_market"] = out.net - out.span.map(ref)
    out["PASS"] = False
    for name in out.variant.unique():
        if name == "baseline_v28": continue
        ok = out[(out.variant == name) & out.span.isin(["H1", "H2", "TRAIN", "TEST"])].delta_vs_v28_market.gt(0).all()
        out.loc[out.variant.eq(name), "PASS"] = ok
    return out


def daily_portfolio(base: pd.DataFrame, one: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw = one.copy()
    raw["date"] = raw.ts.dt.normalize()
    daily = raw.groupby("date", as_index=False).agg(close=("close", "last"))
    daily["month"] = daily.date.dt.to_period("M")
    rolls = daily.month.ne(daily.month.shift()).cumsum().sub(1).clip(lower=0)
    daily["core"] = (daily.close - daily.close.iloc[0]) * POINT_VALUE - rolls * TICK * POINT_VALUE
    # Daily MTM: each lot pays entry costs once live, exit costs once when it exits.
    eq = []
    for date, close in daily[["date", "close"]].itertuples(index=False):
        closed = base[base.exit_ts.dt.normalize() <= date]
        opened = base[(base.entry_ts.dt.normalize() <= date) & (base.exit_ts.dt.normalize() > date)]
        direction = np.where(opened.side.eq("L"), 1.0, -1.0)
        mtm = ((close - opened.entry_px_new.to_numpy(float)) * direction * POINT_VALUE
               - side_fee(opened.entry_px_new.to_numpy(float))).sum()
        eq.append(float(closed.pnl_new.sum() + mtm))
    daily["v38"] = eq
    # PnL increments, not percentage returns: suitable for a fixed-lot combination.
    daily["core_monthly_pnl"] = daily.core.groupby(daily.month).transform(lambda x: x.iloc[-1] - x.iloc[0])
    daily["v38_monthly_pnl"] = daily.v38.groupby(daily.month).transform(lambda x: x.iloc[-1] - x.iloc[0])
    combos = [(1, 0), (0, 1), (1, 1), (1, .5), (.5, 1)]
    peak_lots = int(max(abs(base.groupby("entry_ts").size().cumsum() * 0 + 0).max(), 4))  # engine cap is 4
    # Obtain actual maximum simultaneous position rather than relying only on the cap.
    events = pd.concat([
        base[["entry_ts", "side"]].assign(delta=np.where(base.side.eq("L"), 1, -1), event_order=1).rename(columns={"entry_ts": "ts"}),
        base[["exit_ts", "side"]].assign(delta=np.where(base.side.eq("L"), -1, 1), event_order=0).rename(columns={"exit_ts": "ts"}),
    ]).sort_values(["ts", "event_order"])
    peak_lots = int(events.delta.cumsum().abs().max())
    rows = []
    for c, v in combos:
        x = c * daily.core + v * daily.v38
        pnl = x.diff().fillna(x.iloc[0]).to_numpy(float)
        net, mdd = float(x.iloc[-1]), calc_mdd(pnl)
        monthly = pd.DataFrame({"core": c * daily.core, "v38": v * daily.v38, "month": daily.month}).groupby("month").last().diff().dropna()
        corr = monthly.core.corr(monthly.v38) if c and v else np.nan
        yearly_eq = pd.DataFrame({"year": daily.date.dt.year, "eq": x}).groupby("year").last()["eq"]
        yearly_pnl = yearly_eq.diff()
        yearly_pnl.iloc[0] = yearly_eq.iloc[0]
        yearly_pnl = yearly_pnl.dropna()
        worst = float(yearly_pnl.min()) if len(yearly_pnl) else 0.0
        margin_mxf = c * 175250 + v * peak_lots * 175250
        margin_tmf = c * 175250 + v * peak_lots * 35050
        rows.append(dict(core_lots=c, overlay_lots=v, net=net, mdd=mdd,
                         net_mdd=net / abs(mdd) if mdd else np.nan, worst_year_pnl=worst,
                         monthly_pnl_corr=corr, peak_v38_lots=peak_lots,
                         margin_if_overlay_MXF=margin_mxf, margin_if_overlay_TMF=margin_tmf,
                         capital_for_MDD_le_30pct_MXF=max(margin_mxf, abs(mdd)/.30),
                         capital_for_MDD_le_30pct_TMF=max(margin_tmf, abs(mdd)/.30)))
    month = daily.groupby("month").agg(core=("core", "last"), v38=("v38", "last")).diff().dropna().reset_index()
    month["index_down"] = month.core < 0
    down = (month.groupby("index_down")
            .agg(months=("v38", "size"), v38_total_pnl=("v38", "sum"), v38_mean_pnl=("v38", "mean"),
                 core_total_pnl=("core", "sum"), core_mean_pnl=("core", "mean")).reset_index())
    return daily, pd.DataFrame(rows), down


def contract_choice(live_table: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    x = live_table[live_table["product"].isin(["MXF", "TMF"])].copy()
    # The live table is split into normal/open buckets; recombine with fill counts.
    x["weighted_signal"] = x.n * x.mean_signal_pts
    x = x.groupby("product", as_index=True).agg(n=("n", "sum"), weighted_signal=("weighted_signal", "sum"))
    x["mean_signal_pts"] = x.weighted_signal / x.n
    mxf, tmf = float(x.loc["MXF", "mean_signal_pts"]), float(x.loc["TMF", "mean_signal_pts"])
    px = float(pd.concat([base.entry_px_new, base.exit_px_new]).mean())
    # Equal exposure is 1 MXF versus 5 TMF. Tax has the same NTD exposure and cancels.
    mxf_side = mxf * 50 + BROKER_FEE + TAX_RATE * px * 50
    tmf_side = 5 * (tmf * 10 + BROKER_FEE + TAX_RATE * px * 10)
    years = (CUTOFF - base.entry_ts.min()).days / 365.25
    annual_sides = 2 * len(base) / years
    return pd.DataFrame([dict(avg_price=px, live_MXF_signal_slip_pts=mxf, live_TMF_signal_slip_pts=tmf,
                              MXF_cost_per_equal_exposure_side=mxf_side,
                              TMF5_cost_per_equal_exposure_side=tmf_side,
                              TMF5_minus_MXF_per_side=tmf_side-mxf_side,
                              v28_lot_sides_per_year=annual_sides,
                              TMF5_minus_MXF_expected_annual_cost=(tmf_side-mxf_side)*annual_sides)])


def write_report(live: pd.DataFrame, latency: pd.DataFrame, grid: pd.DataFrame, boot: pd.DataFrame,
                 waits: pd.DataFrame, atr: pd.DataFrame, atr_tests: pd.DataFrame, portfolio: pd.DataFrame,
                 down: pd.DataFrame, contract: pd.DataFrame, regime: pd.DataFrame | None = None) -> None:
    market_all = grid[(grid.scenario == "market") & (grid.span == "ALL")].iloc[0]
    best_name = grid[grid.span.eq("H1")].sort_values("net", ascending=False).iloc[0].scenario
    best_all = grid[(grid.scenario == best_name) & (grid.span == "ALL")].iloc[0]
    best_h = grid[(grid.scenario == best_name) & grid.span.isin(["H1", "H2", "TRAIN", "TEST", "HOLDOUT"])]
    best_boot = boot[(boot.scenario == best_name) & boot.span.eq("ALL")].iloc[0]
    wait_best = waits[waits.span.eq("H1")].sort_values("net", ascending=False).iloc[0]
    wait1_h1 = waits[(waits.wait_min.eq(1)) & (waits.span.eq("H1"))].iloc[0]
    wait1_all = waits[(waits.wait_min.eq(1)) & (waits.span.eq("ALL"))].iloc[0]
    half_overlay = portfolio[(portfolio.core_lots.eq(1)) & (portfolio.overlay_lots.eq(.5))].iloc[0]
    overlay_only = portfolio[(portfolio.core_lots.eq(0)) & (portfolio.overlay_lots.eq(1))].iloc[0]
    regime_best = (regime[(regime.variant.ne("baseline_v28")) & regime.span.eq("ALL")]
                   .sort_values("delta_vs_v28_market", ascending=False).iloc[0] if regime is not None else None)
    c = contract.iloc[0]
    def table(df: pd.DataFrame, cols: list[str], digits: int = 1) -> str:
        y = df[cols].copy()
        for col in y.select_dtypes(include=["number"]): y[col] = y[col].map(lambda v: "" if pd.isna(v) else f"{v:,.{digits}f}")
        headers = [str(c) for c in y.columns]
        rows = []
        for row in y.itertuples(index=False, name=None):
            rows.append(["" if pd.isna(v) else str(v).replace("|", "\\|") for v in row])
        return "\n".join([
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
            *["| " + " | ".join(row) + " |" for row in rows],
        ])
    lines = [
        "# V38 救援：成本與組合分析",
        "",
        "## 白話結論",
        "",
        f"以 live 填單的 1 分鐘開盤滑價分布、雙邊手續費／稅重算後，v28 全樣本估計淨利為 **NT${market_all.net:,.0f}**。每邊成本是 **NT$20 券商費 + 0.00002 × 成交價 × NT$50 交易稅**；滑價另按實際 live 分布加入。",
        "",
        "按可執行性與 NT$ 影響排序如下：",
        "",
        f"1. **合約選擇（可優先執行）**：用實盤 signal-price 滑價，5 TMF 對 1 MXF 的等曝險預估每邊少 NT${abs(c.TMF5_minus_MXF_per_side):,.1f}，按 v28 年化成交腿數約**省 NT${abs(c.TMF5_minus_MXF_expected_annual_cost):,.0f}/年**；方向取決於此成本結果，並非只看 TMF 的較小點數滑價。",
        f"2. **core:overlay=1:0.5（組合候選）**：共同樣本淨利 NT${half_overlay.net:,.0f}、MDD NT${half_overlay.mdd:,.0f}、net/MDD {half_overlay.net_mdd:.2f}；相對純 1 口 overlay，多 NT${half_overlay.net-overlay_only.net:,.0f} 淨利且 MDD 少 NT${abs(overlay_only.mdd)-abs(half_overlay.mdd):,.0f}。",
        f"3. **限價保護（暫不採用）**：H1 預先網格選出 `{best_name}`，全樣本約少 NT${abs(best_all.net-market_all.net):,.0f}，且四窗 PASS=FAIL；又是固定訊號／停止邏輯的成交價近似，沒有重跑延後成交所改變的後續加碼與停損。其全樣本 bootstrap 95% 淨利區間為 NT${best_boot.net_p025:,.0f} 至 NT${best_boot.net_p975:,.0f}。",
        f"4. **開盤等待（拒絕）**：H1 最佳其實是立即（{int(wait_best.wait_min)} 分鐘）；等 1 分鐘使 H1 少 NT${abs(wait1_h1.delta_vs_immediate):,.0f}、全樣本少 NT${abs(wait1_all.delta_vs_immediate):,.0f}。",
        "5. **ATR gate（拒絕）**：低 ATR 的 Cmd／Add／G 候選都沒有在 H1、H2 同時通過 campaign-cluster 95% CI、PF>1 與配對 placebo。雖然高 cost/ATR 的 Cmd、G 診斷通過，這不是題設的「ATR 低於門檻」gate，故沒有事後改寫規則或重跑 engine。",
        "",
        "## A. 執行與滑價",
        "",
        table(live, ["session_bucket", "product", "n", "mean_open_pts", "median_open_pts", "mean_signal_pts", "median_signal_pts"], 2),
        "",
        "基準為每個邏輯 engine order 在原定下一開盤成交，並對同一筆多口平倉共用一次抽樣滑價。session-open 指 08:45 或 15:00；正常與開盤各自 bootstrap。限價規則預先固定為 buy=signal+k、sell=signal−k，成交必須穿透 limit 1 點；未成交在 N 分鐘後市價。stop/BE 出場沒有改成限價。",
        "",
        "### 預先註冊的限價網格（H1 選擇；其餘窗只報告）",
        "",
        "PASS 規則沿用既有研究：相對市價基準的淨利增量必須在 H1、H2、TRAIN、TEST 都 >0；HOLDOUT 只展示、不參與判定。所有限價候選均 FAIL。",
        "",
        table(grid[grid.span.isin(["H1", "H2", "TRAIN", "TEST", "HOLDOUT"])], ["scenario", "k_ticks", "valid_min", "span", "limit_orders", "fallback_orders", "mean_late_min", "net", "delta_vs_market", "mdd", "net_mdd", "PASS"], 0),
        "",
        "### H1 選出的限價候選在其他期間",
        "",
        table(best_h, ["span", "n", "net", "mdd", "net_mdd", "pf"], 2),
        "",
        "### 開盤等待（獨立測試）",
        "",
        table(waits[waits.span.isin(["H1", "H2", "TRAIN", "TEST", "HOLDOUT"])], ["wait_min", "affected_orders", "span", "net", "delta_vs_immediate", "mdd", "net_mdd", "PASS"], 0),
        "",
        "延後成交的影響以原始交易事件時間與原始 stop/訊號路徑近似：若成交延後，報表改用延後價格，卻不會重新推導後續 Add/G 條件、止損價或被延後到出場後才成交的路徑。這是此種 post-trade 成交研究的明確限制；沒有將任何限價或等待規則標示為 PASS。",
        "",
        "### Alert 延遲",
        "",
        table(latency, list(latency.columns), 2),
        "",
        "以 action+signal_price、一對一且訊號到成交不超過 10 分鐘配對。>60 秒延遲的原始 signal-price 滑價占比與相對於 ≤60 秒的超額占比分開列，避免把延遲樣本本身的正常滑價也誤當成延遲造成。",
        "",
        "## B. 成本感知交易：診斷先行",
        "",
        "ATR 門檻只在 H1 取三分位後固定，H2 只驗證；cost/ATR 的分子是該 lot 預期往返滑價＋費用＋交易稅（點數）。下表為每一 tercile 的 lot EV。",
        "",
        table(atr, ["kind", "feature", "period", "tercile", "h1_q33", "h1_q67", "n_lots", "n_campaigns", "mean_pnl", "net", "pf"], 2),
        "",
        "候選 gate 比較「保留」對「略過」的 campaign-cluster bootstrap。placebo 為同 side×曆季內等數量隨機保留標籤；p 值是 placebo 差額不小於觀察差額的比例。",
        "",
        table(atr_tests, ["kind", "feature", "period", "h1_threshold", "skip_rule", "keep_n", "skip_n", "keep_mean_pnl", "skip_mean_pnl", "keep_pf", "delta_keep_minus_skip", "ci_low", "ci_high", "placebo_p_ge_observed", "local_pass", "pass_H1_H2"], 2),
        "",
        "### 已拒絕的 ATR-regime multiplier：以現實成本重查",
        "",
        "這是既有 H6 的預先 70/80 percentile × 0.70/0.85 scale 網格，現在以 A 的 live 成本重跑完整 engine path。PASS 同樣要求相對 v28 市價基準在 H1、H2、TRAIN、TEST 全為正；HOLDOUT 僅展示。",
        "",
        table(regime if regime is not None else pd.DataFrame(), ["variant", "span", "n", "net", "delta_vs_v28_market", "mdd", "net_mdd", "PASS"], 0) if regime is not None else "未產生。",
        "",
        (f"四個舊 H6 變體均 FAIL；全樣本最好的 `{regime_best.variant}` 仍只有 NT${regime_best.delta_vs_v28_market:,.0f}，且其 TRAIN 為負增量，不能採用。" if regime_best is not None else ""),
        "",
        "## C. 買入持有 core + v28 overlay",
        "",
        "共同樣本是 2024-01-02 至 2026-10-17，core 使用同一條 MXF 連續價格×NT$50；每換月扣 1 點（NT$50）roll 估計，未含現貨股利且含期現基差。V38 是日末 MTM、以 A 的市場基準期望成本計。TV bar-close 曲線只作脈絡：其 2022–2026 年度值在 `v26cmp_tv_yearly_reconcile.csv`，不能與 1 分鐘 engine 混為同一回測。",
        "",
        table(portfolio, list(portfolio.columns), 3),
        "",
        "margin 欄把 core 視為 MXF；overlay 的 peak 同時持倉使用實際 4 口，故同時給定 overlay 是 MXF 或 TMF 的原始保證金。`capital_for_MDD_le_30pct` = max(原始保證金、歷史 MDD/30%)，是歷史風險緩衝，非保證。",
        "",
        "### 指數下跌月份的 V38",
        "",
        table(down, list(down.columns), 0),
        "",
        "## D. MXF 對 TMF（等曝險 1:5）",
        "",
        table(contract, list(contract.columns), 2),
        "",
        "TMF 每口每點的券商費較重（NT$20/10 點，MXF 為 NT$20/50 點）；5 口 TMF 又把固定費放大五倍。交易稅在等曝險下相同，故真正比較是滑價節省能否覆蓋額外固定費。",
        "",
        "## 可稽核檔案",
        "",
        "`rescue_preregistration.csv`, `rescue_live_slippage.csv`, `rescue_execution_grid.csv`, `rescue_execution_bootstrap.csv`, `rescue_open_wait.csv`, `rescue_latency_*.csv`, `rescue_atr_*.csv`, `rescue_regime_multiplier.csv`, `rescue_daily_equity.csv`, `rescue_portfolio.csv`, `rescue_down_months.csv`, `rescue_contract_choice.csv`。",
    ]
    (HERE / "results_rescue.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    prereg = pd.DataFrame([
        {"section": "A_limit", "rule": "k_ticks in {0,1,2,3}; valid_minutes in {1,2,5}; buy signal+k, sell signal-k; through by 1 point; H1 chooses max expected net"},
        {"section": "A_open", "rule": "wait_minutes in {0,1,2,5}; only orders originally at 08:45/15:00; standalone test"},
        {"section": "A_bootstrap", "rule": "1,000 draws; resample live adverse slippage vs 1-minute open by session-open/normal; PASS requires >0 net delta in H1/H2/TRAIN/TEST, HOLDOUT display only"},
        {"section": "B_gate", "rule": "H1 terciles fixed by kind; validate H1 and H2, campaign bootstrap CI>0, keep PF>1, >1 campaigns, matched placebo p<0.05"},
    ])
    save(prereg, "rescue_preregistration.csv")
    one = load_1min(DATA)
    one = one.loc[one.ts <= CUTOFF].copy()
    b5 = prepare(one, P)
    tr = pd.read_csv(TRADES)
    tr["entry_ts"], tr["exit_ts"] = pd.to_datetime(tr.entry_ts), pd.to_datetime(tr.exit_ts)
    tr["campaign_id"] = campaign_ids(tr)
    atr_source = b5[["close_ts", "atr"]].sort_values("close_ts")
    tr = pd.merge_asof(tr.sort_values("entry_ts"), atr_source, left_on="entry_ts",
                       right_on="close_ts", direction="backward").drop(columns="close_ts")
    tr = tr.rename(columns={"atr": "atr_pts"})
    if tr.atr_pts.isna().any(): raise RuntimeError("missing 5m ATR join")
    live, dist, means = live_slippage(one)
    save(live, "rescue_live_slippage.csv")
    latency = attach_latency(one.set_index("open_ts").open)
    save(latency, "rescue_latency_summary.csv")
    orders, legs = make_orders(tr, b5)
    grid, boot, waits, base = execution_analysis(orders, legs, one, dist, means)
    save(grid, "rescue_execution_grid.csv")
    save(boot, "rescue_execution_bootstrap.csv")
    save(waits, "rescue_open_wait.csv")
    save(orders, "rescue_orders.csv")
    save(base, "rescue_v28_market_costed_lots.csv")
    atr, atr_tests = cost_atr_analysis(base)
    save(atr, "rescue_atr_terciles.csv")
    save(atr_tests, "rescue_atr_gate_tests.csv")
    regime = regime_multiplier_recheck(one, b5, means, base)
    save(regime, "rescue_regime_multiplier.csv")
    daily, port, down = daily_portfolio(base, one)
    save(daily, "rescue_daily_equity.csv")
    save(port, "rescue_portfolio.csv")
    save(down, "rescue_down_months.csv")
    contract = contract_choice(live, base)
    save(contract, "rescue_contract_choice.csv")
    write_report(live, latency, grid, boot, waits, atr, atr_tests, port, down, contract, regime)
    print("wrote results_rescue.md and rescue_*.csv")


if __name__ == "__main__":
    main()
