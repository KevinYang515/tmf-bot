"""Frozen V38 chop-gate evaluation on data through 2026-10-29.

The vendor engine remains read-only.  H1--H4 are supplied only as the
``opt_ml_gate`` hook implemented by engine_ml_gate_wrapper.py.
"""
from __future__ import annotations

import gc
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

import engine_ml_gate_wrapper as mlg


HERE = Path(__file__).resolve().parent
DATA = HERE / "mxf_1min_2020_20261029.csv"
PANEL = HERE / "ml_features_panel.csv"
CMP_TRADES = HERE / "cmp_20261029_trades.csv"
START = pd.Timestamp("2020-03-02")
CALIBRATION_END = pd.Timestamp("2023-12-31 23:59:59.999999999")
END = pd.Timestamp("2026-10-29")
YEARS = tuple(range(2020, 2027))
G2_THRESHOLD = 0.72777104
ER_P20_EXPECTED = 0.05345144
NET_COST = 2 * (40 - mlg.COMMISSION) + 2 * 4 * mlg.POINT_VALUE

V28 = {
    **mlg.P,
    "opt_stale_hr": 10,
    "opt_cooldown_min": 30,
    "opt_short_pyramid_cap_mode": "hour4",
}
V29 = {
    **V28,
    "l_trailBase": 3.5,
    "l_trailBaseDay": 3.5,
    "l_trailBaseNight": 3.5,
}


def ledger(raw: pd.DataFrame, case: str) -> pd.DataFrame:
    out = raw.copy()
    out["entry_ts"] = pd.to_datetime(out["entry_ts"])
    out["exit_ts"] = pd.to_datetime(out["exit_ts"])
    out["net"] = out["pnl"].astype(float) - NET_COST
    out["case"] = case
    return out


def canonical(trades: pd.DataFrame) -> pd.DataFrame:
    cols = ["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl", "net"]
    out = trades.loc[:, cols].copy()
    out["entry_ts"] = pd.to_datetime(out["entry_ts"])
    out["exit_ts"] = pd.to_datetime(out["exit_ts"])
    return out.sort_values(cols, kind="mergesort").reset_index(drop=True)


def run_engine(case: str, parameters: dict[str, Any]) -> pd.DataFrame:
    df1m = mlg.load_1min(DATA)
    try:
        raw = mlg.run(df1m, p=parameters, intrabar_mode="1min")
    finally:
        del df1m
        gc.collect()
    return ledger(raw, case)


def trading_day(ts: pd.Series) -> pd.Series:
    ts = pd.to_datetime(ts)
    return ts.dt.normalize() + pd.to_timedelta((ts.dt.hour >= 15).astype(int), unit="D")


def daily_net(trades: pd.DataFrame) -> pd.Series:
    active = trades.loc[trades["exit_ts"] >= START].copy()
    return active.assign(day=trading_day(active["exit_ts"])).groupby("day")["net"].sum().sort_index()


def daily_mdd(day_pnl: pd.Series) -> float:
    if day_pnl.empty:
        return 0.0
    equity = day_pnl.cumsum()
    return float((equity - equity.cummax()).min())


def net_and_mdd(day_pnl: pd.Series) -> tuple[float, float]:
    return float(day_pnl.sum()), daily_mdd(day_pnl)


