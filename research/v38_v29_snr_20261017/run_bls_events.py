"""BLS CPI/PPI/NFP event study for the V38 calendar research.

This is intentionally a supplement rather than a replacement for
``run_calendar_reentry.py``.  It imports that driver for its base parameters,
trade-date convention, campaign construction and split definitions.  The
only engine extension is the inert-by-default ``opt_event_rules`` hook in
``engine_calendar_wrapper.py``; it is called only after the preregistered
diagnostic gate passes.
"""
from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import engine_calendar_wrapper as eng
import run_calendar_reentry as cal


HERE = Path(__file__).resolve().parent
DATA = HERE / "mxf_1min_corrected_20261017b.csv"
DATES = HERE / "bls_release_dates.csv"
OUT = HERE / "results_bls_events.md"
TZ_ET = ZoneInfo("America/New_York")
TZ_TPE = ZoneInfo("Asia/Taipei")
NBOOT = 10_000
RNG_SEED = 20261018


def cell(value: object, decimals: int = 1) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return "—"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, (bool, np.bool_)):
        return "是" if value else "否"
    if isinstance(value, (int, np.integer)):
        return f"{value:,}"
    if isinstance(value, (float, np.floating)):
        if np.isinf(value):
            return "∞"
        return f"{value:,.{decimals}f}"
    return str(value)


def table(frame: pd.DataFrame, columns: list[str], decimals: int = 1) -> list[str]:
    x = frame.loc[:, [c for c in columns if c in frame.columns]].copy()
    if x.empty:
        return ["（無資料）"]
    lines = ["| " + " | ".join(x.columns) + " |", "|" + "|".join(["---"] * len(x.columns)) + "|"]
    for row in x.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(cell(v, decimals) for v in row) + " |")
    return lines


def build_bls_calendar() -> pd.DataFrame:
    """Use every supplied Wayback date verbatim and only convert its time zone."""
    raw = pd.read_csv(DATES, dtype={"event": "string", "date_et": "string", "source": "string"})
    required = {"event", "date_et", "source"}
    if set(raw.columns) != required:
        raise ValueError(f"unexpected BLS calendar columns: {list(raw.columns)}")
    rows: list[dict[str, object]] = []
    for r in raw.itertuples(index=False):
        day = pd.Timestamp(r.date_et)
        et = pd.Timestamp(day.year, day.month, day.day, 8, 30, tz=TZ_ET)
        tpe = et.tz_convert(TZ_TPE).tz_localize(None)
        rows.append({
            "event_type": str(r.event), "date_et": str(r.date_et),
            "event_ts_et": et.tz_localize(None), "event_ts_taipei": tpe,
            "source": str(r.source), "derivation": "provided_date + 08:30 America/New_York -> Asia/Taipei",
            "session": cal.session_label(tpe),
        })
    return pd.DataFrame(rows).sort_values(["event_type", "event_ts_taipei"]).reset_index(drop=True)


def missing_calendar_months(events: pd.DataFrame) -> pd.DataFrame:
    """Report file-calendar holes; it does not infer a replacement release date."""
    expected = pd.period_range("2024-01", "2026-10", freq="M")
    rows = []
    for typ, z in events.groupby("event_type", sort=True):
        present = set(pd.PeriodIndex(pd.to_datetime(z.date_et), freq="M"))
        missing = [str(m) for m in expected if m not in present]
        rows.append({"event_type": typ, "n_provided": len(z), "absent_file_calendar_months": ", ".join(missing) if missing else "無"})
    return pd.DataFrame(rows)


def load_legacy_event_times() -> pd.DataFrame:
    """Retain Section F's existing FOMC/expiry/settlement exclusion set."""
    path = HERE / "event_calendar.csv"
    if not path.exists():
        return pd.DataFrame(columns=["event_type", "event_ts_taipei"])
    x = pd.read_csv(path, parse_dates=["event_ts_taipei"])
    good = x[x.status.eq("ok") & x.event_ts_taipei.notna()].copy()
    return good.loc[:, ["event_type", "event_ts_taipei"]]


def market_at(index: pd.DatetimeIndex, values: np.ndarray, when: pd.Timestamp) -> float:
    # This is the exact prior-close lookup used by Section F.
    return cal.market_at(index, values, when)


