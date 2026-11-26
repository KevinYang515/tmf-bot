"""Stop-order replay for the v28 live configuration.

The upstream engine is deliberately never edited.  This runner reads its
``run`` source into memory, swaps only the entry scheduling / intrabar block,
and executes that wrapped function.  The resulting S and S2 variants therefore
retain the engine's exits, sizing, cooldowns and one-minute exit path.
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
DATA = HERE / "mxf_1min_corrected_20261017b.csv"
CUTOFF = pd.Timestamp("2026-10-17 03:58:00")
sys.path.insert(0, str(ENGINE_DIR))
import engine_v26_bbw as engine  # noqa: E402


V28 = {
    "opt_stale_hr": 10,
    "opt_cooldown_min": 30,
    "opt_short_pyramid_cap_mode": "hour4",
}
POINT_VALUE = engine.POINT_VALUE
BROKER = engine.COMMISSION
SLIP_POINTS = 4.0


def save(df: pd.DataFrame, name: str) -> None:
    df.to_csv(HERE / name, index=False, encoding="utf-8-sig")


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"stop-order wrapper anchor missing: {label}")
    return source.replace(old, new, 1)


def make_stop_run() -> Any:
    """Build a source-compatible engine run with next-five-minute stop entries."""
    source = inspect.getsource(engine.run)
    source = _replace_once(
        source,
        'def run(df1m, p=None, intrabar_mode="ohlc", start=None, end=None):',
        'def run(df1m, p=None, intrabar_mode="ohlc", start=None, end=None, stop_variant="S"):',
        "signature",
    )
    source = _replace_once(
        source,
        '    prev_cross_state = {}\n',
        '''    prev_cross_state = {}
    # Orders are created at a completed 5-minute close, and are valid for
    # precisely the following 5-minute bar.  They retain only information
    # available at that decision close.
    stop_orders = []
    stop_events = []
    next_stop_id = 1
    lot_stop_meta = {}
''',
        "state",
    )
    source = _replace_once(
        source,
        '''        trades.append(dict(side="L" if exit_direction > 0 else "S", kind=lot.kind,
                           entry_ts=lot.entry_ts, entry_px=lot.entry_px,
                           exit_ts=t, exit_px=px, exit_sig=comment, pnl=pnl))
''',
        '''        meta = lot_stop_meta.get(id(lot), {})
        trades.append(dict(side="L" if exit_direction > 0 else "S", kind=lot.kind,
                           entry_ts=lot.entry_ts, entry_px=lot.entry_px,
                           exit_ts=t, exit_px=px, exit_sig=comment, pnl=pnl,
                           entry_mode=meta.get("entry_mode", "market"),
                           stop_id=meta.get("id", np.nan),
                           decision_ts=meta.get("decision_ts", pd.NaT),
                           stop_trigger=meta.get("trigger", np.nan)))
        lot_stop_meta.pop(id(lot), None)
''',
        "trade metadata",
    )
    source = _replace_once(
        source,
        '    warmup = 200\n',
        '''    def _new_stop_lot(order, fill_px, fill_ts):
        """Enter an already-authorized stop order; fill price includes 4 points."""
        nonlocal direction, short_pyramid_orders, long_pyramid_orders
        nonlocal baseATR, addATR, gATR, base_entry_px
        kind, dir_ = order["kind"], order["dir"]
        if kind == "Cmd":
            short_pyramid_orders = 0
            long_pyramid_orders = 0
            base_entry_px = fill_px
            baseATR = order["atr"]
        elif kind == "Add":
            addATR = order["atr"]
        else:
            gATR = order["atr"]
        stale_hours = p["opt_stale_hr"]
        if (p["opt_regime_stale_enabled"]
                and np.isfinite(order["atr_regime_pct"])
                and order["atr_regime_pct"] > p["opt_regime_stale_pct_threshold"]):
            stale_hours = p["opt_regime_stale_hours_high"]
        lot = Lot(kind, fill_px, fill_ts, bracket_live=(len(lots) > 0),
                  stale_hours=stale_hours, entry_atr=order["atr"],
                  entry_signal_hour=order["signal_hour"])
        lots.append(lot)
        lot_stop_meta[id(lot)] = order
        direction = dir_
        if dir_ < 0 and kind in ("Add", "G"):
            short_pyramid_orders += 1
        elif dir_ > 0 and kind in ("Add", "G"):
            long_pyramid_orders += 1

    def _order_still_valid(order):
        if order["kind"] == "Cmd":
            return not lots
        return direction == order["dir"] and len(lots) * direction == order["pos_size"]

    warmup = 200
''',
        "stop lot helper",
    )

    intrabar_start = '        # ── 2) 盤中: stop / trail ──\n'
    intrabar_end = '        # ── 3) 收盤: 指標訊號 → 掛單 ──\n'
    a = source.index(intrabar_start)
    b = source.index(intrabar_end, a)
    intrabar = '''        # ── 2) 盤中: existing exits plus this bar's stop entries ──
        active_stop_orders = stop_orders
        stop_orders = []
        if intrabar_mode != "1min":
            raise ValueError("stop variants require intrabar_mode='1min'")
        s_, e_ = bar_start_idx[i], bar_end_idx[i]
        for k in range(s_, e_ + 1 if e_ < len(m_arr) else e_):
            mo, mh, ml, mc = m_arr[k]
            minute_open = m_open[k]

            # A 1-minute opening gap can fill an entry stop at the opening
            # price, plus the fixed adverse four points.  Invalidated Add/G
            # orders are cancelled rather than allowed to re-open a campaign.
            for order in active_stop_orders[:]:
                if not _order_still_valid(order):
                    order["status"] = "cancelled"
                    active_stop_orders.remove(order)
                    continue
                gap_hit = ((order["dir"] > 0 and mo >= order["trigger"])
                           or (order["dir"] < 0 and mo <= order["trigger"]))
                if gap_hit:
                    fill_px = mo + SLIP_POINTS * order["dir"]
                    order.update(status="filled", fill_ts=pd.Timestamp(minute_open),
                                 fill_px=float(fill_px), fill_reason="gap")
                    _new_stop_lot(order, fill_px, minute_open)
                    active_stop_orders.remove(order)

            segs = engine._segments(mo, mh, ml, mc)
            # Preserve the engine's opening stop handling for already-live
            # brackets on the first minute of every 5-minute bar.
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

                # A buy stop is touched only on an upward segment, and a sell
                # stop only on a downward one.  A normal touch fills at the
                # trigger plus/minus four points; the gap case was handled
                # above.  Entry happens at this point in the minute path, so
                # a later adverse segment can still reach a live Add/G lot.
                for order in active_stop_orders[:]:
                    if not _order_still_valid(order):
                        order["status"] = "cancelled"
                        active_stop_orders.remove(order)
                        continue
                    touch = ((order["dir"] > 0 and p1 >= p0 and p0 < order["trigger"] <= p1)
                             or (order["dir"] < 0 and p1 <= p0 and p0 > order["trigger"] >= p1))
                    if touch:
                        fill_px = order["trigger"] + SLIP_POINTS * order["dir"]
                        order.update(status="filled", fill_ts=pd.Timestamp(minute_open),
                                     fill_px=float(fill_px), fill_reason="touch")
                        _new_stop_lot(order, fill_px, minute_open)
                        active_stop_orders.remove(order)

        for order in active_stop_orders:
            order["status"] = "expired"
'''
    source = source[:a] + intrabar + source[b:]

    entry_start = '        # 進場 (opt_max_lots: 金字塔口數上限)\n'
    entry_end = '        # 出場單更新 (下一 bar 生效) + 市價平倉訊號\n'
    a = source.index(entry_start)
    b = source.index(entry_end, a)
    entry = '''        # 進場 (opt_max_lots: 金字塔口數上限)
        # A stop is based on the just-completed state and lives only in the
        # following five minutes.  Strict close inequalities use the next
        # whole MXF point so a touch truly satisfies > / < at tick precision.
        add_cap = min(3, p["opt_max_lots"])
        allow_g = p["opt_max_lots"] >= 4
        def queue_stop(kind, dir_, threshold):
            nonlocal next_stop_id
            trigger = float(np.floor(threshold) + 1 if dir_ > 0 else np.ceil(threshold) - 1)
            order = dict(id=next_stop_id, entry_mode="stop", kind=kind, dir=dir_,
                         trigger=trigger, pos_size=posSize, atr=float(atr_i),
                         atr_regime_pct=float(atr_regime_pct), signal_hour=int(hr),
                         decision_ts=pd.Timestamp(t_close),
                         expected_entry_ts=pd.Timestamp(ts_open[i + 1]) if i + 1 < n else pd.NaT,
                         status="scheduled", fill_ts=pd.NaT, fill_px=np.nan, fill_reason="")
            next_stop_id += 1
            stop_orders.append(order)
            stop_events.append(order)

        # Cmd's price-only components are solved from the EMA recurrences.
        # The remaining gates (MTF trend, ADX, toxicity, cooldown and BBW) are
        # frozen at this completed close, exactly as a pre-placed order needs.
        a10, a30 = 2.0 / 11.0, 2.0 / 31.0
        ema_cross_level = ((1 - a30) * B["ema30"][i] - (1 - a10) * B["ema10"][i]) / (a10 - a30)
        next_hh20 = B["hh20_prev"][i + 1] if i + 1 < n else np.nan
        next_ll20 = B["ll20_prev"][i + 1] if i + 1 < n else np.nan
        cmd_long_levels = []
        if B["ema10"][i] <= B["ema30"][i] and np.isfinite(ema_cross_level):
            cmd_long_levels.append(ema_cross_level)
        if (i + 1 < n and c <= B["hh20_prev"][i] and np.isfinite(next_hh20)):
            cmd_long_levels.append(next_hh20)
        cmd_short_trigger_ok = (i + 1 < n and B["ll20_prev"][i] <= c and np.isfinite(next_ll20))

        if (stop_variant == "S2" and posSize == 0 and not isLongToxic and mtf_bull
                and adx_ok and bbw_long_ok and not in_cooldown and cmd_long_levels):
            queue_stop("Cmd", 1, max(B["ema_long"][i], min(cmd_long_levels)))
            baseATR = atr_i
        elif (stop_variant == "S2" and posSize == 0 and not isShortToxic and mtf_bear
                and (adx_ok if p["opt_adx_short"] else True) and bbw_short_ok
                and not in_cooldown and cmd_short_trigger_ok):
            queue_stop("Cmd", -1, min(B["ema_short"][i], next_ll20))
            baseATR = atr_i
        elif (0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok
              and not long_pyramid_cooldown and not isLongToxic and mtf_bull):
            queue_stop("Add", 1, avgPrice + baseATR * p["l_pyramid_dist"])
        elif (posSize == 3 and allow_g and long_pyramid_cap_ok
              and not long_pyramid_cooldown and not isLongToxic):
            queue_stop("G", 1, avgPrice + baseATR * p["l_pyramid_dist"])
        elif (-add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok
              and not short_pyramid_cooldown and not isShortToxic and mtf_bear):
            queue_stop("Add", -1, avgPrice - baseATR * p["s_pyramid_dist"])
        elif (posSize == -3 and allow_g and short_pyramid_cap_ok
              and not short_pyramid_cooldown and not isShortToxic):
            queue_stop("G", -1, avgPrice - baseATR * p["s_pyramid_dist"])
        # S leaves Cmd exactly at its original next-open market execution.
        elif posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown:
            pending.append(("entry", ("Cmd", 1)))
            baseATR = atr_i
        elif posSize == 0 and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger \\
                and (adx_ok if p["opt_adx_short"] else True) and bbw_short_ok and not in_cooldown:
            pending.append(("entry", ("Cmd", -1)))
            baseATR = atr_i
'''
    source = source[:a] + entry + source[b:]

    source = _replace_once(
        source,
        '    # 期末強制平倉\n',
        '''    # The final decision cannot have a following five-minute window.
    for order in stop_orders:
        order["status"] = "no_next_bar"

    # 期末強制平倉
''',
        "terminal order audit",
    )

    source = _replace_once(
        source,
        '    return tr\n',
        '''    tr.attrs["stoporders_events"] = stop_events
    return tr
''',
        "return attrs",
    )
    namespace: dict[str, Any] = dict(engine.__dict__)
    namespace.update({"np": np, "pd": pd, "engine": engine, "SLIP_POINTS": SLIP_POINTS})
    exec(compile(source, "<stoporders_wrapper>", "exec"), namespace)
    return namespace["run"]


def costed(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the stated cash costs without double-charging an embedded stop fill."""
    x = df.copy()
    x["entry_ts"] = pd.to_datetime(x["entry_ts"])
    x["exit_ts"] = pd.to_datetime(x["exit_ts"])
    direction = np.where(x.side.eq("L"), 1.0, -1.0)
    gross = (x.exit_px.astype(float) - x.entry_px.astype(float)) * direction * POINT_VALUE
    tax = 0.00002 * POINT_VALUE * (x.entry_px.astype(float) + x.exit_px.astype(float))
    market_exit = x.exit_sig.isin({"Trend Rev", "Trend Rev Cap", "L_Cmd_Fast", "S_Cmd_Fast", "L_G_Cut", "S_G_Cut", "TimeStop", "END"})
    entry_slip = np.where(x.entry_mode.eq("stop"), 0.0, SLIP_POINTS * POINT_VALUE)
    exit_slip = np.where(market_exit, SLIP_POINTS * POINT_VALUE, 0.0)
    x["pnl_cost"] = gross - 2 * BROKER - tax - entry_slip - exit_slip
    x["market_exit"] = market_exit
    return x


