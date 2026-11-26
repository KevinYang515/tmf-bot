"""v28 parameter-plateau stability check.

The upstream engine is imported read-only.  Its public ``run`` function is
used as-is for every exposed parameter.  ATR length and the Donchian breakout
lookback are literals inside ``prepare()``, not entries in ``P``; only for
those two requested checks this driver temporarily substitutes an in-memory
copy of ``prepare()``.  Nothing is written to the engine directory.
"""
from __future__ import annotations

import inspect
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
DATA = HERE / "mxf_1min_corrected_20261017b.csv"
CUTOFF = pd.Timestamp("2026-10-17 03:58:00")
NET_COST_PER_LOT = 440.0  # Engine pnl already includes NT$20 per side.
FACTORS = (0.6, 0.8, 0.9, 1.1, 1.25, 1.5)
GRID_FACTORS = (0.8, 0.9, 1.0, 1.1, 1.25)

if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
import engine_v26_bbw as engine  # noqa: E402


# v28 is v27 (10h stale / 30m cooldown) plus the hour-4 short pyramid cap.
V28: dict[str, Any] = {
    "opt_stale_hr": 10,
    "opt_cooldown_min": 30,
    "opt_short_pyramid_cap_mode": "hour4",
}

# ``key`` is an actual engine P key except the two explicitly-labelled source
# literals.  The latter are tested by ``run_engine`` without adding pretend
# parameters to the upstream engine.
SPECS: tuple[dict[str, Any], ...] = (
    {"key": "l_pyramid_dist", "label": "多方 Add/G 距離", "base": 1.2, "integer": False,
     "source": "l_pyramid_dist"},
    {"key": "s_pyramid_dist", "label": "空方 Add/G 距離", "base": 1.0, "integer": False,
     "source": "s_pyramid_dist"},
    {"key": "l_slMult", "label": "多方 Cmd 初始停損", "base": 3.0, "integer": False,
     "source": "l_slMult（會同步映射至 l_slMultDay/Night）"},
    {"key": "s_slMult", "label": "空方 Cmd 初始停損", "base": 2.5, "integer": False,
     "source": "s_slMult"},
    {"key": "l_trailBase", "label": "多方 Cmd trail base", "base": 5.0, "integer": False,
     "source": "l_trailBase（會同步映射至 l_trailBaseDay/Night）"},
    {"key": "s_trailMult", "label": "空方 Cmd trail base", "base": 3.0, "integer": False,
     "source": "s_trailMult"},
    {"key": "plateau_atr_length", "label": "ATR 長度", "base": 14, "integer": True,
     "source": "prepare(): atr(b5, 14)（硬編常數，不是 P 參數）"},
    {"key": "fastEmaLen", "label": "快速 EMA 長度", "base": 35, "integer": True,
     "source": "fastEmaLen"},
    {"key": "l_cmdExitLen", "label": "多方 Cmd exit EMA 長度", "base": 50, "integer": True,
     "source": "l_cmdExitLen"},
    {"key": "s_cmdExitLen", "label": "空方 Cmd exit EMA 長度", "base": 40, "integer": True,
     "source": "s_cmdExitLen"},
    {"key": "l_emaLenLong", "label": "多方趨勢 EMA 長度", "base": 130, "integer": True,
     "source": "l_emaLenLong"},
    {"key": "l_emaLenShort", "label": "空方趨勢 EMA 長度", "base": 125, "integer": True,
     "source": "l_emaLenShort"},
    {"key": "plateau_donchian_lookback", "label": "Donchian／breakout 回看", "base": 20, "integer": True,
     "source": "prepare(): hh20_prev／ll20_prev 的 rolling(20)（硬編常數，不是 P 參數）"},
    {"key": "adxThresh", "label": "ADX 門檻", "base": 20, "integer": True,
     "source": "adxThresh"},
)


def save(df: pd.DataFrame, name: str) -> None:
    df.to_csv(HERE / name, index=False, encoding="utf-8-sig")


def half_up(value: float) -> int:
    """Positive integer rounding, with .5 rounded upward as documented."""
    return int(math.floor(value + 0.5))


def scaled_values(spec: dict[str, Any]) -> list[tuple[float, float | int]]:
    out: list[tuple[float, float | int]] = []
    seen: set[float | int] = set()
    for factor in FACTORS:
        value: float | int = spec["base"] * factor
        if spec["integer"]:
            value = half_up(float(value))
        else:
            value = round(float(value), 10)
        if value not in seen:
            seen.add(value)
            out.append((factor, value))
    return out


