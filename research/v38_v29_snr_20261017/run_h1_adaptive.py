"""Pre-declared V38 adaptive-H1 evaluation (data ending 2026-10-31 00:30)."""
from __future__ import annotations

import gc
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

import engine_ml_gate5_wrapper as gate

HERE = Path(__file__).resolve().parent
DATA, LATEST = HERE / "mxf_1min_2020_20261031.csv", HERE / "latest_20261031_trades.csv"
G2, H1_OLD = 0.7277710401830155, 0.00058451066346192
SLIPPAGES, YEARS, RECENT_START = (4, 8), tuple(range(2020, 2027)), pd.Timestamp("2024-01-01")
ADAPTIVE = ("A60", "A120", "B_roll", "B_fix", "C")
BLOCK_COLUMN = {
    "H1_old": "h1_old_low", "A60": "h1_a60_low", "A120": "h1_a120_low",
    "B_roll": "h1_broll_low", "B_fix": "h1_bfix_low", "C": "h1_c_low",
}
BASE = {
    **gate.P, "opt_stale_hr": 10, "opt_cooldown_min": 30,
    "opt_short_pyramid_cap_mode": "hour4",
    "l_trailBase": 3.5, "l_trailBaseDay": 3.5, "l_trailBaseNight": 3.5,
    "adxThresh": 30,
}


def trading_day(ts: pd.Series) -> pd.Series:
    ts = pd.to_datetime(ts)
    return ts.dt.normalize() + pd.to_timedelta((ts.dt.hour >= 15).astype(int), unit="D")


def canonical(trades: pd.DataFrame) -> pd.DataFrame:
    cols = ["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl"]
    out = trades.loc[:, cols].copy()
    out["entry_ts"], out["exit_ts"] = pd.to_datetime(out["entry_ts"]), pd.to_datetime(out["exit_ts"])
    return out.sort_values(cols, kind="mergesort").reset_index(drop=True)


def daily_mdd(day: pd.Series) -> float:
    if day.empty:
        return 0.0
    equity = day.sort_index().cumsum().to_numpy(dtype=float)
    peak = np.maximum.accumulate(np.r_[0.0, equity])[:-1]
    return float(np.min(equity - peak))


def add_campaign_ids(trades: pd.DataFrame) -> pd.DataFrame:
    out = trades.sort_values(["entry_ts", "exit_ts", "kind"], kind="mergesort").copy()
    ids = pd.Series(index=out.index, dtype="object")
    for side, index in out.groupby("side", sort=False).groups.items():
        x = out.loc[index].sort_values(["entry_ts", "exit_ts", "kind"], kind="mergesort")
        number = x["kind"].eq("Cmd").cumsum()
        if (number == 0).any():
            raise AssertionError("a side has Add/G before its first Cmd")
        ids.loc[x.index] = f"{side}_" + number.astype(str)
    out["campaign_id"] = ids
    return out


def payoff(trades: pd.DataFrame) -> tuple[float, float, int]:
    campaigns = add_campaign_ids(trades).groupby("campaign_id", sort=False)["net"].sum()
    wins, nonwins = campaigns[campaigns > 0], campaigns[campaigns <= 0]
    ratio = float(wins.mean() / -nonwins.mean()) if len(wins) and len(nonwins) and nonwins.mean() < 0 else np.nan
    winrate = float(100.0 * len(wins) / len(campaigns)) if len(campaigns) else np.nan
    return ratio, winrate, int(len(campaigns))


def net_series(trades: pd.DataFrame, slip: int) -> tuple[pd.DataFrame, pd.Series]:
    out = trades.copy()
    out["net"] = out["pnl"].astype(float) - 2 * gate.COMMISSION - 2 * slip * gate.POINT_VALUE
    out["trade_day"] = trading_day(out["exit_ts"])
    return out, out.groupby("trade_day", sort=True)["net"].sum()


