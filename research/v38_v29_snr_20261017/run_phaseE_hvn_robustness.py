"""Phase E robustness tests for the local HVN long-Add gate wrapper."""

from __future__ import annotations

import multiprocessing as mp
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from engine_v29_hvn_wrapper import load_1min, run


HERE = Path(__file__).resolve().parent
DATA_PATH = HERE / "mxf_1min_corrected_20261017.csv"
V29_PATH = HERE / "trades_v29.csv"
V28_PATH = HERE / "trades_v28.csv"
RESULTS_PATH = HERE / "results_phaseE.md"
TRADE_COLS = ["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl"]
H2 = pd.Timestamp("2025-04-01")
TRAIN_START = pd.Timestamp("2026-03-01")
TEST_START = pd.Timestamp("2026-06-01")
HOLDOUT_START = pd.Timestamp("2026-08-22")
WINDOWS = ("full", "H1", "H2", "TRAIN", "TEST", "HOLDOUT")
YEARS = (2024, 2025, 2026)
V29 = {
    "opt_stale_hr": 10,
    "opt_cooldown_min": 30,
    "opt_short_pyramid_cap_mode": "hour4",
    "l_trailBase": 3.5,
}
V28 = {**V29, "l_trailBase": 5.0}


def metric(trades: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {"n": 0, "net": 0.0, "mdd": 0.0}
    equity = trades.groupby("exit_ts", sort=True).pnl.sum().cumsum()
    return {
        "n": int(len(trades)),
        "net": float(trades.pnl.sum()),
        "mdd": float((equity - equity.cummax()).min()),
    }


def splits(trades: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    return {
        "full": metric(trades),
        "H1": metric(trades[trades.entry_ts < H2]),
        "H2": metric(trades[trades.entry_ts >= H2]),
        "TRAIN": metric(trades[(trades.entry_ts >= TRAIN_START) & (trades.entry_ts < TEST_START)]),
        "TEST": metric(trades[(trades.entry_ts >= TEST_START) & (trades.entry_ts < HOLDOUT_START)]),
        "HOLDOUT": metric(trades[trades.entry_ts >= HOLDOUT_START]),
    }


def year_nets(trades: pd.DataFrame) -> dict[int, float]:
    return {
        year: float(trades.loc[trades.entry_ts.dt.year == year, "pnl"].sum())
        for year in YEARS
    }


def delta_summary(candidate: pd.DataFrame, baseline: pd.DataFrame) -> dict[str, Any]:
    candidate_splits, baseline_splits = splits(candidate), splits(baseline)
    candidate_years, baseline_years = year_nets(candidate), year_nets(baseline)
    return {
        "splits": candidate_splits,
        "deltas": {
            key: float(candidate_splits[key]["net"] - baseline_splits[key]["net"])
            for key in WINDOWS
        },
        "years": {
            year: float(candidate_years[year] - baseline_years[year]) for year in YEARS
        },
        "mdd_delta": float(candidate_splits["full"]["mdd"] - baseline_splits["full"]["mdd"]),
    }


def regression_check(fresh: pd.DataFrame, recorded: pd.DataFrame, label: str) -> str:
    pd.testing.assert_frame_equal(
        fresh[TRADE_COLS].reset_index(drop=True),
        recorded[TRADE_COLS].reset_index(drop=True),
        check_dtype=False,
        check_exact=True,
    )
    return f"{label}：{len(fresh):,}/{len(recorded):,} 筆交易逐欄完全一致"


def campaign_pnl(trades: pd.DataFrame) -> pd.DataFrame:
    """Assign every closed lot to the most recent Cmd fill in its run."""
    ordered = trades.copy()
    ordered["_kind_order"] = ordered.kind.ne("Cmd").astype(int)
    ordered = ordered.sort_values(["entry_ts", "_kind_order", "side"]).reset_index(drop=True)
    current: pd.Timestamp | None = None
    campaign_ts: list[pd.Timestamp] = []
    for row in ordered.itertuples(index=False):
        if row.kind == "Cmd":
            current = pd.Timestamp(row.entry_ts)
        if current is None:
            raise RuntimeError("encountered a lot before its first Cmd campaign")
        campaign_ts.append(current)
    ordered["cmd_entry_ts"] = campaign_ts
    cmd_sides = (
        ordered.loc[ordered.kind.eq("Cmd"), ["cmd_entry_ts", "side"]]
        .drop_duplicates("cmd_entry_ts")
        .set_index("cmd_entry_ts").side
    )
    result = ordered.groupby("cmd_entry_ts", as_index=False).agg(
        pnl=("pnl", "sum"), lots=("pnl", "size")
    )
    result["side"] = result.cmd_entry_ts.map(cmd_sides)
    return result


def concentration(baseline: pd.DataFrame, gated: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    months = pd.period_range("2024-01", gated.entry_ts.max().to_period("M"), freq="M")
    base_month = baseline.assign(month=baseline.entry_ts.dt.to_period("M")).groupby("month").pnl.sum()
    gate_month = gated.assign(month=gated.entry_ts.dt.to_period("M")).groupby("month").pnl.sum()
    monthly = pd.DataFrame({"v29": base_month, "pct_2.5_L": gate_month}).reindex(months, fill_value=0.0)
    monthly.index.name = "month"
    monthly["delta"] = monthly["pct_2.5_L"] - monthly["v29"]
    monthly = monthly.reset_index()
    monthly["month"] = monthly.month.astype(str)

    base_campaign = campaign_pnl(baseline).rename(columns={"pnl": "v29_pnl", "lots": "v29_lots"})
    gate_campaign = campaign_pnl(gated).rename(columns={"pnl": "gate_pnl", "lots": "gate_lots"})
    campaigns = base_campaign.merge(
        gate_campaign, on="cmd_entry_ts", how="outer", suffixes=("_v29", "_gate")
    )
    campaigns["side"] = campaigns.side_v29.combine_first(campaigns.side_gate)
    campaigns = campaigns.drop(columns=["side_v29", "side_gate"])
    campaigns[["v29_pnl", "gate_pnl"]] = campaigns[["v29_pnl", "gate_pnl"]].fillna(0.0)
    campaigns[["v29_lots", "gate_lots"]] = campaigns[["v29_lots", "gate_lots"]].fillna(0).astype(int)
    campaigns["delta"] = campaigns.gate_pnl - campaigns.v29_pnl
    campaigns = campaigns.sort_values("delta", ascending=False).reset_index(drop=True)
    total = float(campaigns.delta.sum())
    top5 = float(campaigns.head(5).delta.sum())
    top10 = float(campaigns.head(10).delta.sum())
    stats = {
        "total": total,
        "top5": top5,
        "top10": top10,
        "top5_share": 100 * top5 / total if total else np.nan,
        "top10_share": 100 * top10 / total if total else np.nan,
        "excluding_top5": total - top5,
        "matched": int(campaigns.v29_lots.gt(0).mul(campaigns.gate_lots.gt(0)).sum()),
        "all": int(len(campaigns)),
    }
    return monthly, campaigns, stats


_WORKER_DF: pd.DataFrame | None = None
_WORKER_BASELINE: pd.DataFrame | None = None


def _init_placebo_worker(data_path: str, baseline_path: str) -> None:
    global _WORKER_DF, _WORKER_BASELINE
    _WORKER_DF = load_1min(data_path)
    _WORKER_BASELINE = pd.read_csv(baseline_path, parse_dates=["entry_ts", "exit_ts"])


def _placebo_draw(args: tuple[int, dict[int, float]]) -> dict[str, Any]:
    if _WORKER_DF is None or _WORKER_BASELINE is None:
        raise RuntimeError("placebo worker was not initialized")
    seed, probabilities = args
    trades = run(
        _WORKER_DF,
        {
            **V29,
            "opt_add_random_skip": {
                "seed": seed,
                "prob_by_year": probabilities,
                "sides": ("L",),
            },
        },
        intrabar_mode="1min",
    )
    result = delta_summary(trades, _WORKER_BASELINE)
    audit = pd.DataFrame(trades.attrs["hvn_gate_audit"])
    realized = {
        year: int(
            ((audit.side == "L") & audit.skipped & (audit.entry_ts.dt.year == year)).sum()
        )
        for year in YEARS
    }
    row: dict[str, Any] = {"seed": seed, "mdd_delta": result["mdd_delta"]}
    row.update({f"net_delta_{window}": result["deltas"][window] for window in WINDOWS})
    row.update({f"net_delta_{year}": result["years"][year] for year in YEARS})
    row.update({f"realized_skips_{year}": realized[year] for year in YEARS})
    row["realized_skips_total"] = sum(realized.values())
    return row


def fmt(value: float | int, digits: int = 0, signed: bool = True) -> str:
    if isinstance(value, float) and np.isnan(value):
        return "—"
    sign = "+" if signed else ""
    return f"{value:{sign},.{digits}f}"


def percentile_rank(values: pd.Series, actual: float) -> float:
    return 100.0 * float((values <= actual).mean())


def distribution_line(values: pd.Series) -> dict[str, float]:
    quantiles = values.quantile([0.05, 0.50, 0.95])
    return {"p05": float(quantiles.loc[0.05]), "p50": float(quantiles.loc[0.50]), "p95": float(quantiles.loc[0.95])}


def execute_placebo_draws(
    probabilities: dict[int, float], seeds: list[int], label: str
) -> pd.DataFrame:
    """Run a deterministic batch in one local multiprocessing pool."""
    workers = max(1, (os.cpu_count() or 3) - 2)
    ctx = mp.get_context("spawn")
    draw_rows: list[dict[str, Any]] = []
    with ctx.Pool(
        processes=workers,
        initializer=_init_placebo_worker,
        initargs=(str(DATA_PATH), str(V29_PATH)),
    ) as pool:
        for n, row in enumerate(pool.imap_unordered(_placebo_draw, [(seed, probabilities) for seed in seeds]), 1):
            draw_rows.append(row)
            if n % 10 == 0 or n == len(seeds):
                print(f"{label} {n}/{len(seeds)}", flush=True)
    return pd.DataFrame(draw_rows).sort_values("seed").reset_index(drop=True)


def calibrate_probabilities(
    opportunity_counts: dict[int, int], targets: dict[int, int]
) -> tuple[dict[int, float], pd.DataFrame]:
    """Tune yearly Bernoulli probabilities to account for path-dependent signals.

    A skipped Add can leave room for later Add signals, so target/opportunities
    alone is not calibrated.  Three independent, fixed-seed pilot batches use
    damped multiplicative updates; the final batch is held out from this step.
    """
    probabilities = {year: targets[year] / opportunity_counts[year] for year in YEARS}
    records: list[dict[str, float | int]] = []
    for iteration in range(3):
        seeds = list(range(62001 + iteration * 24, 62025 + iteration * 24))
        pilot = execute_placebo_draws(probabilities, seeds, f"calibration {iteration + 1}")
        means = {year: float(pilot[f"realized_skips_{year}"].mean()) for year in YEARS}
        for year in YEARS:
            records.append({
                "iteration": iteration + 1,
                "year": year,
                "probability": probabilities[year],
                "target_skips": targets[year],
                "pilot_mean_skips": means[year],
            })
        # The final pilot verifies the probabilities in use; do not tune on
        # the held-out 200 final draw outcomes.
        if iteration < 2:
            for year in YEARS:
                ratio = targets[year] / means[year] if means[year] else 1.0
                probabilities[year] = float(np.clip(probabilities[year] * ratio ** 0.7, 0.0, 1.0))
    return probabilities, pd.DataFrame(records)


def markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    return [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
        *["| " + " | ".join(row) + " |" for row in rows],
    ]


def write_report(
    baseline: pd.DataFrame,
    regression_v29: str,
    real: pd.DataFrame,
    real_result: dict[str, Any],
    real_skips: dict[int, int],
    opportunity_counts: dict[int, int],
    probabilities: dict[int, float],
    placebo: pd.DataFrame,
    monthly: pd.DataFrame,
    campaigns: pd.DataFrame,
    concentration_stats: dict[str, float],
    calibration: pd.DataFrame,
    pine_results: dict[str, dict[str, Any]],
    regression_v28: str,
    v28_baseline: pd.DataFrame,
    v28_gate: pd.DataFrame,
    v28_result: dict[str, Any],
) -> None:
    placebo_dist: dict[str, dict[str, float]] = {}
    actuals: dict[str, float] = {"full": real_result["deltas"]["full"]}
    actuals.update({window: real_result["deltas"][window] for window in WINDOWS if window != "full"})
    actuals.update({str(year): real_result["years"][year] for year in YEARS})
    for label, actual in actuals.items():
        col = f"net_delta_{label}"
        placebo_dist[label] = distribution_line(placebo[col])
        placebo_dist[label]["rank"] = percentile_rank(placebo[col], actual)

    mdd_dist = distribution_line(placebo.mdd_delta)
    mdd_rank = percentile_rank(placebo.mdd_delta, real_result["mdd_delta"])
    beat_placebo = (
        real_result["deltas"]["full"] > placebo_dist["full"]["p95"]
        and real_result["years"][2026] > placebo_dist["2026"]["p95"]
        and real_result["years"][2024] >= placebo_dist["2024"]["p50"]
        and real_result["years"][2025] >= placebo_dist["2025"]["p50"]
    )
    pine_passes = {
        name: all(result["deltas"][w] > 0 for w in ("H1", "H2", "TRAIN", "TEST"))
        for name, result in pine_results.items()
    }
    v28_vs_v29_gate = delta_summary(v28_gate, pine_results["pct_2.5_L"]["trades"])

    lines = [
        "# Phase E：HVN long-Add gate 的穩健性檢驗",
        "",
        "## 五行結論",
        "",
        f"1. 匹配年度隨機跳過檢定：{'通過' if beat_placebo else '未通過'}；真實 gate 的全樣本/2026 增益分別位於 placebo 的 {placebo_dist['full']['rank']:.1f}%/{placebo_dist['2026']['rank']:.1f}% 百分位，2024/2025 分別為 {placebo_dist['2024']['rank']:.1f}%/{placebo_dist['2025']['rank']:.1f}% 百分位。",
        f"2. 集中度：增益明顯集中但非完全由少數 campaign 構成；前 5/10 個 campaign 貢獻總增益的 {concentration_stats['top5_share']:.1f}%/{concentration_stats['top10_share']:.1f}%，排除前 5 個後仍為 {fmt(concentration_stats['excluding_top5'])}。",
        f"3. Pine-faithful（以 causal_close5 定價）後：1.5/2.5/3.5 ATR 三個門檻的 PASS 狀態為 " + "、".join(f"{name}={'PASS' if pine_passes[name] else 'FAIL'}" for name in pine_results) + "。",
        f"4. v28（l_trailBase=5.0）下 causal_close5 2.5 ATR gate 的全樣本/HOLDOUT 為 {fmt(v28_result['deltas']['full'])}/{fmt(v28_result['deltas']['HOLDOUT'])}，但 TRAIN 為 {fmt(v28_result['deltas']['TRAIN'])}；故結果為部分保留、非全面 PASS。",
        f"5. 綜合判斷：此訊號的{'超額表現不只是任意減少 long Add' if beat_placebo else '超額表現不能排除只是任意減少 long Add'}；實務採用前仍應重視 campaign 集中度與 causal-close 版本的結果。",
        "",
        "## 設計與再現性",
        "",
        f"- {regression_v29}。原始 engine 未修改；所有測試皆透過本目錄的 wrapper，以 1 分鐘 intrabar、stale=10h、cooldown=30m、v29 參數執行。",
        "- placebo 僅針對 long Add。在每個潛在 Add signal 的實際執行時，以該 fill 年份的固定 Bernoulli 機率跳過；不預先選交易，避免忽略跳過後會改變後續路徑的問題。固定種子為 61001–61200，共 200 次完整 engine run。",
        "- 先以 gate-off 機會數設定初始機率，再用三輪各 24 個固定種子的 pilot（damped multiplicative update）校準路徑相依後的年度期望跳過數；最終 200 個 seed 不參與校準。未對 campaign ordinal 再分層，因跳過會改變 ordinal 的可得性；下表另完整呈現最終 draw 的實現跳過數分布。",
        "- Pine-faithful 版只改 reference：將原本 next-open fill 價替換為既有嚴格因果欄位 `causal_close5`，同時作為距離參考價與 pct-bin 寬度基準；5 日 profile 的資料截止、HVN 定義與 ATR 正規化均不變。",
        "",
        "## 1. 匹配年度 random-skip placebo",
        "",
        "### 校準與實現的跳過數",
        "",
    ]
    skip_rows = []
    for year in YEARS:
        series = placebo[f"realized_skips_{year}"]
        d = distribution_line(series)
        skip_rows.append([
            str(year), str(opportunity_counts[year]), str(real_skips[year]),
            f"{probabilities[year]:.4f}", f"{series.mean():.1f}",
            str(int(series.min())), f"{d['p05']:.0f}", f"{d['p50']:.0f}", f"{d['p95']:.0f}", str(int(series.max())),
        ])
    total_series = placebo.realized_skips_total
    total_d = distribution_line(total_series)
    skip_rows.append([
        "合計", str(sum(opportunity_counts.values())), str(sum(real_skips.values())), "—",
        f"{total_series.mean():.1f}", str(int(total_series.min())), f"{total_d['p05']:.0f}",
        f"{total_d['p50']:.0f}", f"{total_d['p95']:.0f}", str(int(total_series.max())),
    ])
    lines += markdown_table(
        ["年度", "gate-off 機會", "真實跳過", "p", "placebo 平均", "最小", "P5", "P50", "P95", "最大"], skip_rows
    )
    lines += ["", "### 校準 pilot（最終機率取第 3 輪）", ""]
    calibration_rows = [
        [str(int(r.iteration)), str(int(r.year)), f"{r.probability:.4f}", str(int(r.target_skips)), f"{r.pilot_mean_skips:.1f}"]
        for r in calibration.itertuples(index=False)
    ]
    lines += markdown_table(["輪次", "年度", "p", "目標跳過", "pilot 平均跳過"], calibration_rows)
    lines += ["", "### 相對 v29 的淨利 delta 分布", ""]
    dist_rows = []
    for label in ("full", "H1", "H2", "TRAIN", "TEST", "HOLDOUT", "2024", "2025", "2026"):
        actual = actuals[label]
        d = placebo_dist[label]
        dist_rows.append([
            label, fmt(actual), fmt(d["p05"]), fmt(d["p50"]), fmt(d["p95"]), f"{d['rank']:.1f}%",
        ])
    lines += markdown_table(["區間", "真實 gate", "placebo P5", "P50", "P95", "真實百分位"], dist_rows)
    lines += [
        "",
        "### 全樣本 MDD delta（gate/placebo − v29；正值代表回撤較淺）",
        "",
    ]
    lines += markdown_table(
        ["真實 gate", "placebo P5", "P50", "P95", "真實百分位"],
        [[fmt(real_result["mdd_delta"]), fmt(mdd_dist["p05"]), fmt(mdd_dist["p50"]), fmt(mdd_dist["p95"]), f"{mdd_rank:.1f}%"]],
    )
    lines += [
        "",
        "真實 fill-price pct_2.5_L 的全樣本淨利 delta 為 " + fmt(real_result["deltas"]["full"]) +
        f"，MDD delta 為 {fmt(real_result['mdd_delta'])}；隨機檢定的判準是全樣本與 2026 均高於 P95，且 2024、2025 均不低於 P50。",
        "",
        "## 2. pct_2.5_L 的集中度（相對 v29）",
        "",
        "### 按 lot entry month 的淨利 delta",
        "",
    ]
    month_rows = [[r.month, fmt(r.v29), fmt(r._2), fmt(r.delta)] for r in monthly.rename(columns={"pct_2.5_L": "_2"}).itertuples(index=False)]
    lines += markdown_table(["月份", "v29", "pct_2.5_L", "delta"], month_rows)
    top5 = campaigns.head(5)
    lines += [
        "",
        f"Campaign 以 Cmd entry timestamp 精確匹配；{int(concentration_stats['matched']):,}/{int(concentration_stats['all']):,} 個外連結 campaign 在兩邊都有 lot。前 5/10 正 delta campaign 合計為 {fmt(concentration_stats['top5'])}/{fmt(concentration_stats['top10'])}，佔總 delta {concentration_stats['top5_share']:.1f}%/{concentration_stats['top10_share']:.1f}%。",
        "",
        "### Delta 最大的前五個 campaign",
        "",
    ]
    top_rows = [
        [pd.Timestamp(r.cmd_entry_ts).strftime("%Y-%m-%d %H:%M"), r.side, fmt(r.v29_pnl), fmt(r.gate_pnl), fmt(r.delta), str(r.v29_lots), str(r.gate_lots)]
        for r in top5.itertuples(index=False)
    ]
    lines += markdown_table(["Cmd entry", "方向", "v29 pnl", "gate pnl", "delta", "v29 lots", "gate lots"], top_rows)
    lines += [
        "",
        f"排除上述前五個 campaign 後，總 delta = {fmt(concentration_stats['excluding_top5'])}（原總 delta {fmt(concentration_stats['total'])}）。",
        "",
        "## 3. Pine-faithful：causal_close5 參考價",
        "",
    ]
    pine_rows = []
    for name, result in pine_results.items():
        pine_rows.append([
            name, str(result["skipped"]), fmt(result["deltas"]["full"]), fmt(result["deltas"]["H1"]),
            fmt(result["deltas"]["H2"]), fmt(result["deltas"]["TRAIN"]), fmt(result["deltas"]["TEST"]),
            fmt(result["deltas"]["HOLDOUT"]), fmt(result["years"][2024]), fmt(result["years"][2025]),
            fmt(result["years"][2026]), "PASS" if pine_passes[name] else "FAIL",
        ])
    lines += markdown_table(
        ["variant", "跳過 Add", "full", "H1", "H2", "TRAIN", "TEST", "HOLDOUT", "2024", "2025", "2026", "PASS"], pine_rows
    )
    lines += [
        "",
        "PASS 定義完全沿用 Phase D：H1、H2、TRAIN、TEST 的 net delta 都必須嚴格大於零；HOLDOUT 不參與判定。表中所有數字都是相對 v29 的 net delta。",
        "",
        "## 4. v28 base（l_trailBase=5.0）的 causal_close5 pct_2.5_L",
        "",
        f"- {regression_v28}。",
        f"- v28 baseline：full net {fmt(metric(v28_baseline)['net'])}、MDD {fmt(metric(v28_baseline)['mdd'])}；v28+gate：full net {fmt(metric(v28_gate)['net'])}、MDD {fmt(metric(v28_gate)['mdd'])}。",
        "",
    ]
    v28_rows = []
    v28_splits = splits(v28_baseline)
    v28g_splits = splits(v28_gate)
    v29g_splits = splits(pine_results["pct_2.5_L"]["trades"])
    for window in WINDOWS:
        v28_rows.append([
            window, fmt(v28_splits[window]["net"]), fmt(v28g_splits[window]["net"]),
            fmt(v28_result["deltas"][window]), fmt(v29g_splits[window]["net"]),
            fmt(v28g_splits[window]["net"] - v29g_splits[window]["net"]),
        ])
    for year in YEARS:
        v28_base_year = year_nets(v28_baseline)[year]
        v28_gate_year = year_nets(v28_gate)[year]
        v29_gate_year = year_nets(pine_results["pct_2.5_L"]["trades"])[year]
        v28_rows.append([
            str(year), fmt(v28_base_year), fmt(v28_gate_year), fmt(v28_result["years"][year]),
            fmt(v29_gate_year), fmt(v28_gate_year - v29_gate_year),
        ])
    lines += markdown_table(
        ["區間", "v28 baseline", "v28+gate", "gate−v28", "v29+gate", "v28+gate−v29+gate"], v28_rows
    )
    lines += [
        "",
        "此節的 v29+gate 是同一個 Pine-faithful pct_2.5_L 版本，故最後一欄隔離的是 base 版本差異，不混入 fill-price gate 的差異。",
        "",
        "## 產物",
        "",
        "- `phaseE_placebo_draws.csv`：200 次 draw 的固定種子、各區間/年度 net delta、MDD delta 和實現跳過數。",
        "- `phaseE_monthly_delta.csv`、`phaseE_campaign_delta.csv`：集中度的完整明細。",
        "- `trades_phaseE_pine_*.csv`、`trades_phaseE_v28_pine_pct_2.5_L.csv`：每個重新執行的成交明細。",
        "",
    ]
    RESULTS_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    df1m = load_1min(DATA_PATH)
    baseline = pd.read_csv(V29_PATH, parse_dates=["entry_ts", "exit_ts"])
    v28_recorded = pd.read_csv(V28_PATH, parse_dates=["entry_ts", "exit_ts"])

    print("run v29 gate-off regression", flush=True)
    off = run(df1m, {**V29, "opt_add_hvn_gate": None}, intrabar_mode="1min")
    regression_v29 = regression_check(off, baseline, "v29 gate-off")
    opportunities_audit = pd.DataFrame(off.attrs["hvn_gate_audit"])
    opportunity_counts = {
        year: int(((opportunities_audit.side == "L") & (opportunities_audit.entry_ts.dt.year == year)).sum())
        for year in YEARS
    }

    fill_gate = {"feature": "pct", "min_dist_atr": 2.5, "sides": ("L",), "reference": "fill"}
    print("run real fill-price pct_2.5_L", flush=True)
    real = run(df1m, {**V29, "opt_add_hvn_gate": fill_gate}, intrabar_mode="1min")
    real.to_csv(HERE / "trades_phaseE_fill_pct_2.5_L.csv", index=False, encoding="utf-8-sig")
    real_result = delta_summary(real, baseline)
    real_audit = pd.DataFrame(real.attrs["hvn_gate_audit"])
    real_skips = {
        year: int(((real_audit.side == "L") & real_audit.skipped & (real_audit.entry_ts.dt.year == year)).sum())
        for year in YEARS
    }
    if sum(real_skips.values()) != 600:
        raise RuntimeError(f"expected 600 Phase-D pct_2.5_L skips; got {sum(real_skips.values())}")
    probabilities = {year: real_skips[year] / opportunity_counts[year] for year in YEARS}

    print("calibrate path-dependent random-skip probabilities", flush=True)
    probabilities, calibration = calibrate_probabilities(opportunity_counts, real_skips)
    calibration.to_csv(HERE / "phaseE_placebo_calibration.csv", index=False, encoding="utf-8-sig")
    print("run 200 calibrated random-skip placebo draws", flush=True)
    placebo = execute_placebo_draws(probabilities, list(range(61001, 61201)), "placebo")
    placebo.to_csv(HERE / "phaseE_placebo_draws.csv", index=False, encoding="utf-8-sig")

    monthly, campaigns, concentration_stats = concentration(baseline, real)
    monthly.to_csv(HERE / "phaseE_monthly_delta.csv", index=False, encoding="utf-8-sig")
    campaigns.to_csv(HERE / "phaseE_campaign_delta.csv", index=False, encoding="utf-8-sig")

    pine_results: dict[str, dict[str, Any]] = {}
    for threshold in (1.5, 2.5, 3.5):
        name = f"pct_{threshold:.1f}_L"
        print(f"run Pine-faithful {name}", flush=True)
        gate = {
            "feature": "pct", "min_dist_atr": threshold, "sides": ("L",),
            "reference": "causal_close5",
        }
        trades = run(df1m, {**V29, "opt_add_hvn_gate": gate}, intrabar_mode="1min")
        trades.to_csv(HERE / f"trades_phaseE_pine_{name}.csv", index=False, encoding="utf-8-sig")
        info = delta_summary(trades, baseline)
        info["trades"] = trades
        info["skipped"] = int(trades.attrs["hvn_gate_skipped"])
        pine_results[name] = info

    print("run v28 gate-off regression and Pine-faithful gate", flush=True)
    v28_off = run(df1m, {**V28, "opt_add_hvn_gate": None}, intrabar_mode="1min")
    regression_v28 = regression_check(v28_off, v28_recorded, "v28 gate-off")
    v28_gate = run(
        df1m,
        {
            **V28,
            "opt_add_hvn_gate": {
                "feature": "pct", "min_dist_atr": 2.5, "sides": ("L",),
                "reference": "causal_close5",
            },
        },
        intrabar_mode="1min",
    )
    v28_gate.to_csv(HERE / "trades_phaseE_v28_pine_pct_2.5_L.csv", index=False, encoding="utf-8-sig")
    v28_result = delta_summary(v28_gate, v28_recorded)

    write_report(
        baseline, regression_v29, real, real_result, real_skips, opportunity_counts,
        probabilities, placebo, monthly, campaigns, concentration_stats, calibration,
        pine_results, regression_v28, v28_recorded, v28_gate, v28_result,
    )
    print(RESULTS_PATH, flush=True)


if __name__ == "__main__":
    main()
