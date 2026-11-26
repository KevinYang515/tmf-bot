"""Run the pre-specified V38 bear-regime and sustained-range study.

All thresholds and all variants below are declared before the engine calls.
The study writes only UTF-8 report/CSV artefacts in this directory and never
modifies the read-only vendor engine.
"""
from __future__ import annotations

from multiprocessing import Pool
from pathlib import Path
from typing import Any
import sys

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

import engine_bear_range_wrapper as br


HERE = Path(__file__).resolve().parent
ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
import engine_v26_bbw as plain  # noqa: E402


DATA = HERE / "mxf_1min_2020_20261026.csv"
SAVED_LEDGER = HERE / "recent_20261022_trades.csv"
TV_EXPORT = HERE / "tv_exports" / "V38.0707_v27_Session_TAIFEX_MXF1!_2026-10-19_barclose_only.csv"
START = pd.Timestamp("2020-03-02")
REGIME_END = pd.Timestamp("2026-10-22")
SAVED_END = pd.Timestamp("2026-10-22 13:30:00")
YEARS = tuple(range(2020, 2027))
NET_COST = 2 * (40 - plain.COMMISSION) + 2 * 4 * plain.POINT_VALUE

# These are the already-live settings.  v29 is v28 with only its declared
# long Cmd trail base change, as used by the preceding validation studies.
LIVE_V27 = {"opt_stale_hr": 10, "opt_cooldown_min": 30}
LIVE_V28 = {**LIVE_V27, "opt_short_pyramid_cap_mode": "hour4"}
LIVE_V29 = {**LIVE_V28, "l_trailBase": 3.5}
FAMILIES: dict[str, dict[str, tuple[str, ...]]] = {
    "bear": {"definitions": ("BD1", "BD2"), "variants": ("BV1", "BV2", "BV3", "BV4")},
    "range": {"definitions": ("RD1", "RD2"), "variants": ("RV1", "RV2")},
}


def ledger(raw: pd.DataFrame, label: str) -> pd.DataFrame:
    out = raw.copy()
    out["entry_ts"] = pd.to_datetime(out["entry_ts"])
    out["exit_ts"] = pd.to_datetime(out["exit_ts"])
    out["net"] = out["pnl"].astype(float) - NET_COST
    out["case"] = label
    return out


def run_case(family: str, definition: str, variant: str) -> tuple[str, str, str, pd.DataFrame]:
    """Pool worker: load independently and execute exactly one declared case."""
    df1m = br.load_1min(DATA)
    raw = br.run(
        df1m,
        p={**LIVE_V28, "opt_bear_range": {
            "family": family, "definition": definition, "variant": variant,
        }},
        intrabar_mode="1min",
    )
    return family, definition, variant, ledger(raw, variant)


def trading_day(exits: pd.Series) -> pd.Series:
    exits = pd.to_datetime(exits)
    # 15:00–05:00 night-session exits belong to the following trading day.
    return exits.dt.normalize() + pd.to_timedelta((exits.dt.hour >= 15).astype(int), unit="D")


def daily_net(trades: pd.DataFrame) -> pd.Series:
    tr = trades.loc[trades["exit_ts"] >= START].copy()
    days = trading_day(tr["exit_ts"])
    return tr.assign(day=days).groupby("day")["net"].sum().sort_index()


def daily_mdd(day_pnl: pd.Series) -> float:
    equity = day_pnl.cumsum()
    return float((equity - equity.cummax()).min()) if len(equity) else 0.0


def metrics(trades: pd.DataFrame, family: str, definition: str, variant: str) -> tuple[dict[str, Any], pd.DataFrame]:
    tr = trades.loc[trades["exit_ts"] >= START].copy()
    day = daily_net(trades)
    annual = day.groupby(day.index.year).sum()
    mdd = daily_mdd(day)
    row: dict[str, Any] = {
        "family": family,
        "definition": definition,
        "variant": variant,
        "net_total": float(day.sum()),
        "daily_mdd": mdd,
        "net_mdd": float(day.sum() / abs(mdd)) if mdd else np.nan,
        "lots": int(len(tr)),
    }
    for year in YEARS:
        row[f"net_{year}"] = float(annual.get(year, 0.0))
    daily = day.rename("net").reset_index().assign(family=family, definition=definition, variant=variant)
    return row, daily


