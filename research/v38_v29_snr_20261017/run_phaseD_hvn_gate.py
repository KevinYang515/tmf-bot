"""Run the exact predeclared Phase-D HVN-behind Add-gate grid."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from engine_v29_hvn_wrapper import load_1min, run


HERE = Path(__file__).resolve().parent
DATA_PATH = HERE / "mxf_1min_corrected_20261017.csv"
BASELINE_PATH = HERE / "trades_v29.csv"
FEATURE_PATH = HERE / "v29_features_trades.csv"
RESULTS_PATH = HERE / "results_phaseD.md"
TRADE_COLS = ["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl"]
H2 = pd.Timestamp("2025-04-01")
TRAIN_START = pd.Timestamp("2026-03-01")
TEST_START = pd.Timestamp("2026-06-01")
HOLDOUT_START = pd.Timestamp("2026-08-22")
V29 = {
    "opt_stale_hr": 10, "opt_cooldown_min": 30,
    "opt_short_pyramid_cap_mode": "hour4", "l_trailBase": 3.5,
}
VARIANTS = [
    ("pct_1.5_L", {"feature": "pct", "min_dist_atr": 1.5, "sides": ("L",)}),
    ("pct_2.5_L", {"feature": "pct", "min_dist_atr": 2.5, "sides": ("L",)}),
    ("pct_3.5_L", {"feature": "pct", "min_dist_atr": 3.5, "sides": ("L",)}),
    ("atr_0.5_L", {"feature": "atr", "min_dist_atr": 0.5, "sides": ("L",)}),
    ("atr_0.9_L", {"feature": "atr", "min_dist_atr": 0.9, "sides": ("L",)}),
    ("pct_2.5_LS", {"feature": "pct", "min_dist_atr": 2.5, "sides": ("L", "S")}),
]


def metric(trades: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {"n": 0, "wr": np.nan, "net": 0.0, "pf": np.nan, "mdd": 0.0,
                "gross_profit": 0.0, "gross_loss": 0.0}
    gp = float(trades.loc[trades.pnl > 0, "pnl"].sum())
    gl = float(-trades.loc[trades.pnl <= 0, "pnl"].sum())
    equity = trades.groupby("exit_ts", sort=True).pnl.sum().cumsum()
    return {
        "n": int(len(trades)), "wr": 100.0 * (trades.pnl > 0).mean(),
        "net": float(trades.pnl.sum()), "pf": gp / gl if gl else np.inf,
        "mdd": float((equity - equity.cummax()).min()),
        "gross_profit": gp, "gross_loss": gl,
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


def regression_check(fresh: pd.DataFrame, recorded: pd.DataFrame) -> str:
    lhs = fresh[TRADE_COLS].reset_index(drop=True)
    rhs = recorded[TRADE_COLS].reset_index(drop=True)
    pd.testing.assert_frame_equal(lhs, rhs, check_dtype=False, check_exact=True)
    return f"{len(lhs):,}/{len(rhs):,} 筆、逐欄位完全一致"


def feature_check(audit: pd.DataFrame, feature_file: pd.DataFrame) -> dict[str, Any]:
    sample = audit.loc[~audit.skipped].copy().sort_values(["entry_ts", "side"]).head(50)
    reference = feature_file.loc[feature_file.kind.eq("Add"), [
        "entry_ts", "entry_px", "side",
        "hvn_5d_atr_behind_atr", "hvn_5d_pct_behind_atr",
    ]]
    joined = sample.merge(reference, on=["entry_ts", "entry_px", "side"], how="inner",
                          suffixes=("_engine", "_phasec"))
    if len(joined) != 50:
        raise RuntimeError(f"expected 50 Add feature matches; got {len(joined)}")
    diffs = {}
    for name in ("hvn_5d_atr_behind_atr", "hvn_5d_pct_behind_atr"):
        diffs[name] = float(np.nanmax(np.abs(
            joined[f"{name}_engine"].to_numpy(float) - joined[f"{name}_phasec"].to_numpy(float)
        )))
    return {"n": len(joined), "diffs": diffs, "max": max(diffs.values())}


def lot_path_check(base: pd.DataFrame, variant: pd.DataFrame) -> dict[str, float | int]:
    base_ladd = base[(base.side == "L") & (base.kind == "Add")]
    var_ladd = variant[(variant.side == "L") & (variant.kind == "Add")]
    bprofit = float(base_ladd.loc[base_ladd.pnl > 0, "pnl"].sum())
    bloss = float(-base_ladd.loc[base_ladd.pnl <= 0, "pnl"].sum())
    vprofit = float(var_ladd.loc[var_ladd.pnl > 0, "pnl"].sum())
    vloss = float(-var_ladd.loc[var_ladd.pnl <= 0, "pnl"].sum())
    base_g, var_g = base[base.kind == "G"], variant[variant.kind == "G"]
    base_s, var_s = base[base.side == "S"], variant[variant.side == "S"]
    return {
        "ladd_profit_retained_pct": 100 * vprofit / bprofit if bprofit else np.nan,
        "ladd_loss_removed_pct": 100 * (bloss - vloss) / bloss if bloss else np.nan,
        "g_n_delta": int(len(var_g) - len(base_g)),
        "g_net_delta": float(var_g.pnl.sum() - base_g.pnl.sum()),
        "s_n_delta": int(len(var_s) - len(base_s)),
        "s_net_delta": float(var_s.pnl.sum() - base_s.pnl.sum()),
    }


def number(value: float, digits: int = 0) -> str:
    if np.isnan(value):
        return "—"
    if np.isinf(value):
        return "∞"
    return f"{value:,.{digits}f}"


def metric_text(m: dict[str, float | int], delta: float | None = None) -> str:
    ratio = float(m["net"]) / abs(float(m["mdd"])) if m["mdd"] else np.inf
    result = (
        f"n={m['n']:,}，WR={m['wr']:.1f}%，net={m['net']:+,.0f}，"
        f"PF={number(float(m['pf']), 2)}，MDD={m['mdd']:+,.0f}，"
        f"net/|MDD|={number(ratio, 2)}"
    )
    return result if delta is None else f"{result}；相對 v29 {delta:+,.0f}"


def write_report(baseline: pd.DataFrame, regression: str, check: dict[str, Any],
                 all_results: list[dict[str, Any]]) -> None:
    baseline_splits = splits(baseline)
    lines = [
        "# Phase D：5 日 HVN 後方距離 Add gate 全引擎回測",
        "",
        "## 實作與驗證",
        "",
        "- 原始研究引擎完全未修改。本目錄 engine_v29_hvn_wrapper.py 為薄包裝：複製原 run 的控制流，只在 Add 的 next-open 填單前加入 gate；Cmd 與 G 沒有直接套用此 gate。",
        "- 特徵與 Phase C 相同：以 5m typical price=(H+L+C)/3 加權成交量，使用 5 個日曆日內、且 close_ts 嚴格早於 Add signal bar close 的完成 5m bars。ATR-bin 寬為 0.25 倍該嚴格截止點最後一根 5m bar 的 ATR(14)，pct-bin 寬為 0.001 倍 Add 實際 entry price。",
        "- HVN 定義為成交量局部極大值（相等視為極大）且不低於正成交量 bins 的第 75 百分位，並額外納入 POC；Long 取 entry 下方最近 level、Short 取 entry 上方最近 level，距離除以同一個嚴格截止 ATR。",
        "- 訊號的 pending Add 在下一根 5m open、真正建立 lot 前才判斷，使距離能使用實際 fill price；profile 仍沒有使用 signal close 以後的資料。跳過即不建立 lot，因此其後 Add/G 依既有狀態機自然演進。",
        f"- Gate 關閉的逐筆回歸：{regression}。",
        f"- 50 筆 Add 特徵檢查：ATR-bin 最大絕對差 {check['diffs']['hvn_5d_atr_behind_atr']:.12g}；pct-bin 最大絕對差 {check['diffs']['hvn_5d_pct_behind_atr']:.12g}；合計最大值 {check['max']:.12g}。",
        "- 全部回測固定 intrabar_mode=1min、opt_stale_hr=10、opt_cooldown_min=30，且使用 v29 的 hour4 short cap 與 l_trailBase=3.5、指定 corrected 1m 資料。",
        "",
        "## v29 基線",
        "",
    ]
    for window in ("full", "H1", "H2", "TRAIN", "TEST", "HOLDOUT"):
        lines.append(f"- {window}：{metric_text(baseline_splits[window])}。")
    lines += [
        "",
        "## 六個預先宣告變體",
        "",
        "排名只以 TRAIN 淨利為準；PASS 則要求 H1、H2、TRAIN、TEST 四段 net delta 都嚴格大於 0。HOLDOUT 僅最後報告，從未用於選擇。",
        "",
    ]
    for result in all_results:
        gate, path = result["gate"], result["path"]
        lines += [
            f"### {result['name']}：**{result['status']}**",
            "",
            f"設定：feature={gate['feature']}，min_dist_atr={gate['min_dist_atr']}，sides={gate['sides']}；跳過 Add {result['skipped']:,} 筆。",
            "",
        ]
        for window in ("full", "H1", "H2", "TRAIN", "TEST", "HOLDOUT"):
            lines.append(f"- {window}：{metric_text(result['splits'][window], result['deltas'][window])}。")
        lines += [
            "",
            f"- 路徑效果後的 L Add precision check：毛利保留 {path['ladd_profit_retained_pct']:.1f}%；毛損移除 {path['ladd_loss_removed_pct']:.1f}%。這是完整 gate run 的 L Add 總額相對 v29，不是靜態刪交易。",
            f"- G lots：筆數 {path['g_n_delta']:+,}、net {path['g_net_delta']:+,.0f}；S side：筆數 {path['s_n_delta']:+,}、net {path['s_net_delta']:+,.0f}。",
            f"- 年度 net delta：2024 {result['years'][2024]:+,.0f}；2025 {result['years'][2025]:+,.0f}；2026 {result['years'][2026]:+,.0f}。",
            "",
        ]
    ranking = sorted(all_results, key=lambda item: item["deltas"]["TRAIN"], reverse=True)
    passed = [item for item in all_results if item["status"] == "PASS"]
    lines += ["## 結論", "", f"TRAIN 排名第一為 {ranking[0]['name']}（net delta {ranking[0]['deltas']['TRAIN']:+,.0f}）。"]
    if passed:
        best = sorted(passed, key=lambda item: item["deltas"]["TRAIN"], reverse=True)[0]
        lines += [
            f"共有 {len(passed)} 個變體通過四窗口 PASS；可只把 {best['name']} 進一步作為 Pine 實驗分支。",
            "",
            "Pine 邏輯草圖：每個 Add 取 signal close 嚴格之前最後一根 5m bar 的 ATR 與預期/實際 fill，向前 5 個日曆日收集 signal close 前完成的 5m typical-price volume；按 0.25*ATR 或 0.001*price bin 累積 volume，保留 POC 加上局部極大且不低於正 bins P75 的 HVN。Long/Short 分別取後方最近 HVN，距離/ATR 小於門檻時不送 Add。",
            "Pine 可行性：TradingView 沒有能直接重現任意歷史窗 volume profile 的簡單序列，預期需 request.security_lower_tf 或用 arrays 在 5m 資料重建 profile。動態 bin 寬難以快取，約為中高複雜度，並有 request/array 限制與 session 缺 bar 的處理成本。",
        ]
    else:
        lines += [
            "六個預先宣告變體全部 FAIL；不建議在 Pine 實作或上線。即使某些 TRAIN 結果為正，也不足以滿足 H1、H2、TRAIN、TEST 全數為正的預先規則。",
            "負面結果顯示：靜態 Add 分層的關聯未穩健地轉化為動態金字塔路徑的跨期增益；G lots 與另一側交易的連帶變化亦已在上表明列。",
        ]
    lines += [
        "",
        "## 產出",
        "",
        "- engine_v29_hvn_wrapper.py：本地 gate wrapper，原引擎未改動。",
        "- run_phaseD_hvn_gate.py：可重現的全引擎網格、驗證與報告。",
        "- trades_phaseD_*.csv、phaseD_gateoff_add_audit.csv、phaseD_summary.csv：交易與稽核明細。",
        "",
    ]
    RESULTS_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    df1m = load_1min(DATA_PATH)
    baseline = pd.read_csv(BASELINE_PATH, parse_dates=["entry_ts", "exit_ts"])
    print("run gate-off regression", flush=True)
    off = run(df1m, {**V29, "opt_add_hvn_gate": None}, intrabar_mode="1min")
    regression = regression_check(off, baseline)
    audit = pd.DataFrame(off.attrs["hvn_gate_audit"])
    audit.to_csv(HERE / "phaseD_gateoff_add_audit.csv", index=False, encoding="utf-8-sig")
    saved_features = pd.read_csv(FEATURE_PATH, parse_dates=["entry_ts", "exit_ts"])
    check = feature_check(audit, saved_features)
    baseline_splits = splits(baseline)
    result_rows, all_results = [], []
    for name, gate in VARIANTS:
        print(f"run {name}", flush=True)
        trades = run(df1m, {**V29, "opt_add_hvn_gate": gate}, intrabar_mode="1min")
        trades.to_csv(HERE / f"trades_phaseD_{name}.csv", index=False, encoding="utf-8-sig")
        result_splits = splits(trades)
        deltas = {window: float(result_splits[window]["net"] - baseline_splits[window]["net"])
                  for window in baseline_splits}
        years = {
            year: float(trades.loc[trades.entry_ts.dt.year == year, "pnl"].sum()
                        - baseline.loc[baseline.entry_ts.dt.year == year, "pnl"].sum())
            for year in (2024, 2025, 2026)
        }
        status = "PASS" if all(deltas[window] > 0 for window in ("H1", "H2", "TRAIN", "TEST")) else "FAIL"
        path = lot_path_check(baseline, trades)
        skipped = int(trades.attrs["hvn_gate_skipped"])
        result = {"name": name, "gate": gate, "splits": result_splits, "deltas": deltas,
                  "years": years, "status": status, "path": path, "skipped": skipped}
        all_results.append(result)
        for window, values in result_splits.items():
            result_rows.append({
                "variant": name, "window": window, **values,
                "net_delta_vs_v29": deltas[window], "status": status,
                "adds_skipped": skipped, **path,
                "year_2024_net_delta": years[2024],
                "year_2025_net_delta": years[2025],
                "year_2026_net_delta": years[2026],
            })
    pd.DataFrame(result_rows).to_csv(HERE / "phaseD_summary.csv", index=False, encoding="utf-8-sig")
    write_report(baseline, regression, check, all_results)
    print(RESULTS_PATH, flush=True)


if __name__ == "__main__":
    main()