def daily_mdd(x: pd.DataFrame) -> float:
    if x.empty:
        return 0.0
    daily = x.groupby(x.exit_ts.dt.normalize(), sort=True).pnl_cost.sum()
    return float((daily.cumsum() - daily.cumsum().cummax()).min())


def metrics(name: str, x: pd.DataFrame) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    mdd = daily_mdd(x)
    net = float(x.pnl_cost.sum())
    out.append(dict(variant=name, scope="ALL", net=net, daily_mdd=mdd,
                    net_mdd=net / abs(mdd) if mdd else np.inf,
                    add_g_lots=int(x.kind.isin(["Add", "G"]).sum()), n_lots=len(x)))
    for year in (2024, 2025, 2026):
        y = x[x.entry_ts.dt.year.eq(year)]
        out.append(dict(variant=name, scope=str(year), net=float(y.pnl_cost.sum()),
                        daily_mdd=daily_mdd(y),
                        net_mdd=float(y.pnl_cost.sum()) / abs(daily_mdd(y)) if daily_mdd(y) else np.inf,
                        add_g_lots=int(y.kind.isin(["Add", "G"]).sum()), n_lots=len(y)))
    return out


def annotate_stop_matches(stops: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    if stops.empty:
        return stops
    base_key = base[["entry_ts", "side", "kind", "entry_px"]].copy()
    base_key = base_key.rename(columns={"entry_ts": "expected_entry_ts", "entry_px": "baseline_entry_px"})
    # A standard baseline decision at close t fills at next 5-minute open t+5.
    stops["side"] = np.where(stops.dir.eq(1), "L", "S")
    merged = stops.merge(base_key, on=["expected_entry_ts", "side", "kind"], how="left")
    merged["baseline_match"] = merged.baseline_entry_px.notna()
    sign = np.where(merged.side.eq("L"), 1.0, -1.0)
    merged["price_improvement_pts"] = sign * (merged.baseline_entry_px + sign * SLIP_POINTS - merged.fill_px)
    merged.loc[~merged.baseline_match | merged.fill_px.isna(), "price_improvement_pts"] = np.nan
    return merged


def add_trade_match_columns(x: pd.DataFrame, stops: pd.DataFrame) -> pd.DataFrame:
    z = x.copy()
    info = stops[["id", "baseline_match"]].rename(columns={"id": "stop_id"}) if not stops.empty else pd.DataFrame(columns=["stop_id", "baseline_match"])
    z = z.merge(info, on="stop_id", how="left")
    z["extra_lot"] = z.entry_mode.eq("stop") & z.baseline_match.eq(False)
    return z


def main() -> None:
    df = engine.load_1min(DATA)
    df = df[df.ts <= CUTOFF].copy()
    baseline = engine.run(df, p=V28, intrabar_mode="1min")
    baseline["entry_mode"] = "market"
    baseline["stop_id"] = np.nan
    baseline["decision_ts"] = pd.NaT
    baseline["stop_trigger"] = np.nan
    baseline = costed(baseline)

    stop_run = make_stop_run()
    s_raw = stop_run(df, p=V28, intrabar_mode="1min", stop_variant="S")
    s_events = pd.DataFrame(s_raw.attrs["stoporders_events"])
    s_events = annotate_stop_matches(s_events, baseline)
    s = add_trade_match_columns(costed(s_raw), s_events)

    s2_raw = stop_run(df, p=V28, intrabar_mode="1min", stop_variant="S2")
    s2_events = pd.DataFrame(s2_raw.attrs["stoporders_events"])
    s2_events = annotate_stop_matches(s2_events, baseline)
    s2 = add_trade_match_columns(costed(s2_raw), s2_events)
    baseline["baseline_match"] = pd.NA
    baseline["extra_lot"] = False

    runs = {"baseline": baseline, "S": s, "S2": s2}
    for name, tr in runs.items():
        save(tr, f"stoporders_trades_{name.lower()}.csv")
    save(s_events, "stoporders_orders_s.csv")
    save(s2_events, "stoporders_orders_s2.csv")
    metric_df = pd.DataFrame(sum((metrics(name, tr) for name, tr in runs.items()), []))
    save(metric_df, "stoporders_metrics.csv")

    comparison_rows = []
    for name, tr, ev in (("S", s, s_events), ("S2", s2, s2_events)):
        ag = tr[tr.kind.isin(["Add", "G"])]
        extra = ag[ag.extra_lot]
        matched = ev[(ev.status.eq("filled")) & ev.baseline_match & ev.kind.isin(["Add", "G"])]
        comparison_rows.append(dict(
            variant=name,
            add_g_stop_fills=int(len(ag)),
            matched_add_g_fills=int(len(matched)),
            extra_add_g_lots=int(len(extra)),
            avg_price_improvement_pts=float(matched.price_improvement_pts.mean()) if len(matched) else np.nan,
            extra_lots_pnl=float(extra.pnl_cost.sum()),
        ))
    comparison = pd.DataFrame(comparison_rows)
    save(comparison, "stoporders_addg_comparison.csv")

    overall = metric_df[metric_df.scope.eq("ALL")].set_index("variant")
    years = metric_df[metric_df.scope.isin(["2024", "2025", "2026"])].pivot(index="scope", columns="variant", values="net")
    text = [
        "# 預掛停損單（Stop Order）測試",
        "",
        "## 摘要",
        "",
        "以 v28 即時設定為基準，S 將 Add/G 改為上一根 5 分 K 收盤就預掛、在下一個 5 分鐘內觸價成交；S2 再把可價格化的 Cmd 首倉也改為預掛。停損單成交價已含不利 4 點，市價成交另計每邊 4 點滑價；佣金每邊 20 元、證交稅以成交價的 0.00002 × 50 計。MDD 是依出場日彙總的已實現損益日曲線。",
        "",
        "## 結果",
        "",
        "| 版本 | 淨利 | 日 MDD | 淨利/MDD | Add/G 口數 |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in ("baseline", "S", "S2"):
        r = overall.loc[name]
        text.append(f"| {name} | {r.net:,.0f} | {r.daily_mdd:,.0f} | {r.net_mdd:.2f} | {int(r.add_g_lots):,} |")
    text.extend(["", "| 年度 | Baseline | S | S2 |", "|---|---:|---:|---:|"])
    for year in ("2024", "2025", "2026"):
        row = years.loc[year]
        text.append(f"| {year} | {row['baseline']:,.0f} | {row['S']:,.0f} | {row['S2']:,.0f} |")
    text.extend(["", "| 版本 | 配對 Add/G 平均進場改善（點） | 額外 Add/G 口數 | 額外口損益 |",
                 "|---|---:|---:|---:|"])
    for row in comparison.itertuples(index=False):
        text.append(f"| {row.variant} | {row.avg_price_improvement_pts:,.2f} | {row.extra_add_g_lots:,} | {row.extra_lots_pnl:,.0f} |")

    beats = []
    for year in ("2024", "2025", "2026"):
        b, ss, s2v = years.loc[year, ["baseline", "S", "S2"]]
        beats.append(f"{year}：S {'勝' if ss > b else '未勝'}、S2 {'勝' if s2v > b else '未勝'}")
    text.extend([
        "",
        "**判決：** " + "；".join(beats) + "。",
        "",
        "## 引擎條件（白話）",
        "",
        "- Add：已有 1 或 2 口時，多方收盤高於目前平均進場價 + 首倉 ATR × 1.2；空方收盤低於平均進場價 − 首倉 ATR × 1.0。還必須通過當根已知的趨勢、時段、加碼上限與冷卻條件。",
        "- G：已有 3 口時沿用同一個價格門檻（多方 +1.2 ATR、空方 −1.0 ATR）；G 不另要求 MTF 趨勢，但仍受時段、加碼上限與冷卻限制。",
        "- Cmd：多方要高於長 EMA，且 EMA10/30 向上交叉或突破前 20 根高點，同時需 MTF 多頭、ADX 與時段/冷卻通過；空方是低於短 EMA 且跌破前 20 根低點，另有 MTF 空頭與時段/冷卻條件（此 v28 設定沒有空方 ADX 開關）。",
        "",
        "S 對 Add/G 將上述 ATR 價格門檻轉成下一個 5 分鐘有效的 stop；非價格條件均鎖定為下單當刻的值。S2 的 Cmd 則以 EMA 遞迴式和前 20 根突破價解出價格門檻，並同樣鎖定 MTF、ADX、時段、冷卻與 BBW。需要完整新 K 棒高低點的指標沒有在盤中重算。",
        "",
        "明細：`stoporders_metrics.csv`、`stoporders_trades_*.csv`、`stoporders_orders_*.csv`、`stoporders_addg_comparison.csv`。",
    ])
    (HERE / "results_stop_orders.md").write_text("\n".join(text) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
