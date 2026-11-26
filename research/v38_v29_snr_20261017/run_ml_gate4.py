"""Frozen Gate 4: H1/H4 plateaus plus their predeclared combinations."""
from __future__ import annotations

import gc
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

import engine_ml_gate4_wrapper as mlg

HERE = Path(__file__).resolve().parent
DATA, PANEL = HERE / "mxf_1min_2020_20261029.csv", HERE / "ml_features_panel.csv"
START, CAL_END, END = pd.Timestamp("2020-03-02"), pd.Timestamp("2023-12-31 23:59:59.999999999"), pd.Timestamp("2026-10-29")
YEARS, G2 = tuple(range(2020, 2027)), 0.7277710401830155
NET_COST = 2 * (40 - mlg.COMMISSION) + 2 * 4 * mlg.POINT_VALUE
V28 = {**mlg.P, "opt_stale_hr": 10, "opt_cooldown_min": 30, "opt_short_pyramid_cap_mode": "hour4"}
V29 = {**V28, "l_trailBase": 3.5, "l_trailBaseDay": 3.5, "l_trailBaseNight": 3.5}

SPECS = (
    ("H14_p20_H4p33", "H14", .20, .33, 2),
    ("H1_p10", "H1", .10, None, None), ("H1_p15", "H1", .15, None, None),
    ("H1_p20", "H1", .20, None, None), ("H1_p25", "H1", .25, None, None),
    ("H1_p30", "H1", .30, None, None),
    ("H4_p25", "H4", None, .25, 2), ("H4_p33", "H4", None, .33, 2),
    ("H4_p40", "H4", None, .40, 2), ("H4_strict_p33", "H4", None, .33, 3),
    ("H14_p15_H4p25", "H14", .15, .25, 2), ("H14_p25_H4p40", "H14", .25, .40, 2),
)


def q(qv: float) -> str:
    return f"p{int(round(qv * 100)):02d}"


def ledger(raw: pd.DataFrame, case: str) -> pd.DataFrame:
    raw = raw.copy()
    raw["entry_ts"], raw["exit_ts"] = pd.to_datetime(raw["entry_ts"]), pd.to_datetime(raw["exit_ts"])
    raw["net"], raw["case"] = raw["pnl"].astype(float) - NET_COST, case
    return raw


def canonical(x: pd.DataFrame) -> pd.DataFrame:
    cols = ["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl", "net"]
    x = x.loc[:, cols].copy()
    x["entry_ts"], x["exit_ts"] = pd.to_datetime(x["entry_ts"]), pd.to_datetime(x["exit_ts"])
    return x.sort_values(cols, kind="mergesort").reset_index(drop=True)


def run(case: str, p: dict[str, Any]) -> pd.DataFrame:
    data = mlg.load_1min(DATA)
    try:
        return ledger(mlg.run(data, p=p, intrabar_mode="1min"), case)
    finally:
        del data
        gc.collect()


def thresholds() -> tuple[dict[str, float], pd.DataFrame]:
    panel = pd.read_csv(PANEL, parse_dates=["entry_ts"])
    panel = panel.loc[panel.entry_ts.between(START, CAL_END, inclusive="both")]
    out, rows = {}, []

    def add(scope: str, kinds: list[str], feature: str, quant: float, key: str) -> None:
        values = pd.to_numeric(panel.loc[panel.kind.isin(kinds), feature], errors="coerce").dropna()
        out[key] = float(values.quantile(quant))
        rows.append(dict(threshold_key=key, scope=scope, feature=feature, quantile=quant,
                         calibration_start=START, calibration_end=CAL_END, usable_lots=len(values), threshold=out[key]))

    add("Cmd", ["Cmd"], "session_cum_vol_rel20", .20, "G2_cmd_vol_p20")
    for pct in (.10, .15, .20, .25, .30):
        add("Cmd", ["Cmd"], "atr5_pct", pct, f"H1_cmd_atr5_pct_{q(pct)}")
    for pct in (.25, .33, .40):
        for feature, prefix in (("session_cum_vol_rel20", "H4_addg_vol"), ("er5_48", "H4_addg_er5_48"), ("atr5_pct", "H4_addg_atr5_pct")):
            add("Add/G", ["Add", "G"], feature, pct, f"{prefix}_{q(pct)}")
    frozen = {"G2_cmd_vol_p20": G2, "H1_cmd_atr5_pct_p20": .00058451066346192,
              "H4_addg_vol_p33": .8709270767561594, "H4_addg_er5_48_p33": .238412717117202,
              "H4_addg_atr5_pct_p33": .000797024364832677}
    for key, value in frozen.items():
        if not np.isclose(out[key], value, rtol=0, atol=5e-9):
            raise AssertionError(f"frozen threshold drift: {key}")
    return out, pd.DataFrame(rows)