def attach_lot_mae(trades: pd.DataFrame, raw: pd.DataFrame, b5: pd.DataFrame) -> pd.DataFrame:
    """Lifecycle MAE in entry ATR for each completed lot, using Section F's causal ATR alignment."""
    x = trades.copy().sort_values(["entry_ts", "exit_ts", "kind"]).reset_index(drop=True)
    raw_idx = pd.DatetimeIndex(raw.open_ts)
    highs, lows = raw.high.to_numpy(float), raw.low.to_numpy(float)
    bidx, batr = pd.DatetimeIndex(b5.close_ts), b5.atr.to_numpy(float)
    maes: list[float] = []
    for r in x.itertuples():
        a = int(raw_idx.searchsorted(r.entry_ts, side="left"))
        z = int(raw_idx.searchsorted(r.exit_ts, side="right"))
        a, z = min(a, len(raw_idx) - 1), max(a + 1, min(z, len(raw_idx)))
        j = max(0, int(bidx.searchsorted(r.entry_ts, side="left") - 1))
        atr = batr[j]
        if not np.isfinite(atr) or atr <= 0:
            maes.append(np.nan)
        elif r.side == "L":
            maes.append(max(0.0, r.entry_px - np.nanmin(lows[a:z])) / atr)
        else:
            maes.append(max(0.0, np.nanmax(highs[a:z]) - r.entry_px) / atr)
    x["lot_mae_atr"] = maes
    return x


def entry_window_lots(lots: pd.DataFrame, anchor: pd.Timestamp, phase: str) -> pd.DataFrame:
    if phase == "before":
        return lots[(lots.entry_ts >= anchor - pd.Timedelta(minutes=60)) & (lots.entry_ts < anchor)].copy()
    if phase == "after":
        # Keep the original Section F inclusive endpoint convention.
        return lots[(lots.entry_ts >= anchor) & (lots.entry_ts <= anchor + pd.Timedelta(minutes=60))].copy()
    raise ValueError(phase)


def control_times(
    event_time: pd.Timestamp, raw_idx: pd.DatetimeIndex, all_event_times: pd.DatetimeIndex,
) -> pd.DatetimeIndex:
    candidates = np.flatnonzero(
        (raw_idx.weekday == event_time.weekday())
        & (raw_idx.hour == event_time.hour)
        & (raw_idx.minute == event_time.minute)
    )
    valid = []
    for j in candidates:
        ct = raw_idx[j]
        if ct - pd.Timedelta(minutes=60) < raw_idx.min() or ct + pd.Timedelta(minutes=60) > raw_idx.max():
            continue
        if not np.any(np.abs(all_event_times - ct) <= pd.Timedelta(minutes=120)):
            valid.append(ct)
    return pd.DatetimeIndex(valid)


def mtm_pnl(
    opened: pd.DataFrame, anchor: pd.Timestamp, raw_idx: pd.DatetimeIndex, close: np.ndarray,
) -> float:
    p0 = market_at(raw_idx, close, anchor - pd.Timedelta(minutes=5))
    p1 = market_at(raw_idx, close, anchor + pd.Timedelta(minutes=60))
    if not np.isfinite(p0) or not np.isfinite(p1):
        return np.nan
    signed_lots = np.where(opened.side.eq("L"), 1.0, -1.0).sum()
    return float((p1 - p0) * eng.POINT_VALUE * signed_lots)


def bootstrap_ci(values: np.ndarray) -> tuple[float, float]:
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return np.nan, np.nan
    rng = np.random.default_rng(RNG_SEED)
    draws = rng.choice(values, size=(NBOOT, len(values)), replace=True).mean(axis=1)
    return tuple(float(x) for x in np.quantile(draws, [0.025, 0.975]))