def frozen_thresholds(panel: pd.DataFrame) -> tuple[dict[str, float], pd.DataFrame]:
    calibration = panel.loc[panel["entry_ts"].between(START, CALIBRATION_END, inclusive="both")].copy()
    rows: list[dict[str, Any]] = []
    values: dict[str, float] = {}

    def cutoff(scope: str, kind_mask: pd.Series, feature: str, quantile: float, key: str) -> None:
        sample = calibration.loc[kind_mask, feature]
        usable = pd.to_numeric(sample, errors="coerce").dropna()
        if usable.empty:
            raise AssertionError(f"empty frozen sample: {key}")
        threshold = float(usable.quantile(quantile))
        values[key] = threshold
        rows.append({
            "threshold_key": key,
            "scope": scope,
            "feature": feature,
            "quantile": quantile,
            "calibration_start": START,
            "calibration_end": CALIBRATION_END,
            "eligible_lots": int(len(sample)),
            "usable_lots": int(len(usable)),
            "threshold": threshold,
        })

    cmd = calibration["kind"].eq("Cmd")
    addg = calibration["kind"].isin(["Add", "G"])
    cutoff("Cmd", cmd, "session_cum_vol_rel20", 0.20, "G2_cmd_vol_p20")
    cutoff("Cmd", cmd, "atr5_pct", 0.20, "H1_cmd_atr5_pct_p20")
    cutoff("Cmd", cmd, "er5_48", 0.20, "H2_cmd_er5_48_p20")
    for feature, key in (
        ("session_cum_vol_rel20", "H3_cmd_vol_p33"),
        ("er5_48", "H3_cmd_er5_48_p33"),
        ("atr5_pct", "H3_cmd_atr5_pct_p33"),
    ):
        cutoff("Cmd", cmd, feature, 0.33, key)
    for feature, key in (
        ("session_cum_vol_rel20", "H4_addg_vol_p33"),
        ("er5_48", "H4_addg_er5_48_p33"),
        ("atr5_pct", "H4_addg_atr5_pct_p33"),
    ):
        cutoff("Add/G", addg, feature, 0.33, key)

    if not np.isclose(values["G2_cmd_vol_p20"], G2_THRESHOLD, rtol=0, atol=5e-9):
        raise AssertionError("G2 cutoff drifted from the frozen pre-declared value")
    if not np.isclose(values["H2_cmd_er5_48_p20"], ER_P20_EXPECTED, rtol=0, atol=5e-9):
        raise AssertionError("H2 er5_48 cutoff drifted from the pre-declared value")
    return values, pd.DataFrame(rows)


def gate_parameters(variant: str, thresholds: dict[str, float]) -> dict[str, float | str]:
    if variant == "G2":
        return {"variant": "G2", "session_cum_vol_rel20_threshold": G2_THRESHOLD}
    if variant == "H1":
        return {
            "variant": "H1",
            "session_cum_vol_rel20_threshold": G2_THRESHOLD,
            "atr5_pct_threshold": thresholds["H1_cmd_atr5_pct_p20"],
        }
    if variant == "H2":
        return {
            "variant": "H2",
            "session_cum_vol_rel20_threshold": G2_THRESHOLD,
            "er5_48_threshold": thresholds["H2_cmd_er5_48_p20"],
        }
    if variant == "H3":
        return {
            "variant": "H3",
            "session_cum_vol_rel20_threshold": thresholds["H3_cmd_vol_p33"],
            "er5_48_threshold": thresholds["H3_cmd_er5_48_p33"],
            "atr5_pct_threshold": thresholds["H3_cmd_atr5_pct_p33"],
        }
    if variant == "H4":
        return {
            "variant": "H4",
            "session_cum_vol_rel20_threshold": G2_THRESHOLD,
            "chop_session_cum_vol_rel20_threshold": thresholds["H4_addg_vol_p33"],
            "er5_48_threshold": thresholds["H4_addg_er5_48_p33"],
            "atr5_pct_threshold": thresholds["H4_addg_atr5_pct_p33"],
        }
    raise ValueError(f"unknown case variant: {variant}")


def metric_row(trades: pd.DataFrame, case: str) -> tuple[dict[str, Any], pd.DataFrame]:
    day = daily_net(trades)
    annual = day.groupby(day.index.year).sum()
    total, mdd = net_and_mdd(day)
    last12 = day.loc[day.index > END - pd.DateOffset(months=12)]
    last3 = day.loc[day.index > END - pd.DateOffset(months=3)]
    last12_net, last12_mdd = net_and_mdd(last12)
    last3_net, last3_mdd = net_and_mdd(last3)
    row: dict[str, Any] = {
        "case": case,
        "net_total": total,
        "daily_mdd": mdd,
        "net_mdd": total / abs(mdd) if mdd else np.nan,
        "lots": int((trades["exit_ts"] >= START).sum()),
        "net_2024_2026": float(sum(annual.get(year, 0.0) for year in (2024, 2025, 2026))),
        "net_last_12m_2025-10-30_2026-10-29": last12_net,
        "daily_mdd_last_12m_2025-10-30_2026-10-29": last12_mdd,
        "net_last_3m_2026-07-30_2026-10-29": last3_net,
        "daily_mdd_last_3m_2026-07-30_2026-10-29": last3_mdd,
        "net_aug_2026": float(day.loc[day.index.to_period("M") == pd.Period("2026-08")].sum()),
    }
    for year in YEARS:
        row[f"net_{year}"] = float(annual.get(year, 0.0))
    return row, day.rename("net").reset_index().assign(case=case)