def one_metrics(case: str, trades: pd.DataFrame, slip: int) -> dict[str, Any]:
    all_lots, all_day = net_series(trades, slip)
    recent = all_lots.loc[all_lots.trade_day >= RECENT_START].copy()
    day = recent.groupby("trade_day", sort=True)["net"].sum()
    end = day.index.max()
    months = pd.period_range(RECENT_START.to_period("M"), end.to_period("M"), freq="M")
    monthly = day.groupby(day.index.to_period("M")).sum().reindex(months, fill_value=0.0)
    before = all_lots.loc[all_lots.trade_day < RECENT_START]
    before_day = before.groupby("trade_day", sort=True)["net"].sum()
    payoff_ratio, campaign_win_rate, campaigns = payoff(recent)
    row: dict[str, Any] = {
        "case": case, "slip_per_side_points": slip, "net_2024_plus": float(day.sum()),
        "daily_mdd_2024_plus": daily_mdd(day), "positive_months_2024_plus": int((monthly > 0).sum()),
        "months_2024_plus": int(len(monthly)), "campaign_payoff_ratio": payoff_ratio,
        "campaign_win_rate_pct": campaign_win_rate, "campaigns_2024_plus": campaigns,
        "lots_2024_plus": int(len(recent)), "net_2020_2023_reference": float(before_day.sum()),
        "daily_mdd_2020_2023_reference": daily_mdd(before_day),
        "data_last_trading_day": end.date().isoformat(),
    }
    for year in (2024, 2025, 2026):
        row[f"net_{year}"] = float(day.loc[day.index.year == year].sum())
    for months_back in (12, 6, 3):
        row[f"net_last_{months_back}m"] = float(day.loc[day.index > end - pd.DateOffset(months=months_back)].sum())
    return row


def run_case(data: pd.DataFrame, case: str, params: dict[str, Any]) -> pd.DataFrame:
    path = HERE / f"h1a_trades_{case}.csv"
    if path.exists():
        print(f"reusing {path.name}", flush=True)
        return pd.read_csv(path, parse_dates=["entry_ts", "exit_ts"])
    print(f"running {case}", flush=True)
    trades = gate.run(data, p=params, intrabar_mode="1min")
    trades["case"] = case
    trades.to_csv(path, index=False, encoding="utf-8")
    return trades