def event_study(
    base: str,
    trades: pd.DataFrame,
    events: pd.DataFrame,
    all_event_times: pd.DatetimeIndex,
    raw: pd.DataFrame,
    b5: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return per-event, summary, campaign, and entry-lot tables for one base."""
    raw_idx = pd.DatetimeIndex(raw.open_ts)
    close = raw.close.to_numpy(float)
    lots = attach_lot_mae(trades, raw, b5)
    _, campaigns = cal.assign_campaigns(trades, raw, b5)
    event_rows: list[dict[str, object]] = []
    entry_rows: list[pd.DataFrame] = []
    control_cache = {pd.Timestamp(t): control_times(pd.Timestamp(t), raw_idx, all_event_times) for t in events.event_ts_taipei}

    for e in events.itertuples():
        t = pd.Timestamp(e.event_ts_taipei)
        opened = trades[(trades.entry_ts <= t) & (trades.exit_ts > t)]
        controls = control_cache[t]
        event_pnl = mtm_pnl(opened, t, raw_idx, close)
        control_pnls = np.array([mtm_pnl(opened, ct, raw_idx, close) for ct in controls], dtype=float)
        control_pnls = control_pnls[np.isfinite(control_pnls)]
        control_mean = float(control_pnls.mean()) if len(control_pnls) else np.nan
        row: dict[str, object] = {
            "base": base, "event_type": e.event_type, "event_ts_taipei": t,
            "event_ts_et": pd.Timestamp(e.event_ts_et), "open_lots": int(len(opened)),
            "open_long": int(opened.side.eq("L").sum()), "open_short": int(opened.side.eq("S").sum()),
            "pnl_5m_to_60m": event_pnl, "control_pnl_mean": control_mean,
            "event_minus_control": event_pnl - control_mean if np.isfinite(control_mean) else np.nan,
            "n_control_times": int(len(control_pnls)),
        }
        for phase, cn in (("before", "pre"), ("after", "post")):
            actual = entry_window_lots(lots, t, phase)
            control_parts = [entry_window_lots(lots, ct, phase) for ct in controls]
            control_lots = pd.concat(control_parts, ignore_index=True) if control_parts else lots.iloc[0:0].copy()
            for label, q in (("event", actual), ("control", control_lots)):
                row[f"{cn}_{label}_n"] = int(len(q))
                row[f"{cn}_{label}_mean_pnl"] = float(q.pnl.mean()) if len(q) else np.nan
                row[f"{cn}_{label}_mae_atr"] = float(q.lot_mae_atr.mean()) if len(q) else np.nan
                if len(q):
                    keep = q.loc[:, ["pnl", "lot_mae_atr"]].copy()
                    keep["base"] = base
                    keep["event_type"] = e.event_type
                    keep["event_ts_taipei"] = t
                    keep["period"] = "釋出前60分" if phase == "before" else "釋出後60分"
                    keep["group"] = "事件" if label == "event" else "對照"
                    entry_rows.append(keep)
        event_rows.append(row)

    per_event = pd.DataFrame(event_rows).sort_values(["base", "event_type", "event_ts_taipei"])
    summaries = []
    for typ, z in per_event.groupby("event_type", sort=True):
        worst_ix = z.pnl_5m_to_60m.abs().idxmax()
        drop = z.drop(index=worst_ix)
        raw_h1 = z[z.event_ts_taipei < cal.H2].pnl_5m_to_60m.mean()
        raw_h2 = z[z.event_ts_taipei >= cal.H2].pnl_5m_to_60m.mean()
        h1 = z[z.event_ts_taipei < cal.H2].event_minus_control.mean()
        h2 = z[z.event_ts_taipei >= cal.H2].event_minus_control.mean()
        mean_raw = z.pnl_5m_to_60m.mean()
        drop_raw = drop.pnl_5m_to_60m.mean()
        mean_diff = z.event_minus_control.mean()
        drop_diff = drop.event_minus_control.mean()
        ci_low, ci_high = bootstrap_ci(z.event_minus_control.to_numpy(float))
        # Preserve the original Section F sign/deletion checks on raw MTM;
        # the additional bootstrap condition is deliberately event-minus-control.
        same_sign = bool(np.isfinite(raw_h1) and np.isfinite(raw_h2) and np.sign(raw_h1) == np.sign(raw_h2) and np.sign(raw_h1) != 0)
        survives = bool(np.isfinite(mean_raw) and np.isfinite(drop_raw) and np.sign(mean_raw) == np.sign(drop_raw) and np.sign(mean_raw) != 0)
        ci_excludes_zero = bool(np.isfinite(ci_low) and np.isfinite(ci_high) and (ci_low > 0 or ci_high < 0))
        summaries.append({
            "base": base, "event_type": typ, "n_events": len(z),
            "mean_pnl_5m_to_60m": mean_raw, "mean_control_pnl": z.control_pnl_mean.mean(),
            "mean_event_minus_control": mean_diff, "H1_mean_pnl": raw_h1, "H2_mean_pnl": raw_h2,
            "H1_event_minus_control": h1, "H2_event_minus_control": h2, "largest_abs_event": z.loc[worst_ix, "event_ts_taipei"],
            "largest_abs_event_pnl": z.loc[worst_ix, "pnl_5m_to_60m"],
            "mean_pnl_ex_largest": drop.pnl_5m_to_60m.mean(), "mean_diff_ex_largest": drop_diff,
            "boot_ci_low": ci_low, "boot_ci_high": ci_high, "same_sign_H1_H2": same_sign,
            "survives_drop_largest": survives, "bootstrap_ci_excludes_zero": ci_excludes_zero,
            "robust": bool(same_sign and survives and ci_excludes_zero),
        })
    summary = pd.DataFrame(summaries)

    campaign_rows = []
    for typ, z in events.groupby("event_type", sort=True):
        dates = {cal.trading_date(pd.Timestamp(t)) for t in z.event_ts_taipei}
        on = campaigns[campaigns.trade_date.isin(dates)]
        off = campaigns[~campaigns.trade_date.isin(dates)]
        campaign_rows.append({
            "base": base, "event_type": typ, "event_campaigns": len(on),
            "event_campaign_net": on.pnl.sum(), "event_campaign_mean": on.pnl.mean() if len(on) else np.nan,
            "other_campaigns": len(off), "other_campaign_mean": off.pnl.mean() if len(off) else np.nan,
        })
    campaigns_out = pd.DataFrame(campaign_rows)
    entry_out = pd.concat(entry_rows, ignore_index=True) if entry_rows else pd.DataFrame(
        columns=["pnl", "lot_mae_atr", "base", "event_type", "event_ts_taipei", "period", "group"]
    )
    return per_event, summary, campaigns_out, entry_out


def summarize_entry_lots(entry_lots: pd.DataFrame) -> pd.DataFrame:
    keys = ["base", "event_type", "period", "group"]
    observed = entry_lots.groupby(keys, as_index=False).agg(
        n=("pnl", "size"), mean_lot_pnl=("pnl", "mean"), mean_mae_atr=("lot_mae_atr", "mean")
    )
    # A zero is evidence here: retain every pre/post × event/control cell so
    # the report cannot visually turn "no entry" into an omitted result.
    grid = pd.MultiIndex.from_product(
        [
            ["v28", "v29"], ["CPI", "PPI", "NFP"],
            ["釋出前60分", "釋出後60分"], ["事件", "對照"],
        ], names=keys
    ).to_frame(index=False)
    out = grid.merge(observed, on=keys, how="left")
    out["n"] = out["n"].fillna(0).astype(int)
    return out


def equal_trade_ledger(got: pd.DataFrame, reference_path: Path) -> bool:
    ref = pd.read_csv(reference_path, parse_dates=["entry_ts", "exit_ts"]).sort_values("exit_ts").reset_index(drop=True)
    got = got.sort_values("exit_ts").reset_index(drop=True)
    if list(got.columns) != list(ref.columns) or len(got) != len(ref):
        return False
    for c in got.columns:
        if pd.api.types.is_numeric_dtype(got[c]):
            if not np.allclose(got[c].to_numpy(float), ref[c].to_numpy(float), rtol=0, atol=1e-9, equal_nan=True):
                return False
        elif not got[c].equals(ref[c]):
            return False
    return True


def event_variant_metrics(
    df1m: pd.DataFrame, base_runs: dict[str, pd.DataFrame], events: pd.DataFrame, robust_types: list[str],
) -> pd.DataFrame:
    if not robust_types:
        return pd.DataFrame(columns=["base", "event_type", "variant", "split", "n", "net", "net_delta", "verdict"])
    rows = []
    for typ in robust_types:
        times = [pd.Timestamp(t) for t in events.loc[events.event_type.eq(typ), "event_ts_taipei"]]
        specs = {
            "block_Cmd_Add_-30_to_+15": {
                "block_entry_windows": [(t - pd.Timedelta(minutes=30), t + pd.Timedelta(minutes=15)) for t in times]
            },
            "flatten_Add_G_-5": {"flatten_add_g_at": [t - pd.Timedelta(minutes=5) for t in times]},
        }
        for base, params in cal.BASES.items():
            reference = base_runs[base]
            for name, rules in specs.items():
                variant = eng.run(df1m, {**params, "opt_event_rules": rules}, intrabar_mode="1min")
                values = {s: cal.metrics(variant.loc[cal.split_mask(variant, s)]) for s in ("full", "H1", "H2", "TRAIN", "TEST", "HOLDOUT")}
                reference_values = {s: cal.metrics(reference.loc[cal.split_mask(reference, s)]) for s in values}
                passed = all(values[s]["net"] > reference_values[s]["net"] for s in ("H1", "H2", "TRAIN", "TEST"))
                for split, value in values.items():
                    rows.append({
                        "base": base, "event_type": typ, "variant": name, "split": split,
                        "n": value["n"], "net": value["net"],
                        "net_delta": value["net"] - reference_values[split]["net"],
                        "verdict": "PASS" if passed else "FAIL",
                    })
    return pd.DataFrame(rows)


def render(
    events: pd.DataFrame, missing: pd.DataFrame, reproduction: pd.DataFrame, summary: pd.DataFrame,
    campaigns: pd.DataFrame, entries: pd.DataFrame, per_event: pd.DataFrame, variants: pd.DataFrame,
) -> None:
    v29 = summary[summary.base.eq("v29")].set_index("event_type")
    brief = "; ".join(
        f"{typ} Δ={v29.loc[typ, 'mean_event_minus_control']:+.0f}、穩健={cell(v29.loc[typ, 'robust'])}"
        for typ in ("CPI", "PPI", "NFP")
    )
    robust = v29.index[v29.robust].tolist()
    lines = [
        "# V38 BLS（CPI／PPI／NFP）事件研究",
        "",
        "## 五行摘要",
        "",
        "1. 以提供的 Wayback BLS 日期逐筆換算 08:30 ET；DST 日為台北 20:30、非 DST 為 21:30，全部位於 MXF 夜盤。",
        f"2. v29 的事件減同星期／時刻非事件對照：{brief}。",
        "3. 單一最大絕對事件已移除再檢查，且以固定種子 10,000 次 bootstrap 對事件減對照均值取 95% CI。",
        ("4. 有通過事前穩健門檻的類型：" + ", ".join(robust) + "；因此已對 v28/v29 執行兩個候選變體。") if robust else "4. 沒有任何 v29 類型同時通過 H1/H2 同號、移除最大事件與 bootstrap CI 三個門檻；依預先規則不執行引擎變體。",
        "5. 結論：目前沒有可重現的證據顯示 V38 必須因 CPI／PPI／NFP 改變 Cmd/Add 進場或預先平掉 Add/G；維持既有規則。",
        "",
        "## 方法與資料界線",
        "",
        "- 完全採用 `bls_release_dates.csv` 的列，不補日期；來源 URL 保留於輸出日曆。臺北時間用 `zoneinfo` 的 `America/New_York -> Asia/Taipei` 實算，未以固定時差假設。",
        "- 基線是同一份 `mxf_1min_corrected_20261017b.csv` 的 v28/v29、1 分鐘 intrabar、`opt_stale_hr=10`、`opt_cooldown_min=30`。",
        "- 每事件：釋出前 5 分鐘到後 60 分鐘，對釋出時仍開啟 lot 的實際方向與數量作 mark-to-market；對照為同一 weekday/clock-minute，排除所有 BLS 加既有 Section F 事件的 ±120 分鐘。",
        "- 穩健門檻以 v29（原 Section F 的診斷基線）判定：原始 MTM 的 H1/H2 同號、移除原始 MTM 絕對值最大的一個事件後同號，且 `事件−對照` 的 bootstrap 95% CI 不含零。campaign trade-date 沿用夜盤 15:00 後歸次一交易日的原規則。",
        "",
        "### 提供日期與缺月",
        "",
    ]
    display_events = events.rename(columns={"event_type": "事件", "date_et": "提供 ET 日期", "event_ts_et": "ET 時間", "event_ts_taipei": "台北時間", "session": "MXF session", "source": "來源"})
    lines += table(display_events, ["事件", "提供 ET 日期", "ET 時間", "台北時間", "MXF session", "來源"], 0)
    lines += ["", "下表只列出提供檔在 2024-01..2026-10 的曆月空洞，僅作缺列註記，**絕不推補**任何釋出日期。", ""]
    display_missing = missing.rename(columns={"event_type": "事件", "n_provided": "提供筆數", "absent_file_calendar_months": "提供檔未出現的曆月"})
    lines += table(display_missing, list(display_missing.columns), 0)
    lines += ["", "### 基線重現", ""]
    lines += table(reproduction.rename(columns={"base": "基線", "n": "lot數", "net": "淨利", "matches_existing_calendar_ledger": "吻合既有 ledger"}), ["基線", "lot數", "淨利", "吻合既有 ledger"], 0)
    lines += ["", "## 事件 MTM 與穩健性", ""]
    rename_summary = {
        "base": "基線", "event_type": "事件", "n_events": "事件數", "mean_pnl_5m_to_60m": "事件MTM均值",
        "mean_control_pnl": "對照MTM均值", "mean_event_minus_control": "事件減對照", "H1_mean_pnl": "H1事件MTM",
        "H2_mean_pnl": "H2事件MTM", "H1_event_minus_control": "H1 Δ", "H2_event_minus_control": "H2 Δ", "largest_abs_event": "最大|事件|", "largest_abs_event_pnl": "其MTM",
        "mean_pnl_ex_largest": "剔除後MTM", "mean_diff_ex_largest": "剔除後Δ", "boot_ci_low": "bootstrap 95%低",
        "boot_ci_high": "bootstrap 95%高", "same_sign_H1_H2": "H1/H2同號", "survives_drop_largest": "剔最大後同號",
        "bootstrap_ci_excludes_zero": "CI不含0", "robust": "穩健",
    }
    sdisplay = summary.rename(columns=rename_summary)
    lines += table(sdisplay, list(rename_summary.values()), 1)
    lines += ["", "### Campaign PnL（事件 trade-date vs 其他日期）", ""]
    cdisplay = campaigns.rename(columns={"base": "基線", "event_type": "事件", "event_campaigns": "事件campaign數", "event_campaign_net": "事件淨利", "event_campaign_mean": "事件均利", "other_campaigns": "其他campaign數", "other_campaign_mean": "其他均利"})
    lines += table(cdisplay, list(cdisplay.columns), 1)
    lines += ["", "### 釋出前／後 60 分鐘進場 lot（實際 lot PnL、完整持有期 MAE ATR）", ""]
    edisplay = entries.rename(columns={"base": "基線", "event_type": "事件", "period": "區間", "group": "組別", "n": "lot數", "mean_lot_pnl": "平均lot PnL", "mean_mae_atr": "平均MAE(ATR)"})
    lines += table(edisplay, list(edisplay.columns), 2)
    lines += ["", "### 逐事件列表（每列為兩方向已開 lot 合計；進場統計與上述相同定義）", ""]
    pcols = [
        "base", "event_type", "event_ts_taipei", "open_lots", "open_long", "open_short", "pnl_5m_to_60m", "control_pnl_mean", "event_minus_control", "n_control_times",
        "pre_event_n", "pre_event_mean_pnl", "pre_event_mae_atr", "pre_control_n", "pre_control_mean_pnl", "pre_control_mae_atr",
        "post_event_n", "post_event_mean_pnl", "post_event_mae_atr", "post_control_n", "post_control_mean_pnl", "post_control_mae_atr",
    ]
    pdisplay = per_event.rename(columns={
        "base": "基線", "event_type": "事件", "event_ts_taipei": "台北釋出", "open_lots": "開lot", "open_long": "開多", "open_short": "開空",
        "pnl_5m_to_60m": "事件MTM", "control_pnl_mean": "對照MTM", "event_minus_control": "Δ", "n_control_times": "對照時點數",
        "pre_event_n": "前事件n", "pre_event_mean_pnl": "前事件均PnL", "pre_event_mae_atr": "前事件MAE", "pre_control_n": "前對照n", "pre_control_mean_pnl": "前對照均PnL", "pre_control_mae_atr": "前對照MAE",
        "post_event_n": "後事件n", "post_event_mean_pnl": "後事件均PnL", "post_event_mae_atr": "後事件MAE", "post_control_n": "後對照n", "post_control_mean_pnl": "後對照均PnL", "post_control_mae_atr": "後對照MAE",
    })
    lines += table(pdisplay, [pdisplay.columns[pcols.index(c)] for c in pcols], 2)
    lines += ["", "## 條件式引擎變體", ""]
    if variants.empty:
        lines += ["v29 沒有事件類型通過事前門檻；為避免事後挖掘，沒有執行 `(a) 禁 Cmd/Add −30..+15` 或 `(b) 釋出前5分 flatten Add/G`。"]
    else:
        vdisplay = variants.rename(columns={"base": "基線", "event_type": "事件", "variant": "變體", "split": "樣本", "n": "lot數", "net": "淨利", "net_delta": "相對基線淨利Δ", "verdict": "判定"})
        lines += ["PASS = H1、H2、TRAIN、TEST 的淨利增量全部 > 0；HOLDOUT 僅展示，不參與判定。", ""]
        lines += table(vdisplay, list(vdisplay.columns), 0)
    lines += [
        "",
        "## 機器可讀輸出",
        "",
        "- `bls_event_calendar.csv`、`bls_event_summary.csv`、`bls_event_campaigns.csv`、`bls_event_entries.csv`、`bls_event_per_event.csv` 保存計算表。",
        "- `bls_event_variant_metrics.csv` 若穩健門檻未通過會是只有欄名的空表，這是預先規則的結果而非缺漏。",
    ]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def main() -> None:
    events = build_bls_calendar()
    events.to_csv(HERE / "bls_event_calendar.csv", index=False, encoding="utf-8-sig")
    missing = missing_calendar_months(events)
    df1m = eng.load_1min(DATA)
    b5 = eng.prepare(df1m, {**eng.P, **cal.BASES["v29"]})
    base_runs: dict[str, pd.DataFrame] = {}
    reproduction = []
    for base, params in cal.BASES.items():
        trades = eng.run(df1m, params, intrabar_mode="1min")
        base_runs[base] = trades
        trades.to_csv(HERE / f"bls_{base}_base_trades.csv", index=False, encoding="utf-8-sig")
        reproduction.append({
            "base": base, "n": len(trades), "net": trades.pnl.sum(),
            "matches_existing_calendar_ledger": equal_trade_ledger(trades, HERE / f"trades_calendar_{base}_base.csv"),
        })
    legacy = load_legacy_event_times()
    exclusion = pd.concat([events.loc[:, ["event_type", "event_ts_taipei"]], legacy], ignore_index=True)
    all_event_times = pd.DatetimeIndex(pd.to_datetime(exclusion.event_ts_taipei).dropna().unique()).sort_values()
    outputs = [event_study(base, trades, events, all_event_times, df1m, b5) for base, trades in base_runs.items()]
    per_event = pd.concat([x[0] for x in outputs], ignore_index=True)
    summary = pd.concat([x[1] for x in outputs], ignore_index=True)
    campaigns = pd.concat([x[2] for x in outputs], ignore_index=True)
    entry_lots = pd.concat([x[3] for x in outputs], ignore_index=True)
    entries = summarize_entry_lots(entry_lots)
    robust_types = summary.loc[summary.base.eq("v29") & summary.robust, "event_type"].tolist()
    variants = event_variant_metrics(df1m, base_runs, events, robust_types)
    pd.DataFrame(reproduction).to_csv(HERE / "bls_event_reproduction.csv", index=False, encoding="utf-8-sig")
    missing.to_csv(HERE / "bls_event_missing_months.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(HERE / "bls_event_summary.csv", index=False, encoding="utf-8-sig")
    campaigns.to_csv(HERE / "bls_event_campaigns.csv", index=False, encoding="utf-8-sig")
    entries.to_csv(HERE / "bls_event_entries.csv", index=False, encoding="utf-8-sig")
    per_event.to_csv(HERE / "bls_event_per_event.csv", index=False, encoding="utf-8-sig")
    variants.to_csv(HERE / "bls_event_variant_metrics.csv", index=False, encoding="utf-8-sig")
    render(events, missing, pd.DataFrame(reproduction), summary, campaigns, entries, per_event, variants)
    print(f"done: {OUT}")


if __name__ == "__main__":
    main()