def gate(spec: tuple[str, str, float | None, float | None, int | None], th: dict[str, float]) -> dict[str, Any]:
    _, kind, h1, h4, score = spec
    args: dict[str, Any] = {"variant": kind, "session_cum_vol_rel20_threshold": G2}
    if kind in ("H1", "H14"):
        args["cmd_atr5_pct_threshold"] = th[f"H1_cmd_atr5_pct_{q(h1)}"]
    if kind in ("H4", "H14"):
        args.update(chop_session_cum_vol_rel20_threshold=th[f"H4_addg_vol_{q(h4)}"],
                    er5_48_threshold=th[f"H4_addg_er5_48_{q(h4)}"],
                    addg_atr5_pct_threshold=th[f"H4_addg_atr5_pct_{q(h4)}"], chop_score_min=score)
    return args


def daynet(trades: pd.DataFrame) -> pd.Series:
    x = trades.loc[trades.exit_ts >= START].copy()
    x["day"] = x.exit_ts.dt.normalize() + pd.to_timedelta((x.exit_ts.dt.hour >= 15).astype(int), unit="D")
    return x.groupby("day").net.sum().sort_index()


def mdd(day: pd.Series) -> float:
    return float((day.cumsum() - day.cumsum().cummax()).min()) if len(day) else 0.


def metrics(trades: pd.DataFrame, case: str) -> tuple[dict[str, Any], pd.DataFrame]:
    day = daynet(trades)
    annual = day.groupby(day.index.year).sum()
    last12, last3 = day.loc[day.index > END - pd.DateOffset(months=12)], day.loc[day.index > END - pd.DateOffset(months=3)]
    out: dict[str, Any] = dict(case=case, net_total=float(day.sum()), daily_mdd=mdd(day),
                               lots=int((trades.exit_ts >= START).sum()),
                               net_2024_2026=float(sum(annual.get(y, 0.) for y in (2024, 2025, 2026))),
                               net_last_12m_2025_10_30_2026_10_29=float(last12.sum()), daily_mdd_last_12m_2025_10_30_2026_10_29=mdd(last12),
                               net_last_3m_2026_07_30_2026_10_29=float(last3.sum()), daily_mdd_last_3m_2026_07_30_2026_10_29=mdd(last3),
                               net_aug_2026=float(day.loc[day.index.to_period("M") == pd.Period("2026-08")].sum()))
    out["net_mdd"] = out["net_total"] / abs(out["daily_mdd"]) if out["daily_mdd"] else np.nan
    out.update({f"net_{y}": float(annual.get(y, 0.)) for y in YEARS})
    return out, day.rename("net").reset_index().assign(case=case)


def compare(row: dict[str, Any], base: dict[str, Any]) -> None:
    wins = []
    for year in YEARS:
        row[f"delta_{year}_vs_v29_G2"] = row[f"net_{year}"] - base[f"net_{year}"]
        if row[f"delta_{year}_vs_v29_G2"] > 0:
            wins.append(year)
    row["delta_total_vs_v29_G2"] = row["net_total"] - base["net_total"]
    row["delta_2024_2026_vs_v29_G2"] = row["net_2024_2026"] - base["net_2024_2026"]
    row["years_beating_v29_G2"], row["years_beating_v29_G2_count"] = ",".join(map(str, wins)) if wins else "none", len(wins)
    row["daily_mdd_abs_ratio_to_v29_G2"] = abs(row["daily_mdd"]) / abs(base["daily_mdd"])


def fixed(row: dict[str, Any], base: dict[str, Any]) -> tuple[str, str]:
    checks = (row["net_total"] > base["net_total"], row["years_beating_v29_G2_count"] >= 5,
              abs(row["daily_mdd"]) <= abs(base["daily_mdd"]) * 1.10, row["net_2024_2026"] >= base["net_2024_2026"])
    return ("PASS" if all(checks) else "FAIL",
            f"總淨利{'是' if checks[0] else '否'}；年度勝出 {row['years_beating_v29_G2_count']}/7；MDD 10%限制{'是' if checks[2] else '否'}；2024-2026 {'是' if checks[3] else '否'}")