def _custom_prepare(atr_length: int, donchian_lookback: int):
    """Compile the vendor ``prepare`` with only its two requested literals changed."""
    source = inspect.getsource(engine.prepare)
    old_head = "def prepare(df1m, p):"
    if old_head not in source:
        raise RuntimeError("engine prepare signature changed")
    source = source.replace(old_head, "def _plateau_prepare(df1m, p):", 1)
    anchors = {
        "atr(b5, 14)": f"atr(b5, {int(atr_length)})",
        'b5["high"].rolling(20).max().shift(1)':
            f'b5["high"].rolling({int(donchian_lookback)}).max().shift(1)',
        'b5["low"].rolling(20).min().shift(1)':
            f'b5["low"].rolling({int(donchian_lookback)}).min().shift(1)',
    }
    for old, new in anchors.items():
        if old not in source:
            raise RuntimeError(f"engine prepare layout changed: missing {old}")
        source = source.replace(old, new, 1)
    namespace = dict(vars(engine))
    exec(compile(source, __file__, "exec"), namespace)
    return namespace["_plateau_prepare"]


def run_engine(df1m: pd.DataFrame, overrides: dict[str, Any]) -> pd.DataFrame:
    """Run the unmodified engine, wrapping only non-parameter source literals."""
    local = dict(overrides)
    atr_length = local.pop("plateau_atr_length", None)
    donchian_lookback = local.pop("plateau_donchian_lookback", None)
    if atr_length is None and donchian_lookback is None:
        return engine.run(df1m, p=local, intrabar_mode="1min")
    atr_length = 14 if atr_length is None else int(atr_length)
    donchian_lookback = 20 if donchian_lookback is None else int(donchian_lookback)
    if atr_length < 1 or donchian_lookback < 2:
        raise ValueError("ATR length must be >=1 and Donchian lookback must be >=2")
    original_prepare = engine.prepare
    engine.prepare = _custom_prepare(atr_length, donchian_lookback)
    try:
        return engine.run(df1m, p=local, intrabar_mode="1min")
    finally:
        engine.prepare = original_prepare


def daily_mdd(trades: pd.DataFrame) -> float:
    """Closed-PnL MDD after aggregating all exits in each calendar day."""
    if trades.empty:
        return 0.0
    daily = trades.groupby(trades["exit_ts"].dt.normalize(), sort=True)["net"].sum()
    curve = daily.cumsum()
    return float((curve - curve.cummax()).min())


def metrics(trades: pd.DataFrame) -> dict[str, float | int]:
    z = trades.copy()
    z["entry_ts"] = pd.to_datetime(z["entry_ts"])
    z["exit_ts"] = pd.to_datetime(z["exit_ts"])
    z["net"] = z["pnl"].astype(float) - NET_COST_PER_LOT
    years = z["entry_ts"].dt.year
    y = {year: float(z.loc[years.eq(year), "net"].sum()) for year in (2024, 2025, 2026)}
    total = float(z["net"].sum())
    mdd = daily_mdd(z)
    return {
        "lots": int(len(z)),
        "net_2024": y[2024],
        "net_2025": y[2025],
        "net_2026": y[2026],
        "total_net": total,
        "daily_mdd": mdd,
        "net_mdd": total / abs(mdd) if mdd else np.inf,
        "year_positive_count": int(sum(value > 0 for value in y.values())),
    }


def evaluate(df1m: pd.DataFrame, run_id: str, run_type: str, overrides: dict[str, Any],
             **details: Any) -> dict[str, Any]:
    trades = run_engine(df1m, overrides)
    result: dict[str, Any] = {
        "run_id": run_id,
        "run_type": run_type,
        "overrides": json.dumps(overrides, sort_keys=True, ensure_ascii=False),
        **details,
        **metrics(trades),
    }
    return result


def fmt_num(value: Any, digits: int = 0) -> str:
    if pd.isna(value):
        return "—"
    if isinstance(value, (float, np.floating)) and np.isinf(value):
        return "∞"
    if isinstance(value, (float, np.floating, int, np.integer)):
        return f"{float(value):,.{digits}f}"
    return str(value)


