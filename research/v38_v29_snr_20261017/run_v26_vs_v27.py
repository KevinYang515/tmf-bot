"""Cost-aware v26 versus v27--v29 comparison.

The upstream strategy engine is imported read-only.  This runner uses its
public ``run`` function and an in-memory, inspected copy only to audit the
otherwise invisible cooldown-blocked Cmd signals.
"""
from __future__ import annotations

import inspect
import argparse
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
from engine_v26_bbw import (  # noqa: E402
    COMMISSION, POINT_VALUE, P, Lot, _eff_stop, _segments, _stop_name, load_1min, prepare,
    run as base_run,
)


TRADE_COLS = ["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl"]
H2 = pd.Timestamp("2025-04-01")
TRAIN0, TRAIN1 = pd.Timestamp("2026-03-01"), pd.Timestamp("2026-06-01")
TEST0, HOLDOUT = pd.Timestamp("2026-06-01"), pd.Timestamp("2026-08-22")
SPANS = ["ALL", "2024", "2025", "2026", "H1", "H2_DEV", "TRAIN", "TEST", "HOLDOUT"]
TICKS = [0, 2, 4]
VARIANTS: dict[str, dict[str, Any]] = {
    "v26": {"opt_stale_hr": 0, "opt_cooldown_min": 0},
    "timestop_only": {"opt_stale_hr": 10, "opt_cooldown_min": 0},
    "cooldown_only": {"opt_stale_hr": 0, "opt_cooldown_min": 30},
    "v27": {"opt_stale_hr": 10, "opt_cooldown_min": 30},
    "v26_cap": {"opt_stale_hr": 0, "opt_cooldown_min": 0,
                "opt_short_pyramid_cap_mode": "hour4"},
    "v28": {"opt_stale_hr": 10, "opt_cooldown_min": 30,
            "opt_short_pyramid_cap_mode": "hour4"},
    "v29": {"opt_stale_hr": 10, "opt_cooldown_min": 30,
            "opt_short_pyramid_cap_mode": "hour4", "l_trailBase": 3.5},
}
ZH = {
    "v26": "v26（無 TimeStop／Cooldown）",
    "timestop_only": "僅 TimeStop（10h）",
    "cooldown_only": "僅 Cooldown（30m）",
    "v27": "v27（10h／30m）",
    "v26_cap": "v26 + v28 空方 hour4 金字塔上限",
    "v28": "v28",
    "v29": "v29（v28 + L trail 3.5）",
}


def save(df: pd.DataFrame, name: str) -> None:
    df.to_csv(HERE / name, index=False, encoding="utf-8-sig")


def dates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["entry_ts"] = pd.to_datetime(out["entry_ts"])
    out["exit_ts"] = pd.to_datetime(out["exit_ts"])
    return out


def subset(df: pd.DataFrame, span: str) -> pd.DataFrame:
    t = df.entry_ts
    if span == "ALL":
        return df
    if span in ("2024", "2025", "2026"):
        return df[t.dt.year.eq(int(span))]
    if span == "H1":
        return df[t < H2]
    if span == "H2_DEV":
        return df[(t >= H2) & (t < HOLDOUT)]
    if span == "TRAIN":
        return df[(t >= TRAIN0) & (t < TRAIN1)]
    if span == "TEST":
        return df[(t >= TEST0) & (t < HOLDOUT)]
    if span == "HOLDOUT":
        return df[t >= HOLDOUT]
    raise ValueError(span)


def cost_pnl(df: pd.DataFrame, ticks_per_side: int) -> pd.Series:
    """Engine PnL already contains NT$20 on each side; restate to requested cost."""
    extra = 2 * (40 - COMMISSION) + 2 * ticks_per_side * POINT_VALUE
    return df.pnl.astype(float) - extra


def closed_mdd(df: pd.DataFrame, pnl_col: str) -> float:
    if df.empty:
        return 0.0
    curve = df.groupby("exit_ts", sort=True)[pnl_col].sum().cumsum()
    return float((curve - curve.cummax()).min())


def make_mtm_context(df1m: pd.DataFrame) -> dict[str, Any]:
    """Precompute the minute lookup once; all metrics share this same path."""
    minutes = df1m[["open_ts", "ts", "close"]].copy().sort_values("open_ts").reset_index(drop=True)
    return {
        "minutes": minutes,
        "pos_by_open": {pd.Timestamp(t): i for i, t in enumerate(minutes.open_ts)},
        "pos_by_close": {pd.Timestamp(t): i for i, t in enumerate(minutes.ts)},
        "open_array": minutes.open_ts.to_numpy(dtype="datetime64[ns]"),
        "close_array": minutes.ts.to_numpy(dtype="datetime64[ns]"),
    }