def precision(ref: pd.DataFrame, cur: pd.DataFrame, refcase: str, case: str, basis: str) -> dict[str, Any]:
    key = ["side", "kind", "entry_ts", "entry_px"]
    def keyed(x: pd.DataFrame) -> pd.DataFrame:
        x = x.loc[x.exit_ts >= START, key + ["net"]].copy()
        x["occurrence"] = x.groupby(key, sort=False).cumcount()
        return x
    refx, curx = keyed(ref), keyed(cur)
    removed = refx.merge(curx[key + ["occurrence"]], on=key + ["occurrence"], how="left", indicator=True)
    removed = removed.loc[removed._merge.eq("left_only")]
    winners, losers = removed.loc[removed.net > 0, "net"], removed.loc[removed.net < 0, "net"]
    return dict(precision_basis=basis, reference_case=refcase, case=case, removed_lots=len(removed),
                removed_winning_lots=len(winners), removed_winning_lot_profit=float(winners.sum()),
                removed_losing_lots=len(losers), removed_losing_lot_loss=float(-losers.sum()),
                removed_net=float(removed.net.sum()), removed_loss_to_profit_ratio=float(-losers.sum()/winners.sum()) if len(winners) else np.nan)


def h14_check(data: pd.DataFrame, h14: str, h1: str, h4: str) -> dict[str, Any]:
    x = data.set_index("case")
    a, one, four = x.loc[h14], x.loc[h1], x.loc[h4]
    total_ok = a.net_total > max(one.net_total, four.net_total)
    limit = min(abs(one.daily_mdd), abs(four.daily_mdd)) * 1.05
    mdd_ok = abs(a.daily_mdd) <= limit
    w1, w4 = sum(a[f"net_{y}"] > one[f"net_{y}"] for y in YEARS), sum(a[f"net_{y}"] > four[f"net_{y}"] for y in YEARS)
    years_ok = w1 >= 4 and w4 >= 4
    return dict(test=f"{h14} adds value", h14_case=h14, h1_case=h1, h4_case=h4, h14_total=a.net_total,
                max_component_total=max(one.net_total, four.net_total), total_ok=total_ok, h14_daily_mdd_abs=abs(a.daily_mdd),
                mdd_limit_abs=limit, mdd_ok=mdd_ok, h14_years_beating_h1=w1, h14_years_beating_h4=w4,
                years_ok=years_ok, verdict="PASS" if total_ok and mdd_ok and years_ok else "FAIL")


def cash(x: float) -> str:
    return "NA" if not np.isfinite(x) else f"{x:,.0f}"


def metric_table(data: pd.DataFrame, labels: list[str]) -> list[str]:
    x, lines = data.set_index("case"), []
    for case in labels:
        r, years = x.loc[case], " | ".join(cash(x.loc[case, f"net_{y}"]) for y in YEARS)
        verdict = "參考" if r.fixed_verdict == "REFERENCE" else r.fixed_verdict
        lines.append(f"| {case} | {years} | {cash(r.net_total)} | {cash(r.daily_mdd)} | {r.net_mdd:.2f} | {int(r.lots):,} | {cash(r.delta_total_vs_v29_G2)} | {int(r.years_beating_v29_G2_count)}/7 | {cash(r.net_2024_2026)} | {cash(r.net_last_12m_2025_10_30_2026_10_29)}/{cash(r.daily_mdd_last_12m_2025_10_30_2026_10_29)} | {cash(r.net_last_3m_2026_07_30_2026_10_29)}/{cash(r.daily_mdd_last_3m_2026_07_30_2026_10_29)} | {cash(r.net_aug_2026)} | {verdict} |")
    return lines