def markdown_table(df: pd.DataFrame, columns: list[str], names: dict[str, str],
                   decimals: dict[str, int] | None = None) -> str:
    decimals = decimals or {}
    lines = [
        "| " + " | ".join(names.get(c, c) for c in columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for row in df[columns].itertuples(index=False, name=None):
        lines.append("| " + " | ".join(
            fmt_num(value, decimals.get(column, 0))
            for column, value in zip(columns, row)
        ) + " |")
    return "\n".join(lines)


def make_verdicts(sweeps: pd.DataFrame, baseline: pd.Series) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    baseline_signs = [np.sign(baseline[f"net_{year}"]) for year in (2024, 2025, 2026)]
    for spec in SPECS:
        x = sweeps[sweeps["parameter"].eq(spec["key"])].copy()
        near = x[x["factor"].isin([0.9, 1.1])].copy()
        checks: list[bool] = []
        near_notes: list[str] = []
        for factor in (0.9, 1.1):
            r = near[np.isclose(near["factor"], factor)]
            if r.empty:
                continue
            item = r.iloc[0]
            net_change = float(item.total_net / baseline.total_net - 1.0)
            signs_ok = all(
                np.sign(item[f"net_{year}"]) == sign
                for year, sign in zip((2024, 2025, 2026), baseline_signs)
            )
            checks.append(abs(net_change) <= 0.15 and signs_ok)
            near_notes.append(f"×{factor:g}: {net_change:+.1%}，正年 {int(item.year_positive_count)}/3")
        verdict = "plateau" if checks and all(checks) else "spike/cliff"
        worst_near = min(
            (float(v.total_net / baseline.total_net - 1.0) for v in near.itertuples()),
            default=np.nan,
        )
        worst_all = min(
            (float(v.total_net / baseline.total_net - 1.0) for v in x.itertuples()),
            default=np.nan,
        )
        rows.append({
            "parameter": spec["key"],
            "label": spec["label"],
            "source": spec["source"],
            "base_value": spec["base"],
            "verdict": verdict,
            "nearby_checks": "；".join(near_notes),
            "worst_near_net_change": worst_near,
            "worst_all_net_change": worst_all,
        })
    return pd.DataFrame(rows)


def write_report(core: pd.DataFrame, baseline: pd.Series, sweeps: pd.DataFrame,
                 grid: pd.DataFrame, verdicts: pd.DataFrame) -> None:
    common = ["factor", "value", "lots", "net_2024", "net_2025", "net_2026", "total_net", "daily_mdd", "net_mdd", "year_positive_count"]
    common_names = {
        "factor": "倍數", "value": "測試值", "lots": "lots",
        "net_2024": "2024 淨利", "net_2025": "2025 淨利", "net_2026": "2026 淨利",
        "total_net": "總淨利", "daily_mdd": "日 MDD", "net_mdd": "淨利/MDD",
        "year_positive_count": "正報酬年數",
    }
    fragile = verdicts[verdicts["verdict"].eq("spike/cliff")]
    overall = "是" if fragile.empty else "否（至少一項核心參數在 ±10% 鄰近變動未通過門檻）"
    lines = [
        "# v28 參數平台（plateau）穩定性檢查",
        "",
        "## 摘要",
        "",
        f"- 結論：v28 的整體參數組合是否位於平台：**{overall}**。此為穩定性檢查，不從結果挑選或建議替代參數組。",
        f"- 基準 v28：2024／2025／2026 淨利分別為 NT${fmt_num(baseline.net_2024)}／{fmt_num(baseline.net_2025)}／{fmt_num(baseline.net_2026)}；總淨利 NT${fmt_num(baseline.total_net)}；日 MDD NT${fmt_num(baseline.daily_mdd)}；淨利/MDD {fmt_num(baseline.net_mdd, 2)}。",
        ("- 小幅變動較脆弱的參數：" + "、".join(f"`{x.parameter}`" for x in fragile.itertuples()) + "。"
         if not fragile.empty else "- 在本檢查定義的 ±10% 鄰近變動下，沒有參數被標為脆弱。"),
        "",
        "判定規則：對每一個一維掃描，只有 ×0.9 與 ×1.1 都同時滿足「總淨利距基準不超過 ±15%」且 2024、2025、2026 三年與基準同號，才標示為 `plateau`；否則為 `spike/cliff`。較寬的 ×0.6、×0.8、×1.25、×1.5 是用來辨認懸崖，而非用來選參數。",
        "",
        "## 固定條件與成本",
        "",
        "- 資料：`mxf_1min_corrected_20261017b.csv`，只取至 2026-10-17 03:58（含）；1 分鐘 intrabar。",
        "- v28：`opt_stale_hr=10`、`opt_cooldown_min=30`、`opt_short_pyramid_cap_mode='hour4'`；其餘為引擎預設值。",
        "- 成本：每邊 NT$40 + 每邊 4 點；引擎 `pnl` 已含每邊 NT$20 手續費，故本報告統一以 **net = pnl − NT$440／lot round trip** 計算。",
        "- 年度淨利按 entry timestamp 分年，與 `results_v26_vs_v27.md` 一致；日 MDD 為所有已實現淨利按 exit date 彙總後的日頻 closed-equity MDD。",
        "",
        "## 基準重現",
        "",
        markdown_table(pd.DataFrame([baseline]), ["lots", "net_2024", "net_2025", "net_2026", "total_net", "daily_mdd", "net_mdd", "year_positive_count"], common_names, {"net_mdd": 2}),
        "",
        "## 引擎核心值",
        "",
        "`l_slMult` 與 `l_trailBase` 是相容性總開關：當傳入時，引擎會映射到 day/night 兩個同名 session 欄位。`plateau_atr_length`、`plateau_donchian_lookback` 僅是本研究 wrapper 的標籤；它們對應下表所示的原始碼常數，並非引擎的可直接設定 P key。",
        "",
        markdown_table(core, ["label", "source", "base_value"], {"label": "項目", "source": "引擎名稱／位置", "base_value": "v28 值"}, {"base_value": 2}),
        "",
        "補充：`adxLen=14` 固定不變；`ema10`／`ema30`（10／30）為進場 crossover 的硬編觸發均線，並非 P 字典參數。本次所有可設定的 fast、Cmd-exit 與趨勢 EMA 長度均各自掃描。",
        "",
        "## 一維掃描與判定",
        "",
        markdown_table(verdicts, ["parameter", "base_value", "verdict", "nearby_checks", "worst_near_net_change", "worst_all_net_change"], {
            "parameter": "參數", "base_value": "基準", "verdict": "判定", "nearby_checks": "±10% 結果", "worst_near_net_change": "鄰近最差總淨利變化", "worst_all_net_change": "全掃描最差總淨利變化",
        }, {"base_value": 2, "worst_near_net_change": 3, "worst_all_net_change": 3}),
        "",
    ]
    for spec in SPECS:
        x = sweeps[sweeps["parameter"].eq(spec["key"])].sort_values("factor")
        lines.extend([
            f"### `{spec['key']}`：{spec['label']}（基準 {spec['base']:g}）",
            "",
            markdown_table(x, common, common_names, {"factor": 2, "value": 2, "net_mdd": 2}),
            "",
        ])
    grid_view = grid.pivot(index="add_factor", columns="trail_factor", values="grid_cell")
    grid_view = grid_view.reindex(index=GRID_FACTORS, columns=GRID_FACTORS)
    grid_display = grid_view.reset_index()
    lines.extend([
        "## 2D 網格：Add/G 距離 × trail base",
        "",
        "兩軸皆為同時縮放多／空兩側：Add/G 為 `l_pyramid_dist=1.2×a`、`s_pyramid_dist=1.0×a`；trail 為 `l_trailBase=5.0×t`、`s_trailMult=3.0×t`。每格為 **總淨利（正報酬年數／3）**，不代表推薦或選擇。",
        "",
        markdown_table(grid_display, ["add_factor", *GRID_FACTORS], {"add_factor": "Add/G 倍數", **{x: f"trail ×{x:g}" for x in GRID_FACTORS}}, {"add_factor": 2}),
        "",
        "### 2D 網格完整逐格指標",
        "",
        markdown_table(grid.sort_values(["add_factor", "trail_factor"]), ["add_factor", "trail_factor", "lots", "net_2024", "net_2025", "net_2026", "total_net", "daily_mdd", "net_mdd", "year_positive_count"], {
            "add_factor": "Add/G 倍數", "trail_factor": "trail 倍數", "lots": "lots",
            "net_2024": "2024 淨利", "net_2025": "2025 淨利", "net_2026": "2026 淨利", "total_net": "總淨利", "daily_mdd": "日 MDD", "net_mdd": "淨利/MDD", "year_positive_count": "正報酬年數",
        }, {"add_factor": 2, "trail_factor": 2, "net_mdd": 2}),
        "",
        "## 結論說明",
        "",
        f"以明確的 ±10%／±15% 規則，整體判定為 **{overall}**。`spike/cliff` 僅表示在此歷史樣本與成本假設下對鄰近擾動敏感；不表示較高或較低的格子應被採用。",
        "",
        "完整機器可讀結果：`plateau_all_runs.csv`（全部 1D、2D 與基準）、`plateau_sweep.csv`、`plateau_grid.csv`、`plateau_parameter_verdicts.csv`、`plateau_core_parameters.csv`。",
    ])
    (HERE / "results_param_plateau.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    # Detect accidental upstream drift before spending time on the full grid.
    required_defaults = {
        "l_pyramid_dist": 1.2, "s_pyramid_dist": 1.0,
        "l_slMult": 3.0, "s_slMult": 2.5,
        "l_trailBase": 5.0, "s_trailMult": 3.0,
        "fastEmaLen": 35, "l_cmdExitLen": 50, "s_cmdExitLen": 40,
        "l_emaLenLong": 130, "l_emaLenShort": 125, "adxThresh": 20,
    }
    drift = {key: (engine.P.get(key), value) for key, value in required_defaults.items()
             if engine.P.get(key) != value}
    if drift:
        raise RuntimeError(f"upstream engine defaults differ from task baseline: {drift}")

    print("load common-cutoff 1m data", flush=True)
    df1m = engine.load_1min(DATA)
    df1m = df1m.loc[df1m.ts <= CUTOFF].copy()

    print("run baseline v28", flush=True)
    all_rows: list[dict[str, Any]] = [evaluate(df1m, "baseline", "baseline", V28)]
    baseline = pd.Series(all_rows[0])
    expected = {"lots": 4224, "total_net": 2_122_980.0, "net_2024": 181_740.0,
                "net_2025": 624_400.0, "net_2026": 1_316_840.0}
    actual = {key: baseline[key] for key in expected}
    if actual != expected:
        raise RuntimeError(f"v28 baseline did not reproduce expected values: {actual}")
    save(pd.DataFrame(all_rows), "plateau_all_runs.csv")

    total_sweeps = sum(len(scaled_values(spec)) for spec in SPECS)
    done = 0
    for spec in SPECS:
        for factor, value in scaled_values(spec):
            done += 1
            print(f"sweep {done}/{total_sweeps}: {spec['key']} x{factor:g}", flush=True)
            overrides = {**V28, spec["key"]: value}
            all_rows.append(evaluate(
                df1m, f"sweep__{spec['key']}__x{factor:g}", "sweep", overrides,
                parameter=spec["key"], parameter_label=spec["label"],
                factor=factor, value=value,
            ))
            save(pd.DataFrame(all_rows), "plateau_all_runs.csv")

    done = 0
    for add_factor in GRID_FACTORS:
        for trail_factor in GRID_FACTORS:
            done += 1
            print(f"grid {done}/25: add x{add_factor:g}, trail x{trail_factor:g}", flush=True)
            overrides = {
                **V28,
                "l_pyramid_dist": 1.2 * add_factor,
                "s_pyramid_dist": 1.0 * add_factor,
                "l_trailBase": 5.0 * trail_factor,
                "s_trailMult": 3.0 * trail_factor,
            }
            all_rows.append(evaluate(
                df1m, f"grid__add_x{add_factor:g}__trail_x{trail_factor:g}", "grid", overrides,
                add_factor=add_factor, trail_factor=trail_factor,
                l_pyramid_dist=overrides["l_pyramid_dist"],
                s_pyramid_dist=overrides["s_pyramid_dist"],
                l_trailBase=overrides["l_trailBase"],
                s_trailMult=overrides["s_trailMult"],
            ))
            save(pd.DataFrame(all_rows), "plateau_all_runs.csv")

    all_runs = pd.DataFrame(all_rows)
    sweeps = all_runs[all_runs.run_type.eq("sweep")].copy()
    grid = all_runs[all_runs.run_type.eq("grid")].copy()
    grid["grid_cell"] = grid.apply(
        lambda row: f"{fmt_num(row.total_net)}（{int(row.year_positive_count)}/3）", axis=1
    )
    core = pd.DataFrame(SPECS)[["label", "source", "base"]].rename(columns={"base": "base_value"})
    verdicts = make_verdicts(sweeps, baseline)
    save(sweeps, "plateau_sweep.csv")
    save(grid, "plateau_grid.csv")
    save(verdicts, "plateau_parameter_verdicts.csv")
    save(core, "plateau_core_parameters.csv")
    write_report(core, baseline, sweeps, grid, verdicts)
    print("wrote results_param_plateau.md and plateau_*.csv", flush=True)


if __name__ == "__main__":
    main()
