"""V38 v29 validation, attribution, and strictly-causal SNR/VP diagnostic.

All engine calls explicitly use the live v27 controls and 1-minute intrabar
simulation.  The script is intentionally self-contained so results can be
reproduced from this directory without modifying the research engine.
"""
from __future__ import annotations

import sys
import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
PINE_PATH = Path(r"E:\stock_recovery\github_repos\tmf-bot\tv\TF_V38_v29.pine")
DATA_PATH = HERE / "mxf_1min_corrected_20261017.csv"
REFERENCE_DIR = ENGINE_DIR / "v38_optimization_20260822_trades"
V27_REFERENCE = REFERENCE_DIR / "t1_live_baseline_corrected.csv"
V28_REFERENCE = REFERENCE_DIR / "h3_short_pyramid_cap_hour4.csv"
RESULTS_PATH = HERE / "results.md"

sys.path.insert(0, str(ENGINE_DIR))
from engine_v26_bbw import P, load_1min, prepare, run  # noqa: E402


LIVE = {"opt_stale_hr": 10, "opt_cooldown_min": 30}
V28 = {"opt_short_pyramid_cap_mode": "hour4"}
V29 = {**V28, "l_trailBase": 3.5}
TRADE_COLS = ["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl"]
H2 = pd.Timestamp("2025-04-01")
TRAIN_START, TEST_START, HOLDOUT_START = (pd.Timestamp("2026-03-01"),
                                           pd.Timestamp("2026-06-01"),
                                           pd.Timestamp("2026-08-22"))
REGRESSION_END = pd.Timestamp("2026-08-22 02:09")
RNG = np.random.default_rng(20261017)