def report(th: pd.DataFrame, data: pd.DataFrame, prec: pd.DataFrame, verdicts: pd.DataFrame, rep: pd.DataFrame) -> str:
    h1p, h4p = verdicts.loc[verdicts.test.eq("H1 plateau"), "verdict"].iat[0], verdicts.loc[verdicts.test.eq("H4 plateau"), "verdict"].iat[0]
    h14p = verdicts.loc[verdicts.test.eq("v29_H14_p20_H4p33 adds value"), "verdict"].iat[0]
    passed = data.loc[data.case.str.startswith("v29_") & data.fixed_verdict.eq("PASS"), "case"].tolist()
    header = "| case | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | total | 日 MDD | net/MDD | lots | vs v29+G2 | 勝出年 | 2024--26 | 近12月 net/MDD | 近3月 net/MDD | 2026-08 | 裁決 |"
    rule = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"
    lines = ["# ML Gate 4：H1/H4 組合與門檻平臺", "", f"## 裁決：H1 平臺 {h1p}；H4 平臺 {h4p}；中心 H14 增值檢查 {h14p}。",
             "", f"v29 固定規則 PASS：{'、'.join(passed) if passed else '無'}。基準固定為 v29+G2；PASS 同時要求總淨利較高、至少 5/7 年勝出、日結算 MDD 不比基準惡化超過 10%，且 2024--2026 小計不低於基準。沒有與買進持有比較。",
             "", "H1 平臺須 p10、p15、p25、p30 全 PASS；H4 平臺須 p25、p40 均 PASS。H14 增值須高於相配 H1/H4 較高總淨利、MDD 絕對值不超過兩者較小者 1.05 倍，並分別至少 4/7 年勝過 H1 與 H4。",
             "", "所有特徵使用已收盤的 5 分鐘決策 bar，下一根開盤成交；成本、日結算 MDD、v28 校準樣本與 Gate 3 相同。",
             "", "## 凍結門檻（v28 lots，2020-03-02--2023-12-31）", "", "| 用途 | 樣本 | 特徵 | 分位數 | 可用 lots | 門檻 |", "|---|---|---|---:|---:|---:|"]
    for r in th.itertuples(index=False):
        lines.append(f"| {r.threshold_key} | {r.scope} | {r.feature} | {r.quantile:.0%} | {int(r.usable_lots):,} | {r.threshold:.8f} |")
    v29, v28 = ["v29_G2"] + [f"v29_{s[0]}" for s in SPECS], ["v28_G2"] + [f"v28_{s[0]}" for s in SPECS]
    lines += ["", "## v29 主結果（淨利；MDD 為負值）", "", header, rule, *metric_table(data, v29),
              "", "## v28 參考結果", "", "v28 是版本參考；相對數值仍以固定 v29+G2 計算，因此不給固定 PASS/FAIL。", "", header, rule, *metric_table(data, v28),
              "", "## 平臺與 H14 增值檢查（v29）", "", "| 檢查 | 裁決 | 摘要 |", "|---|---|---|"]
    for r in verdicts.itertuples(index=False):
        if r.test == "H1 plateau": desc = "p10、p15、p25、p30 必須全 PASS"
        elif r.test == "H4 plateau": desc = "p25、p40 必須均 PASS"
        else: desc = f"總淨利 {cash(r.h14_total)} vs {cash(r.max_component_total)}；MDD |{cash(r.h14_daily_mdd_abs)}|/限額 {cash(r.mdd_limit_abs)}；年度勝出 H1 {int(r.h14_years_beating_h1)}/7、H4 {int(r.h14_years_beating_h4)}/7"
        lines.append(f"| {r.test} | {r.verdict} | {desc} |")
    lines += ["", "## 被移除 lots 的精確度檢查", "", "v29 以固定 v29+G2 比對；v28 參考以同版 v28+G2 比對，以免把版本差異誤當成濾網效果。移除獲利/虧損分別是原本正/負淨利 lots 的金額；這是 ledger 比對，後續倉位路徑可能改變。",
              "", "| case | 參考 | 移除 lots | 移除獲利 lots/金額 | 移除虧損 lots/金額 | 移除淨額 | 虧損/獲利 |", "|---|---|---:|---:|---:|---:|---:|"]
    for r in prec.itertuples(index=False):
        lines.append(f"| {r.case} | {r.reference_case} | {int(r.removed_lots):,} | {int(r.removed_winning_lots):,}/{cash(r.removed_winning_lot_profit)} | {int(r.removed_losing_lots):,}/{cash(r.removed_losing_lot_loss)} | {cash(r.removed_net)} | {r.removed_loss_to_profit_ratio:.2f} |")
    assertions = "；".join(f"{c}={bool(rep.iloc[0][c])}" for c in rep.columns if c.endswith("_equals_gate3"))
    lines += ["", "## 重現檢查", "", f"Gate 3 逐 lot assert：{assertions}。資料截至 {rep.iloc[0].data_end}；每 lot 淨成本 {cash(rep.iloc[0].net_cost_per_lot)}。完整數值與每日序列見 mlg4_*.csv。"]
    return "\n".join(lines) + "\n"