def with_lot_key(trades: pd.DataFrame) -> pd.DataFrame:
    out = trades.loc[trades.exit_ts >= START, ["side", "kind", "entry_ts", "entry_px", "net"]].copy()
    cols = ["side", "kind", "entry_ts", "entry_px"]
    out["occurrence"] = out.groupby(cols).cumcount()
    return out


def precision(baseline: pd.DataFrame, candidate: pd.DataFrame, family: str, definition: str,
              variant: str, base_row: dict[str, Any], candidate_row: dict[str, Any]) -> dict[str, Any]:
    base = with_lot_key(baseline)
    other = with_lot_key(candidate)
    key = ["side", "kind", "entry_ts", "entry_px", "occurrence"]
    removed = base.merge(other[key], on=key, how="left", indicator=True)
    removed = removed.loc[removed["_merge"] == "left_only"].copy()
    added = other.merge(base[key], on=key, how="left", indicator=True)
    added = added.loc[added["_merge"] == "left_only"].copy()
    beating_years = [year for year in YEARS if candidate_row[f"net_{year}"] > base_row[f"net_{year}"]]
    return {
        "family": family,
        "definition": definition,
        "variant": variant,
        "removed_lots": int(len(removed)),
        "removed_winning_lots": int((removed.net > 0).sum()),
        "removed_losing_lots": int((removed.net <= 0).sum()),
        "profit_removed_from_winners": float(removed.loc[removed.net > 0, "net"].sum()),
        "loss_removed_from_losers": float(-removed.loc[removed.net <= 0, "net"].sum()),
        "baseline_lot_net_removed": float(removed.net.sum()),
        "variant_only_lots": int(len(added)),
        "years_beating_v28": ",".join(map(str, beating_years)) if beating_years else "none",
        "years_beating_count": len(beating_years),
        "total_delta_vs_v28": float(candidate_row["net_total"] - base_row["net_total"]),
        "mdd_worse_pct": (abs(candidate_row["daily_mdd"]) / abs(base_row["daily_mdd"]) - 1.0)
        if base_row["daily_mdd"] else np.nan,
    }


def add_deltas(metrics_df: pd.DataFrame) -> pd.DataFrame:
    out = metrics_df.copy()
    for family, spec in FAMILIES.items():
        for definition in spec["definitions"]:
            selector = (out.family == family) & (out.definition == definition)
            base = out.loc[selector & (out.variant == "v28")].iloc[0]
            for year in YEARS:
                out.loc[selector, f"delta_{year}_vs_v28"] = out.loc[selector, f"net_{year}"] - base[f"net_{year}"]
            out.loc[selector, "delta_total_vs_v28"] = out.loc[selector, "net_total"] - base["net_total"]
    return out