def checks_and_diagnostics(data: pd.DataFrame, base: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    bars = gate.prepare(data, BASE)
    features = gate.h1_adaptive_features(data, bars)
    features["h1_old_low"] = np.isfinite(features["atr5_pct"]) & (features["atr5_pct"] < H1_OLD)
    threshold_cols = ["a60_threshold", "a120_threshold", "broll_threshold", "c_threshold"]
    session = (
        features.groupby("session_id", sort=False)
        .agg(session=("session", "first"), session_date=("session_date", "first"),
             session_seq=("session_seq", "first"), first_bar_open=("open_ts", "first"),
             bars=("open_ts", "size"), **{c: (c, "first") for c in threshold_cols})
        .reset_index()
    )
    for col in threshold_cols:
        if int(features.groupby("session_id", sort=False)[col].nunique(dropna=False).max()) != 1:
            raise AssertionError(f"{col} changed inside a session")
    decision = features.copy()
    decision["entry_ts"] = decision["open_ts"].shift(-1)
    feature_cols = ["entry_ts", "session_id", "session", "clock", "atr5_pct", "b_ratio", "atr14_atr500", *BLOCK_COLUMN.values()]
    cmd = base.loc[base["kind"].eq("Cmd")].copy()
    cmd = cmd.merge(decision.loc[:, feature_cols], on="entry_ts", how="left", validate="one_to_one")
    if cmd["session_id"].isna().any():
        raise AssertionError(f"unmatched base Cmd decision bars: {int(cmd['session_id'].isna().sum())}")
    cmd["entry_year"] = cmd["entry_ts"].dt.year
    for col in BLOCK_COLUMN.values():
        if cmd[col].isna().any():
            raise AssertionError(f"missing H1 block flag: {col}")
        cmd[col] = cmd[col].astype(bool)
    rows: list[dict[str, Any]] = []
    for variant, col in BLOCK_COLUMN.items():
        for year in YEARS:
            x, blocked = cmd.loc[cmd.entry_year.eq(year)].copy(), cmd.loc[cmd.entry_year.eq(year) & cmd[col]].copy()
            row: dict[str, Any] = {
                "variant": variant, "entry_year": year, "base_cmd_lots": int(len(x)),
                "blocked_cmd_lots": int(len(blocked)), "block_rate_pct": float(100 * len(blocked) / len(x)) if len(x) else np.nan,
            }
            for slip in SLIPPAGES:
                net = x["pnl"].astype(float) - 2 * gate.COMMISSION - 2 * slip * gate.POINT_VALUE
                bnet = blocked["pnl"].astype(float) - 2 * gate.COMMISSION - 2 * slip * gate.POINT_VALUE
                row[f"mean_all_cmd_net_slip{slip}"] = float(net.mean()) if len(net) else np.nan
                row[f"mean_blocked_cmd_net_slip{slip}"] = float(bnet.mean()) if len(bnet) else np.nan
            rows.append(row)
    return pd.DataFrame(rows), cmd, session


def verdicts(metrics: pd.DataFrame) -> pd.DataFrame:
    table = metrics.set_index(["case", "slip_per_side_points"])
    base4, base8 = table.loc[("noH1", 4)], table.loc[("noH1", 8)]
    rows = []
    for case in ("H1_old", *ADAPTIVE):
        x4, x8 = table.loc[(case, 4)], table.loc[(case, 8)]
        total4, total8 = bool(x4.net_2024_plus > base4.net_2024_plus), bool(x8.net_2024_plus > base8.net_2024_plus)
        mdd_ok = bool(abs(x4.daily_mdd_2024_plus) <= abs(base4.daily_mdd_2024_plus) * 1.10)
        yearly_wins = int(sum(x4[f"net_{year}"] > base4[f"net_{year}"] for year in (2024, 2025, 2026)))
        rows.append({
            "case": case, "recent_total_beats_base_slip4": total4, "recent_total_beats_base_slip8": total8,
            "mdd_within_110pct_base_slip4": mdd_ok, "years_beating_base_slip4": yearly_wins,
            "fixed_verdict": "PASS" if total4 and total8 and mdd_ok and yearly_wins >= 2 else "FAIL",
        })
    return pd.DataFrame(rows)


def cash(value: float) -> str:
    return "NA" if not np.isfinite(value) else f"{value:,.0f}"


def number(value: float, digits: int = 2) -> str:
    return "NA" if not np.isfinite(value) else f"{value:.{digits}f}"


def report(metrics: pd.DataFrame, blocks: pd.DataFrame, verdict: pd.DataFrame, reproduction: pd.DataFrame) -> str:
    v = verdict.set_index("case")
    adaptive_pass = verdict.loc[verdict.case.isin(ADAPTIVE) & verdict.fixed_verdict.eq("PASS"), "case"].tolist()
    lead = (f"結論：自適應 H1 通過固定門檻的是 {', '.join(adaptive_pass)}；其餘版本不應採用。"
            if adaptive_pass else "結論：沒有任何自適應 H1 通過固定門檻；H1 應移除。")
    lines = [
        "# H1 自適應評估", "", lead, "",
        "固定判定相對於 noH1：slip 4、8 的 2024+ 淨利都必須較高；slip 4 的 2024+ 日 MDD 不得比基準差超過 10%；且 slip 4 必須在 2024、2025、2026 至少勝出 2 年。所有淨利均為每 lot pnl − 40 − 2×slip×50。",
        "",
        f"資料截至交易日 {metrics.data_last_trading_day.iloc[0]}；日盤與夜盤各算一個 session，A/B/C 的 60/120 session 歷史以時間順序合併，B 的 ATR 分母則嚴格限相同 session 類型和相同 5 分鐘時鐘。A/B/C 在完整回看期尚未形成時不封鎖（warm-up）。",
        "",
        f"舊 H1 lot-by-lot 重現：**{'PASS' if bool(reproduction.old_h1_equals_latest.iloc[0]) else 'FAIL'}**（latest_20261031_trades.csv 的 v29+G2+H1+ADX30）。",
        "", "## 固定 verdict", "",
        "| 版本 | 4 點總利勝基準 | 8 點總利勝基準 | 4 點 MDD ≤ 基準 110% | 4 點年度勝出 | verdict |",
        "|---|---|---|---|---:|---|",
    ]
    for row in verdict.itertuples(index=False):
        lines.append(f"| {row.case} | {'是' if row.recent_total_beats_base_slip4 else '否'} | {'是' if row.recent_total_beats_base_slip8 else '否'} | {'是' if row.mdd_within_110pct_base_slip4 else '否'} | {row.years_beating_base_slip4}/3 | {row.fixed_verdict} |")
    for slip in SLIPPAGES:
        lines += ["", f"## 成績：單邊滑價 {slip} 點", "",
                  "| 版本 | 2024 | 2025 | 2026 | 2024+ | 近12月 | 近6月 | 近3月 | 2024+日MDD | 正月數 | campaign payoff | campaign 勝率 | lots | 2020–23 淨利/MDD（參考） | verdict |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for case in ("noH1", "H1_old", *ADAPTIVE):
            row = metrics.loc[(metrics.case.eq(case)) & (metrics.slip_per_side_points.eq(slip))].iloc[0]
            tag = "基準" if case == "noH1" else v.loc[case, "fixed_verdict"]
            lines.append(f"| {case} | {cash(row.net_2024)} | {cash(row.net_2025)} | {cash(row.net_2026)} | {cash(row.net_2024_plus)} | {cash(row.net_last_12m)} | {cash(row.net_last_6m)} | {cash(row.net_last_3m)} | {cash(row.daily_mdd_2024_plus)} | {int(row.positive_months_2024_plus)}/{int(row.months_2024_plus)} | {number(row.campaign_payoff_ratio)} | {number(row.campaign_win_rate_pct, 1)}% | {int(row.lots_2024_plus):,} | {cash(row.net_2020_2023_reference)}/{cash(row.daily_mdd_2020_2023_reference)} | {tag} |")
    lines += [
        "", "## base Cmd 上的額外 H1 封鎖診斷", "",
        "每列皆以 noH1 的 Cmd lots 在其已完成的決策 5 分鐘 bar 評估；這是條件本身的樣本品質，不受某個 H1 在先前封鎖後改變後續路徑的影響。封鎖率的年份為 entry 年；均值為封鎖 Cmd／全部 Cmd 的單 lot 淨利。",
        "", "| 版本 | 年 | base Cmd | 封鎖 | 封鎖率 | slip4 封鎖/全部 | slip8 封鎖/全部 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in blocks.itertuples(index=False):
        lines.append(f"| {row.variant} | {row.entry_year} | {row.base_cmd_lots:,} | {row.blocked_cmd_lots:,} | {number(row.block_rate_pct, 1)}% | {cash(row.mean_blocked_cmd_net_slip4)}/{cash(row.mean_all_cmd_net_slip4)} | {cash(row.mean_blocked_cmd_net_slip8)}/{cash(row.mean_all_cmd_net_slip8)} |")
    lines += [
        "", "## 方法與可重現性", "",
        "- H1_old：atr5_pct < 0.00058451066346192；A60/A120：此前 60/120 個完整 day/night session 的所有 5 分鐘 atr5_pct 的 20 分位；B_roll：atr5 / 此前 20 個相同 session 類型且同時鐘的 ATR 平均，再對此前 120 sessions 的 r 取 20 分位；B_fix：相同 r < 0.80；C：引擎同一 RMA ATR 定義的 ATR14 / ATR500，此前 120 sessions 的 20 分位。",
        "- 每個 session 的門檻只在 session 第一根 bar 前的資料計算一次；決策使用已完成的 5 分鐘 bar，成交仍在下一根開盤。G2 與 H1 以 OR 合併；程式只把 Cmd 條件加上封鎖，沒有把 H1 套用到 Add/G。",
        "- 完整 CSV：h1a_metrics.csv、h1a_block_diagnostics.csv、h1a_cmd_lots.csv、h1a_threshold_sessions.csv、h1a_reproduction.csv，以及各版本 h1a_trades_*.csv。",
        "", "## Codex 的獨立看法", "",
        "這仍是六個事前指定的 H1 比較，並非完全沒有多重測試風險；PASS 只能算篩選，不該直接上線。2024+ 只有約三年、且末段夜盤尚未結束，對 regime 結論仍偏短。下一步我會保留一段完全未看的高波動、寬 spread 樣本，檢查不同滑價、跳空/公告日、夜盤和流動性急降時的成交與尾端損失；並用 walk-forward 固定門檻，而不是再對此表挑新分位數。"
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    if not DATA.exists() or not LATEST.exists():
        raise FileNotFoundError("required V38 data or latest reference ledger is missing")
    params: dict[str, dict[str, Any]] = {
        "noH1": {**BASE, "opt_ml_gate": {"variant": "G2", "session_cum_vol_rel20_threshold": G2}},
        "H1_old": {**BASE, "opt_ml_gate": {"variant": "H1", "session_cum_vol_rel20_threshold": G2, "cmd_atr5_pct_threshold": H1_OLD}},
        **{case: {**BASE, "opt_ml_gate": {"variant": case, "session_cum_vol_rel20_threshold": G2}} for case in ADAPTIVE},
    }
    data = gate.load_1min(DATA)
    cases = {case: run_case(data, case, p) for case, p in params.items()}
    reference = pd.read_csv(LATEST, parse_dates=["entry_ts", "exit_ts"])
    reference = reference.loc[reference["case"].eq("v29+G2+H1+ADX30")]
    assert_frame_equal(canonical(cases["H1_old"]), canonical(reference), check_dtype=False, check_exact=True)
    reproduction = pd.DataFrame([{
        "data": DATA.name, "reference": LATEST.name, "reference_case": "v29+G2+H1+ADX30",
        "old_h1_equals_latest": True, "old_h1_lots": len(cases["H1_old"]), "reference_lots": len(reference),
        "g2_threshold": G2, "h1_old_threshold": H1_OLD,
    }])
    metrics = pd.DataFrame([one_metrics(case, trades, slip) for case, trades in cases.items() for slip in SLIPPAGES])
    blocks, cmd, sessions = checks_and_diagnostics(data, cases["noH1"])
    fixed = verdicts(metrics)
    metrics.to_csv(HERE / "h1a_metrics.csv", index=False, encoding="utf-8")
    blocks.to_csv(HERE / "h1a_block_diagnostics.csv", index=False, encoding="utf-8")
    cmd.to_csv(HERE / "h1a_cmd_lots.csv", index=False, encoding="utf-8")
    sessions.to_csv(HERE / "h1a_threshold_sessions.csv", index=False, encoding="utf-8")
    reproduction.to_csv(HERE / "h1a_reproduction.csv", index=False, encoding="utf-8")
    fixed.to_csv(HERE / "h1a_verdicts.csv", index=False, encoding="utf-8")
    (HERE / "results_h1_adaptive.md").write_text(report(metrics, blocks, fixed, reproduction), encoding="utf-8")
    print(fixed.to_string(index=False))
    print("completed", flush=True)
    del data
    gc.collect()


if __name__ == "__main__":
    main()