def main() -> None:
    for path in (DATA, PANEL):
        if not path.exists(): raise FileNotFoundError(path)
    th, thdf = thresholds()
    todo = [("v28_G2", {**V28, "opt_ml_gate": {"variant": "G2", "session_cum_vol_rel20_threshold": G2}}),
            ("v29_G2", {**V29, "opt_ml_gate": {"variant": "G2", "session_cum_vol_rel20_threshold": G2}})]
    for version, params in (("v28", V28), ("v29", V29)):
        todo.extend((f"{version}_{s[0]}", {**params, "opt_ml_gate": gate(s, th)}) for s in SPECS)
    cases = {}
    for case, params in todo:
        trade_path = HERE / f"mlg4_trades_{case}.csv"
        if trade_path.exists():
            print(f"reusing {case}", flush=True)
            cases[case] = pd.read_csv(trade_path, parse_dates=["entry_ts", "exit_ts"])
        else:
            print(f"running {case}", flush=True)
            cases[case] = run(case, params)
            cases[case].to_csv(trade_path, index=False, encoding="utf-8")
    prior = {"v28_G2": "v28_G2", "v29_G2": "v29_G2", "v28_H1_p20": "v28_H1", "v29_H1_p20": "v29_H1", "v28_H4_p33": "v28_H4", "v29_H4_p33": "v29_H4"}
    reproduction: dict[str, Any] = dict(g2_cmd_vol_p20=th["G2_cmd_vol_p20"], h1_cmd_atr5_pct_p20=th["H1_cmd_atr5_pct_p20"], h4_addg_vol_p33=th["H4_addg_vol_p33"], h4_addg_er5_48_p33=th["H4_addg_er5_48_p33"], h4_addg_atr5_pct_p33=th["H4_addg_atr5_pct_p33"], net_cost_per_lot=NET_COST, data=DATA.name, data_end=END.date().isoformat())
    for ours, old in prior.items():
        priorfile = HERE / f"mlg3_trades_{old}.csv"
        if not priorfile.exists(): raise FileNotFoundError(priorfile)
        assert_frame_equal(canonical(cases[ours]), canonical(pd.read_csv(priorfile, parse_dates=["entry_ts", "exit_ts"])), check_dtype=False, check_exact=True)
        reproduction[f"{ours}_equals_gate3"] = True
    rows, daily = zip(*(metrics(trades, case) for case, trades in cases.items()))
    rows, base = list(rows), next(r for r in rows if r["case"] == "v29_G2")
    for r in rows:
        compare(r, base)
        r["fixed_verdict"], r["fixed_verdict_detail"] = fixed(r, base) if r["case"].startswith("v29_") and r["case"] != "v29_G2" else ("REFERENCE", "v28 為參考或為基準")
    mdf, ddf = pd.DataFrame(rows), pd.concat(daily, ignore_index=True)
    precision_rows = [precision(cases[f"{v}_G2"], cases[f"{v}_{s[0]}"], f"{v}_G2", f"{v}_{s[0]}", "fixed_v29_G2" if v == "v29" else "same_version_v28_G2") for v in ("v28", "v29") for s in SPECS]
    pdf = pd.DataFrame(precision_rows)
    indexed = mdf.set_index("case")
    verdict_rows = [dict(test="H1 plateau", verdict="PASS" if indexed.loc[[f"v29_H1_{q(x)}" for x in (.10, .15, .25, .30)], "fixed_verdict"].eq("PASS").all() else "FAIL"),
                    dict(test="H4 plateau", verdict="PASS" if indexed.loc[[f"v29_H4_{q(x)}" for x in (.25, .40)], "fixed_verdict"].eq("PASS").all() else "FAIL"),
                    h14_check(mdf, "v29_H14_p20_H4p33", "v29_H1_p20", "v29_H4_p33"),
                    h14_check(mdf, "v29_H14_p15_H4p25", "v29_H1_p15", "v29_H4_p25"),
                    h14_check(mdf, "v29_H14_p25_H4p40", "v29_H1_p25", "v29_H4_p40")]
    vdf, rdf = pd.DataFrame(verdict_rows), pd.DataFrame([reproduction])
    for name, frame in (("mlg4_thresholds.csv", thdf), ("mlg4_metrics.csv", mdf), ("mlg4_daily_pnl.csv", ddf), ("mlg4_precision.csv", pdf), ("mlg4_verdicts.csv", vdf), ("mlg4_reproduction.csv", rdf)):
        frame.to_csv(HERE / name, index=False, encoding="utf-8")
    for case, trades in cases.items(): trades.to_csv(HERE / f"mlg4_trades_{case}.csv", index=False, encoding="utf-8")
    (HERE / "results_ml_gate4.md").write_text(report(thdf, mdf, pdf, vdf, rdf), encoding="utf-8")
    print(mdf.to_string(index=False)); print(vdf.to_string(index=False)); print("completed", flush=True)


if __name__ == "__main__":
    main()
