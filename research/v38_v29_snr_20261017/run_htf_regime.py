"""Run the predeclared V38 daily higher-timeframe regime study."""
from __future__ import annotations

from multiprocessing import Pool
from pathlib import Path
from typing import Any

import sys

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

import engine_htf_regime_wrapper as htf


HERE = Path(__file__).resolve().parent
ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
import engine_v26_bbw as plain  # noqa: E402


DATA = HERE / "mxf_1min_corrected_20261022.csv"
SAVED_LEDGER = HERE / "recent_20261022_trades.csv"
LIVE_V28 = {
    "opt_stale_hr": 10,
    "opt_cooldown_min": 30,
    "opt_short_pyramid_cap_mode": "hour4",
}
LIVE_V27 = {"opt_stale_hr": 10, "opt_cooldown_min": 30}
VARIANTS = ("R1", "R2", "R3", "R4", "R5", "R6")
DEFINITIONS = ("D1", "D2")
NET_COST = 2 * (40 - plain.COMMISSION) + 2 * 4 * plain.POINT_VALUE
START = pd.Timestamp("2024-01-01")
PERIOD_END = pd.Timestamp("2026-10-22")


def ledger(raw: pd.DataFrame, label: str) -> pd.DataFrame:
    tr = raw.copy()
    tr["entry_ts"] = pd.to_datetime(tr["entry_ts"])
    tr["exit_ts"] = pd.to_datetime(tr["exit_ts"])
    tr["net"] = tr["pnl"].astype(float) - NET_COST
    tr["case"] = label
    return tr


def run_htf_case(definition: str, variant: str) -> tuple[str, str, pd.DataFrame]:
    """Pool worker: load locally, then execute one fully specified variant."""
    df1m = htf.load_1min(DATA)
    raw = htf.run(
        df1m,
        p={**LIVE_V28, "opt_htf_regime": {"definition": definition, "variant": variant}},
        intrabar_mode="1min",
    )
    return definition, variant, ledger(raw, f"{definition}_{variant}")


def trading_day(exits: pd.Series) -> pd.Series:
    exits = pd.to_datetime(exits)
    return exits.dt.normalize() + pd.to_timedelta((exits.dt.hour >= 15).astype(int), unit="D")


def daily_net(trades: pd.DataFrame) -> pd.Series:
    tr = trades.loc[trades["exit_ts"] >= START].copy()
    d = trading_day(tr["exit_ts"])
    return tr.assign(day=d).groupby("day")["net"].sum().sort_index()


def daily_mdd(day_pnl: pd.Series) -> float:
    # This intentionally matches run_recent_20261022.py's daily-PnL MDD.
    curve = day_pnl.cumsum()
    return float((curve - curve.cummax()).min()) if len(curve) else 0.0


def metrics(trades: pd.DataFrame, definition: str, variant: str) -> tuple[dict[str, Any], pd.DataFrame]:
    tr = trades.loc[trades["exit_ts"] >= START].copy()
    d = daily_net(trades)
    by_year = d.groupby(d.index.year).sum()
    # These recency windows are fixed to the supplied data endpoint, rather
    # than a variant's own last exit (which can legitimately be earlier).
    last12 = d[d.index > PERIOD_END - pd.DateOffset(months=12)]
    last3 = d[d.index > PERIOD_END - pd.DateOffset(months=3)]
    win = tr.loc[tr.net > 0, "net"]
    loss = tr.loc[tr.net <= 0, "net"]
    mdd = daily_mdd(d)
    row = {
        "definition": definition,
        "variant": variant,
        "net_2024": float(by_year.get(2024, 0.0)),
        "net_2025": float(by_year.get(2025, 0.0)),
        "net_2026": float(by_year.get(2026, 0.0)),
        "net_total": float(d.sum()),
        "net_last12m": float(last12.sum()),
        "net_last3m": float(last3.sum()),
        "daily_mdd": mdd,
        "net_mdd": float(d.sum() / abs(mdd)) if mdd else np.nan,
        "lots": int(len(tr)),
        "win_rate": float((tr.net > 0).mean()) if len(tr) else np.nan,
        "avg_win": float(win.mean()) if len(win) else np.nan,
        "avg_loss": float(loss.mean()) if len(loss) else np.nan,
        "period_end": PERIOD_END.date().isoformat(),
    }
    daily = d.rename("net").reset_index().assign(definition=definition, variant=variant)
    return row, daily


