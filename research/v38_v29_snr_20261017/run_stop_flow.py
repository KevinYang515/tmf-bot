"""Flow-confirmed early Add/G replay for the v28 live configuration.

The upstream engine remains read-only.  This file compiles an in-memory copy
of ``engine.run``: ordinary Cmd/Add/G decisions and exits are retained, while
an additional, five-minute-lived Add/G candidate can be filled at the next
one-minute open only after its completed one-minute bar confirms both price
and signed BVC imbalance.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import ndtr

import run_stop_orders as stop


HERE = Path(__file__).resolve().parent
engine = stop.engine
V28 = stop.V28
POINT_VALUE = stop.POINT_VALUE
BROKER = stop.BROKER
SLIP_POINTS = stop.SLIP_POINTS


def save(df: pd.DataFrame, name: str) -> None:
    df.to_csv(HERE / name, index=False, encoding="utf-8-sig")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"flow wrapper anchor missing: {label}")
    return source.replace(old, new, 1)


def add_flow_imbalance(df: pd.DataFrame) -> pd.DataFrame:
    """BVC proxy using only completed END-labelled one-minute rows."""
    x = df.sort_values("ts").copy()
    dp = x["close"].diff()
    dp.loc[x["ts"].diff() > pd.Timedelta("5min")] = np.nan
    sigma60 = dp.rolling(60, min_periods=20).std()
    x["flow_imb"] = 2.0 * ndtr(dp / sigma60) - 1.0
    return x


def make_flow_run() -> Any:
    """Return an engine-compatible run with optional F1/F2 early Add/G lots."""
    source = inspect.getsource(engine.run)
    source = replace_once(
        source,
        'def run(df1m, p=None, intrabar_mode="ohlc", start=None, end=None):',
        'def run(df1m, p=None, intrabar_mode="ohlc", start=None, end=None, flow_threshold=None):',
        "signature",
    )
    source = replace_once(
        source,
        '    p = {**P, **overrides}\n',
        '''    p = {**P, **overrides}
    if flow_threshold is None or not np.isfinite(flow_threshold):
        raise ValueError("a finite flow_threshold is required")
''',
        "threshold validation",
    )
    source = replace_once(
        source,
        '        m_arr = df1m[["open", "high", "low", "close"]].values\n',
        '''        m_arr = df1m[["open", "high", "low", "close"]].values
        m_flow = df1m["flow_imb"].values
''',
        "minute flow array",
    )
    source = replace_once(
        source,
        '    prev_cross_state = {}\n',
        '''    prev_cross_state = {}
    # Candidates are authorized from a completed five-minute bar and are
    # valid only in its immediately following five-minute interval.
    flow_orders = []
    flow_events = []
    next_flow_id = 1
    lot_flow_meta = {}
''',
        "state",
    )
    source = replace_once(
        source,
        '''        trades.append(dict(side="L" if exit_direction > 0 else "S", kind=lot.kind,
                           entry_ts=lot.entry_ts, entry_px=lot.entry_px,
                           exit_ts=t, exit_px=px, exit_sig=comment, pnl=pnl))
''',
        '''        meta = lot_flow_meta.get(id(lot), {})
        trades.append(dict(side="L" if exit_direction > 0 else "S", kind=lot.kind,
                           entry_ts=lot.entry_ts, entry_px=lot.entry_px,
                           exit_ts=t, exit_px=px, exit_sig=comment, pnl=pnl,
                           entry_mode=meta.get("entry_mode", "market"),
                           flow_id=meta.get("id", np.nan),
                           decision_ts=meta.get("decision_ts", pd.NaT),
                           flow_trigger=meta.get("trigger", np.nan)))
        lot_flow_meta.pop(id(lot), None)
''',
        "trade metadata",
    )
    source = replace_once(
        source,
        '    warmup = 200\n',
        '''    def _flow_order_still_valid(order):
        # It must still add to the identical campaign/state it was authorized
        # from; ordinary next-five-minute market entries can invalidate it.
        return direction == order["dir"] and len(lots) * direction == order["pos_size"]

    def _new_flow_lot(order, fill_px, fill_ts):
        nonlocal direction, short_pyramid_orders, long_pyramid_orders
        nonlocal addATR, gATR
        if order["kind"] == "Add":
            addATR = order["atr"]
        else:
            gATR = order["atr"]
        stale_hours = p["opt_stale_hr"]
        if (p["opt_regime_stale_enabled"]
                and np.isfinite(order["atr_regime_pct"])
                and order["atr_regime_pct"] > p["opt_regime_stale_pct_threshold"]):
            stale_hours = p["opt_regime_stale_hours_high"]
        lot = Lot(order["kind"], fill_px, fill_ts,
                  bracket_live=(len(lots) > 0), stale_hours=stale_hours,
                  entry_atr=order["atr"], entry_signal_hour=order["signal_hour"])
        lots.append(lot)
        lot_flow_meta[id(lot)] = order
        direction = order["dir"]
        if direction < 0:
            short_pyramid_orders += 1
        else:
            long_pyramid_orders += 1

    warmup = 200
''',
        "flow helper",
    )

    # Preserve the engine's one-minute exit path.  Flow is tested *after* a
    # minute's OHLC has completed.  The candidate condition itself excludes
    # the duplicated boundary row in the legacy exit scanner, leaving exactly
    # the five END-labelled minutes immediately after the decision close.
    intrabar_start = source.index('        if lots:\n            if intrabar_mode == "1min":')
    intrabar_end = source.index('        posSize = len(lots) * direction', intrabar_start)
    intrabar = '''        # Existing exits plus flow-confirmed early Add/G entries.
        active_flow_orders = flow_orders
        flow_orders = []
        if intrabar_mode != "1min":
            raise ValueError("flow variants require intrabar_mode='1min'")
        s_, e_ = bar_start_idx[i], bar_end_idx[i]
        # ``e_`` is the first minute of the following five-minute bar.  It is
        # retained in the exit replay for compatibility, but never supplies a
        # flow decision for this interval.
        scan_stop = e_ + 1 if e_ < len(m_arr) else e_
        for k in range(s_, scan_stop):
            mo, mh, ml, mc = m_arr[k]
            minute_open = m_open[k]
            segs = engine._segments(mo, mh, ml, mc)
            if k == s_ and lots:
                first_px = segs[0][0] if segs else mo
                for lot in lots[:]:
                    if not lot.bracket_live:
                        continue
                    if lot.trail_act is not None and not lot.trail_on and (first_px - lot.trail_act) * direction >= 0:
                        lot.trail_on = True
                        lot.peak = first_px
                    eff = engine._eff_stop(lot, direction)
                    if eff is not None and (first_px - eff) * direction <= 0:
                        close_lot(lot, first_px, t_open, engine._stop_name(lot, eff, direction))

            for p0, p1 in segs:
                if lots:
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
                            eff = engine._eff_stop(lot, direction)
                            if eff is None:
                                continue
                            lo_, hi_ = (p1, p0) if direction > 0 else (p0, p1)
                            if lo_ <= eff <= hi_:
                                close_lot(lot, eff, t_close, engine._stop_name(lot, eff, direction))

            # The close and imbalance are known now.  A filled order executes
            # at the *next* one-minute open (its actual open plus 4 points),
            # so it never sees the deciding bar's intrabar path.
            if k < e_:
                for order in active_flow_orders[:]:
                    if not _flow_order_still_valid(order):
                        order["status"] = "cancelled"
                        active_flow_orders.remove(order)
                        continue
                    beyond = (mc - order["trigger"]) * order["dir"] > 0
                    signed_imb = m_flow[k] * order["dir"]
                    next_k = k + 1
                    contiguous = (
                        next_k < len(m_arr)
                        and m_open[next_k] - minute_open == np.timedelta64(1, "m")
                    )
                    if beyond and np.isfinite(signed_imb) and signed_imb >= flow_threshold and contiguous:
                        fill_px = float(m_arr[next_k][0] + SLIP_POINTS * order["dir"])
                        order.update(status="filled", fill_ts=pd.Timestamp(m_open[next_k]),
                                     fill_px=fill_px, fill_reason="close_flow")
                        _new_flow_lot(order, fill_px, m_open[next_k])
                        active_flow_orders.remove(order)

        for order in active_flow_orders:
            order["status"] = "expired"
'''
    source = source[:intrabar_start] + intrabar + source[intrabar_end:]

    entry_anchor = '        add_cap = min(3, p["opt_max_lots"])\n        allow_g = p["opt_max_lots"] >= 4\n'
    flow_queue = '''        add_cap = min(3, p["opt_max_lots"])
        allow_g = p["opt_max_lots"] >= 4
        # Freeze every non-price Add/G gate at this completed five-minute
        # close.  The subsequent one-minute close must provide both the
        # threshold break and the independently calculated flow confirmation.
        def queue_flow(kind, dir_, threshold):
            nonlocal next_flow_id
            if i + 1 >= n:
                return
            order = dict(
                id=next_flow_id, entry_mode="flow", kind=kind, dir=dir_,
                trigger=float(threshold), pos_size=posSize, atr=float(atr_i),
                atr_regime_pct=float(atr_regime_pct), signal_hour=int(hr),
                decision_ts=pd.Timestamp(t_close),
                window_start=pd.Timestamp(ts_open[i + 1]),
                window_end=pd.Timestamp(ts_close[i + 1]),
                status="scheduled", fill_ts=pd.NaT, fill_px=np.nan,
                fill_reason="", threshold=float(flow_threshold),
            )
            next_flow_id += 1
            flow_orders.append(order)
            flow_events.append(order)

        if (0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok
                and not long_pyramid_cooldown and not isLongToxic and mtf_bull):
            queue_flow("Add", 1, avgPrice + baseATR * p["l_pyramid_dist"])
        elif (posSize == 3 and allow_g and long_pyramid_cap_ok
                and not long_pyramid_cooldown and not isLongToxic):
            queue_flow("G", 1, avgPrice + baseATR * p["l_pyramid_dist"])
        elif (-add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok
                and not short_pyramid_cooldown and not isShortToxic and mtf_bear):
            queue_flow("Add", -1, avgPrice - baseATR * p["s_pyramid_dist"])
        elif (posSize == -3 and allow_g and short_pyramid_cap_ok
                and not short_pyramid_cooldown and not isShortToxic):
            queue_flow("G", -1, avgPrice - baseATR * p["s_pyramid_dist"])
'''
    source = replace_once(source, entry_anchor, flow_queue, "flow queue")
    terminal_lots = source.rindex('    for lot in lots[:]:')
    source = source[:terminal_lots] + '''    for order in flow_orders:
        order["status"] = "no_next_bar"

''' + source[terminal_lots:]
    source = replace_once(
        source,
        '    return tr\n',
        '''    tr.attrs["flow_events"] = flow_events
    return tr
''',
        "return attrs",
    )
    namespace: dict[str, Any] = dict(engine.__dict__)
    namespace.update({"np": np, "pd": pd, "engine": engine, "SLIP_POINTS": SLIP_POINTS})
    exec(compile(source, "<stopflow_wrapper>", "exec"), namespace)
    return namespace["run"]


def costed(x: pd.DataFrame) -> pd.DataFrame:
    """Use the established cash model; a flow fill already embeds 4 points."""
    out = x.copy()
    out["entry_ts"] = pd.to_datetime(out["entry_ts"])
    out["exit_ts"] = pd.to_datetime(out["exit_ts"])
    direction = np.where(out.side.eq("L"), 1.0, -1.0)
    gross = (out.exit_px.astype(float) - out.entry_px.astype(float)) * direction * POINT_VALUE
    tax = 0.00002 * POINT_VALUE * (out.entry_px.astype(float) + out.exit_px.astype(float))
    market_exit = out.exit_sig.isin({"Trend Rev", "Trend Rev Cap", "L_Cmd_Fast", "S_Cmd_Fast", "L_G_Cut", "S_G_Cut", "TimeStop", "END"})
    entry_slip = np.where(out.entry_mode.eq("market"), SLIP_POINTS * POINT_VALUE, 0.0)
    exit_slip = np.where(market_exit, SLIP_POINTS * POINT_VALUE, 0.0)
    out["pnl_cost"] = gross - 2 * BROKER - tax - entry_slip - exit_slip
    out["market_exit"] = market_exit
    return out


def daily_mdd(x: pd.DataFrame) -> float:
    if x.empty:
        return 0.0
    daily = x.groupby(x.exit_ts.dt.normalize(), sort=True).pnl_cost.sum()
    return float((daily.cumsum() - daily.cumsum().cummax()).min())


def metrics(name: str, x: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scope, z in [("ALL", x)] + [(str(y), x[x.entry_ts.dt.year.eq(y)]) for y in (2024, 2025, 2026)]:
        net = float(z.pnl_cost.sum())
        mdd = daily_mdd(z)
        rows.append(dict(variant=name, scope=scope, net=net, daily_mdd=mdd,
                         net_mdd=net / abs(mdd) if mdd else np.inf,
                         add_g_lots=int(z.kind.isin(["Add", "G"]).sum()), n_lots=len(z)))
    return rows


def comparison(name: str, x: pd.DataFrame, events: pd.DataFrame, baseline: pd.DataFrame) -> dict[str, Any]:
    """Pair an early fill with baseline's close-confirmed lot at window end."""
    f = x[x.kind.isin(["Add", "G"])].copy()
    e = events[events.status.eq("filled")].copy()
    e["side"] = np.where(e.dir.eq(1), "L", "S")
    b = baseline[baseline.kind.isin(["Add", "G"])][["entry_ts", "side", "kind", "entry_px"]]
    b = b.rename(columns={"entry_px": "baseline_entry_px"})
    # The baseline can only take the corresponding lot at the next completed
    # five-minute close: its market entry is therefore window_end.  This
    # excludes genuinely extra intrabar opportunities from the price metric.
    z = e.merge(b, left_on=["window_end", "side", "kind"],
                right_on=["entry_ts", "side", "kind"], how="left")
    direction = np.where(z.side.eq("L"), 1.0, -1.0)
    b_effective = z.baseline_entry_px + SLIP_POINTS * direction
    z["entry_diff_pts"] = direction * (b_effective - z.fill_px)
    matched = z[z.baseline_entry_px.notna()]
    return dict(
        variant=name,
        add_g_lots=int(len(f)),
        flow_add_g_lots=int(f.entry_mode.eq("flow").sum()),
        matched_add_g_lots=int(len(matched)),
        avg_entry_difference_pts=float(matched.entry_diff_pts.mean()) if len(matched) else np.nan,
    )