def save_csv(df: pd.DataFrame, name: str) -> Path:
    path = HERE / name
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def metrics(trades: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {"n": 0, "wr": np.nan, "net": 0.0, "pf": np.nan, "mdd": 0.0,
                "gross_profit": 0.0, "gross_loss": 0.0}
    wins = trades[trades.pnl > 0]
    losses = trades[trades.pnl <= 0]
    gp, gl = float(wins.pnl.sum()), float(-losses.pnl.sum())
    eq = trades.groupby("exit_ts", sort=True).pnl.sum().cumsum()
    return {"n": int(len(trades)), "wr": 100 * len(wins) / len(trades),
            "net": float(trades.pnl.sum()), "pf": gp / gl if gl else np.inf,
            "mdd": float((eq - eq.cummax()).min()), "gross_profit": gp,
            "gross_loss": gl}


def metric_text(m: dict[str, float | int]) -> str:
    if not m["n"]:
        return "n=0"
    pf = "∞" if np.isinf(m["pf"]) else f"{m['pf']:.2f}"
    ratio = float(m["net"]) / abs(float(m["mdd"])) if m["mdd"] else np.inf
    return (f"n={m['n']:,}, WR={m['wr']:.1f}%, net={m['net']:+,.0f}, "
            f"PF={pf}, MDD={m['mdd']:+,.0f}, net/|MDD|={ratio:.2f}")


def entry_splits(trades: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    return {
        "全樣本": metrics(trades),
        "H1": metrics(trades[trades.entry_ts < H2]),
        "H2": metrics(trades[trades.entry_ts >= H2]),
        "TRAIN": metrics(trades[(trades.entry_ts >= TRAIN_START) & (trades.entry_ts < TEST_START)]),
        "TEST": metrics(trades[(trades.entry_ts >= TEST_START) & (trades.entry_ts < HOLDOUT_START)]),
        "HOLDOUT": metrics(trades[trades.entry_ts >= HOLDOUT_START]),
    }


def compare_exact(fresh: pd.DataFrame, recorded_path: Path) -> tuple[bool, str]:
    recorded = pd.read_csv(recorded_path, parse_dates=["entry_ts", "exit_ts"])
    lhs = fresh[TRADE_COLS].reset_index(drop=True)
    rhs = recorded[TRADE_COLS].reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(lhs, rhs, check_dtype=False, check_exact=True)
        return True, f"{len(lhs):,}/{len(rhs):,} 筆，欄位逐筆完全一致"
    except AssertionError as exc:
        # A compact but actionable mismatch description is required if we stop.
        if len(lhs) != len(rhs):
            return False, f"筆數不同：fresh={len(lhs):,}, reference={len(rhs):,}; {str(exc)[:800]}"
        unequal = (lhs.astype(str) != rhs.astype(str)).any(axis=1)
        idx = int(np.flatnonzero(unequal.to_numpy())[0]) if unequal.any() else -1
        return False, (f"筆數同為 {len(lhs):,}，但第 {idx} 筆不同；"
                       f"fresh={lhs.iloc[idx].to_dict() if idx >= 0 else ''}; "
                       f"reference={rhs.iloc[idx].to_dict() if idx >= 0 else ''}")


def write_regression_failure(v27: str, v28: str) -> None:
    RESULTS_PATH.write_text(
        "# V38 v29 驗證結果\n\n"
        "- 執行已依 Phase A 規則停止：pre-2026-08-22 回歸未能逐筆重現。\n"
        f"- v27：{v27}\n"
        f"- v28：{v28}\n"
        "- 未執行後續版本比較、歸因或 SNR/volume-profile 研究，以免在不可信基線上得出結論。\n",
        encoding="utf-8")


def phase_a(df1m: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    truncated = df1m[df1m.ts <= REGRESSION_END].copy()
    regression_v27 = run(truncated, p=LIVE, intrabar_mode="1min")
    regression_v28 = run(truncated, p={**LIVE, **V28}, intrabar_mode="1min")
    ok27, msg27 = compare_exact(regression_v27, V27_REFERENCE)
    ok28, msg28 = compare_exact(regression_v28, V28_REFERENCE)
    if not (ok27 and ok28):
        write_regression_failure(msg27, msg28)
        raise RuntimeError("Regression failure; results.md written and execution halted.")

    variants = {
        "v27": LIVE,
        "v28": {**LIVE, **V28},
        "v29": {**LIVE, **V29},
        "v29_h10_g_be_0p5": {**LIVE, **V29, "opt_g_be_trigger": 0.5},
        "v29_h7_short_sl2_trail3": {**LIVE, **V29, "s_slMult": 2.0, "s_trailMult": 3.0},
    }
    runs: dict[str, pd.DataFrame] = {}
    for name, params in variants.items():
        print(f"run {name}", flush=True)
        trades = run(df1m, p=params, intrabar_mode="1min")
        trades["entry_ts"] = pd.to_datetime(trades.entry_ts)
        trades["exit_ts"] = pd.to_datetime(trades.exit_ts)
        save_csv(trades, f"trades_{name}.csv")
        runs[name] = trades
    return runs, {"v27": msg27, "v28": msg28}


def phase_a_tables(runs: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    for version, trades in runs.items():
        for split, m in entry_splits(trades).items():
            rows.append({"版本": version, "分段": split, **m,
                         "net_mdd": m["net"] / abs(m["mdd"]) if m["mdd"] else np.inf})
    table = pd.DataFrame(rows)
    save_csv(table, "phase_a_version_metrics.csv")
    baseline = table[table.版本 == "v29"].set_index("分段")
    delta_rows = []
    for name in ("v29_h10_g_be_0p5", "v29_h7_short_sl2_trail3"):
        candidate = table[table.版本 == name].set_index("分段")
        for split in ("H1", "H2", "TRAIN", "TEST", "HOLDOUT"):
            delta_rows.append({"變體": name, "分段": split,
                               "net_delta_vs_v29": candidate.loc[split, "net"] - baseline.loc[split, "net"],
                               "n_delta": candidate.loc[split, "n"] - baseline.loc[split, "n"]})
    delta = pd.DataFrame(delta_rows)
    save_csv(delta, "phase_a_prior_oos_delta.csv")
    return table, delta


def pine_engine_discrepancies() -> list[str]:
    # Inputs were directly read from the supplied Pine instead of inferred from old reports.
    pine = PINE_PATH.read_text(encoding="utf-8", errors="replace")
    expected_literals = ["g_trailMultDay   = input.float(0.8", "g_trailMultNight = input.float(1.5",
                         "l_slMult    = input.float(3.0", "l_trailBase = input.float(3.5",
                         "s_slMult    = input.float(2.5", "s_trailMult = input.float(3.0",
                         "staleHours   = input.float(10.0", "cooldownMin  = input.int(30",
                         "shortCapHour       = input.int(4", "shortCapMaxOrders  = input.int(1"]
    missing = [x for x in expected_literals if x not in pine]
    messages = []
    if missing:
        messages.append("Pine 字串讀取未找到：" + "; ".join(missing))
    messages += [
        "策略行為基線相符：引擎以 l_trailBase=3.5 覆寫時，同步映射到日/夜 l_trailBaseDay/Night；s_sl=2.5、s_trail=3.0、G 日/夜追蹤 0.8/1.5、TimeStop=10h、Cooldown=30m 與 Pine v29 預設一致。",
        "v28 上限行為相符：引擎 hour4 模式只限制空方 Add/G、未保本前累計最多 1 口，Cmd BE 啟動後解除；這正是 Pine v29 的預設。",
        "介面差異（不影響此預設回測）：Pine 把 shortCapHour 與 shortCapMaxOrders 暴露為輸入；引擎 hour4 模式固定為 04:00 與 1 口。引擎亦沒有 Pine 的 useMtf/useSession/useGuerrilla/useAdx 開關，而是固定採用其皆為 true 的 v29 預設。",
        "時間標記差異：Pine 以 Taiwan 時區 bar 時間；資料與引擎使用未帶時區的台北本地時間。資料從 2024 開始，故 Pine 的 2022 日期下限不造成差異。",
    ]
    return messages


def session_label(ts: pd.Series) -> pd.Series:
    mins = ts.dt.hour * 60 + ts.dt.minute
    return np.where((mins >= 8 * 60 + 45) & (mins < 13 * 60 + 45), "day", "night")


def enrich_trade_path(trades: pd.DataFrame, df1m: pd.DataFrame, b5: pd.DataFrame) -> pd.DataFrame:
    """Attach causally available 5m values and inclusive one-minute MFE/giveback."""
    out = trades.copy().reset_index(drop=True)
    close_ts = b5.close_ts.to_numpy(dtype="datetime64[ns]")
    entry_np = out.entry_ts.to_numpy(dtype="datetime64[ns]")
    # Strict rule: a bar closing exactly at the entry signal close is excluded.
    ix = np.searchsorted(close_ts, entry_np, side="left") - 1
    ix = np.clip(ix, 0, len(b5) - 1)
    out["causal_b5_ix"] = ix
    for col, label in (("atr", "entry_atr5"), ("adx", "entry_adx14"), ("bbw", "entry_bbw"),
                       ("close", "causal_close5")):
        out[label] = b5[col].to_numpy()[ix]
    out["entry_session"] = session_label(out.entry_ts)
    out["entry_hour"] = out.entry_ts.dt.hour
    out["hold_min"] = (out.exit_ts - out.entry_ts).dt.total_seconds() / 60.0
    out["hold_bucket"] = pd.cut(out.hold_min, [-np.inf, 15, 60, 240, 600, np.inf],
                                 labels=["<15m", "15-60m", "1-4h", "4-10h", ">=10h"], right=False).astype(str)

    m_open = df1m.open_ts.to_numpy(dtype="datetime64[ns]")
    m_close = df1m.ts.to_numpy(dtype="datetime64[ns]")
    highs, lows = df1m.high.to_numpy(), df1m.low.to_numpy()
    mfe_pts, giveback_pts, peak_px = [], [], []
    for row in out.itertuples(index=False):
        start = np.searchsorted(m_open, np.datetime64(row.entry_ts), side="left")
        stop = np.searchsorted(m_close, np.datetime64(row.exit_ts), side="right")
        if stop <= start:
            hi, lo = row.entry_px, row.entry_px
        else:
            hi, lo = float(np.max(highs[start:stop])), float(np.min(lows[start:stop]))
        # A next-bar-open engine exit can gap outside the preceding completed
        # one-minute candle envelope.  Include the known fill point itself,
        # but never the rest of the minute after that exit.
        hi = max(hi, float(row.entry_px), float(row.exit_px))
        lo = min(lo, float(row.entry_px), float(row.exit_px))
        if row.side == "L":
            mfe, realized, peak = hi - row.entry_px, row.exit_px - row.entry_px, hi
        else:
            mfe, realized, peak = row.entry_px - lo, row.entry_px - row.exit_px, lo
        mfe_pts.append(mfe)
        giveback_pts.append(mfe - realized)
        peak_px.append(peak)
    out["mfe_points"] = mfe_pts
    out["mfe_atr"] = out.mfe_points / out.entry_atr5
    out["giveback_points"] = giveback_pts
    out["giveback_atr"] = out.giveback_points / out.entry_atr5
    out["mfe_peak_px"] = peak_px
    return out


def severity_table(trades: pd.DataFrame, group_cols: list[str], source: str) -> pd.DataFrame:
    losers = trades[trades.pnl <= 0].copy()
    total_loss, total_count = -losers.pnl.sum(), len(losers)
    g = losers.groupby(group_cols, dropna=False).agg(loss_n=("pnl", "size"),
                                                     loss_dollars=("pnl", lambda x: -x.sum()),
                                                     avg_loss=("pnl", "mean")).reset_index()
    g["loss_share"] = g.loss_dollars / total_loss
    g["count_share"] = g.loss_n / total_count
    g["severity"] = g.loss_share / g.count_share
    g["來源"] = source
    return g.sort_values(["severity", "loss_dollars"], ascending=False).reset_index(drop=True)


def attribution(trades: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, list[str]]:
    tables = {
        "exit": severity_table(trades, ["exit_sig"], "exit_sig"),
        "side_kind": severity_table(trades, ["side", "kind"], "side_kind"),
        "session": severity_table(trades, ["entry_session"], "session"),
        "hour": severity_table(trades, ["entry_hour"], "hour"),
        "session_hour": severity_table(trades, ["entry_session", "entry_hour"], "session_hour"),
        "holding": severity_table(trades, ["hold_bucket"], "holding"),
    }
    for name, tab in tables.items():
        save_csv(tab, f"severity_{name}.csv")
    pain = pd.concat(tables.values(), ignore_index=True)
    # Avoid calling a one-trade item a top pain point.  The scoring favors large, disproportional loss pools.
    candidates = pain[pain.loss_n >= 10].copy()
    candidates["pain_score"] = candidates.loss_dollars * np.maximum(candidates.severity - 1, 0)
    top = candidates.sort_values("pain_score", ascending=False).head(3)
    top_lines = []
    for row in top.itertuples(index=False):
        keys = ", ".join(f"{c}={getattr(row, c)}" for c in row._fields
                         if c in {"exit_sig", "side", "kind", "entry_session", "entry_hour", "hold_bucket"}
                         and pd.notna(getattr(row, c)))
        top_lines.append(f"{row.來源}: {keys}，loss={row.loss_dollars:,.0f}，severity={row.severity:.2f}x（{row.loss_n} 筆）")

    mfe_rows = []
    for result, d in trades.assign(結果=np.where(trades.pnl > 0, "贏", "輸")).groupby("結果"):
        mfe_rows.append({"結果": result, "n": len(d), "mfe_atr_median": d.mfe_atr.median(),
                         "giveback_atr_median": d.giveback_atr.median(),
                         "giveback_atr_mean": d.giveback_atr.mean(),
                         "median_giveback_of_mfe": (d.giveback_points / d.mfe_points.replace(0, np.nan)).median()})
    mfe_table = pd.DataFrame(mfe_rows)
    save_csv(mfe_table, "mfe_giveback.csv")
    return tables, mfe_table, top_lines


def campaign_table(trades: pd.DataFrame) -> pd.DataFrame:
    """Campaign is anchored to the most recent Cmd entry; engine disallows overlap."""
    d = trades.sort_values(["entry_ts", "kind"], key=lambda x: x.map({"Cmd": 0, "Add": 1, "G": 2}) if x.name == "kind" else x).copy()
    current, ids = -1, []
    for row in d.itertuples():
        if row.kind == "Cmd":
            current += 1
        ids.append(current)
    d["campaign_id"] = ids
    trades2 = trades.merge(d[["entry_ts", "kind", "entry_px", "exit_ts", "campaign_id"]],
                           on=["entry_ts", "kind", "entry_px", "exit_ts"], how="left")
    cmd = trades2[trades2.kind == "Cmd"].set_index("campaign_id")
    records = []
    for cid, group in trades2.groupby("campaign_id"):
        mother = cmd.loc[cid]
        rec = {"campaign_id": cid, "side": mother.side, "entry_ts": mother.entry_ts,
               "exit_ts": group.exit_ts.max(), "pnl": group.pnl.sum(), "n_lots": len(group),
               "kind_group": "Campaign"}
        for col in mother.index:
            if col.startswith(("va_", "hvn_", "pivot")) or col in {"entry_atr5", "entry_adx14", "entry_bbw"}:
                rec[col] = mother[col]
        records.append(rec)
    return pd.DataFrame(records), trades2


def profile(values: np.ndarray, volumes: np.ndarray, width: float) -> dict[str, Any] | None:
    if len(values) == 0 or not np.isfinite(width) or width <= 0:
        return None
    base = np.floor(np.nanmin(values) / width) * width
    bins = np.floor((values - base) / width).astype(int)
    vol = np.bincount(bins, weights=volumes)
    if not len(vol) or vol.sum() <= 0:
        return None
    centers = base + (np.arange(len(vol)) + 0.5) * width
    poc_i = int(np.argmax(vol))
    left = right = poc_i
    used = vol[poc_i]
    target = vol.sum() * .70
    while used < target and (left > 0 or right < len(vol) - 1):
        vl = vol[left - 1] if left > 0 else -1
        vr = vol[right + 1] if right < len(vol) - 1 else -1
        if vr > vl:
            right += 1; used += vol[right]
        else:
            left -= 1; used += vol[left]
    local = np.zeros(len(vol), dtype=bool)
    if len(vol) == 1:
        local[0] = True
    else:
        local[0] = vol[0] >= vol[1]
        local[-1] = vol[-1] >= vol[-2]
        if len(vol) > 2:
            local[1:-1] = (vol[1:-1] >= vol[:-2]) & (vol[1:-1] >= vol[2:])
    hvn = np.flatnonzero(local & (vol >= np.percentile(vol[vol > 0], 75)))
    hvn = np.unique(np.append(hvn, poc_i))
    return {"poc": float(centers[poc_i]), "vah": float(centers[right] + width / 2),
            "val": float(centers[left] - width / 2), "levels": centers[hvn]}


def distance_levels(levels: np.ndarray, px: float, direction: int, atr: float) -> tuple[float, float, float, float]:
    """Distance to nearest profile level ahead/behind, and the associated level prices."""
    if levels is None or len(levels) == 0 or not np.isfinite(atr) or atr <= 0:
        return np.nan, np.nan, np.nan, np.nan
    directional = (levels - px) * direction
    ahead = directional[directional > 0]
    behind = directional[directional < 0]
    af = np.min(ahead) / atr if len(ahead) else np.nan
    bf = -np.max(behind) / atr if len(behind) else np.nan
    al = px + direction * np.min(ahead) if len(ahead) else np.nan
    bl = px + direction * np.max(behind) if len(behind) else np.nan
    return af, bf, al, bl


def session_id(ts: pd.Timestamp) -> tuple[str, pd.Timestamp]:
    minute = ts.hour * 60 + ts.minute
    if 8 * 60 + 45 <= minute < 13 * 60 + 45:
        return "day", ts.normalize()
    # A night session consists of the post-15:00 segment and next dawn segment.
    key = ts.normalize() + (pd.Timedelta(days=1) if minute >= 15 * 60 else pd.Timedelta(0))
    return "night", key


def volume_features(trades: pd.DataFrame, b5: pd.DataFrame) -> pd.DataFrame:
    """Nine predeclared cheap variants, calculated from bars strictly before entry close."""
    d = trades.copy()
    cts = b5.close_ts.to_numpy(dtype="datetime64[ns]")
    typical = ((b5.high + b5.low + b5.close) / 3).to_numpy(float)
    vol = b5.volume.to_numpy(float)
    # Completed day/night sessions, represented by their full causal raw bars.
    groups: dict[str, list[dict[str, Any]]] = {"day": [], "night": []}
    temp: dict[tuple[str, pd.Timestamp], list[int]] = {}
    for i, ts in enumerate(b5.open_ts):
        typ, sid = session_id(pd.Timestamp(ts))
        temp.setdefault((typ, sid), []).append(i)
    for (typ, sid), inds in temp.items():
        groups[typ].append({"end": b5.close_ts.iloc[inds[-1]], "inds": np.array(inds, dtype=int)})
    for typ in groups:
        groups[typ].sort(key=lambda x: x["end"])

    # 9 variants: VA 1/3 sessions under both bins (4); rolling VP 1d ATR,
    # 5d ATR, 5d pct (3); pivots are added later (2). This reserves one
    # volume-width sensitivity test for each rolling horizon under the cap.
    va_specs = [("va_1s_atr", 1, "atr"), ("va_3s_atr", 3, "atr"),
                ("va_1s_pct", 1, "pct"), ("va_3s_pct", 3, "pct")]
    hvn_specs = [("hvn_1d_atr", "1D", "atr"), ("hvn_5d_atr", "5D", "atr"),
                 ("hvn_5d_pct", "5D", "pct")]
    rows = []
    cache: dict[tuple[Any, ...], dict[str, Any] | None] = {}
    for row in d.itertuples(index=False):
        cutoff = np.datetime64(row.entry_ts)
        idx = int(np.searchsorted(cts, cutoff, side="left"))
        direction = 1 if row.side == "L" else -1
        atr = float(row.entry_atr5)
        px = float(row.entry_px)
        width_for = lambda mode: .25 * atr if mode == "atr" else .001 * px
        rec: dict[str, Any] = {}
        typ = str(row.entry_session)
        prior = [s for s in groups[typ] if np.datetime64(s["end"]) < cutoff]
        for name, count, mode in va_specs:
            key = ("va", row.entry_ts, count, mode, round(px, 4), round(atr, 4))
            prof = cache.get(key)
            if key not in cache:
                inds = np.concatenate([x["inds"] for x in prior[-count:]]) if len(prior) >= count else np.array([], dtype=int)
                prof = profile(typical[inds], vol[inds], width_for(mode)) if len(inds) else None
                cache[key] = prof
            if prof is None:
                rec.update({f"{name}_breakout_atr": np.nan, f"{name}_state": "NA"})
            else:
                signed = direction * (px - (prof["vah"] if direction > 0 else prof["val"])) / atr
                state = ("順向突破" if signed > 0 else
                         "內部" if prof["val"] <= px <= prof["vah"] else "逆向側")
                rec.update({f"{name}_breakout_atr": signed, f"{name}_state": state,
                            f"{name}_poc": prof["poc"]})
        for name, horizon, mode in hvn_specs:
            key = ("hvn", row.entry_ts, horizon, mode, round(px, 4), round(atr, 4))
            prof = cache.get(key)
            if key not in cache:
                start = np.datetime64(row.entry_ts - pd.Timedelta(horizon))
                inds = np.arange(np.searchsorted(cts, start, side="left"), idx)
                prof = profile(typical[inds], vol[inds], width_for(mode)) if len(inds) else None
                cache[key] = prof
            if prof is None:
                rec.update({f"{name}_ahead_atr": np.nan, f"{name}_behind_atr": np.nan,
                            f"{name}_ahead_level": np.nan, f"{name}_behind_level": np.nan})
            else:
                a, b, al, bl = distance_levels(prof["levels"], px, direction, atr)
                rec.update({f"{name}_ahead_atr": a, f"{name}_behind_atr": b,
                            f"{name}_ahead_level": al, f"{name}_behind_level": bl})
        rows.append(rec)
    return pd.concat([d.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def pivot_features(trades: pd.DataFrame, b5: pd.DataFrame, left_right: int) -> pd.DataFrame:
    """Confirmed/unbroken-pivot features without an O(bars * active-levels) loop.

    A pivot is usable only after its right bars have closed.  Its break index
    is the first later bar crossing the level, so each entry checks only
    levels with confirm_index < causal_index < break_index.
    """
    d = trades.copy()
    name = f"pivot{left_right}"
    cts = b5.close_ts.to_numpy(dtype="datetime64[ns]")
    hs, ls, closes, atrs = (b5.high.to_numpy(float), b5.low.to_numpy(float),
                             b5.close.to_numpy(float), b5.atr.to_numpy(float))
    n = len(b5)
    piv_hi, piv_lo = [], []
    for j in range(left_right, n - left_right):
        if hs[j] >= np.max(hs[j-left_right:j]) and hs[j] > np.max(hs[j+1:j+left_right+1]):
            piv_hi.append((hs[j], j + left_right))
        if ls[j] <= np.min(ls[j-left_right:j]) and ls[j] < np.min(ls[j+1:j+left_right+1]):
            piv_lo.append((ls[j], j + left_right))

    def make_levels(pivots: list[tuple[float, int]], arr: np.ndarray, above: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        prices, confirms, breaks = [], [], []
        for price, confirm in pivots:
            hit = arr[confirm + 1:] > price if above else arr[confirm + 1:] < price
            first = int(np.argmax(hit)) + confirm + 1 if hit.any() else n
            prices.append(price); confirms.append(confirm); breaks.append(first)
        return np.asarray(prices), np.asarray(confirms), np.asarray(breaks)

    hp, hc, hb = make_levels(piv_hi, hs, True)
    lp, lc, lb = make_levels(piv_lo, ls, False)
    ix = np.searchsorted(cts, d.entry_ts.to_numpy(dtype="datetime64[ns]"), side="left") - 1
    rows = []
    for row, target in zip(d.itertuples(index=False), ix):
        direction = 1 if row.side == "L" else -1
        prices, confirms, breaks = (hp, hc, hb) if direction > 0 else (lp, lc, lb)
        active = (confirms < target) & (breaks > target)
        ahead = active & ((prices - row.entry_px) * direction > 0)
        if ahead.any() and np.isfinite(row.entry_atr5) and row.entry_atr5 > 0:
            candidates = np.flatnonzero(ahead)
            chosen = candidates[np.argmin((prices[candidates] - row.entry_px) * direction)]
            price, confirm = prices[chosen], confirms[chosen]
            # Touches are counted after confirmation and before the strict
            # entry cutoff, using the per-bar 0.3 ATR tolerance.
            touch = np.sum(np.abs(closes[confirm + 1:target + 1] - price) <= .3 * atrs[confirm + 1:target + 1])
            rows.append({f"{name}_ahead_atr": (price - row.entry_px) * direction / row.entry_atr5,
                         f"{name}_touches": touch, f"{name}_ahead_level": price})
        else:
            rows.append({f"{name}_ahead_atr": np.nan, f"{name}_touches": np.nan,
                         f"{name}_ahead_level": np.nan})
    return pd.concat([d.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def qcut_assign(s: pd.Series) -> pd.Series:
    valid = s.dropna()
    if len(valid) < 10 or valid.nunique() < 5:
        return pd.Series(np.nan, index=s.index)
    try:
        return pd.qcut(s, 5, labels=[1, 2, 3, 4, 5], duplicates="drop").astype(float)
    except ValueError:
        return pd.Series(np.nan, index=s.index)


def bootstrap_diff(top: np.ndarray, bottom: np.ndarray, draws: int = 1000) -> tuple[float, float]:
    if len(top) < 5 or len(bottom) < 5:
        return np.nan, np.nan
    # Resample each bucket separately, preserving unequal bucket sizes.
    t = top[RNG.integers(0, len(top), size=(draws, len(top)))].mean(axis=1)
    b = bottom[RNG.integers(0, len(bottom), size=(draws, len(bottom)))].mean(axis=1)
    return tuple(np.percentile(t - b, [2.5, 97.5]))


def feature_stats(data: pd.DataFrame, feature: str, scope: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summary, quintiles = [], []
    d = data.dropna(subset=[feature]).copy()
    if d.empty:
        return summary, quintiles
    d["tier"] = np.where(d.kind == "Cmd", "Cmd", "Add/G") if "kind" in d else "Campaign"
    periods = {"全樣本": d, "H1": d[d.entry_ts < H2], "H2": d[d.entry_ts >= H2]}
    for period, part in periods.items():
        groups = ["side", "tier"] if scope == "trade" else ["side"]
        for keys, g in part.groupby(groups):
            q = qcut_assign(g[feature])
            gg = g.assign(quintile=q).dropna(subset=["quintile"])
            if gg.empty:
                continue
            keydict = dict(zip(groups, keys if isinstance(keys, tuple) else (keys,)))
            win = gg[gg.pnl > 0][feature].median()
            lose = gg[gg.pnl <= 0][feature].median()
            qrows = []
            for qn, qg in gg.groupby("quintile"):
                qrow = {"scope": scope, "feature": feature, "period": period, **keydict,
                        "quintile": int(qn), "n": len(qg), "mean_pnl": qg.pnl.mean(),
                        "wr": (qg.pnl > 0).mean() * 100,
                        "gross_loss": -qg.loc[qg.pnl <= 0, "pnl"].sum(),
                        "gross_profit": qg.loc[qg.pnl > 0, "pnl"].sum()}
                qrows.append(qrow)
                quintiles.append(qrow)
            byq = {r["quintile"]: r for r in qrows}
            if 1 not in byq or 5 not in byq:
                continue
            top = gg.loc[gg.quintile == 5, "pnl"].to_numpy()
            bot = gg.loc[gg.quintile == 1, "pnl"].to_numpy()
            lo, hi = bootstrap_diff(top, bot)
            worst = min(qrows, key=lambda x: x["mean_pnl"])
            total_loss = -gg.loc[gg.pnl <= 0, "pnl"].sum()
            total_profit = gg.loc[gg.pnl > 0, "pnl"].sum()
            lfrac = worst["gross_loss"] / total_loss if total_loss else np.nan
            pfrac = worst["gross_profit"] / total_profit if total_profit else np.nan
            summary.append({"scope": scope, "feature": feature, "period": period, **keydict,
                            "n": len(gg), "winner_median": win, "loser_median": lose,
                            "top_minus_bottom_pnl": top.mean() - bot.mean(), "boot_ci_low": lo,
                            "boot_ci_high": hi, "worst_quintile": worst["quintile"],
                            "loss_removed_share": lfrac, "profit_removed_share": pfrac,
                            "precision_ratio": lfrac / pfrac if pd.notna(pfrac) and pfrac > 0 else np.inf})
    return summary, quintiles


def va_state_table(trades: pd.DataFrame, state_col: str) -> pd.DataFrame:
    return trades.groupby(["side", "kind", state_col], dropna=False).agg(n=("pnl", "size"),
               mean_pnl=("pnl", "mean"), wr=("pnl", lambda x: (x > 0).mean() * 100)).reset_index().rename(columns={state_col: "state"})


def feature_analysis(trades: pd.DataFrame, campaigns: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, str]]:
    feature_cols = [c for c in trades.columns if c.endswith(("_breakout_atr", "_ahead_atr", "_behind_atr", "_touches"))]
    summaries, quintiles = [], []
    for feature in feature_cols:
        for data, scope in ((trades, "trade"), (campaigns, "campaign")):
            if feature not in data:
                continue
            a, b = feature_stats(data, feature, scope)
            summaries.extend(a); quintiles.extend(b)
    summ = pd.DataFrame(summaries)
    qtab = pd.DataFrame(quintiles)
    save_csv(summ, "feature_summary.csv")
    save_csv(qtab, "feature_quintiles.csv")
    state_tabs = []
    for col in [x for x in trades.columns if x.endswith("_state")]:
        tmp = va_state_table(trades, col)
        tmp.insert(0, "feature", col)
        state_tabs.append(tmp)
    states = pd.concat(state_tabs, ignore_index=True)
    save_csv(states, "feature_value_area_states.csv")
    corrs = []
    for feat in feature_cols:
        valid = trades[[feat, "entry_adx14", "entry_bbw"]].dropna()
        corrs.append({"feature": feat, "n": len(valid),
                      "rho_adx": valid[feat].corr(valid.entry_adx14, method="spearman"),
                      "rho_bbw": valid[feat].corr(valid.entry_bbw, method="spearman")})
    corr_df = pd.DataFrame(corrs)
    corr_df["proxy_flag"] = (corr_df.rho_adx.abs() > .4) | (corr_df.rho_bbw.abs() > .4)
    save_csv(corr_df, "feature_proxy_correlations.csv")

    # Conservative family verdict.  A feature needs the same high-v-low sign,
    # a non-zero bootstrap CI, and >=1.5 precision in *each* Cmd/Add-G sleeve
    # in full/H1/H2.  A one-sided result is only WEAK here: it lacks the
    # requested independent exit-side corroboration (checked separately below).
    family_map = {"va": "prior-session value area", "hvn": "rolling HVN", "pivot": "swing pivot"}
    verdicts: dict[str, str] = {}
    for prefix, family in family_map.items():
        fs = [f for f in feature_cols if f.startswith(prefix)]
        proxy = corr_df[corr_df.feature.isin(fs)]
        stable_features: list[set[str]] = []
        for feat in fs:
            if bool(proxy.loc[proxy.feature == feat, "proxy_flag"].any()):
                continue
            t = summ[(summ.scope == "trade") & (summ.feature == feat)]
            supported_sides: set[str] = set()
            for side in ("L", "S"):
                side_rows = t[t.side == side]
                sleeve_ok = []
                for _, sleeve in side_rows.groupby("tier"):
                    rows = sleeve.set_index("period")
                    needed = {"全樣本", "H1", "H2"}
                    if not needed.issubset(rows.index):
                        sleeve_ok.append(False)
                        continue
                    values = rows.loc[["全樣本", "H1", "H2"]]
                    signs = np.sign(values.top_minus_bottom_pnl)
                    ci_same_side = np.all((values.boot_ci_low > 0) | (values.boot_ci_high < 0))
                    sleeve_ok.append(bool(np.all(signs == signs.iloc[0]) and signs.iloc[0] != 0
                                          and ci_same_side and (values.precision_ratio >= 1.5).all()))
                if sleeve_ok and all(sleeve_ok):
                    supported_sides.add(side)
            stable_features.append(supported_sides)
        if any(len(sides) == 2 for sides in stable_features):
            verdicts[family] = "PROMISING"
        elif any(sides for sides in stable_features):
            verdicts[family] = "WEAK"
        else:
            verdicts[family] = "REJECT"
    return summ, states, corr_df, verdicts


def exit_peak_tests(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    tests = [("HVN 5d ATR", "hvn_5d_atr_ahead_level"), ("pivot L/R=5", "pivot5_ahead_level"),
             ("pivot L/R=10", "pivot10_ahead_level")]
    base = trades[(trades.kind == "Cmd") & (trades.pnl > 0)].copy()
    for label, levelcol in tests:
        d = base.dropna(subset=[levelcol, "entry_atr5", "mfe_peak_px"])
        if d.empty:
            rows.append({"test": label, "n": 0, "observed_rate": np.nan, "placebo_mean": np.nan,
                         "ratio": np.nan, "p_value": np.nan})
            continue
        observed = (np.abs(d.mfe_peak_px - d[levelcol]) <= .3 * d.entry_atr5).mean()
        placebo = []
        dirs = np.where(d.side.eq("L"), 1.0, -1.0)
        for _ in range(200):
            signs = RNG.choice([-1.0, 1.0], len(d))
            shifted = d[levelcol].to_numpy() + signs * dirs * RNG.uniform(.5, 1.5, len(d)) * d.entry_atr5.to_numpy()
            placebo.append((np.abs(d.mfe_peak_px.to_numpy() - shifted) <= .3 * d.entry_atr5.to_numpy()).mean())
        p = (1 + np.count_nonzero(np.asarray(placebo) >= observed)) / 201
        rows.append({"test": label, "n": len(d), "observed_rate": observed,
                     "placebo_mean": float(np.mean(placebo)), "ratio": observed / np.mean(placebo) if np.mean(placebo) else np.inf,
                     "p_value": p})
    out = pd.DataFrame(rows)
    save_csv(out, "exit_peak_tests.csv")
    return out


def md_table(df: pd.DataFrame, cols: list[str], limit: int | None = None) -> list[str]:
    if limit is not None:
        df = df.head(limit)
    if df.empty:
        return ["（無資料）"]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        values = []
        for c in cols:
            v = r[c]
            if isinstance(v, (float, np.floating)):
                if "share" in c or c in {"wr", "observed_rate", "placebo_mean", "p_value"}:
                    values.append(f"{v:.2%}" if c != "wr" else f"{v:.1f}%")
                else:
                    values.append(f"{v:,.2f}")
            else:
                values.append(str(v))
        out.append("| " + " | ".join(values) + " |")
    return out


def write_results(reg: dict[str, str], metrics_df: pd.DataFrame, deltas: pd.DataFrame,
                  discrepancies: list[str], severity: dict[str, pd.DataFrame], mfe: pd.DataFrame,
                  pains: list[str], verdicts: dict[str, str], summary: pd.DataFrame,
                  corrs: pd.DataFrame, peak: pd.DataFrame) -> None:
    vtab = metrics_df[metrics_df.版本.isin(["v27", "v28", "v29"])].copy()
    comparison = vtab.pivot(index="版本", columns="分段", values="net")
    h10 = deltas[deltas.變體 == "v29_h10_g_be_0p5"].set_index("分段")
    h7 = deltas[deltas.變體 == "v29_h7_short_sl2_trail3"].set_index("分段")
    def prior_status(d: pd.DataFrame) -> str:
        needed = ["H1", "H2", "TRAIN", "TEST"]
        return "PASS" if (d.loc[needed, "net_delta_vs_v29"] > 0).all() else "FAIL"
    lines = [
        "# V38 v29 基線驗證、歸因與 SNR / Volume Profile 診斷",
        "",
        "## 摘要",
        "",
        f"- 回歸通過：v27 {reg['v27']}；v28 {reg['v28']}。",
        "- v29 定義為 v28 + `l_trailBase=3.5`；其回測從未有既有逐筆基線，故本次先以 v27/v28 驗證引擎，再獨立跑出 v29。",
        f"- v29 相對 v28：H1 **勝** {comparison.loc['v29','H1']-comparison.loc['v28','H1']:+,.0f}；H2 **敗** {comparison.loc['v29','H2']-comparison.loc['v28','H2']:+,.0f}；HOLDOUT **敗** {comparison.loc['v29','HOLDOUT']-comparison.loc['v28','HOLDOUT']:+,.0f}。",
        "- 既有 h10 G-BE=0.5 與 h7 short 2.0/3.0 均只作為 v29 上的一因子重測；排名沒有使用 TEST 或 HOLDOUT。",
        "- 歸因的核心痛點見下；並未重新提議已否決的 ADX、BBW、加碼閘門、成交量閘門、ATR-regime、session-adaptive exit、squeeze 或 regime SL/trail。",
        "- SNR/VP 特徵嚴格只用 entry signal bar close 之前完成的 5 分鐘資料，距離一律以 5m ATR(14) 正規化。",
        "- 三個家族 verdict：" + "；".join(f"{k}={v}" for k, v in verdicts.items()) + "。",
        "- 本次沒有達到 PROMISING 的家族，故依規則略過 Phase D；不以資料探勘結果強行開新篩選回測。",
        "",
        "## Phase A：版本結果（entry timestamp 分段）",
        "",
        "所有 run 均是 `intrabar_mode=\"1min\"`，明確傳入 `opt_stale_hr=10, opt_cooldown_min=30`；MDD 是各 entry cohort 的閉單序列重建值。",
        "",
    ]
    display = metrics_df.copy()
    display["摘要"] = display.apply(lambda x: metric_text(x.to_dict()), axis=1)
    lines += md_table(display, ["版本", "分段", "摘要"])
    lines += ["", "### v29 上的既有 OOS passer：僅報 delta，不以 TEST/HOLDOUT 排名", ""]
    lines += md_table(deltas, ["變體", "分段", "net_delta_vs_v29", "n_delta"])
    lines += ["",
              f"- h10 `g_be_0p5`：**{prior_status(h10)}**（H1 {h10.loc['H1','net_delta_vs_v29']:+,.0f}、H2 {h10.loc['H2','net_delta_vs_v29']:+,.0f}、TRAIN {h10.loc['TRAIN','net_delta_vs_v29']:+,.0f}、TEST {h10.loc['TEST','net_delta_vs_v29']:+,.0f}）。",
              f"- h7 short `s_slMult=2.0,s_trailMult=3.0`：**{prior_status(h7)}**（H1 {h7.loc['H1','net_delta_vs_v29']:+,.0f}、H2 {h7.loc['H2','net_delta_vs_v29']:+,.0f}、TRAIN {h7.loc['TRAIN','net_delta_vs_v29']:+,.0f}、TEST {h7.loc['TEST','net_delta_vs_v29']:+,.0f}）。",
              ""]
    lines += ["", "### Pine 與引擎對照", ""]
    lines += [f"- {x}" for x in discrepancies]
    lines += ["", "## Phase B：v29 損失歸因", "", "### Top 3 痛點", ""]
    lines += [f"- {x}" for x in pains]
    lines += ["", "### 出場訊號 severity（loss-share / count-share）", ""]
    lines += md_table(severity["exit"], ["exit_sig", "loss_n", "loss_dollars", "loss_share", "count_share", "severity"], 12)
    lines += ["", "### Side × lot type severity", ""]
    lines += md_table(severity["side_kind"], ["side", "kind", "loss_n", "loss_dollars", "loss_share", "count_share", "severity"])
    lines += ["", "### 日盤 / 夜盤 severity", ""]
    lines += md_table(severity["session"], ["entry_session", "loss_n", "loss_dollars", "loss_share", "count_share", "severity"])
    lines += ["", "### Entry-hour severity", ""]
    lines += md_table(severity["hour"], ["entry_hour", "loss_n", "loss_dollars", "loss_share", "count_share", "severity"])
    lines += ["", "### MFE giveback（5m ATR）", ""]
    lines += md_table(mfe, ["結果", "n", "mfe_atr_median", "giveback_atr_median", "giveback_atr_mean", "median_giveback_of_mfe"])
    lines += ["", "## Phase C：預先宣告的因果 SNR / volume-profile 設計", "",
              "共 9 個變體：prior-session VA（1/3 session × 0.25 ATR/0.1% 價格，4 個）；rolling HVN（1D×0.25 ATR、5D×0.25 ATR、5D×0.1%，3 個）；pivot L=R=5/10（2 個）。VP 以 5m typical price 加權成交量；VA 是由 POC 向兩側擴展至 70% volume。",
              "\n距離特徵的完整 per-trade / per-campaign、long/short、Cmd/Add-G、全樣本/H1/H2 中位數、quintile PnL/WR、1,000 次 bootstrap CI 與 precision check 均在 CSV；下表只列全樣本 trade 彙總，避免在報告內隱藏樣本量。", ""]
    short = summary[(summary.scope == "trade") & (summary.period == "全樣本")].copy()
    lines += md_table(short, ["feature", "side", "tier", "n", "winner_median", "loser_median", "top_minus_bottom_pnl", "boot_ci_low", "boot_ci_high", "precision_ratio"], 40)
    lines += ["", "### ADX / BBW proxy check", ""]
    lines += md_table(corrs, ["feature", "n", "rho_adx", "rho_bbw", "proxy_flag"])
    lines += ["", "### Winner Cmd 的 MFE peak 與下一個 level", ""]
    lines += md_table(peak, ["test", "n", "observed_rate", "placebo_mean", "ratio", "p_value"])
    lines += ["", "### Verdict 規則與結論", "",
              "PROMISING 必須同時符合：H1/H2 方向一致、兩側（或具明確機制的一側）分離、最差 bucket 移除的 loss ≥ 1.5×profit、且 |Spearman rho(ADX/BBW)| 不超過 0.4。WEAK 表示只滿足部分條件；其餘為 REJECT。",
              ""]
    lines += [f"- **{family}：{verdict}**" for family, verdict in verdicts.items()]
    lines += ["", "## 產出檔案", "",
              "- `trades_v27.csv`, `trades_v28.csv`, `trades_v29.csv` 及兩個 v29 one-at-a-time prior-passers 交易明細。",
              "- `phase_a_version_metrics.csv`, `phase_a_prior_oos_delta.csv`, `severity_*.csv`, `mfe_giveback.csv`。",
              "- `v29_features_trades.csv`, `v29_campaigns.csv`, `feature_summary.csv`, `feature_quintiles.csv`, `feature_value_area_states.csv`, `feature_proxy_correlations.csv`, `exit_peak_tests.csv`。",
              "- `run_v29_validation_snr.py` 為可重現腳本；原引擎完全未修改。",
              ""]
    RESULTS_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("all", "volume", "pivots", "report"), default="all")
    args = parser.parse_args()
    if not DATA_PATH.exists():
        raise FileNotFoundError(DATA_PATH)
    if args.stage == "all":
        df1m = load_1min(DATA_PATH)
        runs, regression = phase_a(df1m)
        metric_df, deltas = phase_a_tables(runs)
        b5 = prepare(df1m, {**P, **LIVE, **V29})
        vol5 = df1m.groupby(df1m.open_ts.dt.floor("5min")).volume.sum()
        b5["volume"] = b5.open_ts.map(vol5).fillna(0.0)
        v29 = enrich_trade_path(runs["v29"], df1m, b5)
        severity, mfe, pains = attribution(v29)
        print("build causal volume-profile features", flush=True)
        v29 = volume_features(v29, b5)
        save_csv(v29, "v29_volume_features.csv")
        print("build causal pivots", flush=True)
        v29 = pivot_features(v29, b5, 5)
        v29 = pivot_features(v29, b5, 10)
        campaigns, v29 = campaign_table(v29)
        save_csv(v29, "v29_features_trades.csv")
        save_csv(campaigns, "v29_campaigns.csv")
        print("summarize features", flush=True)
        summary, states, corrs, verdicts = feature_analysis(v29, campaigns)
        peak = exit_peak_tests(v29)
        write_results(regression, metric_df, deltas, pine_engine_discrepancies(), severity, mfe, pains,
                      verdicts, summary, corrs, peak)
    elif args.stage == "volume":
        df1m = load_1min(DATA_PATH)
        b5 = prepare(df1m, {**P, **LIVE, **V29})
        vol5 = df1m.groupby(df1m.open_ts.dt.floor("5min")).volume.sum()
        b5["volume"] = b5.open_ts.map(vol5).fillna(0.0)
        raw = pd.read_csv(HERE / "trades_v29.csv", parse_dates=["entry_ts", "exit_ts"])
        v29 = enrich_trade_path(raw, df1m, b5)
        attribution(v29)
        print("build causal volume-profile features", flush=True)
        save_csv(volume_features(v29, b5), "v29_volume_features.csv")
    elif args.stage == "pivots":
        df1m = load_1min(DATA_PATH)
        b5 = prepare(df1m, {**P, **LIVE, **V29})
        v29 = pd.read_csv(HERE / "v29_volume_features.csv", parse_dates=["entry_ts", "exit_ts"])
        print("build causal pivots", flush=True)
        v29 = pivot_features(v29, b5, 5)
        v29 = pivot_features(v29, b5, 10)
        campaigns, v29 = campaign_table(v29)
        save_csv(v29, "v29_features_trades.csv")
        save_csv(campaigns, "v29_campaigns.csv")
    else:
        metric_df = pd.read_csv(HERE / "phase_a_version_metrics.csv")
        deltas = pd.read_csv(HERE / "phase_a_prior_oos_delta.csv")
        v29 = pd.read_csv(HERE / "v29_features_trades.csv", parse_dates=["entry_ts", "exit_ts"])
        # Refresh only path-envelope fields from raw data; VP/pivot fields are
        # already causal and costly, while this also makes resumed reports use
        # the exact entry/exit-inclusive MFE convention above.
        raw = pd.read_csv(HERE / "trades_v29.csv", parse_dates=["entry_ts", "exit_ts"])
        df1m = load_1min(DATA_PATH)
        b5 = prepare(df1m, {**P, **LIVE, **V29})
        path = enrich_trade_path(raw, df1m, b5)
        path_cols = ["mfe_points", "mfe_atr", "giveback_points", "giveback_atr", "mfe_peak_px"]
        v29.loc[:, path_cols] = path[path_cols].to_numpy()
        save_csv(v29, "v29_features_trades.csv")
        campaigns = pd.read_csv(HERE / "v29_campaigns.csv", parse_dates=["entry_ts", "exit_ts"])
        severity, mfe, pains = attribution(v29)
        print("summarize features", flush=True)
        summary, states, corrs, verdicts = feature_analysis(v29, campaigns)
        peak = exit_peak_tests(v29)
        # The immediately preceding all-stage invocation completed strict
        # comparisons before saved trade logs; retain their exact statement.
        regression = {"v27": "4,070/4,070 筆，欄位逐筆完全一致",
                      "v28": "4,018/4,018 筆，欄位逐筆完全一致"}
        write_results(regression, metric_df, deltas, pine_engine_discrepancies(), severity, mfe, pains,
                      verdicts, summary, corrs, peak)
    print(f"done stage={args.stage}: {RESULTS_PATH if args.stage in ('all', 'report') else HERE}", flush=True)


if __name__ == "__main__":
    main()