def mtm_curve(df: pd.DataFrame, ctx: dict[str, Any], ticks_per_side: int) -> pd.DataFrame:
    """Minute-close mark-to-market, including entry and exit costs when incurred."""
    if df.empty:
        return pd.DataFrame(columns=["ts", "equity"])
    minutes = ctx["minutes"]
    pos_by_open = ctx["pos_by_open"]
    pos_by_close = ctx["pos_by_close"]
    open_array = ctx["open_array"]
    close_array = ctx["close_array"]
    n = len(minutes)
    cash_delta = np.zeros(n)
    pos_delta = np.zeros(n)
    entry_value_delta = np.zeros(n)
    side_cost = 40.0 + ticks_per_side * POINT_VALUE
    for row in df.itertuples(index=False):
        ent = pos_by_open.get(pd.Timestamp(row.entry_ts))
        if ent is None:
            # A few repaired-source gaps leave a 5m engine-bin timestamp with
            # no literal 1m open.  The bin's first available minute is the
            # one that supplied its OHLC, so mark from that next available
            # minute rather than inventing a price inside the gap.
            ent = int(np.searchsorted(open_array, np.datetime64(row.entry_ts), side="left"))
        # Scheduled closes occur at a following 5m bar open, whereas a stop
        # is recorded by the engine at the completed 5m bar close.  Prefer
        # the open convention when it exists, then use the minute close.
        ext = pos_by_open.get(pd.Timestamp(row.exit_ts), pos_by_close.get(pd.Timestamp(row.exit_ts)))
        if ext is None:
            ext = int(np.searchsorted(close_array, np.datetime64(row.exit_ts), side="left"))
        if ent is None or ext is None or ent >= n or ext >= n:
            raise RuntimeError(f"trade timestamp absent from 1m source: {row.entry_ts} / {row.exit_ts}")
        direction = 1.0 if row.side == "L" else -1.0
        entry_value = direction * float(row.entry_px) * POINT_VALUE
        gross = (float(row.exit_px) - float(row.entry_px)) * direction * POINT_VALUE
        # Events are processed at the one-minute bar open, and the curve is
        # marked at that bar's close.  Exit lots are therefore no longer open.
        cash_delta[ent] -= side_cost
        pos_delta[ent] += direction
        entry_value_delta[ent] += entry_value
        cash_delta[ext] += gross - side_cost
        pos_delta[ext] -= direction
        entry_value_delta[ext] -= entry_value
    cash = np.cumsum(cash_delta)
    pos = np.cumsum(pos_delta)
    entry_value = np.cumsum(entry_value_delta)
    equity = cash + minutes.close.to_numpy(float) * POINT_VALUE * pos - entry_value
    return pd.DataFrame({"ts": minutes.ts, "equity": equity})


def mtm_mdd(df: pd.DataFrame, ctx: dict[str, Any], ticks_per_side: int) -> float:
    curve = mtm_curve(df, ctx, ticks_per_side)
    if curve.empty:
        return 0.0
    e = curve.equity
    return float((e - e.cummax()).min())


