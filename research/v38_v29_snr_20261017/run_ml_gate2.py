"""Pre-declared G2 robustness checks for the frozen V38/v28 ML gate study.

The vendor engine remains read-only: all calls use engine_ml_gate_wrapper.py.
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
DATA = HERE / "mxf_1min_2020_20261026.csv"
PANEL = HERE / "ml_features_panel.csv"
PREVIOUS_V28 = HERE / "mlg_trades_v28.csv"
PREVIOUS_G2 = HERE / "mlg_trades_G2.csv"
PREVIOUS_V29 = HERE / "br_trades_v29.csv"
START = pd.Timestamp("2020-03-02")
CALIBRATION_END = pd.Timestamp("2023-12-31 23:59:59.999999999")
YEARS = tuple(range(2020, 2027))
PERCENTILES = (0.10, 0.15, 0.20, 0.25, 0.30)
FROZEN_20 = 0.72777104
NET_COST = 2 * (40 - mlg.COMMISSION) + 2 * 4 * mlg.POINT_VALUE
LIVE_V28 = {
    **mlg.P,
    "opt_stale_hr": 10,
    "opt_cooldown_min": 30,
    "opt_short_pyramid_cap_mode": "hour4",
}
# LIVE_V28 deliberately materializes the engine defaults.  The engine's
# compatibility mapping only changes session-specific settings when they are
# absent from overrides, so set all three long-trail keys here to preserve the
# established meaning of the single v29 l_trailBase=3.5 setting.
LIVE_V29 = {
    **LIVE_V28,
    "l_trailBase": 3.5,
    "l_trailBaseDay": 3.5,
    "l_trailBaseNight": 3.5,
}


def ledger(raw: pd.DataFrame, label: str) -> pd.DataFrame:
    out = raw.copy()
    out["entry_ts"] = pd.to_datetime(out["entry_ts"])
    out["exit_ts"] = pd.to_datetime(out["exit_ts"])
    out["net"] = out["pnl"].astype(float) - NET_COST
    out["case"] = label
    return out


def canonical(trades: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px",
        "exit_sig", "pnl", "net", "case",
    ]
    out = trades.loc[:, columns].copy()
    out["entry_ts"] = pd.to_datetime(out["entry_ts"])
    out["exit_ts"] = pd.to_datetime(out["exit_ts"])
    return out.sort_values(columns, kind="mergesort").reset_index(drop=True)


def canonical_without_case(trades: pd.DataFrame) -> pd.DataFrame:
    out = trades.drop(columns="case", errors="ignore").copy()
    columns = [
        "side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px",
        "exit_sig", "pnl", "net",
    ]
    out = out.loc[:, columns]
    out["entry_ts"] = pd.to_datetime(out["entry_ts"])
    out["exit_ts"] = pd.to_datetime(out["exit_ts"])
    return out.sort_values(columns, kind="mergesort").reset_index(drop=True)


def frozen_thresholds(panel: pd.DataFrame) -> pd.DataFrame:
    calibration = panel.loc[
        panel["entry_ts"].between(START, CALIBRATION_END, inclusive="both")
        & panel["kind"].eq("Cmd")
    ].copy()
    values = pd.to_numeric(calibration["session_cum_vol_rel20"], errors="coerce").dropna()
    if values.empty:
        raise AssertionError("empty frozen calibration sample")
    rows = []
    for percentile in PERCENTILES:
        threshold = float(values.quantile(percentile))
        rows.append({
            "case": f"G2_p{int(percentile * 100):02d}",
            "variant": "G2",
            "feature": "session_cum_vol_rel20",
            "quantile": percentile,
            "calibration_start": START,
            "calibration_end": CALIBRATION_END,
            "eligible_cmd_lots": int(len(calibration)),
            "usable_cmd_lots": int(len(values)),
            "threshold": threshold,
        })
    thresholds = pd.DataFrame(rows)
    actual_20 = float(thresholds.loc[thresholds["quantile"].eq(0.20), "threshold"].iloc[0])
    if not np.isclose(actual_20, FROZEN_20, rtol=0, atol=5e-9):
        raise AssertionError(f"20% frozen cutoff drifted: {actual_20:.8f}")
    return thresholds


def run_engine(label: str, parameters: dict[str, Any]) -> pd.DataFrame:
    # Match the original study: each run receives a freshly loaded input frame.
    df1m = mlg.load_1min(DATA)
    try:
        raw = mlg.run(df1m, p=parameters, intrabar_mode="1min")
    finally:
        del df1m
        gc.collect()
    return ledger(raw, label)


def trading_day(exits: pd.Series) -> pd.Series:
    exits = pd.to_datetime(exits)
    return exits.dt.normalize() + pd.to_timedelta((exits.dt.hour >= 15).astype(int), unit="D")


def daily_net(trades: pd.DataFrame) -> pd.Series:
    tr = trades.loc[trades["exit_ts"] >= START].copy()
    return tr.assign(day=trading_day(tr["exit_ts"])).groupby("day")["net"].sum().sort_index()


def daily_mdd(day_pnl: pd.Series) -> float:
    equity = day_pnl.cumsum()
    return float((equity - equity.cummax()).min()) if len(equity) else 0.0


def metrics(trades: pd.DataFrame, label: str) -> tuple[dict[str, Any], pd.DataFrame]:
    day = daily_net(trades)
    annual = day.groupby(day.index.year).sum()
    total = float(day.sum())
    mdd = daily_mdd(day)
    row: dict[str, Any] = {
        "case": label,
        "net_total": total,
        "daily_mdd": mdd,
        "net_mdd": float(total / abs(mdd)) if mdd else np.nan,
        "lots": int((trades["exit_ts"] >= START).sum()),
        "net_2024_2026": float(sum(annual.get(year, 0.0) for year in (2024, 2025, 2026))),
    }
    for year in YEARS:
        row[f"net_{year}"] = float(annual.get(year, 0.0))
    return row, day.rename("net").reset_index().assign(case=label)


def annual_comparison(candidate: dict[str, Any], baseline: dict[str, Any], name: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    beating = []
    for year in YEARS:
        delta = candidate[f"net_{year}"] - baseline[f"net_{year}"]
        out[f"delta_{year}_vs_{name}"] = delta
        if delta > 0:
            beating.append(year)
    out[f"delta_total_vs_{name}"] = candidate["net_total"] - baseline["net_total"]
    out[f"delta_2024_2026_vs_{name}"] = candidate["net_2024_2026"] - baseline["net_2024_2026"]
    out[f"years_beating_{name}"] = ",".join(map(str, beating)) if beating else "none"
    out[f"years_beating_{name}_count"] = len(beating)
    out[f"mdd_delta_vs_{name}"] = candidate["daily_mdd"] - baseline["daily_mdd"]
    out[f"mdd_better_vs_{name}"] = candidate["daily_mdd"] > baseline["daily_mdd"]
    return out


def with_lot_key(trades: pd.DataFrame) -> pd.DataFrame:
    out = trades.loc[
        trades["exit_ts"] >= START,
        ["side", "kind", "entry_ts", "entry_px", "net"],
    ].copy()
    columns = ["side", "kind", "entry_ts", "entry_px"]
    out["occurrence"] = out.groupby(columns).cumcount()
    return out


def removal_audit(baseline: pd.DataFrame, candidate: pd.DataFrame, candidate_case: str) -> dict[str, Any]:
    base = with_lot_key(baseline)
    other = with_lot_key(candidate)
    key = ["side", "kind", "entry_ts", "entry_px", "occurrence"]
    removed = base.merge(other[key], on=key, how="left", indicator=True)
    removed = removed.loc[removed["_merge"].eq("left_only")]
    return {
        "case": candidate_case,
        "removed_lots": int(len(removed)),
        "removed_cmd_lots": int(removed["kind"].eq("Cmd").sum()),
        "baseline_net_of_removed_lots": float(removed["net"].sum()),
    }


def session_minutes(blocked: pd.DataFrame) -> pd.Series:
    session_date = pd.to_datetime(blocked["session_date"])
    start = session_date + pd.Timedelta(hours=8, minutes=45)
    night = blocked["session"].eq("night")
    start.loc[night] = session_date.loc[night] - pd.Timedelta(days=1) + pd.Timedelta(hours=15)
    minutes = (pd.to_datetime(blocked["entry_ts"]) - start).dt.total_seconds() / 60.0
    if (minutes < 0).any():
        raise AssertionError("negative session elapsed time")
    return minutes


def settlement_bucket(session_dates: pd.Series, trading_calendar: pd.Series) -> pd.Series:
    """Classify against the calendar third Wednesday and observed trading dates."""
    dates = pd.to_datetime(session_dates).dt.normalize()
    all_dates = pd.DatetimeIndex(sorted(pd.to_datetime(trading_calendar).dt.normalize().unique()))
    result = pd.Series("other", index=dates.index, dtype="object")
    for period, index in dates.groupby(dates.dt.to_period("M")).groups.items():
        month_dates = all_dates[(all_dates.to_period("M") == period)]
        # Third Wednesday: first day + offset to Wednesday + 14 calendar days.
        month_start = period.to_timestamp()
        settlement = month_start + pd.Timedelta(days=(2 - month_start.weekday()) % 7 + 14)
        if settlement in month_dates:
            settlement_pos = int(month_dates.get_loc(settlement))
            settlement_and_prior2 = month_dates[max(0, settlement_pos - 2):settlement_pos + 1]
        else:
            # A calendar settlement can be a market holiday (2023-06-21 in
            # this sample).  There is no settlement-day campaign to classify,
            # so retain the two *observed* trading dates before its anchor.
            settlement_and_prior2 = month_dates[month_dates < settlement][-2:]
        this_dates = dates.loc[index]
        result.loc[index] = np.where(
            this_dates.isin(settlement_and_prior2),
            "settlement_day_and_prior_2_trading_days",
            np.where(this_dates > settlement, "after_settlement_rest_of_month", "other"),
        )
    return result


def bucket_summary(blocked: pd.DataFrame, column: str, order: list[str]) -> pd.DataFrame:
    total_count = len(blocked)
    total_net = float(blocked["campaign_net"].sum())
    grouped = (
        blocked.groupby(column, observed=False)
        .agg(blocked_campaign_count=("campaign_id", "size"), blocked_campaign_net=("campaign_net", "sum"))
        .reindex(order, fill_value=0.0)
        .reset_index()
        .rename(columns={column: "bucket"})
    )
    grouped["share_blocked_count"] = grouped["blocked_campaign_count"] / total_count if total_count else np.nan
    grouped["share_blocked_campaign_net"] = (
        grouped["blocked_campaign_net"] / total_net if total_net else np.nan
    )
    return grouped


def blocked_campaign_buckets(panel: pd.DataFrame, threshold: float) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    active = panel.loc[panel["entry_ts"] >= START].copy()
    campaign_net = active.groupby("campaign_id", sort=True)["net"].sum().rename("campaign_net")
    cmd = active.loc[active["kind"].eq("Cmd")].copy()
    blocked = cmd.loc[
        pd.to_numeric(cmd["session_cum_vol_rel20"], errors="coerce").lt(threshold)
    ].copy()
    blocked = blocked.merge(campaign_net, on="campaign_id", how="left", validate="one_to_one")
    if blocked["campaign_net"].isna().any():
        raise AssertionError("missing campaign net")
    blocked["minutes_since_session_open"] = session_minutes(blocked)
    elapsed = blocked["minutes_since_session_open"]
    blocked["minutes_bucket"] = np.select(
        [elapsed < 15, elapsed < 60, elapsed <= 180, elapsed > 180],
        ["<15", "15_to_<60", "60_to_180", ">180"],
        default=None,
    )
    blocked["minutes_bucket"] = blocked["minutes_bucket"].astype("string")
    blocked["day_night_bucket"] = blocked["session"].astype("string")
    blocked["settlement_bucket"] = settlement_bucket(
        blocked["session_date"], active["session_date"]
    ).astype("string")
    if blocked[["minutes_bucket", "day_night_bucket", "settlement_bucket"]].isna().any().any():
        raise AssertionError("unclassified blocked campaign")
    minutes = bucket_summary(blocked, "minutes_bucket", ["<15", "15_to_<60", "60_to_180", ">180"])
    sessions = bucket_summary(blocked, "day_night_bucket", ["day", "night"])
    settlement = bucket_summary(
        blocked,
        "settlement_bucket",
        ["settlement_day_and_prior_2_trading_days", "after_settlement_rest_of_month", "other"],
    )
    return blocked, minutes, sessions, settlement


def money(value: float) -> str:
    return "NA" if not np.isfinite(value) else f"{value:,.0f}"


def pct(value: float) -> str:
    return "NA" if not np.isfinite(value) else f"{value * 100:.1f}%"


def table_rows(metrics_df: pd.DataFrame, labels: list[str], reference: str) -> list[str]:
    data = metrics_df.set_index("case")
    lines = []
    for label in labels:
        r = data.loc[label]
        annual = " | ".join(money(r[f"net_{year}"]) for year in YEARS)
        if label == reference:
            delta = "-"
            years = "-"
        else:
            delta = money(r[f"delta_total_vs_{reference}"])
            years = f"{int(r[f'years_beating_{reference}_count'])}/7"
        lines.append(
            f"| {label} | {annual} | {money(r.net_total)} | {delta} | {years} | "
            f"{money(r.daily_mdd)} | {money(r.net_2024_2026)} |"
        )
    return lines


def v29_table_rows(metrics_df: pd.DataFrame) -> list[str]:
    data = metrics_df.set_index("case")
    lines = []
    for label in ("v29", "v29_G2_p20"):
        r = data.loc[label]
        annual = " | ".join(money(r[f"net_{year}"]) for year in YEARS)
        vs_v29 = "-" if label == "v29" else money(r["delta_total_vs_v29"])
        wins = "-" if label == "v29" else f"{int(r['years_beating_v29_count'])}/7"
        lines.append(
            f"| {label} | {annual} | {money(r.net_total)} | {money(r.delta_total_vs_v28)} | "
            f"{vs_v29} | {wins} | {money(r.daily_mdd)} | {money(r.net_2024_2026)} |"
        )
    return lines


def report(thresholds: pd.DataFrame, metrics_df: pd.DataFrame, removal_df: pd.DataFrame,
           minute_df: pd.DataFrame, session_df: pd.DataFrame, settlement_df: pd.DataFrame) -> str:
    plateau_labels = [f"G2_p{int(q * 100):02d}" for q in PERCENTILES]
    v28 = metrics_df.set_index("case").loc["v28"]
    p20 = metrics_df.set_index("case").loc["G2_p20"]
    neighbours = [label for label in plateau_labels if label != "G2_p20"]
    plateau = all(
        metrics_df.set_index("case").loc[label, "net_total"] > v28.net_total
        and metrics_df.set_index("case").loc[label, "daily_mdd"] > v28.daily_mdd
        for label in neighbours
    )
    v29 = metrics_df.set_index("case").loc["v29"]
    v29g2 = metrics_df.set_index("case").loc["v29_G2_p20"]
    v29_helps = v29g2.net_total > v29.net_total and v29g2.daily_mdd > v29.daily_mdd
    blocked_total_count = int(minute_df["blocked_campaign_count"].sum())
    blocked_total_net = float(minute_df["blocked_campaign_net"].sum())
    late = minute_df.loc[minute_df["bucket"].eq(">180")].iloc[0]
    dominant_session = session_df.loc[session_df["share_blocked_count"].idxmax()]
    dominant_settlement_count = settlement_df.loc[settlement_df["share_blocked_count"].idxmax()]
    dominant_settlement_net = settlement_df.loc[settlement_df["blocked_campaign_net"].abs().idxmax()]
    lines = [
        "# G2 穩健性檢查（預先宣告、無調參）",
        "",
        "所有執行沿用 `results_ml_gate.md` 的 1 分鐘資料、成本（每 lot 440）、交易日定義與日頻 MDD；引擎僅透過既有的唯讀 `engine_ml_gate_wrapper.py` 呼叫。門檻只使用 v28 Cmd lots 在 2020-03-02 至 2023-12-31 的特徵分布一次凍結。",
        "",
        "## 凍結門檻",
        "",
        "| G2 case | percentile | usable Cmd lots | `session_cum_vol_rel20` threshold |",
        "|---|---:|---:|---:|",
    ]
    for r in thresholds.itertuples(index=False):
        lines.append(f"| {r.case} | {r.quantile:.0%} | {r.usable_cmd_lots:,} | {r.threshold:.8f} |")
    lines += [
        "",
        "## 1. v28 的 G2 門檻平台",
        "",
        "`vs v28` 與勝出年份皆以未加 gate 的 v28 為準；MDD 較大（較不負）為改善。",
        "",
        "| case | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | total | vs v28 | 勝出年份 | 日頻 MDD | 2024–2026 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *table_rows(metrics_df, ["v28", *plateau_labels], "v28"),
        "",
        "## 2. v29（`l_trailBase=3.5`）與凍結 G2-20%",
        "",
        "G2-20% 仍固定使用 0.72777104，沒有依 v29 lots 重算。`vs v28` 保留共同基準，`vs v29` 檢查 gate 對 v29 本身的增益。",
        "",
        "| case | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | total | vs v28 | vs v29 | 勝出年份 vs v29 | 日頻 MDD | 2024–2026 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *v29_table_rows(metrics_df),
        "",
        "## 3. G2-20% 直接封鎖的 v28 Cmd campaign bucket check",
        "",
        f"下表的母體是 feature 值 < 0.72777104 的 v28 Cmd（每個 Cmd 對應一個 v28 campaign），共 {blocked_total_count:,} 個；`blocked campaign net` 是該 Cmd 所屬完整 v28 campaign 的淨利，而不是僅 Cmd lot 的淨利。合計為 {money(blocked_total_net)}。",
        "",
        "進場距 session open 以 Cmd 的 entry timestamp 計算；日盤 open=08:45、夜盤 open=前一日 15:00。邊界為 <15、[15,60)、[60,180]、>180 分鐘。結算分類按資料中可交易日：第三個星期三及前兩個交易日、結算後至月底、其他。2023-06-21 這個第三個星期三不在資料交易日；該月因此只標記其前兩個觀測交易日。",
        "",
        "### 距 session open",
        "",
        "| bucket | blocked campaign count | count share | blocked campaign net | net share |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in minute_df.itertuples(index=False):
        lines.append(f"| {r.bucket} | {int(r.blocked_campaign_count):,} | {pct(r.share_blocked_count)} | {money(r.blocked_campaign_net)} | {pct(r.share_blocked_campaign_net)} |")
    lines += [
        "",
        "### 日／夜盤",
        "",
        "| bucket | blocked campaign count | count share | blocked campaign net | net share |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in session_df.itertuples(index=False):
        lines.append(f"| {r.bucket} | {int(r.blocked_campaign_count):,} | {pct(r.share_blocked_count)} | {money(r.blocked_campaign_net)} | {pct(r.share_blocked_campaign_net)} |")
    lines += [
        "",
        "### 月結算距離",
        "",
        "| bucket | blocked campaign count | count share | blocked campaign net | net share |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in settlement_df.itertuples(index=False):
        lines.append(f"| {r.bucket} | {int(r.blocked_campaign_count):,} | {pct(r.share_blocked_count)} | {money(r.blocked_campaign_net)} | {pct(r.share_blocked_campaign_net)} |")
    plateau_text = "平台" if plateau else "尖峰"
    v29_text = "有幫助" if v29_helps else "沒有同時改善 total 與 MDD"
    lines += [
        "",
        "## 結論",
        "",
        f"G2-20% 判定為**{plateau_text}**：四個相鄰預先指定門檻（10%、15%、25%、30%）必須全部同時優於 v28 的 total 且 MDD 較佳；本次條件的結果為 {'全部成立' if plateau else '至少一個不成立'}。",
        f"對 v29，凍結 G2-20% **{v29_text}**（total {money(v29g2.net_total - v29.net_total)}、MDD 變動 {money(v29g2.daily_mdd - v29.daily_mdd)}）。",
        f"bucket 歸因：效果**主要集中在進場已超過 180 分鐘**，不是 session open：該 bucket 佔直接封鎖 campaign 的 {pct(late.share_blocked_count)}、封鎖 campaign 淨利的 {pct(late.share_blocked_campaign_net)}。但它不是日／夜或月結算 rollover 的單一現象：日／夜最大的 `{dominant_session.bucket}` 只有 {pct(dominant_session.share_blocked_count)}；結算計數最大的 `{dominant_settlement_count.bucket}` 為 {pct(dominant_settlement_count.share_blocked_count)}，而淨利絕對值最大的 `{dominant_settlement_net.bucket}` 為 {pct(dominant_settlement_net.share_blocked_campaign_net)}。",
        "",
        "## 可稽核輸出",
        "",
        "`mlg2_thresholds.csv`、`mlg2_metrics.csv`、`mlg2_daily_pnl.csv`、`mlg2_removal_audit.csv`、`mlg2_blocked_campaigns.csv`、三個 `mlg2_bucket_*.csv`、`mlg2_reproduction.csv` 與各 case 的 `mlg2_trades_*.csv`。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    for path in (DATA, PANEL, PREVIOUS_V28, PREVIOUS_G2, PREVIOUS_V29):
        if not path.exists():
            raise FileNotFoundError(f"required input missing: {path}")
    panel = pd.read_csv(PANEL, parse_dates=["entry_ts", "exit_ts", "session_date"])
    thresholds = frozen_thresholds(panel)
    threshold_map = dict(zip(thresholds["case"], thresholds["threshold"], strict=True))

    cases: dict[str, pd.DataFrame] = {}
    cases["v28"] = run_engine("v28", LIVE_V28)
    for label, threshold in threshold_map.items():
        cases[label] = run_engine(
            label,
            {**LIVE_V28, "opt_ml_gate": {"variant": "G2", "session_cum_vol_rel20_threshold": threshold}},
        )
    cases["v29"] = run_engine("v29", LIVE_V29)
    cases["v29_G2_p20"] = run_engine(
        "v29_G2_p20",
        {**LIVE_V29, "opt_ml_gate": {"variant": "G2", "session_cum_vol_rel20_threshold": FROZEN_20}},
    )

    # Reproduce both previously archived baselines before writing new outputs.
    prior_v28 = pd.read_csv(PREVIOUS_V28, parse_dates=["entry_ts", "exit_ts"])
    prior_g2 = pd.read_csv(PREVIOUS_G2, parse_dates=["entry_ts", "exit_ts"])
    prior_v29 = pd.read_csv(PREVIOUS_V29, parse_dates=["entry_ts", "exit_ts"])
    assert_frame_equal(canonical(cases["v28"]), canonical(prior_v28), check_dtype=False, check_exact=True)
    assert_frame_equal(canonical_without_case(cases["G2_p20"]), canonical_without_case(prior_g2), check_dtype=False, check_exact=True)
    assert_frame_equal(canonical_without_case(cases["v29"]), canonical_without_case(prior_v29), check_dtype=False, check_exact=True)

    metric_rows: list[dict[str, Any]] = []
    daily_rows: list[pd.DataFrame] = []
    for label, trades in cases.items():
        row, daily = metrics(trades, label)
        metric_rows.append(row)
        daily_rows.append(daily)
    metrics_df = pd.DataFrame(metric_rows)
    rows = {r["case"]: r for r in metric_rows}
    for label in metrics_df["case"]:
        comparison = annual_comparison(rows[label], rows["v28"], "v28")
        for key, value in comparison.items():
            metrics_df.loc[metrics_df["case"].eq(label), key] = value
    for label in ("v29", "v29_G2_p20"):
        comparison = annual_comparison(rows[label], rows["v29"], "v29")
        for key, value in comparison.items():
            metrics_df.loc[metrics_df["case"].eq(label), key] = value
    daily_df = pd.concat(daily_rows, ignore_index=True)

    removal_df = pd.DataFrame([
        removal_audit(cases["v28"], cases[label], label)
        for label in [*threshold_map, "v29"]
    ] + [removal_audit(cases["v29"], cases["v29_G2_p20"], "v29_G2_p20")])
    blocked, minute_df, session_df, settlement_df = blocked_campaign_buckets(panel, FROZEN_20)
    direct_blocked_count = int(blocked.shape[0])
    removed_cmd_count = int(removal_df.loc[removal_df["case"].eq("G2_p20"), "removed_cmd_lots"].iloc[0])
    # A direct gate decision must remove its corresponding v28 Cmd.  More Cmd
    # lots can disappear as a downstream path consequence, so equality is not
    # assumed for the attribution universe.
    if direct_blocked_count > removed_cmd_count:
        raise AssertionError("direct blocked Cmd count exceeds removed Cmd count")

    reproduction = pd.DataFrame([{
        "v28_equals_previous_mlg": True,
        "g2_p20_equals_previous_mlg": True,
        "v29_equals_previous_br": True,
        "frozen_g2_p20_threshold": FROZEN_20,
        "direct_g2_p20_blocked_cmd_campaigns": direct_blocked_count,
        "all_g2_p20_removed_cmd_lots": removed_cmd_count,
        "net_cost_per_lot": NET_COST,
        "data": DATA.name,
    }])
    thresholds.to_csv(HERE / "mlg2_thresholds.csv", index=False, encoding="utf-8")
    metrics_df.to_csv(HERE / "mlg2_metrics.csv", index=False, encoding="utf-8")
    daily_df.to_csv(HERE / "mlg2_daily_pnl.csv", index=False, encoding="utf-8")
    removal_df.to_csv(HERE / "mlg2_removal_audit.csv", index=False, encoding="utf-8")
    blocked.to_csv(HERE / "mlg2_blocked_campaigns.csv", index=False, encoding="utf-8")
    minute_df.to_csv(HERE / "mlg2_bucket_minutes.csv", index=False, encoding="utf-8")
    session_df.to_csv(HERE / "mlg2_bucket_day_night.csv", index=False, encoding="utf-8")
    settlement_df.to_csv(HERE / "mlg2_bucket_settlement.csv", index=False, encoding="utf-8")
    reproduction.to_csv(HERE / "mlg2_reproduction.csv", index=False, encoding="utf-8")
    for label, trades in cases.items():
        trades.to_csv(HERE / f"mlg2_trades_{label}.csv", index=False, encoding="utf-8")
    (HERE / "results_ml_gate2.md").write_text(
        report(thresholds, metrics_df, removal_df, minute_df, session_df, settlement_df),
        encoding="utf-8",
    )
    print(metrics_df.to_string(index=False))
    print("blocked campaigns:", len(blocked))


if __name__ == "__main__":
    main()