def main() -> None:
    proxy = pd.read_csv(HERE / "flow" / "flow_proxy_lots.csv")
    h1 = proxy.loc[proxy.H.eq("H1"), "tm_imb"].dropna()
    median = float(h1.quantile(0.5))
    top_tercile = float(h1.quantile(2.0 / 3.0))

    if "--report-only" in sys.argv:
        parse_trade = ["entry_ts", "exit_ts", "decision_ts"]
        parse_event = ["decision_ts", "window_start", "window_end", "fill_ts"]
        baseline = pd.read_csv(HERE / "stopflow_trades_baseline.csv", parse_dates=parse_trade)
        s = pd.read_csv(HERE / "stopflow_trades_s.csv", parse_dates=parse_trade)
        f1 = pd.read_csv(HERE / "stopflow_trades_f1.csv", parse_dates=parse_trade)
        f2 = pd.read_csv(HERE / "stopflow_trades_f2.csv", parse_dates=parse_trade)
        f1_events = pd.read_csv(HERE / "stopflow_orders_f1.csv", parse_dates=parse_event)
        f2_events = pd.read_csv(HERE / "stopflow_orders_f2.csv", parse_dates=parse_event)
    else:
        df = engine.load_1min(stop.DATA)
        df = df[df.ts <= stop.CUTOFF].copy()
        df = add_flow_imbalance(df)

        # Recreate the stated baseline, and preserve the previously completed S
        # result as requested rather than changing its already-approved method.
        baseline = engine.run(df, p=V28, intrabar_mode="1min")
        baseline["entry_mode"] = "market"
        baseline["flow_id"] = np.nan
        baseline["decision_ts"] = pd.NaT
        baseline["flow_trigger"] = np.nan
        baseline = costed(baseline)
        s = pd.read_csv(HERE / "stoporders_trades_s.csv", parse_dates=["entry_ts", "exit_ts", "decision_ts"])
        if "pnl_cost" not in s:
            s = stop.costed(s)

        flow_run = make_flow_run()
        f1_raw = flow_run(df, p=V28, intrabar_mode="1min", flow_threshold=top_tercile)
        f1_events = pd.DataFrame(f1_raw.attrs["flow_events"])
        f1 = costed(f1_raw)
        f2_raw = flow_run(df, p=V28, intrabar_mode="1min", flow_threshold=median)
        f2_events = pd.DataFrame(f2_raw.attrs["flow_events"])
        f2 = costed(f2_raw)

    runs = {"baseline": baseline, "S": s, "F1": f1, "F2": f2}
    for name, tr in runs.items():
        save(tr, f"stopflow_trades_{name.lower()}.csv")
    save(f1_events, "stopflow_orders_f1.csv")
    save(f2_events, "stopflow_orders_f2.csv")
    metric_df = pd.DataFrame(sum((metrics(name, tr) for name, tr in runs.items()), []))
    save(metric_df, "stopflow_metrics.csv")
    comp = pd.DataFrame([
        comparison("F1", f1, f1_events, baseline),
        comparison("F2", f2, f2_events, baseline),
    ])
    save(comp, "stopflow_addg_comparison.csv")

    overall = metric_df[metric_df.scope.eq("ALL")].set_index("variant")
    annual = metric_df[metric_df.scope.isin(["2024", "2025", "2026"])].pivot(index="scope", columns="variant", values="net")
    text = [
        "# S-flow：以 1 分鐘訂單流確認的提前 Add/G",
        "",
        f"結論：F1（H1 上三分位門檻 {top_tercile:.6f}）與 F2（H1 中位數門檻 {median:.6f}）均未能在 2024、2025、2026 三個年度全部勝過 baseline。F1/F2 僅在完整收盤的一分鐘 K 同時越過既定 Add/G 價格門檻且方向調整後 BVC 不平衡達門檻時，以下一分鐘開盤市價進場（已含 4 點滑價）；未提前進場時保留 baseline 的 5 分鐘收盤決策。",
        "",
        "## 整體績效",
        "",
        "| 版本 | 淨利 | 日 MDD | 淨利/MDD | Add/G 口數 | 相對 baseline 配對提前口的平均進場差（點） |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    comp_idx = comp.set_index("variant")
    for name in ("baseline", "S", "F1", "F2"):
        r = overall.loc[name]
        diff = "—" if name in ("baseline", "S") else f"{comp_idx.loc[name, 'avg_entry_difference_pts']:.2f}"
        text.append(f"| {name} | {r.net:,.0f} | {r.daily_mdd:,.0f} | {r.net_mdd:.2f} | {int(r.add_g_lots):,} | {diff} |")
    text.extend(["", "## 年度淨利", "", "| 年度 | baseline | S（既有結果） | F1 | F2 |", "|---|---:|---:|---:|---:|"])
    for year in ("2024", "2025", "2026"):
        r = annual.loc[year]
        text.append(f"| {year} | {r['baseline']:,.0f} | {r['S']:,.0f} | {r['F1']:,.0f} | {r['F2']:,.0f} |")
    text.extend(["", "## F 版本的 Add/G 配對與提前口數", "", "| 版本 | Add/G 總口數 | 提前 flow Add/G 口數 | 與 baseline 配對提前口數 | 平均進場差（點；正值較佳） |", "|---|---:|---:|---:|---:|"])
    for r in comp.itertuples(index=False):
        text.append(f"| {r.variant} | {r.add_g_lots:,} | {r.flow_add_g_lots:,} | {r.matched_add_g_lots:,} | {r.avg_entry_difference_pts:.2f} |")
    verdict = []
    for year in ("2024", "2025", "2026"):
        b, f1v, f2v = annual.loc[year, ["baseline", "F1", "F2"]]
        verdict.append(f"{year}：F1{'勝過' if f1v > b else '未勝過'} baseline，F2{'勝過' if f2v > b else '未勝過'} baseline")
    text.extend([
        "",
        "**年度判定：** " + "；".join(verdict) + "。",
        "",
        "## 方法",
        "",
        "- BVC 代理值為 `(2·Φ(dp/σ60)-1)·方向`；`dp` 是 1 分鐘收盤變動，`σ60` 為 60 根滾動標準差，跨 session 的 `dp` 設為缺值。資料列為分鐘結束時間，因此訊號只在該分鐘收盤後使用。",
        "- 每個 5 分鐘收盤先凍結 Add/G 的非價格條件與價格門檻。接下來剛好五根分鐘 K 中，若收盤嚴格越過門檻且 `tm_imb ≥ T`，則在下一分鐘開盤以市價成交；成交價內含 4 點不利滑價。",
        "- 普通 Add/G、Cmd、出場、部位大小及成本沿用 v28 baseline；S 是既有 stop-order 結果，未重新改寫。提前口只在 baseline 於該 5 分鐘窗口結束時確有同方向、同種類 Add/G 時配對，並比較含進場滑價的有效價格；真正的額外盤中口不納入此價格差。",
        "",
        "明細：`stopflow_metrics.csv`、`stopflow_trades_*.csv`、`stopflow_orders_f1.csv`、`stopflow_orders_f2.csv`、`stopflow_addg_comparison.csv`。",
    ])
    (HERE / "results_stop_flow.md").write_text("\n".join(text) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