def with_lot_key(trades: pd.DataFrame) -> pd.DataFrame:
    """Stable occurrence key for the precision check, robust to rare ties."""
    out = trades.loc[trades.exit_ts >= START, ["side", "kind", "entry_ts", "entry_px", "net"]].copy()
    key_cols = ["side", "kind", "entry_ts", "entry_px"]
    out["occurrence"] = out.groupby(key_cols).cumcount()
    return out


def precision(baseline: pd.DataFrame, variant: pd.DataFrame, definition: str, name: str,
              base_metrics: dict[str, Any], var_metrics: dict[str, Any]) -> dict[str, Any]:
    b = with_lot_key(baseline)
    v = with_lot_key(variant)
    key = ["side", "kind", "entry_ts", "entry_px", "occurrence"]
    removed = b.merge(v[key], on=key, how="left", indicator=True)
    removed = removed.loc[removed["_merge"] == "left_only"]
    added = v.merge(b[key], on=key, how="left", indicator=True)
    added = added.loc[added["_merge"] == "left_only"]
    removed_win = float(removed.loc[removed.net > 0, "net"].sum())
    removed_loss = float(-removed.loc[removed.net <= 0, "net"].sum())
    years = [str(year) for year in (2024, 2025, 2026)
             if var_metrics[f"net_{year}"] > base_metrics[f"net_{year}"]]
    return {
        "definition": definition,
        "variant": name,
        "removed_lots": int(len(removed)),
        "removed_winning_lots": int((removed.net > 0).sum()),
        "removed_losing_lots": int((removed.net <= 0).sum()),
        "profit_removed_from_winners": removed_win,
        "loss_removed_from_losers": removed_loss,
        "baseline_lot_net_removed": float(removed.net.sum()),
        "variant_only_lots": int(len(added)),
        "beats_v28_years": ",".join(years) if years else "none",
        "beats_all_three_years": len(years) == 3,
        "mdd_worse_pct": (
            abs(var_metrics["daily_mdd"]) / abs(base_metrics["daily_mdd"]) - 1.0
            if base_metrics["daily_mdd"] else np.nan
        ),
        "mdd_within_10pct": (
            abs(var_metrics["daily_mdd"]) <= 1.10 * abs(base_metrics["daily_mdd"])
            if base_metrics["daily_mdd"] else False
        ),
    }


def regime_summary(daily: pd.DataFrame) -> pd.DataFrame:
    recent = daily.loc[daily.date >= START].copy()
    rows = []
    for definition in DEFINITIONS:
        counts = recent[definition].value_counts(normalize=True)
        current = daily.loc[daily.date == pd.Timestamp("2026-10-22"), definition]
        if len(current) != 1:
            raise AssertionError("2026-10-22 daily regime is missing or duplicated")
        rows.append({
            "definition": definition,
            "start": "2024-01-01",
            "end": "2026-10-22",
            "days": int(len(recent)),
            "up_pct": float(counts.get("UP", 0.0) * 100),
            "down_pct": float(counts.get("DOWN", 0.0) * 100),
            "range_pct": float(counts.get("RANGE", 0.0) * 100),
            "current_date": "2026-10-22",
            "current_regime": current.iloc[0],
        })
    return pd.DataFrame(rows)


def assert_baseline(df1m: pd.DataFrame) -> pd.DataFrame:
    """Require wrapper-off and saved v28 ledgers to equal plain-engine v28."""
    raw_plain = plain.run(df1m, p=LIVE_V28, intrabar_mode="1min")
    raw_off = htf.run(df1m, p=LIVE_V28, intrabar_mode="1min")
    cols = list(raw_plain.columns)
    assert_frame_equal(raw_plain.reset_index(drop=True), raw_off[cols].reset_index(drop=True), check_exact=True)

    saved = pd.read_csv(SAVED_LEDGER)
    saved = saved.loc[saved.v == "v28", cols].copy()
    for c in ("entry_ts", "exit_ts"):
        saved[c] = pd.to_datetime(saved[c])
        raw_plain[c] = pd.to_datetime(raw_plain[c])
    assert_frame_equal(raw_plain.reset_index(drop=True), saved.reset_index(drop=True), check_exact=True)
    return ledger(raw_plain, "v28")


