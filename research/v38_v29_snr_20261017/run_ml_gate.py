"""Execute the four pre-specified causal ML feature gates for V38/v28."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

import engine_ml_gate_wrapper as mlg


HERE = Path(__file__).resolve().parent
DATA = HERE / "mxf_1min_2020_20261026.csv"
PANEL = HERE / "ml_features_panel.csv"
SAVED_V28 = HERE / "br_trades_v28.csv"
START = pd.Timestamp("2020-03-02")
CALIBRATION_END = pd.Timestamp("2023-12-31 23:59:59.999999999")
YEARS = tuple(range(2020, 2027))
NET_COST = 2 * (40 - mlg.COMMISSION) + 2 * 4 * mlg.POINT_VALUE
LIVE_V28 = {
    **mlg.P,
    "opt_stale_hr": 10,
    "opt_cooldown_min": 30,
    "opt_short_pyramid_cap_mode": "hour4",
}
VARIANTS = ("G1", "G2", "G3", "G4")


def ledger(raw: pd.DataFrame, label: str) -> pd.DataFrame:
    out = raw.copy()
    out["entry_ts"] = pd.to_datetime(out["entry_ts"])
    out["exit_ts"] = pd.to_datetime(out["exit_ts"])
    out["net"] = out["pnl"].astype(float) - NET_COST
    out["case"] = label
    return out


def canonical(trades: pd.DataFrame) -> pd.DataFrame:
    columns = ["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl", "net", "case"]
    out = trades.loc[:, columns].copy()
    out["entry_ts"] = pd.to_datetime(out["entry_ts"])
    out["exit_ts"] = pd.to_datetime(out["exit_ts"])
    # The feature panel is deliberately sorted by entry/exit timing whereas
    # the engine ledger retains close order.  Equality is therefore checked
    # lot-for-lot, independent of an inconsequential row ordering.
    return out.sort_values(columns, kind="mergesort").reset_index(drop=True)


def assert_panel_identity(panel: pd.DataFrame, saved: pd.DataFrame) -> None:
    actual = canonical(panel)
    expected = canonical(saved)
    assert_frame_equal(actual, expected, check_dtype=False, check_exact=True)


def frozen_thresholds(panel: pd.DataFrame) -> tuple[dict[str, dict[str, float]], pd.DataFrame]:
    calibration = panel.loc[
        panel["entry_ts"].between(START, CALIBRATION_END, inclusive="both")
    ].copy()
    if calibration.empty:
        raise AssertionError("empty 2020-03 through 2023-12 calibration sample")

    specs = (
        ("G1", "Cmd", "er5_48", 0.20),
        ("G2", "Cmd", "session_cum_vol_rel20", 0.20),
        ("G3", "Cmd", "er5_48", 0.33),
        ("G3", "Cmd", "session_cum_vol_rel20", 0.33),
        ("G4", "Add_G", "er5_48", 0.20),
    )
    rows: list[dict[str, Any]] = []
    rules: dict[str, dict[str, float]] = {name: {} for name in VARIANTS}
    for variant, scope, feature, quantile in specs:
        eligible = calibration.loc[
            calibration["kind"].eq("Cmd") if scope == "Cmd" else calibration["kind"].isin(["Add", "G"])
        ].copy()
        values = pd.to_numeric(eligible[feature], errors="coerce").dropna()
        if values.empty:
            raise AssertionError(f"no usable values for {variant} {scope} {feature}")
        threshold = float(values.quantile(quantile))
        key = f"{feature}_threshold"
        rules[variant][key] = threshold
        rows.append({
            "variant": variant,
            "lot_type": scope,
            "feature": feature,
            "quantile": quantile,
            "calibration_start": START,
            "calibration_end": CALIBRATION_END,
            "eligible_lots": int(len(eligible)),
            "usable_lots": int(len(values)),
            "threshold": threshold,
        })
    return rules, pd.DataFrame(rows)


def run_case(args: tuple[str, dict[str, float]]) -> tuple[str, pd.DataFrame]:
    variant, thresholds = args
    df1m = mlg.load_1min(DATA)
    raw = mlg.run(
        df1m,
        p={**LIVE_V28, "opt_ml_gate": {"variant": variant, **thresholds}},
        intrabar_mode="1min",
    )
    return variant, ledger(raw, variant)


def trading_day(exits: pd.Series) -> pd.Series:
    exits = pd.to_datetime(exits)
    return exits.dt.normalize() + pd.to_timedelta((exits.dt.hour >= 15).astype(int), unit="D")


def daily_net(trades: pd.DataFrame) -> pd.Series:
    tr = trades.loc[trades["exit_ts"] >= START].copy()
    return tr.assign(day=trading_day(tr["exit_ts"])).groupby("day")["net"].sum().sort_index()


def daily_mdd(day_pnl: pd.Series) -> float:
    equity = day_pnl.cumsum()
    return float((equity - equity.cummax()).min()) if len(equity) else 0.0


def metrics(trades: pd.DataFrame, variant: str) -> tuple[dict[str, Any], pd.DataFrame]:
    tr = trades.loc[trades["exit_ts"] >= START].copy()
    day = daily_net(trades)
    annual = day.groupby(day.index.year).sum()
    total = float(day.sum())
    mdd = daily_mdd(day)
    row: dict[str, Any] = {
        "variant": variant,
        "net_total": total,
        "daily_mdd": mdd,
        "net_mdd": float(total / abs(mdd)) if mdd else np.nan,
        "lots": int(len(tr)),
        "net_2024_2026": float(sum(annual.get(year, 0.0) for year in (2024, 2025, 2026))),
    }
    for year in YEARS:
        row[f"net_{year}"] = float(annual.get(year, 0.0))
    daily = day.rename("net").reset_index().assign(variant=variant)
    return row, daily


def with_lot_key(trades: pd.DataFrame) -> pd.DataFrame:
    out = trades.loc[trades["exit_ts"] >= START, ["side", "kind", "entry_ts", "entry_px", "net"]].copy()
    columns = ["side", "kind", "entry_ts", "entry_px"]
    out["occurrence"] = out.groupby(columns).cumcount()
    return out


def precision(baseline: pd.DataFrame, candidate: pd.DataFrame,
              base_row: dict[str, Any], candidate_row: dict[str, Any]) -> dict[str, Any]:
    base = with_lot_key(baseline)
    other = with_lot_key(candidate)
    key = ["side", "kind", "entry_ts", "entry_px", "occurrence"]
    removed = base.merge(other[key], on=key, how="left", indicator=True)
    removed = removed.loc[removed["_merge"].eq("left_only")].copy()
    variant_only = other.merge(base[key], on=key, how="left", indicator=True)
    variant_only = variant_only.loc[variant_only["_merge"].eq("left_only")].copy()
    beating = [year for year in YEARS if candidate_row[f"net_{year}"] > base_row[f"net_{year}"]]
    return {
        "variant": candidate_row["variant"],
        "removed_lots": int(len(removed)),
        "removed_winning_lots": int((removed["net"] > 0).sum()),
        "removed_losing_lots": int((removed["net"] <= 0).sum()),
        "profit_removed_from_winners": float(removed.loc[removed["net"] > 0, "net"].sum()),
        "loss_removed_from_losers": float(-removed.loc[removed["net"] <= 0, "net"].sum()),
        "baseline_lot_net_removed": float(removed["net"].sum()),
        "variant_only_lots": int(len(variant_only)),
        "years_beating_v28": ",".join(map(str, beating)) if beating else "none",
        "years_beating_count": int(len(beating)),
        "total_delta_vs_v28": float(candidate_row["net_total"] - base_row["net_total"]),
        "mdd_worse_pct": (
            float(abs(candidate_row["daily_mdd"]) / abs(base_row["daily_mdd"]) - 1.0)
            if base_row["daily_mdd"] else np.nan
        ),
    }


def add_deltas(metrics_df: pd.DataFrame) -> pd.DataFrame:
    out = metrics_df.copy()
    base = out.loc[out["variant"].eq("v28")].iloc[0]
    for year in YEARS:
        out[f"delta_{year}_vs_v28"] = out[f"net_{year}"] - base[f"net_{year}"]
    out["delta_total_vs_v28"] = out["net_total"] - base["net_total"]
    out["delta_2024_2026_vs_v28"] = out["net_2024_2026"] - base["net_2024_2026"]
    return out


def verdicts(metrics_df: pd.DataFrame, precision_df: pd.DataFrame) -> pd.DataFrame:
    base = metrics_df.loc[metrics_df["variant"].eq("v28")].iloc[0]
    rows: list[dict[str, Any]] = []
    for variant in VARIANTS:
        metric = metrics_df.loc[metrics_df["variant"].eq(variant)].iloc[0]
        prec = precision_df.loc[precision_df["variant"].eq(variant)].iloc[0]
        total_ok = bool(metric["net_total"] > base["net_total"])
        years_ok = bool(prec["years_beating_count"] >= 5)
        mdd_ok = bool(prec["mdd_worse_pct"] <= 0.10)
        recent_ok = bool(metric["net_2024_2026"] >= base["net_2024_2026"])
        passed = total_ok and years_ok and mdd_ok and recent_ok
        rows.append({
            "variant": variant,
            "total_net_gt_v28": total_ok,
            "years_beating_count": int(prec["years_beating_count"]),
            "years_beating_at_least_5_of_7": years_ok,
            "mdd_worse_pct": float(prec["mdd_worse_pct"]),
            "mdd_not_worse_than_10pct": mdd_ok,
            "net_2024_2026_ge_v28": recent_ok,
            "verdict": "PASS" if passed else "FAIL",
        })
    return pd.DataFrame(rows)


def money(value: float) -> str:
    return "NA" if not np.isfinite(value) else f"{value:,.0f}"


def pct(value: float) -> str:
    return "NA" if not np.isfinite(value) else f"{value * 100:.1f}%"


def report(thresholds: pd.DataFrame, metrics_df: pd.DataFrame, precision_df: pd.DataFrame,
           verdict_df: pd.DataFrame, reproduction: pd.DataFrame) -> str:
    outcome = "；".join(
        f"{r.variant} {r.verdict}" for r in verdict_df.itertuples(index=False)
    )
    lines = [
        f"# 裁決：{outcome}",
        "",
        "# V38 v28：兩項穩定 ML 特徵的全路徑因果閘門",
        "",
        "固定判定條件為：總淨利高於 v28、至少 5/7 年高於 v28、日 PnL MDD 不比 v28 惡化超過 10%，且 2024--2026 小計不低於 v28。未同時符合即為 FAIL。",
        "",
        "## 方法與再現檢查",
        "",
        "- 使用 mxf_1min_2020_20261026.csv、1 分鐘 intrabar、每口淨利為 pnl 減 440；交易日以 15:00 之後歸入次一日，MDD 以交易日淨利累積計算。",
        "- 讀取既有 ml_features_panel.csv 的 v28 lots，僅以進場時間落在 2020-03-02 至 2023-12-31 的指定 lot 類型計算分位數，之後對全樣本凍結不再調整。",
        "- 包裝器直接匯入 run_ml_attrib.py 的 volume_features 與 er 定義；在引擎的已收盤 5 分鐘訊號列 B[i] 判斷，只有下一根開盤才可能成交。NaN 並非低於門檻，因此維持 v28 原決策。",
        f"- gate-off 與 br_trades_v28.csv 逐 lot 完全一致：{int(reproduction.iloc[0]['lots'])} lots，驗證結果 {reproduction.iloc[0]['gate_off_equals_br_trades_v28']}。",
        "",
        "## 凍結門檻",
        "",
        "| 變體 | lot 類型 | 特徵 | 分位數 | 可用 lots | 凍結門檻 |",
        "|---|---|---|---:|---:|---:|",
    ]
    for row in thresholds.itertuples(index=False):
        lines.append(
            f"| {row.variant} | {row.lot_type} | {row.feature} | {row.quantile:.0%} | {row.usable_lots:,} | {row.threshold:.8f} |"
        )
    lines += [
        "",
        "G1：Cmd 的 er5_48 < 20% 門檻；G2：Cmd 的 session_cum_vol_rel20 < 20% 門檻；G3：Cmd 同時低於兩個 33% 門檻；G4：Add/G 的 er5_48 < 20% 門檻，Cmd 不變。",
        "",
        "## 淨利、風險與年度差額",
        "",
        "| 組合 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | 合計 | 日 PnL MDD | 淨利/MDD | 口數 | 勝 v28 年數 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    order = metrics_df.set_index("variant").loc[["v28", *VARIANTS]].reset_index()
    precision_map = precision_df.set_index("variant")
    for row in order.itertuples(index=False):
        wins = "-" if row.variant == "v28" else f"{int(precision_map.loc[row.variant, 'years_beating_count'])}/7"
        annual = " | ".join(money(getattr(row, f"net_{year}")) for year in YEARS)
        lines.append(
            f"| {row.variant} | {annual} | {money(row.net_total)} | {money(row.daily_mdd)} | {row.net_mdd:.2f} | {row.lots:,} | {wins} |"
        )
    lines += [
        "",
        "| 組合 | Δ2020 | Δ2021 | Δ2022 | Δ2023 | Δ2024 | Δ2025 | Δ2026 | Δ合計 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in order.itertuples(index=False):
        if row.variant == "v28":
            continue
        delta = " | ".join(money(getattr(row, f"delta_{year}_vs_v28")) for year in YEARS)
        lines.append(f"| {row.variant} | {delta} | {money(row.delta_total_vs_v28)} |")
    lines += [
        "",
        "## 2024--2026 小計",
        "",
        "| 組合 | 2024--2026 淨利 | 相對 v28 | 是否不低於 v28 |",
        "|---|---:|---:|---|",
    ]
    verdict_map = verdict_df.set_index("variant")
    for row in order.itertuples(index=False):
        recent = "-" if row.variant == "v28" else ("是" if bool(verdict_map.loc[row.variant, "net_2024_2026_ge_v28"]) else "否")
        lines.append(
            f"| {row.variant} | {money(row.net_2024_2026)} | {money(row.delta_2024_2026_vs_v28)} | {recent} |"
        )
    lines += [
        "",
        "## 移除 lot 的精確度檢查",
        "",
        "移除 lots 是以 side、kind、entry_ts、entry_px 與同鍵序號對應 v28 帳本；獲利移除額越小、虧損移除額越大通常較有利。變體路徑才出現的 lots 另列，避免把連鎖路徑變化誤作直接刪除。",
        "",
        "| 變體 | 移除 lots | 移除獲利 lot 淨利 | 移除虧損 lot 損失 | 移除 lot 淨額 | 變體特有 lots | MDD 惡化 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in precision_df.itertuples(index=False):
        lines.append(
            f"| {row.variant} | {row.removed_lots:,} | {money(row.profit_removed_from_winners)} | {money(row.loss_removed_from_losers)} | {money(row.baseline_lot_net_removed)} | {row.variant_only_lots:,} | {pct(row.mdd_worse_pct)} |"
        )
    lines += [
        "",
        "## 固定裁決逐項檢查",
        "",
        "| 變體 | 總淨利 > v28 | 至少 5/7 年勝 v28 | MDD 惡化 <= 10% | 2024--2026 >= v28 | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for row in verdict_df.itertuples(index=False):
        lines.append(
            f"| {row.variant} | {'是' if row.total_net_gt_v28 else '否'} | {'是' if row.years_beating_at_least_5_of_7 else '否'} ({row.years_beating_count}/7) | {'是' if row.mdd_not_worse_than_10pct else '否'} ({pct(row.mdd_worse_pct)}) | {'是' if row.net_2024_2026_ge_v28 else '否'} | {row.verdict} |"
        )
    lines += [
        "",
        "精確數值與可重算帳本見 mlg_thresholds.csv、mlg_metrics.csv、mlg_precision.csv、mlg_verdicts.csv、mlg_daily_pnl.csv、mlg_reproduction.csv 及 mlg_trades_*.csv。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    for path in (DATA, PANEL, SAVED_V28):
        if not path.exists():
            raise FileNotFoundError(f"required input missing: {path}")

    panel = pd.read_csv(PANEL, parse_dates=["entry_ts", "exit_ts"])
    saved = pd.read_csv(SAVED_V28, parse_dates=["entry_ts", "exit_ts"])
    assert_panel_identity(panel, saved)
    rules, thresholds = frozen_thresholds(panel)

    df1m = mlg.load_1min(DATA)
    gate_off = ledger(mlg.run(df1m, p=LIVE_V28, intrabar_mode="1min"), "v28")
    assert_frame_equal(canonical(gate_off), canonical(saved), check_dtype=False, check_exact=True)
    reproduction = pd.DataFrame([{
        "gate_off_equals_br_trades_v28": True,
        "lots": int(len(gate_off)),
        "net_cost_per_lot": NET_COST,
        "data": DATA.name,
    }])
    del df1m

    # Keep this study in one process so the engine runs and all audit writes
    # share one attached, reproducible execution context.
    cases = dict(run_case((variant, rules[variant])) for variant in VARIANTS)

    metric_rows: list[dict[str, Any]] = []
    daily_rows: list[pd.DataFrame] = []
    base_row, base_daily = metrics(gate_off, "v28")
    metric_rows.append(base_row)
    daily_rows.append(base_daily)
    candidate_rows: dict[str, dict[str, Any]] = {}
    for variant in VARIANTS:
        row, daily = metrics(cases[variant], variant)
        metric_rows.append(row)
        daily_rows.append(daily)
        candidate_rows[variant] = row
    metrics_df = add_deltas(pd.DataFrame(metric_rows))
    daily_df = pd.concat(daily_rows, ignore_index=True)

    base_final = metrics_df.loc[metrics_df["variant"].eq("v28")].iloc[0].to_dict()
    precision_df = pd.DataFrame([
        precision(
            gate_off,
            cases[variant],
            base_final,
            metrics_df.loc[metrics_df["variant"].eq(variant)].iloc[0].to_dict(),
        )
        for variant in VARIANTS
    ])
    verdict_df = verdicts(metrics_df, precision_df)

    thresholds.to_csv(HERE / "mlg_thresholds.csv", index=False, encoding="utf-8")
    reproduction.to_csv(HERE / "mlg_reproduction.csv", index=False, encoding="utf-8")
    metrics_df.to_csv(HERE / "mlg_metrics.csv", index=False, encoding="utf-8")
    daily_df.to_csv(HERE / "mlg_daily_pnl.csv", index=False, encoding="utf-8")
    precision_df.to_csv(HERE / "mlg_precision.csv", index=False, encoding="utf-8")
    verdict_df.to_csv(HERE / "mlg_verdicts.csv", index=False, encoding="utf-8")
    gate_off.to_csv(HERE / "mlg_trades_v28.csv", index=False, encoding="utf-8")
    for variant, trades in cases.items():
        trades.to_csv(HERE / f"mlg_trades_{variant}.csv", index=False, encoding="utf-8")
    (HERE / "results_ml_gate.md").write_text(
        report(thresholds, metrics_df, precision_df, verdict_df, reproduction),
        encoding="utf-8",
    )
    print(verdict_df.to_string(index=False))


if __name__ == "__main__":
    main()