def regime_outputs(daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    sample = daily.loc[daily.date.between(START, REGIME_END)].copy()
    rows: list[dict[str, Any]] = []
    for family, definitions in (("bear", ("BD1", "BD2")), ("range", ("RD1", "RD2"))):
        for definition in definitions:
            for year in YEARS:
                section = sample.loc[sample.date.dt.year == year]
                state_days = int(section[definition].sum())
                rows.append({
                    "family": family,
                    "definition": definition,
                    "year": year,
                    "days": int(len(section)),
                    "state_days": state_days,
                    "state_pct": float(state_days / len(section) * 100) if len(section) else np.nan,
                })
    thresholds = pd.DataFrame([
        {"definition": "RD1", "calibration_start": "2010-01-01", "calibration_end": "2019-12-31",
         "quantile": 0.33, "threshold": float(daily["RD1_threshold"].iloc[0]), "measure": "abs(MA200-MA200[t-60])/MA200"},
        {"definition": "RD2", "calibration_start": "2010-01-01", "calibration_end": "2019-12-31",
         "quantile": 0.33, "threshold": float(daily["RD2_threshold"].iloc[0]), "measure": "ER60"},
    ])
    return pd.DataFrame(rows), thresholds


def tv_comparison(v27: pd.DataFrame) -> pd.DataFrame:
    engine = metrics(v27, "baseline", "baseline", "v27")[0]
    if not TV_EXPORT.exists():
        raise FileNotFoundError(f"missing TV export: {TV_EXPORT}")
    tv = pd.read_csv(TV_EXPORT)
    type_col = "類型"
    time_col = "日期和時間"
    pnl_col = "淨損益 TWD"
    missing = [c for c in (type_col, time_col, pnl_col) if c not in tv.columns]
    if missing:
        raise ValueError(f"TV export columns missing: {missing}")
    # TradingView exports can append non-trade/footer rows (for example an
    # opening-balance marker); they have no parseable timestamp and are not
    # part of the exit-ledger aggregation.
    tv[time_col] = pd.to_datetime(tv[time_col], errors="coerce")
    exits = tv.loc[tv[type_col].astype(str).str.contains("出場", na=False) & tv[time_col].notna()].copy()
    exits[pnl_col] = pd.to_numeric(exits[pnl_col], errors="coerce")
    rows = []
    for year in (2022, 2023):
        rows.append({
            "year": year,
            "engine_v27_net_1min": engine[f"net_{year}"],
            "tv_v27_net_barclose": float(exits.loc[exits[time_col].dt.year == year, pnl_col].sum()),
            "engine_minus_tv": engine[f"net_{year}"] - float(exits.loc[exits[time_col].dt.year == year, pnl_col].sum()),
            "tv_exit_rows": int((exits[time_col].dt.year == year).sum()),
        })
    return pd.DataFrame(rows)


def verdicts(metrics_df: pd.DataFrame, precision_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for family, spec in FAMILIES.items():
        for variant in spec["variants"]:
            per_definition = []
            for definition in spec["definitions"]:
                metric = metrics_df.loc[
                    (metrics_df.family == family) & (metrics_df.definition == definition) & (metrics_df.variant == variant)
                ].iloc[0]
                prec = precision_df.loc[
                    (precision_df.family == family) & (precision_df.definition == definition) & (precision_df.variant == variant)
                ].iloc[0]
                total_ok = bool(metric.delta_total_vs_v28 > 0)
                years_ok = bool(prec.years_beating_count >= 5)
                mdd_ok = bool(prec.mdd_worse_pct <= 0.10)
                bear_2022_ok = bool(metric.delta_2022_vs_v28 > 0) if family == "bear" else True
                passed = total_ok and years_ok and mdd_ok and bear_2022_ok
                per_definition.append((definition, passed, total_ok, years_ok, mdd_ok, bear_2022_ok, prec))
            pass_count = sum(bool(x[1]) for x in per_definition)
            overall = "PASS" if pass_count == len(per_definition) else "BORDERLINE" if pass_count == 1 else "FAIL"
            row: dict[str, Any] = {"family": family, "variant": variant, "pass_definitions": pass_count,
                                   "overall_verdict": overall}
            for definition, passed, total_ok, years_ok, mdd_ok, bear_2022_ok, prec in per_definition:
                row[f"{definition}_pass"] = passed
                row[f"{definition}_total_ok"] = total_ok
                row[f"{definition}_years_beating"] = int(prec.years_beating_count)
                row[f"{definition}_years_ok"] = years_ok
                row[f"{definition}_mdd_worse_pct"] = float(prec.mdd_worse_pct)
                row[f"{definition}_mdd_ok"] = mdd_ok
                if family == "bear":
                    row[f"{definition}_improves_2022"] = bear_2022_ok
            rows.append(row)
    return pd.DataFrame(rows)


def fmt_money(value: float) -> str:
    return "—" if not np.isfinite(value) else f"{value:,.0f}"


def fmt_pct(value: float) -> str:
    return "—" if not np.isfinite(value) else f"{value * 100:.1f}%"


def state_table(regime_df: pd.DataFrame, definition: str) -> list[str]:
    sub = regime_df.loc[regime_df.definition == definition]
    return [
        "| 年度 | 日數 | 狀態日數 | 佔比 |",
        "|---:|---:|---:|---:|",
        *[f"| {int(r.year)} | {int(r.days)} | {int(r.state_days)} | {r.state_pct:.2f}% |" for _, r in sub.iterrows()],
    ]


def metrics_table(rows: pd.DataFrame) -> list[str]:
    header = "| 組合 | " + " | ".join(str(y) for y in YEARS) + " | 合計 | 日PnL MDD | 淨利/MDD | 口數 |"
    divider = "|---|" + "---:|" * (len(YEARS) + 4)
    lines = [header, divider]
    for _, r in rows.iterrows():
        values = " | ".join(fmt_money(float(r[f"net_{year}"])) for year in YEARS)
        ratio = "—" if not np.isfinite(r.net_mdd) else f"{r.net_mdd:.2f}"
        lines.append(
            f"| {r.variant} | {values} | {fmt_money(float(r.net_total))} | {fmt_money(float(r.daily_mdd))} | {ratio} | {int(r.lots):,} |"
        )
    return lines


def report(metrics_df: pd.DataFrame, precision_df: pd.DataFrame, verdict_df: pd.DataFrame,
           regime_df: pd.DataFrame, thresholds: pd.DataFrame, tv_df: pd.DataFrame) -> str:
    base = metrics_df.loc[(metrics_df.family == "bear") & (metrics_df.definition == "BD1")]
    v27 = base.loc[base.variant == "v27"].iloc[0]
    v28 = base.loc[base.variant == "v28"].iloc[0]
    oos_years = (2020, 2021, 2022, 2023)
    oos_delta = sum(v28[f"net_{y}"] - v27[f"net_{y}"] for y in oos_years)
    oos_wins = sum(v28[f"net_{y}"] > v27[f"net_{y}"] for y in oos_years)
    oos_text = "仍勝過" if oos_delta > 0 else "未勝過"

    bear_cases = metrics_df.loc[(metrics_df.family == "bear") & (~metrics_df.variant.isin(["v27", "v28", "v29"]))]
    clean_bear = []
    for _, r in bear_cases.iterrows():
        other_ok = all(r[f"delta_{y}_vs_v28"] >= 0 for y in YEARS if y != 2022)
        if r.delta_2022_vs_v28 > 0 and other_ok:
            clean_bear.append(f"{r.definition}/{r.variant}")
    bear_pass = verdict_df.loc[(verdict_df.family == "bear") & (verdict_df.overall_verdict == "PASS"), "variant"].tolist()

    range_cases = metrics_df.loc[(metrics_df.family == "range") & (~metrics_df.variant.isin(["v27", "v28", "v29"]))]
    range_mdd_better = range_cases.loc[range_cases.daily_mdd.abs() < float(v28.daily_mdd.__abs__()), ["definition", "variant"]]
    range_mdd_labels = [f"{r.definition}/{r.variant}" for _, r in range_mdd_better.iterrows()]
    range_pass = verdict_df.loc[(verdict_df.family == "range") & (verdict_df.overall_verdict == "PASS"), "variant"].tolist()

    lines = [
        "# V38 v28：熊市參數與持續盤整金字塔研究",
        "",
        "## 先說結論",
        "",
        f"- **2020–2023 的 v28 對 v27：{oos_text}。** 四年合計差額為 {fmt_money(oos_delta)} 元，v28 在 {oos_wins}/4 年較佳；因此不能只憑 2024–2026 的結果判定 v28 在早期樣本也更好。",
        f"- **熊市模式：**完整 PASS 的變體為 {', '.join(bear_pass) if bear_pass else '無'}。2022 改善且其餘六年均未變差的組合為 {', '.join(clean_bear) if clean_bear else '無'}；所以熊市處理{'有' if clean_bear else '沒有'}證據能改善 2022 而不以其他年度為代價。",
        f"- **盤整模式：**完整 PASS 的變體為 {', '.join(range_pass) if range_pass else '無'}。日 MDD 較 v28 改善的定義/變體為 {', '.join(range_mdd_labels) if range_mdd_labels else '無'}；是否是有效地減少金字塔損害，仍以後面的移除贏家/輸家與固定 verdict 為準，而非只看口數下降。",
        "",
        "所有回測均為 1 分鐘 intrabar，淨利 = 引擎 pnl − 每口往返 440 元；夜盤 15:00 至隔日 05:00 的出場歸入下一交易日。熊市/盤整狀態在每根 5 分鐘訊號 bar 只讀取最近完成日盤的日資料 `(t − 13:45).normalize()`，不使用當日尚未完成的日線。Wrapper 關閉時，完整樣本結果已逐筆與原引擎一致；另以相同的 2024 起、2026-10-22 13:30 止輸入重跑 v28，逐筆比對 `recent_20261022_trades.csv`。",
        "",
        "## 基準：全樣本",
        "",
    ]
    lines.extend(metrics_table(base.loc[base.variant.isin(["v27", "v28", "v29"])]))
    lines += [
        "",
        "2020–2023 是 v28 相對 v27 的真正樣本外區段；上表與結論均使用全額新資料，而非只用 2024 以後。v29 = v28 + `l_trailBase=3.5`，僅供基準比較，熊市/盤整實驗的差額一律對 v28 計算。",
        "",
        "## 日線狀態與凍結門檻",
        "",
        "BD1：`close < MA200 且 MA200 < 20 日前 MA200`。BD2：收盤跌破前 120 日（不含當日）最低收盤時進入熊市；收盤高於 MA60 才離開。2022 的熊市比例如下，若比例不高亦會如實呈現。",
        "",
        "### BD1 熊市日比例",
        "",
    ]
    lines.extend(state_table(regime_df, "BD1"))
    lines += ["", "### BD2 熊市日比例", ""]
    lines.extend(state_table(regime_df, "BD2"))
    lines += [
        "",
        "RD1 的 `|MA200−MA200[t−60]|/MA200` 與 RD2 的 ER60 都只以 2010-01-01 至 2019-12-31 的日資料取第 33 百分位校準，門檻在回測前凍結：",
        "",
        "| 定義 | 訓練區間 | 分位數 | 凍結門檻 |",
        "|---|---|---:|---:|",
    ]
    for _, r in thresholds.iterrows():
        lines.append(
            f"| {r['definition']} | {r['calibration_start']} 至 {r['calibration_end']} | "
            f"{r['quantile']:.2f} | {r['threshold']:.8f} |"
        )
    lines += ["", "### RD1 盤整日比例", ""]
    lines.extend(state_table(regime_df, "RD1"))
    lines += ["", "### RD2 盤整日比例", ""]
    lines.extend(state_table(regime_df, "RD2"))

    lines += ["", "## 變體績效（差額以 v28 為準）", ""]
    for family, spec in FAMILIES.items():
        family_label = "熊市" if family == "bear" else "持續盤整"
        for definition in spec["definitions"]:
            lines += [f"### {definition}／{family_label}", ""]
            rows = metrics_df.loc[(metrics_df.family == family) & (metrics_df.definition == definition)].copy()
            order = ["v28", *spec["variants"], "v27", "v29"]
            rows["_order"] = pd.Categorical(rows.variant, categories=order, ordered=True)
            lines.extend(metrics_table(rows.sort_values("_order")))
            lines += ["", "年度差額（變體 − v28）：", "", "| 組合 | " + " | ".join(str(y) for y in YEARS) + " | 合計 |", "|---|" + "---:|" * (len(YEARS) + 1)]
            for _, r in rows.sort_values("_order").iterrows():
                if r.variant in ("v27", "v28", "v29"):
                    continue
                deltas = " | ".join(fmt_money(float(r[f"delta_{y}_vs_v28"])) for y in YEARS)
                lines.append(f"| {r.variant} | {deltas} | {fmt_money(float(r.delta_total_vs_v28))} |")
            lines.append("")

    lines += [
        "## 精確性檢查：相對 v28 被移除的 lot",
        "",
        "以 `(side, kind, entry_ts, entry_px, occurrence)` 對齊 lot。正確的減碼不應只是少做交易：被移除輸家的損失應能補償被移除贏家的利潤；`variant_only_lots` 顯示因路徑改變而新增、無法一對一配對的 lot。",
        "",
        "| 定義/變體 | 移除 lot | 移除贏家利潤 | 移除輸家損失 | 移除 lot 淨額 | 僅變體 lot | 勝 v28 年數 | MDD 變差 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, r in precision_df.iterrows():
        lines.append(
            f"| {r.definition}/{r.variant} | {int(r.removed_lots):,} | {fmt_money(float(r.profit_removed_from_winners))} | {fmt_money(float(r.loss_removed_from_losers))} | {fmt_money(float(r.baseline_lot_net_removed))} | {int(r.variant_only_lots):,} | {int(r.years_beating_count)} ({r.years_beating_v28}) | {fmt_pct(float(r.mdd_worse_pct))} |"
        )

    lines += [
        "",
        "## 預先固定的 verdict",
        "",
        "每個定義均須：總淨利大於 v28、7 年至少 5 年勝過 v28、日 MDD 不比 v28 差超過 10%；熊市變體另須改善 2022。兩個定義都通過才是 PASS，僅一個定義通過是 BORDERLINE，否則 FAIL。沒有事後調整門檻。",
        "",
        "| 類別 | 變體 | 通過定義數 | Verdict |",
        "|---|---|---:|---|",
    ]
    for _, r in verdict_df.iterrows():
        lines.append(f"| {'熊市' if r.family == 'bear' else '盤整'} | {r.variant} | {int(r.pass_definitions)}/2 | {r.overall_verdict} |")

    lines += [
        "",
        "## v27 2022/2023 與 TradingView bar-close 匯出的交叉檢查",
        "",
        "TV 僅加總 `類型` 含「出場」的 `淨損益 TWD`；引擎則是 1 分鐘 intrabar 並扣每口 440 元。因此兩者差異預期存在，僅作量級 sanity check。",
        "",
        "| 年度 | 引擎 v27 淨利（1 分鐘） | TV v27 淨利（bar-close） | 引擎−TV | TV 出場列 |",
        "|---:|---:|---:|---:|---:|",
    ]
    for _, r in tv_df.iterrows():
        lines.append(f"| {int(r.year)} | {fmt_money(float(r.engine_v27_net_1min))} | {fmt_money(float(r.tv_v27_net_barclose))} | {fmt_money(float(r.engine_minus_tv))} | {int(r.tv_exit_rows):,} |")

    lines += [
        "",
        "機器可讀結果：`br_metrics.csv`、`br_precision.csv`、`br_verdicts.csv`、`br_regime_daily.csv`、`br_regime_summary.csv`、`br_range_thresholds.csv`、`br_daily_pnl.csv`、`br_tv_compare.csv`，以及各基準與變體的 `br_trades_*.csv`。",
    ]
    return "\n".join(lines) + "\n"


def assert_baselines(df1m: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Assert wrapper-off equivalence and 2024+ reproduction before experiments."""
    raw_v28 = plain.run(df1m, p=LIVE_V28, intrabar_mode="1min")
    raw_off = br.run(df1m, p=LIVE_V28, intrabar_mode="1min")
    columns = list(raw_v28.columns)
    assert_frame_equal(raw_v28.reset_index(drop=True), raw_off[columns].reset_index(drop=True), check_exact=True)

    # The supplied reference was generated from the 2024+ input only, ending
    # at 2026-10-22 13:30.  Recreate exactly that input window for its ledger
    # assertion; the full 2020+ run legitimately has different inherited
    # campaign state during the first few 2024 sessions.
    recent_df1m = df1m.loc[
        (df1m["ts"] >= pd.Timestamp("2024-01-01")) & (df1m["ts"] <= SAVED_END)
    ].copy()
    raw_recent = plain.run(recent_df1m, p=LIVE_V28, intrabar_mode="1min")
    raw_recent_off = br.run(recent_df1m, p=LIVE_V28, intrabar_mode="1min")
    assert_frame_equal(raw_recent.reset_index(drop=True), raw_recent_off[columns].reset_index(drop=True), check_exact=True)

    saved = pd.read_csv(SAVED_LEDGER)
    saved = saved.loc[saved.v == "v28", columns].copy()
    current = raw_recent.copy()
    for column in ("entry_ts", "exit_ts"):
        saved[column] = pd.to_datetime(saved[column])
        current[column] = pd.to_datetime(current[column])
    assert_frame_equal(current.reset_index(drop=True), saved.reset_index(drop=True), check_exact=True)

    raw_v27 = plain.run(df1m, p=LIVE_V27, intrabar_mode="1min")
    raw_v29 = plain.run(df1m, p=LIVE_V29, intrabar_mode="1min")
    return ledger(raw_v27, "v27"), ledger(raw_v28, "v28"), ledger(raw_v29, "v29")


def main() -> None:
    for path in (DATA, SAVED_LEDGER, TV_EXPORT):
        if not path.exists():
            raise FileNotFoundError(f"required input missing: {path}")

    df1m = br.load_1min(DATA)
    v27, v28, v29 = assert_baselines(df1m)
    del df1m

    cases: dict[tuple[str, str, str], pd.DataFrame] = {}
    jobs = [(family, definition, variant)
            for family, spec in FAMILIES.items()
            for definition in spec["definitions"]
            for variant in spec["variants"]]
    with Pool(processes=3) as pool:
        for family, definition, variant, trades in pool.starmap(run_case, jobs):
            cases[(family, definition, variant)] = trades

    metric_rows: list[dict[str, Any]] = []
    daily_rows: list[pd.DataFrame] = []
    baseline_by_case: dict[tuple[str, str], dict[str, Any]] = {}
    for family, spec in FAMILIES.items():
        for definition in spec["definitions"]:
            for name, trades in (("v27", v27), ("v28", v28), ("v29", v29)):
                row, daily = metrics(trades, family, definition, name)
                metric_rows.append(row)
                daily_rows.append(daily)
                if name == "v28":
                    baseline_by_case[(family, definition)] = row
            for variant in spec["variants"]:
                row, daily = metrics(cases[(family, definition, variant)], family, definition, variant)
                metric_rows.append(row)
                daily_rows.append(daily)
    metrics_df = add_deltas(pd.DataFrame(metric_rows))
    daily_df = pd.concat(daily_rows, ignore_index=True)

    precision_rows = []
    for family, spec in FAMILIES.items():
        for definition in spec["definitions"]:
            base_row = baseline_by_case[(family, definition)]
            for variant in spec["variants"]:
                candidate_row = metrics_df.loc[
                    (metrics_df.family == family) & (metrics_df.definition == definition) & (metrics_df.variant == variant)
                ].iloc[0].to_dict()
                precision_rows.append(precision(v28, cases[(family, definition, variant)], family, definition,
                                                variant, base_row, candidate_row))
    precision_df = pd.DataFrame(precision_rows)
    verdict_df = verdicts(metrics_df, precision_df)

    daily_regime = br.daily_regime_table()
    regime_df, thresholds = regime_outputs(daily_regime)
    tv_df = tv_comparison(v27)

    # Exact numeric artefacts are kept separate from rounded Markdown tables.
    daily_regime.to_csv(HERE / "br_regime_daily.csv", index=False, encoding="utf-8-sig")
    regime_df.to_csv(HERE / "br_regime_summary.csv", index=False, encoding="utf-8-sig")
    thresholds.to_csv(HERE / "br_range_thresholds.csv", index=False, encoding="utf-8-sig")
    metrics_df.to_csv(HERE / "br_metrics.csv", index=False, encoding="utf-8-sig")
    precision_df.to_csv(HERE / "br_precision.csv", index=False, encoding="utf-8-sig")
    verdict_df.to_csv(HERE / "br_verdicts.csv", index=False, encoding="utf-8-sig")
    daily_df.to_csv(HERE / "br_daily_pnl.csv", index=False, encoding="utf-8-sig")
    tv_df.to_csv(HERE / "br_tv_compare.csv", index=False, encoding="utf-8-sig")
    for name, trades in (("v27", v27), ("v28", v28), ("v29", v29)):
        trades.to_csv(HERE / f"br_trades_{name}.csv", index=False, encoding="utf-8-sig")
    for (family, definition, variant), trades in cases.items():
        trades.to_csv(HERE / f"br_trades_{definition}_{variant}.csv", index=False, encoding="utf-8-sig")

    (HERE / "results_bear_range.md").write_text(
        report(metrics_df, precision_df, verdict_df, regime_df, thresholds, tv_df), encoding="utf-8"
    )
    print("bear/range study complete")
    print(verdict_df[["family", "variant", "overall_verdict"]].to_string(index=False))


if __name__ == "__main__":
    main()