def fmt_wan(value: float) -> str:
    return "—" if not np.isfinite(value) else f"{value / 10000:,.1f}"


def fmt_ratio(value: float) -> str:
    return "—" if not np.isfinite(value) else f"{value:.2f}"


def fmt_pct(value: float) -> str:
    return "—" if not np.isfinite(value) else f"{value * 100:.1f}%"


def metrics_table(rows: pd.DataFrame) -> list[str]:
    lines = [
        "| 版本 | 2024 淨利(萬) | 2025 淨利(萬) | 2026 淨利(萬) | 合計(萬) | 近12月(萬) | 近3月(萬) | 日PnL MDD(萬) | 淨利/MDD | 口數 | 勝率 | 平均獲利(元) | 平均虧損(元) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, r in rows.iterrows():
        lines.append(
            f"| {r.variant} | {fmt_wan(r.net_2024)} | {fmt_wan(r.net_2025)} | {fmt_wan(r.net_2026)} | "
            f"{fmt_wan(r.net_total)} | {fmt_wan(r.net_last12m)} | {fmt_wan(r.net_last3m)} | "
            f"{fmt_wan(r.daily_mdd)} | {fmt_ratio(r.net_mdd)} | {int(r.lots):,} | "
            f"{fmt_pct(r.win_rate)} | {r.avg_win:,.0f} | {r.avg_loss:,.0f} |"
        )
    return lines


def verdicts(metrics_df: pd.DataFrame, precision_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    # Borderline is fixed before reviewing the results: all annual nets must
    # win under both definitions, but the MDD guard fails in at least one.
    for variant in VARIANTS:
        p = precision_df.loc[precision_df.variant == variant].set_index("definition")
        all_years_both = bool(p.loc[list(DEFINITIONS), "beats_all_three_years"].all())
        mdd_ok_both = bool(p.loc[list(DEFINITIONS), "mdd_within_10pct"].all())
        if all_years_both and mdd_ok_both:
            verdict = "PASS"
        elif all_years_both:
            verdict = "BORDERLINE"
        else:
            verdict = "FAIL"
        rows.append({
            "variant": variant,
            "D1_beats_years": p.loc["D1", "beats_v28_years"],
            "D1_mdd_worse_pct": p.loc["D1", "mdd_worse_pct"],
            "D1_mdd_within_10pct": p.loc["D1", "mdd_within_10pct"],
            "D2_beats_years": p.loc["D2", "beats_v28_years"],
            "D2_mdd_worse_pct": p.loc["D2", "mdd_worse_pct"],
            "D2_mdd_within_10pct": p.loc["D2", "mdd_within_10pct"],
            "verdict": verdict,
        })
    return pd.DataFrame(rows)


def report(metrics_df: pd.DataFrame, precision_df: pd.DataFrame, regimes: pd.DataFrame,
           verdict_df: pd.DataFrame) -> str:
    lines = ["# V38 v28：日線高週期市場狀態測試", ""]
    passed = verdict_df.loc[verdict_df.verdict == "PASS", "variant"].tolist()
    borderline = verdict_df.loc[verdict_df.verdict == "BORDERLINE", "variant"].tolist()
    fail = verdict_df.loc[verdict_df.verdict == "FAIL", "variant"].tolist()
    lines += [
        "## 摘要",
        "",
        "本測試以 2026-10-22 13:30 為資料終點，使用 v28 實盤設定、1 分鐘盤中路徑與每口完整往返成本 440 元。高週期狀態在每根 5 分鐘訊號 bar 收盤時，以 `(t − 13:45).normalize()` 對應最後完成的 TX 日盤；因此日盤 13:45 收盤後才會使用當日資料，沒有向前偷看。",
        "",
        "Wrapper 關閉時，重新執行的 v28 逐筆交易帳與原始引擎相同，也與 `recent_20261022_trades.csv` 的 v28 帳逐列相同（4,248 口）；這是所有比較的基準。",
        "",
        f"嚴格門檻結果：PASS＝{', '.join(passed) if passed else '無'}；BORDERLINE＝{', '.join(borderline) if borderline else '無'}；FAIL＝{', '.join(fail) if fail else '無'}。PASS 必須在 D1、D2 均同時勝過 v28 的 2024、2025、2026 三年，且各自日 PnL MDD 的惡化不超過 10%。BORDERLINE 僅保留「兩個定義三年皆勝、但 MDD 門檻未過」的情形；其餘均為 FAIL。",
        "",
        "R1/R2/R4/R6 在訊號決策 bar 套用狀態門檻；R3 只在 RANGE 將 long `l_pyramid_dist`、short `s_pyramid_dist` 乘 1.5；R5 每根決策 bar 依當時狀態調整 Cmd 的 `l_trailBase` / `s_trailMult`（順勢 ×1.2、RANGE ×0.8）。部位不會因狀態切換而強制平倉。",
        "",
        "## 日線狀態覆蓋率（2024 年起）",
        "",
        "| 定義 | 日數 | UP | DOWN | RANGE | 2026-10-22 狀態 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for _, r in regimes.iterrows():
        lines.append(
            f"| {r.definition} | {int(r.days):,} | {r.up_pct:.2f}% | {r.down_pct:.2f}% | {r.range_pct:.2f}% | {r.current_regime} |"
        )

    lines += [
        "",
        "D1：收盤相對 MA60 且 MA60 相對十日前同向才是 UP/DOWN，否則 RANGE。D2：使用 adjusted high/low/close 的 Wilder ADX(14)；ADX<20 為 RANGE，否則依收盤相對 MA60 判定 UP/DOWN。",
        "",
        "## 完整績效表",
        "",
        "年度、總計、近 12 月與近 3 月均依出場交易日歸屬；15:00 之後的夜盤出場歸到下一交易日。近 12 / 3 月採與既有 `run_recent_20261022.py` 相同的嚴格大於日期窗。MDD 是 2024 年起、上述交易日淨損益序列的最大回落；金額未年化。",
        "",
    ]
    order = ["v28", "v27", *VARIANTS]
    for definition in DEFINITIONS:
        lines += [f"### {definition}", ""]
        sub = metrics_df.loc[metrics_df.definition == definition].copy()
        sub["_order"] = pd.Categorical(sub.variant, categories=order, ordered=True)
        sub = sub.sort_values("_order")
        lines.extend(metrics_table(sub))
        lines.append("")

    lines += [
        "## 精確度檢查：相對 v28 被移除的基準口數",
        "",
        "「賺少／虧少」以 v28 中、變體不再具有同一 `(side, kind, entry_ts, entry_px, occurrence)` 的交易口為準；先按 v28 該口淨利正負分類，再分別加總。因此它衡量的是被規則阻擋或因路徑改變而消失的基準口，不把仍存在但出場價不同的口誤記為「移除」。`變體獨有口數`揭露後續交易路徑新增的口數。",
        "",
    ]
    for definition in DEFINITIONS:
        lines += [f"### {definition}", "", "| 變體 | 移除口數 | 賺少（移除獲利口，萬） | 虧少（移除虧損口，萬） | 移除基準淨額(萬) | 變體獨有口數 | 勝過 v28 年度 | MDD 惡化 |", "|---|---:|---:|---:|---:|---:|---|---:|"]
        sub = precision_df.loc[precision_df.definition == definition]
        for _, r in sub.iterrows():
            lines.append(
                f"| {r.variant} | {int(r.removed_lots):,} | {fmt_wan(r.profit_removed_from_winners)} | "
                f"{fmt_wan(r.loss_removed_from_losers)} | {fmt_wan(r.baseline_lot_net_removed)} | "
                f"{int(r.variant_only_lots):,} | {r.beats_v28_years} | {fmt_pct(r.mdd_worse_pct)} |"
            )
        lines.append("")

    lines += [
        "## 固定門檻判定",
        "",
        "| 變體 | D1 勝過 v28 的年度 | D1 MDD 惡化 | D1 MDD ≤10% | D2 勝過 v28 的年度 | D2 MDD 惡化 | D2 MDD ≤10% | 判定 |",
        "|---|---|---:|---|---|---:|---|---|",
    ]
    for _, r in verdict_df.iterrows():
        lines.append(
            f"| {r.variant} | {r.D1_beats_years} | {fmt_pct(r.D1_mdd_worse_pct)} | {'是' if r.D1_mdd_within_10pct else '否'} | "
            f"{r.D2_beats_years} | {fmt_pct(r.D2_mdd_worse_pct)} | {'是' if r.D2_mdd_within_10pct else '否'} | {r.verdict} |"
        )
    lines += [
        "",
        "原始可稽核資料已輸出為 `htf_regime_daily.csv`、`htf_metrics.csv`、`htf_precision.csv`、`htf_verdicts.csv`、`htf_daily_pnl.csv` 與各版本 `htf_trades_*.csv`。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    if not DATA.exists() or not SAVED_LEDGER.exists():
        raise FileNotFoundError("Required 2026-10-22 input data or saved baseline ledger is missing")

    # Execute and assert the inert wrapper before any experimental run.
    df1m = htf.load_1min(DATA)
    v28 = assert_baseline(df1m)
    v27 = ledger(plain.run(df1m, p=LIVE_V27, intrabar_mode="1min"), "v27")

    cases: dict[tuple[str, str], pd.DataFrame] = {}
    jobs = [(definition, variant) for definition in DEFINITIONS for variant in VARIANTS]
    with Pool(processes=3) as pool:
        for definition, variant, tr in pool.starmap(run_htf_case, jobs):
            cases[(definition, variant)] = tr

    all_metrics: list[dict[str, Any]] = []
    all_daily: list[pd.DataFrame] = []
    baseline_metrics: dict[str, dict[str, Any]] = {}
    for definition in DEFINITIONS:
        for name, tr in (("v28", v28), ("v27", v27)):
            row, day = metrics(tr, definition, name)
            all_metrics.append(row)
            all_daily.append(day)
            if name == "v28":
                baseline_metrics[definition] = row
        for variant in VARIANTS:
            row, day = metrics(cases[(definition, variant)], definition, variant)
            all_metrics.append(row)
            all_daily.append(day)
    metrics_df = pd.DataFrame(all_metrics)
    daily_df = pd.concat(all_daily, ignore_index=True)

    precision_rows = []
    for definition in DEFINITIONS:
        base_row = baseline_metrics[definition]
        for variant in VARIANTS:
            var_row = metrics_df.loc[
                (metrics_df.definition == definition) & (metrics_df.variant == variant)
            ].iloc[0].to_dict()
            precision_rows.append(precision(v28, cases[(definition, variant)], definition, variant, base_row, var_row))
    precision_df = pd.DataFrame(precision_rows)
    verdict_df = verdicts(metrics_df, precision_df)

    regimes_daily = htf.daily_regime_table()
    regimes = regime_summary(regimes_daily)

    # All numerical artefacts remain machine-readable (full dollars, not the
    # rounded ten-thousand-dollar display used in the Markdown tables).
    regimes_daily.to_csv(HERE / "htf_regime_daily.csv", index=False, encoding="utf-8-sig")
    regimes.to_csv(HERE / "htf_regime_summary.csv", index=False, encoding="utf-8-sig")
    metrics_df.to_csv(HERE / "htf_metrics.csv", index=False, encoding="utf-8-sig")
    precision_df.to_csv(HERE / "htf_precision.csv", index=False, encoding="utf-8-sig")
    verdict_df.to_csv(HERE / "htf_verdicts.csv", index=False, encoding="utf-8-sig")
    daily_df.to_csv(HERE / "htf_daily_pnl.csv", index=False, encoding="utf-8-sig")
    v28.to_csv(HERE / "htf_trades_v28.csv", index=False, encoding="utf-8-sig")
    v27.to_csv(HERE / "htf_trades_v27.csv", index=False, encoding="utf-8-sig")
    for (definition, variant), tr in cases.items():
        tr.to_csv(HERE / f"htf_trades_{definition}_{variant}.csv", index=False, encoding="utf-8-sig")

    (HERE / "results_htf_regime.md").write_text(
        report(metrics_df, precision_df, regimes, verdict_df), encoding="utf-8"
    )
    print("HTF regime study complete")
    print(f"v28 lots: {len(v28)} | variants: {len(cases)} | end: {metrics_df.period_end.iloc[0]}")
    print(verdict_df[["variant", "verdict"]].to_string(index=False))


if __name__ == "__main__":
    main()