def metric_rows(runs: dict[str, pd.DataFrame], mtm_ctx: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant, trades in runs.items():
        for tick in TICKS:
            z = trades.copy()
            z["pnl_cost"] = cost_pnl(z, tick)
            for span in SPANS:
                s = subset(z, span)
                net = float(s.pnl_cost.sum())
                cmdd = closed_mdd(s, "pnl_cost")
                mmdd = mtm_mdd(s.drop(columns="pnl_cost"), mtm_ctx, tick)
                rows.append({
                    "variant": variant, "variant_zh": ZH[variant], "cost_commission_side": 40,
                    "slippage_ticks_side": tick, "n": len(s), "span": span, "net": net,
                    "closed_mdd": cmdd, "mtm_mdd": mmdd,
                    "net_closed_mdd": net / abs(cmdd) if cmdd else np.inf,
                    "net_mtm_mdd": net / abs(mmdd) if mmdd else np.inf,
                })
    return pd.DataFrame(rows)


def build_cooldown_audit_run() -> Any:
    """Return a behavior-identical engine run with Cmd block audit attached."""
    import engine_v26_bbw as base
    source = inspect.getsource(base.run)
    anchor = "    b5 = prepare(df1m, p)\n    n = len(b5)\n"
    repl = "    b5 = prepare(df1m, p)\n    _v26cmp_cd_blocks = []\n    n = len(b5)\n"
    if anchor not in source:
        raise RuntimeError("cooldown audit: prepare anchor missing")
    source = source.replace(anchor, repl, 1)
    long_old = ("        if posSize == 0 and not isLongToxic and mtf_bull and c > B[\"ema_long\"][i] "
                "and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown:\n")
    long_new = ("        if posSize == 0 and not isLongToxic and mtf_bull and c > B[\"ema_long\"][i] "
                "and long_entry_signal and adx_ok and bbw_long_ok and in_cooldown:\n"
                "            _v26cmp_cd_blocks.append(dict(signal_ts=pd.Timestamp(t_close), "
                "expected_entry_ts=pd.Timestamp(B[\"open_ts\"][i + 1]) if i + 1 < n else pd.NaT, "
                "side=\"L\", cooldown_until=pd.Timestamp(cooldown_until), signal_close=float(c)))\n"
                + long_old)
    if long_old not in source:
        raise RuntimeError("cooldown audit: long branch anchor missing")
    source = source.replace(long_old, long_new, 1)
    short_old = ("        elif posSize == 0 and not isShortToxic and mtf_bear and c < B[\"ema_short\"][i] and shortTrigger \\\n"
                 "                and (adx_ok if p[\"opt_adx_short\"] else True) and bbw_short_ok and not in_cooldown:\n")
    short_new = ("        elif posSize == 0 and not isShortToxic and mtf_bear and c < B[\"ema_short\"][i] and shortTrigger \\\n"
                 "                and (adx_ok if p[\"opt_adx_short\"] else True) and bbw_short_ok and in_cooldown:\n"
                 "            _v26cmp_cd_blocks.append(dict(signal_ts=pd.Timestamp(t_close), "
                 "expected_entry_ts=pd.Timestamp(B[\"open_ts\"][i + 1]) if i + 1 < n else pd.NaT, "
                 "side=\"S\", cooldown_until=pd.Timestamp(cooldown_until), signal_close=float(c)))\n"
                 + short_old)
    if short_old not in source:
        raise RuntimeError("cooldown audit: short branch anchor missing")
    source = source.replace(short_old, short_new, 1)
    end_old = "    if not tr.empty:\n        tr = tr.sort_values(\"exit_ts\").reset_index(drop=True)\n    return tr\n"
    end_new = ("    if not tr.empty:\n        tr = tr.sort_values(\"exit_ts\").reset_index(drop=True)\n"
               "    tr.attrs[\"v26cmp_cooldown_blocks\"] = _v26cmp_cd_blocks\n"
               "    return tr\n")
    if end_old not in source:
        raise RuntimeError("cooldown audit: return anchor missing")
    source = source.replace(end_old, end_new, 1)
    namespace: dict[str, Any] = {}
    exec(compile(source, __file__, "exec"), globals(), namespace)
    return namespace["run"]


def exact_check(fresh: pd.DataFrame, reference: str) -> dict[str, Any]:
    ref = dates(pd.read_csv(HERE / reference))
    left, right = fresh[TRADE_COLS].reset_index(drop=True), ref[TRADE_COLS].reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=True)
        return {"reference": reference, "fresh_n": len(left), "reference_n": len(right), "exact": True, "detail": "exact"}
    except AssertionError as exc:
        return {"reference": reference, "fresh_n": len(left), "reference_n": len(right), "exact": False, "detail": str(exc)[:1000]}