def compare_metrics(candidate: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    wins = []
    for year in YEARS:
        delta = candidate[f"net_{year}"] - base[f"net_{year}"]
        out[f"delta_{year}_vs_v29_G2"] = delta
        if delta > 0:
            wins.append(year)
    out["delta_total_vs_v29_G2"] = candidate["net_total"] - base["net_total"]
    out["delta_2024_2026_vs_v29_G2"] = candidate["net_2024_2026"] - base["net_2024_2026"]
    out["years_beating_v29_G2"] = ",".join(map(str, wins)) if wins else "none"
    out["years_beating_v29_G2_count"] = len(wins)
    out["daily_mdd_delta_vs_v29_G2"] = candidate["daily_mdd"] - base["daily_mdd"]
    out["daily_mdd_abs_ratio_to_v29_G2"] = (
        abs(candidate["daily_mdd"]) / abs(base["daily_mdd"]) if base["daily_mdd"] else np.nan
    )
    return out


def fixed_verdict(row: dict[str, Any], base: dict[str, Any]) -> tuple[str, str]:
    total_ok = row["net_total"] > base["net_total"]
    years_ok = row["years_beating_v29_G2_count"] >= 5
    mdd_ok = abs(row["daily_mdd"]) <= abs(base["daily_mdd"]) * 1.10
    recent_ok = row["net_2024_2026"] >= base["net_2024_2026"]
    verdict = "PASS" if total_ok and years_ok and mdd_ok and recent_ok else "FAIL"
    detail = f"總淨利{'是' if total_ok else '否'}；年度勝出 {int(row['years_beating_v29_G2_count'])}/7；MDD 10% 限制{'是' if mdd_ok else '否'}；2024-2026 {'是' if recent_ok else '否'}"
    return verdict, detail


def lot_keys(trades: pd.DataFrame) -> pd.DataFrame:
    out = trades.loc[trades["exit_ts"] >= START, ["side", "kind", "entry_ts", "entry_px", "net"]].copy()
    key = ["side", "kind", "entry_ts", "entry_px"]
    out["occurrence"] = out.groupby(key, sort=False).cumcount()
    return out


def precision(reference: pd.DataFrame, candidate: pd.DataFrame, reference_case: str, candidate_case: str) -> dict[str, Any]:
    ref = lot_keys(reference)
    other = lot_keys(candidate)
    key = ["side", "kind", "entry_ts", "entry_px", "occurrence"]
    removed = ref.merge(other[key], on=key, how="left", indicator=True)
    removed = removed.loc[removed["_merge"].eq("left_only")]
    winning = removed.loc[removed["net"] > 0, "net"]
    losing = removed.loc[removed["net"] < 0, "net"]
    profit = float(winning.sum())
    loss = float(-losing.sum())
    return {
        "reference_case": reference_case,
        "case": candidate_case,
        "reference_lots": int(len(ref)),
        "candidate_lots": int(len(other)),
        "removed_lots": int(len(removed)),
        "removed_winning_lots": int(len(winning)),
        "removed_winning_lot_profit": profit,
        "removed_losing_lots": int(len(losing)),
        "removed_losing_lot_loss": loss,
        "removed_net": float(removed["net"].sum()),
        "removed_loss_to_profit_ratio": loss / profit if profit else np.nan,
    }


def money(value: float) -> str:
    return "NA" if not np.isfinite(value) else f"{value:,.0f}"


def table_rows(metrics: pd.DataFrame, labels: list[str]) -> list[str]:
    data = metrics.set_index("case")
    lines = []
    for label in labels:
        r = data.loc[label]
        years = " | ".join(money(r[f"net_{year}"]) for year in YEARS)
        verdict = r["fixed_verdict"] if r["fixed_verdict"] != "REFERENCE" else "參考"
        lines.append(
            f"| {label} | {years} | {money(r.net_total)} | {money(r.daily_mdd)} | {r.net_mdd:.2f} | "
            f"{int(r.lots):,} | {money(r.delta_total_vs_v29_G2)} | {int(r.years_beating_v29_G2_count)}/7 | "
            f"{money(r.net_2024_2026)} | {money(r['net_last_12m_2025-10-30_2026-10-29'])}/{money(r['daily_mdd_last_12m_2025-10-30_2026-10-29'])} | "
            f"{money(r['net_last_3m_2026-07-30_2026-10-29'])}/{money(r['daily_mdd_last_3m_2026-07-30_2026-10-29'])} | "
            f"{money(r.net_aug_2026)} | {verdict} |"
        )
    return lines


def make_report(thresholds: pd.DataFrame, metrics: pd.DataFrame, precision_df: pd.DataFrame,
                reproduction: pd.DataFrame) -> str:
    decisions = metrics.loc[metrics["case"].isin(["v29_H1", "v29_H2", "v29_H3", "v29_H4"])]
    passing = decisions.loc[decisions["fixed_verdict"].eq("PASS"), "case"].tolist()
    conclusion = "、".join(passing) + " 通過固定門檻。" if passing else "H1 至 H4 均未通過固定門檻。"
    lines = [
        "# ML Gate 3：波動、成交量與趨勢強度的震盪濾網",
        "",
        f"## 結論：{conclusion}",
        "",
        "固定裁決基準為 v29+G2。PASS 必須同時滿足：總淨利較高、至少 5/7 年勝出、日結算 MDD 不比基準惡化超過 10%，且 2024--2026 小計不低於基準。這不是買進持有比較。",
        "",
        "所有訊號均在已收盤的 5 分鐘決策 bar 上計算，下一根 bar 開盤成交；成本、淨利與日結算 MDD 與 `run_cmp_20261029.py` 相同。H4 的 Cmd 保留 G2 (Cmd p20)；其 Add/G 才用 Add/G p33 的三項震盪分數。",
        "",
        "## 凍結門檻（v28 lots，2020-03-02--2023-12-31）",
        "",
        "| 用途 | 樣本 | 特徵 | 分位數 | 可用 lots | 門檻 |",
        "|---|---|---|---:|---:|---:|",
    ]
    for r in thresholds.itertuples(index=False):
        lines.append(f"| {r.threshold_key} | {r.scope} | {r.feature} | {r.quantile:.0%} | {int(r.usable_lots):,} | {r.threshold:.8f} |")
    lines += [
        "",
        "H1：G2 + Cmd `atr5_pct` < Cmd p20 時封鎖。H2：G2 + Cmd `er5_48` < Cmd p20 時封鎖。H3：不使用 G2，Cmd 三項 p33 震盪分數至少 2 時封鎖。H4：Cmd 只用 G2；Add/G 使用 Add/G p33 三項分數至少 2 時封鎖。",
        "",
        "## v29 主結果（淨利；MDD 為負值）",
        "",
        "| case | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | total | 日 MDD | net/MDD | lots | vs v29+G2 | 勝出年 | 2024--26 | 近12月 net/MDD | 近3月 net/MDD | 2026-08 | 裁決 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        *table_rows(metrics, ["v29", "v29_G2", "v29_H1", "v29_H2", "v29_H3", "v29_H4"]),
        "",
        "## v28 參考結果",
        "",
        "H1、H2、H4 在此列仍包含 G2；H3 依定義取代 G2。欄位中的差額仍是相對於固定裁決基準 v29+G2，僅供跨版本參考。",
        "",
        "| case | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | total | 日 MDD | net/MDD | lots | vs v29+G2 | 勝出年 | 2024--26 | 近12月 net/MDD | 近3月 net/MDD | 2026-08 | 裁決 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        *table_rows(metrics, ["v28", "v28_G2", "v28_H1", "v28_H2", "v28_H3", "v28_H4"]),
        "",
        "## 被移除 lots 的精確度檢查",
        "",
        "「移除獲利」是被濾掉且原本為正淨利的金額；「移除虧損」是被濾掉且原本為負淨利的絕對金額。H1/H2/H4 以相同版本的 G2 為參考；H3 因為取代 G2，改以無 G2 的 v29/v28 為參考。後續倉位路徑改變會造成額外 lot 差異，故此為 ledger lot 比對而非反事實重估。",
        "",
        "| case | 參考 | 移除 lots | 移除獲利 lots/金額 | 移除虧損 lots/金額 | 移除淨額 | 虧損/獲利 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in precision_df.itertuples(index=False):
        lines.append(
            f"| {r.case} | {r.reference_case} | {int(r.removed_lots):,} | "
            f"{int(r.removed_winning_lots):,}/{money(r.removed_winning_lot_profit)} | "
            f"{int(r.removed_losing_lots):,}/{money(r.removed_losing_lot_loss)} | "
            f"{money(r.removed_net)} | {r.removed_loss_to_profit_ratio:.2f} |"
        )
    rep = reproduction.iloc[0]
    lines += [
        "",
        "## 重現檢查",
        "",
        f"以 `cmp_20261029_trades.csv` 作逐 lot assert：v29={bool(rep.v29_equals_cmp)}；v29+G2={bool(rep.v29_G2_equals_cmp)}。資料截至 {rep.data_end}；每 lot 淨成本 {money(rep.net_cost_per_lot)}。完整數值與每日序列見 `mlg3_*.csv`。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    for path in (DATA, PANEL, CMP_TRADES):
        if not path.exists():
            raise FileNotFoundError(f"required input missing: {path}")
    panel = pd.read_csv(PANEL, parse_dates=["entry_ts"])
    thresholds, threshold_df = frozen_thresholds(panel)

    case_parameters: list[tuple[str, dict[str, Any]]] = [
        ("v28", V28),
        ("v28_G2", {**V28, "opt_ml_gate": gate_parameters("G2", thresholds)}),
        ("v29", V29),
        ("v29_G2", {**V29, "opt_ml_gate": gate_parameters("G2", thresholds)}),
    ]
    for version, params in (("v28", V28), ("v29", V29)):
        for variant in ("H1", "H2", "H3", "H4"):
            case_parameters.append((f"{version}_{variant}", {**params, "opt_ml_gate": gate_parameters(variant, thresholds)}))

    cases: dict[str, pd.DataFrame] = {}
    for case, parameters in case_parameters:
        print(f"running {case}", flush=True)
        cases[case] = run_engine(case, parameters)

    cmp = pd.read_csv(CMP_TRADES, parse_dates=["entry_ts", "exit_ts"])
    cmp_v29 = cmp.loc[cmp["v"].eq("v29")].drop(columns="v")
    cmp_v29_g2 = cmp.loc[cmp["v"].eq("v29_G2")].drop(columns="v")
    assert_frame_equal(canonical(cases["v29"]), canonical(cmp_v29), check_dtype=False, check_exact=True)
    assert_frame_equal(canonical(cases["v29_G2"]), canonical(cmp_v29_g2), check_dtype=False, check_exact=True)

    metric_rows: list[dict[str, Any]] = []
    daily_rows: list[pd.DataFrame] = []
    for case, trades in cases.items():
        row, daily = metric_row(trades, case)
        metric_rows.append(row)
        daily_rows.append(daily)
    base = next(row for row in metric_rows if row["case"] == "v29_G2")
    for row in metric_rows:
        row.update(compare_metrics(row, base))
        if row["case"] in {"v29_H1", "v29_H2", "v29_H3", "v29_H4"}:
            row["fixed_verdict"], row["fixed_verdict_detail"] = fixed_verdict(row, base)
        else:
            row["fixed_verdict"] = "REFERENCE"
            row["fixed_verdict_detail"] = "固定裁決僅適用 v29 H1--H4"
    metrics_df = pd.DataFrame(metric_rows)
    daily_df = pd.concat(daily_rows, ignore_index=True)

    precision_rows = []
    for version in ("v28", "v29"):
        for variant in ("H1", "H2", "H3", "H4"):
            reference = f"{version}" if variant == "H3" else f"{version}_G2"
            candidate = f"{version}_{variant}"
            precision_rows.append(precision(cases[reference], cases[candidate], reference, candidate))
    precision_df = pd.DataFrame(precision_rows)

    reproduction = pd.DataFrame([{
        "v29_equals_cmp": True,
        "v29_G2_equals_cmp": True,
        "g2_cmd_vol_p20": thresholds["G2_cmd_vol_p20"],
        "h2_cmd_er5_48_p20": thresholds["H2_cmd_er5_48_p20"],
        "net_cost_per_lot": NET_COST,
        "data": DATA.name,
        "data_end": END.date().isoformat(),
    }])

    threshold_df.to_csv(HERE / "mlg3_thresholds.csv", index=False, encoding="utf-8")
    metrics_df.to_csv(HERE / "mlg3_metrics.csv", index=False, encoding="utf-8")
    daily_df.to_csv(HERE / "mlg3_daily_pnl.csv", index=False, encoding="utf-8")
    precision_df.to_csv(HERE / "mlg3_precision.csv", index=False, encoding="utf-8")
    reproduction.to_csv(HERE / "mlg3_reproduction.csv", index=False, encoding="utf-8")
    for case, trades in cases.items():
        trades.to_csv(HERE / f"mlg3_trades_{case}.csv", index=False, encoding="utf-8")
    (HERE / "results_ml_gate3.md").write_text(
        make_report(threshold_df, metrics_df, precision_df, reproduction), encoding="utf-8"
    )
    print(metrics_df.to_string(index=False))
    print("completed", flush=True)


if __name__ == "__main__":
    main()