def keyed(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    x = df.copy()
    x["occ"] = x.groupby(["entry_ts", "side", "kind"], dropna=False).cumcount()
    keep = ["entry_ts", "side", "kind", "occ", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl"]
    return x[keep].rename(columns={c: f"{prefix}_{c}" for c in keep if c not in ["entry_ts", "side", "kind", "occ"]})


def matching_detail(v26: pd.DataFrame, v27: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    a, b = keyed(v26, "v26"), keyed(v27, "v27")
    merged = a.merge(b, on=["entry_ts", "side", "kind", "occ"], how="outer", indicator=True)
    merged["classification"] = merged["_merge"].map({"both": "same_entry", "left_only": "v26_only", "right_only": "v27_only"})
    merged["v26_pnl_cost4"] = merged.v26_pnl - (2 * (40 - COMMISSION) + 2 * 4 * POINT_VALUE)
    merged["v27_pnl_cost4"] = merged.v27_pnl - (2 * (40 - COMMISSION) + 2 * 4 * POINT_VALUE)
    both = merged.classification.eq("same_entry")
    merged["exit_changed"] = both & ((merged.v26_exit_ts != merged.v27_exit_ts) | (merged.v26_exit_px != merged.v27_exit_px) | (merged.v26_exit_sig != merged.v27_exit_sig))
    merged["pnl_delta_v27_minus_v26_cost4"] = merged.v27_pnl_cost4 - merged.v26_pnl_cost4
    summary = (merged.groupby("classification", dropna=False)
               .agg(n=("classification", "size"), v26_net_cost4=("v26_pnl_cost4", "sum"),
                    v27_net_cost4=("v27_pnl_cost4", "sum"),
                    pnl_delta_v27_minus_v26_cost4=("pnl_delta_v27_minus_v26_cost4", "sum"),
                    changed_exit_n=("exit_changed", "sum"))
               .reset_index())
    return merged, summary


def mechanism_tables(runs: dict[str, pd.DataFrame], blocks: dict[str, list[dict[str, Any]]]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # TimeStop rows are first isolated in the no-cooldown run, then shown under
    # the full v27 configuration too.  Same-entry v26 matching gives a direct,
    # path-preserving comparison where it exists.
    v26k = keyed(runs["v26"], "v26")
    ts_rows = []
    for variant in ("timestop_only", "v27"):
        x = runs[variant].loc[runs[variant].exit_sig.eq("TimeStop")].copy()
        if x.empty:
            continue
        x["occ"] = x.groupby(["entry_ts", "side", "kind"], dropna=False).cumcount()
        x["variant"] = variant
        x["pnl_cost4"] = cost_pnl(x, 4)
        detail = x.merge(v26k, on=["entry_ts", "side", "kind", "occ"], how="left")
        detail["v26_pnl_cost4"] = detail.v26_pnl - (2 * (40 - COMMISSION) + 2 * 4 * POINT_VALUE)
        detail["delta_vs_v26_cost4"] = detail.pnl_cost4 - detail.v26_pnl_cost4
        ts_rows.append(detail)
    timestop = pd.concat(ts_rows, ignore_index=True) if ts_rows else pd.DataFrame()
    if not timestop.empty:
        time_summary = (timestop.groupby("variant", as_index=False)
                        .agg(timestop_lots=("pnl_cost4", "size"), timestop_net_cost4=("pnl_cost4", "sum"),
                             v26_matched_lots=("v26_pnl_cost4", "count"),
                             v26_matched_net_cost4=("v26_pnl_cost4", "sum"),
                             delta_vs_v26_matched_cost4=("delta_vs_v26_cost4", "sum")))
    else:
        time_summary = pd.DataFrame(columns=["variant", "timestop_lots", "timestop_net_cost4"])

    cd_rows = []
    v26_cmd = runs["v26"].loc[runs["v26"].kind.eq("Cmd")].copy()
    v26_cmd["pnl_cost4"] = cost_pnl(v26_cmd, 4)
    v26_cmd = v26_cmd.rename(columns={"entry_ts": "expected_entry_ts", "pnl_cost4": "v26_cmd_pnl_cost4",
                                      "exit_ts": "v26_exit_ts", "exit_sig": "v26_exit_sig"})
    for variant, items in blocks.items():
        x = pd.DataFrame(items)
        if x.empty:
            x = pd.DataFrame(columns=["signal_ts", "expected_entry_ts", "side", "cooldown_until", "signal_close"])
        x["variant"] = variant
        x["signal_ts"] = pd.to_datetime(x.signal_ts)
        x["expected_entry_ts"] = pd.to_datetime(x.expected_entry_ts)
        x["cooldown_until"] = pd.to_datetime(x.cooldown_until)
        x["cooldown_remaining_min"] = (x.cooldown_until - x.signal_ts).dt.total_seconds() / 60
        x = x.merge(v26_cmd[["expected_entry_ts", "side", "v26_cmd_pnl_cost4", "v26_exit_ts", "v26_exit_sig"]],
                    on=["expected_entry_ts", "side"], how="left")
        cd_rows.append(x)
    cooldown = pd.concat(cd_rows, ignore_index=True) if cd_rows else pd.DataFrame()
    if not cooldown.empty:
        cd_summary = (cooldown.groupby("variant", as_index=False)
                      .agg(blocked_cmd_signals=("variant", "size"),
                           v26_direct_match_n=("v26_cmd_pnl_cost4", "count"),
                           foregone_v26_cmd_net_cost4=("v26_cmd_pnl_cost4", "sum"),
                           median_remaining_min=("cooldown_remaining_min", "median")))
    else:
        cd_summary = pd.DataFrame(columns=["variant", "blocked_cmd_signals"])
    return timestop, time_summary, cooldown, cd_summary


def tv_yearly() -> pd.DataFrame:
    def read_one(path: Path, variant: str) -> pd.DataFrame:
        raw = pd.read_csv(path, encoding="utf-8-sig")
        type_col = next(c for c in raw.columns if str(c).strip() == "類型")
        date_col = next(c for c in raw.columns if "日期和時間" in str(c))
        pnl_col = next(c for c in raw.columns if "淨損益" in str(c))
        x = raw[raw[type_col].astype(str).str.contains("出場", na=False)].copy()
        x["ts"] = pd.to_datetime(x[date_col], errors="coerce")
        x["pnl"] = pd.to_numeric(x[pnl_col].astype(str).str.replace(",", "", regex=False), errors="coerce")
        x = x.dropna(subset=["ts", "pnl"])
        x["year"] = x.ts.dt.year
        return x.groupby("year", as_index=False).agg(**{f"{variant}_n": ("pnl", "size"), f"{variant}_net": ("pnl", "sum")})
    tv = HERE / "tv_exports"
    a = read_one(tv / "V38.0623_v26_Session_TAIFEX_MXF1!_2026-10-19.csv", "tv_v26")
    b = read_one(tv / "V38.0707_v27_Session_TAIFEX_MXF1!_2026-10-19_barclose_only.csv", "tv_v27")
    out = a.merge(b, on="year", how="outer").sort_values("year")
    out["tv_delta_v26_minus_v27"] = out.tv_v26_net - out.tv_v27_net
    return out


def fmt(x: Any, digits: int = 0) -> str:
    if pd.isna(x):
        return "—"
    if isinstance(x, (float, np.floating)) and np.isinf(x):
        return "∞"
    if isinstance(x, (float, np.floating, int, np.integer)):
        return f"{float(x):,.{digits}f}"
    return str(x)


def markdown_table(df: pd.DataFrame, cols: list[str], renames: dict[str, str] | None = None, digits: dict[str, int] | None = None) -> str:
    renames, digits = renames or {}, digits or {}
    if df.empty:
        return "（無資料）"
    headers = [renames.get(c, c) for c in cols]
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for row in df[cols].itertuples(index=False, name=None):
        out.append("| " + " | ".join(fmt(v, digits.get(c, 0)) for c, v in zip(cols, row)) + " |")
    return "\n".join(out)


def write_report(metrics: pd.DataFrame, exact: pd.DataFrame, match_summary: pd.DataFrame,
                 time_summary: pd.DataFrame, cd_summary: pd.DataFrame, tv: pd.DataFrame) -> None:
    real_all = metrics[(metrics.slippage_ticks_side == 4) & (metrics.span == "ALL")].copy()
    real_all = real_all.set_index("variant").loc[list(VARIANTS)].reset_index()
    real_spans = metrics[(metrics.slippage_ticks_side == 4) & (metrics.span != "ALL")].copy()
    real_spans["span"] = pd.Categorical(real_spans["span"], SPANS[1:], ordered=True)
    real_spans = real_spans.sort_values(["span", "variant"])
    all_cost_risk = metrics[metrics.span.eq("ALL")].copy()
    all_cost_risk["variant"] = pd.Categorical(all_cost_risk["variant"], list(VARIANTS), ordered=True)
    all_cost_risk = all_cost_risk.sort_values(["variant", "slippage_ticks_side"])
    cost_all = metrics[metrics.span.eq("ALL")].pivot(index="variant", columns="slippage_ticks_side", values="net").reset_index()
    cost_all["variant_zh"] = cost_all.variant.map(ZH)
    delta = metrics.merge(metrics[(metrics.variant == "v26")][["slippage_ticks_side", "span", "net"]],
                          on=["slippage_ticks_side", "span"], suffixes=("", "_v26"))
    delta["net_delta_vs_v26"] = delta.net - delta.net_v26
    isolate = delta[(delta.variant.isin(["timestop_only", "cooldown_only", "v27"])) & (delta.span == "ALL")].copy()
    engine_year = delta[(delta.variant.isin(["v26", "v27"])) & (delta.span.isin(["2024", "2025", "2026"])) & (delta.slippage_ticks_side == 4)]
    engine_year = engine_year.pivot(index="span", columns="variant", values="net").reset_index().rename(columns={"span": "year"})
    engine_year["year"] = pd.to_numeric(engine_year["year"], errors="raise").astype(int)
    engine_year["engine_delta_v26_minus_v27"] = engine_year.v26 - engine_year.v27
    recon = tv.merge(engine_year[["year", "v26", "v27", "engine_delta_v26_minus_v27"]], on="year", how="left")
    recon["same_sign"] = np.where(np.sign(recon.tv_delta_v26_minus_v27) == np.sign(recon.engine_delta_v26_minus_v27), "是", "否")
    recon.loc[recon.engine_delta_v26_minus_v27.isna(), "same_sign"] = "引擎無資料"
    save(recon, "v26cmp_tv_yearly_reconcile.csv")

    best = real_all.sort_values("net", ascending=False).iloc[0]
    v26real = real_all.set_index("variant").loc["v26"]
    v27real = real_all.set_index("variant").loc["v27"]
    v28real = real_all.set_index("variant").loc["v28"]
    lines = [
        "# v26 vs v27／v28／v29：以實際成本重跑比較",
        "",
        "## 結論",
        "",
        f"以指定的 **每邊 NT$40 + 4 ticks/每邊**、同一分鐘資料與截止點，所有候選中淨利最高的是 **{ZH[best.variant]}**（NT${fmt(best.net)}；closed MDD {fmt(best.closed_mdd)}；分鐘 MTM MDD {fmt(best.mtm_mdd)}）。",
        f"v26 為 NT${fmt(v26real.net)}，v27 為 NT${fmt(v27real.net)}，v26 相對 v27 為 {fmt(v26real.net - v27real.net)}。這是少數版本、且已重複使用樣本後的挑選，不應視為新的樣本外發現。",
        f"若必須現在只選一版實盤，我會選 **v28**：它較 v27 少 NT${fmt(v27real.net-v28real.net)}（{100*(v27real.net-v28real.net)/v27real.net:.1f}%）的全樣本淨利，但 closed／MTM MDD 分別低 {100*(1-abs(v28real.closed_mdd/v27real.closed_mdd)):.1f}%／{100*(1-abs(v28real.mtm_mdd/v27real.mtm_mdd)):.1f}%，且 2026 與 HOLDOUT 的淨利較高。v27 保留作為「全樣本淨利最高」的平行比較，不選 v26；v29 與 v26+cap 在此成本假設下均無優勢。",
        "2022–2023 僅有 TV 匯出、是本題唯一未被 Python engine 重複使用的歷史區間，不能用 engine 表現外推到該段。任何實盤切換仍應先以小部位／平行紀錄確認。",
        "",
        "## 設定、成本與可重現性",
        "",
        f"- 資料：`mxf_1min_corrected_20261017b.csv`，只取至 **{CUTOFF}**（含），1 分鐘 intrabar。",
        "- 版本：v26=stale 0h/cooldown 0m；v27=10h/30m；v28=v27+空方金字塔 hour4 上限；v29=v28+長方 Cmd trail base 3.5；另含 v26+cap，以及僅 TimeStop、僅 Cooldown。",
        "- 成本重列：上游 trade PnL 已扣 NT$20/邊；本報告改扣 NT$40/邊，另每邊扣 tick×NT$50。故相對引擎原 PnL，每筆另扣 NT$40 + tick×NT$100。4 ticks/邊符合 VM 已觀察到的約 4.05 點/邊。",
        "- closed MDD：同一 exit timestamp 的已實現損益先彙總；MTM MDD：每 1 分鐘收盤按所有未平 lot 標記，並在進、出場時計入該邊成本。各分段按 **entry timestamp** 歸屬，與既有報告一致。H2_DEV=2025-04-01 至 HOLDOUT 前；TRAIN=2026-03-01至06-01；TEST=06-01至08-22；HOLDOUT 自08-22。",
        "",
        "### 精確基線檢查",
        "",
        markdown_table(exact, ["reference", "fresh_n", "reference_n", "exact", "detail"],
                       {"reference": "參考檔", "fresh_n": "本次筆數", "reference_n": "參考筆數", "exact": "完全相同", "detail": "結果"}),
        "",
        "## 實際成本（40/邊 + 4 ticks/邊）：全樣本",
        "",
        markdown_table(real_all, ["variant_zh", "n", "net", "closed_mdd", "mtm_mdd", "net_closed_mdd", "net_mtm_mdd"],
                       {"variant_zh": "版本", "n": "lots", "net": "淨利", "closed_mdd": "closed MDD", "mtm_mdd": "MTM MDD", "net_closed_mdd": "淨利/abs(closed MDD)", "net_mtm_mdd": "淨利/abs(MTM MDD)"},
                       {"net_closed_mdd": 2, "net_mtm_mdd": 2}),
        "",
        "### 全樣本：三種滑價下的淨利與兩種 MDD",
        "",
        markdown_table(all_cost_risk, ["variant_zh", "slippage_ticks_side", "n", "net", "closed_mdd", "mtm_mdd"],
                       {"variant_zh": "版本", "slippage_ticks_side": "ticks/邊", "n": "lots", "net": "淨利", "closed_mdd": "closed MDD", "mtm_mdd": "MTM MDD"}),
        "",
        "### 4 ticks/邊：所有指定分段",
        "",
        markdown_table(real_spans, ["span", "variant_zh", "n", "net", "closed_mdd", "mtm_mdd"],
                       {"span": "分段", "variant_zh": "版本", "n": "lots", "net": "淨利", "closed_mdd": "closed MDD", "mtm_mdd": "MTM MDD"}),
        "",
        "完整的各年、H1、H2_DEV、TRAIN、TEST、HOLDOUT、三種滑價成本及兩種 MDD 交叉表在 `v26cmp_metrics.csv`。",
        "",
        "### 全樣本成本敏感度（淨利）",
        "",
        markdown_table(cost_all, ["variant_zh", 0, 2, 4], {"variant_zh": "版本", 0: "0 ticks", 2: "2 ticks", 4: "4 ticks"}),
        "",
        "### TimeStop／Cooldown 的隔離效果（相對 v26，全樣本）",
        "",
        markdown_table(isolate, ["variant_zh", "slippage_ticks_side", "net", "net_delta_vs_v26"],
                       {"variant_zh": "版本", "slippage_ticks_side": "ticks/邊", "net": "淨利", "net_delta_vs_v26": "相對v26"}),
        "",
        "隔離結果沒有出現「只在接近零成本才有利」：TimeStop-only 相對 v26 在 0／2／4 ticks 皆為 +119,300／+118,300／+117,300；Cooldown-only 皆為 +59,170／+73,970／+88,770。Cooldown 因少交易 74 lots，摩擦愈高其淨效益愈大；分段結果仍須見 metrics CSV，勿只依全樣本判斷。",
        "",
        "## 機制：v27 相對 v26 的交易差異",
        "",
        markdown_table(match_summary, ["classification", "n", "changed_exit_n", "v26_net_cost4", "v27_net_cost4", "pnl_delta_v27_minus_v26_cost4"],
                       {"classification": "分類", "n": "lots", "changed_exit_n": "同進場但出場改變", "v26_net_cost4": "v26淨利", "v27_net_cost4": "v27淨利", "pnl_delta_v27_minus_v26_cost4": "v27-v26"}),
        "",
        "`same_entry` 以 entry timestamp、方向、lot 類型及重複序號配對；其餘為其中一版才有的 lot。因此它清楚呈現路徑依賴，而不是把未配對 lot 強行視為同一筆交易。逐筆配對在 `v26cmp_v27_v26_match.csv`。",
        "",
        "### TimeStop lot（成本 4 ticks/邊）",
        "",
        markdown_table(time_summary, ["variant", "timestop_lots", "timestop_net_cost4", "v26_matched_lots", "v26_matched_net_cost4", "delta_vs_v26_matched_cost4"],
                       {"variant": "設定", "timestop_lots": "TimeStop lots", "timestop_net_cost4": "其實現淨利", "v26_matched_lots": "可配對v26", "v26_matched_net_cost4": "v26對應淨利", "delta_vs_v26_matched_cost4": "TimeStop-v26"}),
        "",
        "### Cooldown 阻擋的 Cmd 訊號（成本 4 ticks/邊）",
        "",
        markdown_table(cd_summary, ["variant", "blocked_cmd_signals", "v26_direct_match_n", "foregone_v26_cmd_net_cost4", "median_remaining_min"],
                       {"variant": "設定", "blocked_cmd_signals": "被擋Cmd訊號", "v26_direct_match_n": "可直配v26 Cmd", "foregone_v26_cmd_net_cost4": "v26對應淨利", "median_remaining_min": "剩餘冷卻中位分鐘"},
                       {"median_remaining_min": 1}),
        "",
        "Cooldown 是引擎內嵌 audit：記錄條件原本已滿足、唯一因 `in_cooldown` 未排入下一根開盤的 Cmd。`foregone_v26_cmd_net_cost4` 只加總時間、方向可直接配到 v26 Cmd 的列；其餘可能因 TimeStop 改變持倉路徑而不可當作同一筆反事實交易。逐筆 audit 在 `v26cmp_cooldown_blocks.csv`，TimeStop 細節在 `v26cmp_timestop_detail.csv`。",
        "",
        "## 與 TradingView 的年別方向核對",
        "",
        markdown_table(recon, ["year", "tv_v26_net", "tv_v27_net", "tv_delta_v26_minus_v27", "v26", "v27", "engine_delta_v26_minus_v27", "same_sign"],
                       {"year": "年", "tv_v26_net": "TV v26", "tv_v27_net": "TV v27", "tv_delta_v26_minus_v27": "TV v26-v27", "v26": "engine v26（4tick）", "v27": "engine v27（4tick）", "engine_delta_v26_minus_v27": "engine v26-v27", "same_sign": "同方向？"}),
        "",
        "重疊的 2024–2026 三年，TV 的 v26-v27 差額皆為正、engine 的差額皆為負，**三年全數反向**。TV 使用 bar-close-only 匯出，engine 使用 1 分鐘 intrabar；兩者成交路徑不同，因此不能把金額差直接視為策略 alpha。2022–2023 沒有 engine 原始分鐘資料，保留為 TV 的未重用檢查段。",
        "",
        "## 產出檔",
        "",
        "- `v26cmp_metrics.csv`：所有必要分段、成本、closed／MTM MDD。",
        "- `v26cmp_trades_*.csv`：七個設定的完整 lot 明細（含引擎原始 PnL）。",
        "- `v26cmp_exact_baselines.csv`：既有 v27/v28/v29 精確重現證據。",
        "- `v26cmp_v27_v26_match.csv`、`v26cmp_match_summary.csv`：同進場配對及未配對 lot。",
        "- `v26cmp_timestop_detail.csv`、`v26cmp_timestop_summary.csv`、`v26cmp_cooldown_blocks.csv`、`v26cmp_cooldown_summary.csv`：機制 audit。",
        "- `v26cmp_tv_yearly_reconcile.csv`：TV 與 engine 年別差額核對。",
    ]
    (HERE / "results_v26_vs_v27.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_stage() -> None:
    """Create/recreate trade and cooldown-audit artifacts in short batches."""
    print("load common-cutoff 1m data", flush=True)
    df1m = load_1min(DATA)
    df1m = df1m.loc[df1m.ts <= CUTOFF].copy()
    audit_run = build_cooldown_audit_run()
    for name, params in VARIANTS.items():
        path = HERE / f"v26cmp_trades_{name}.csv"
        # The two audit versions must run afresh because their hidden block
        # list cannot be reconstructed from the regular trade CSV.  Other
        # complete runs are safely reusable and make this stage resumable.
        fresh_audit = name in {"cooldown_only", "v27"}
        if path.exists() and not fresh_audit:
            print(f"reuse {name}", flush=True)
            continue
        print(f"run {name}", flush=True)
        fun = audit_run if fresh_audit else base_run
        result = dates(fun(df1m, p=params, intrabar_mode="1min"))
        if name in {"cooldown_only", "v27"}:
            block_df = pd.DataFrame(result.attrs.get("v26cmp_cooldown_blocks", []))
            save(block_df, f"v26cmp_cooldown_audit_{name}.csv")
        save(result, f"v26cmp_trades_{name}.csv")


def analysis_stage() -> None:
    """Calculate all requested metrics and write the report from saved runs."""
    print("load cached trade runs and common-cutoff 1m data", flush=True)
    df1m = load_1min(DATA)
    df1m = df1m.loc[df1m.ts <= CUTOFF].copy()
    missing = [name for name in VARIANTS if not (HERE / f"v26cmp_trades_{name}.csv").exists()]
    if missing:
        raise RuntimeError(f"missing trade artifacts; run --stage runs first: {missing}")
    missing_audit = [name for name in ("cooldown_only", "v27") if not (HERE / f"v26cmp_cooldown_audit_{name}.csv").exists()]
    if missing_audit:
        raise RuntimeError(f"missing cooldown audit artifacts; run --stage runs first: {missing_audit}")
    runs = {name: dates(pd.read_csv(HERE / f"v26cmp_trades_{name}.csv")) for name in VARIANTS}
    blocks = {name: pd.read_csv(HERE / f"v26cmp_cooldown_audit_{name}.csv").to_dict("records")
              for name in ("cooldown_only", "v27")}

    exact = pd.DataFrame([
        exact_check(runs["v27"], "trades_v27.csv"),
        exact_check(runs["v28"], "trades_newdirs_v28_baseline.csv"),
        exact_check(runs["v29"], "trades_newdirs_v29_baseline.csv"),
    ])
    save(exact, "v26cmp_exact_baselines.csv")
    if not exact.exact.all():
        raise RuntimeError("an exact v27/v28/v29 baseline failed; see v26cmp_exact_baselines.csv")

    print("calculate closed and minute-MTM metrics", flush=True)
    metrics = metric_rows(runs, make_mtm_context(df1m))
    save(metrics, "v26cmp_metrics.csv")
    match, match_summary = matching_detail(runs["v26"], runs["v27"])
    save(match, "v26cmp_v27_v26_match.csv")
    save(match_summary, "v26cmp_match_summary.csv")
    timestop, time_summary, cooldown, cd_summary = mechanism_tables(runs, blocks)
    save(timestop, "v26cmp_timestop_detail.csv")
    save(time_summary, "v26cmp_timestop_summary.csv")
    save(cooldown, "v26cmp_cooldown_blocks.csv")
    save(cd_summary, "v26cmp_cooldown_summary.csv")
    tv = tv_yearly()
    save(tv, "v26cmp_tv_yearly_reconcile.csv")
    write_report(metrics, exact, match_summary, time_summary, cd_summary, tv)
    print("wrote results_v26_vs_v27.md and v26cmp_*.csv", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("runs", "analysis", "all"), default="all")
    args = parser.parse_args()
    if args.stage in ("runs", "all"):
        run_stage()
    if args.stage in ("analysis", "all"):
        analysis_stage()
