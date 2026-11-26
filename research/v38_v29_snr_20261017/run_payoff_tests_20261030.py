"""Pre-declared payoff tests on v29+G2+H1(p20): Cmd stop, Add stop, stricter long, no G."""
from pathlib import Path
from multiprocessing import Pool
import pandas as pd
import engine_ml_gate4_wrapper as mlg
HERE = Path(__file__).resolve().parent
DATA = HERE / "mxf_1min_2020_20261029.csv"
COST = 2 * (40 - mlg.COMMISSION) + 2 * 4 * mlg.POINT_VALUE
V28 = {**mlg.P, "opt_stale_hr": 10, "opt_cooldown_min": 30, "opt_short_pyramid_cap_mode": "hour4"}
V29 = {**V28, "l_trailBase": 3.5, "l_trailBaseDay": 3.5, "l_trailBaseNight": 3.5}
GATE = {"opt_ml_gate": {"variant": "H1", "session_cum_vol_rel20_threshold": 0.7277710401830155,
                               "cmd_atr5_pct_threshold": 0.00058451066346192}}
BASE = {**V29, "opt_ml_gate": {"variant": "H1", "session_cum_vol_rel20_threshold": 0.7277710401830155,
                               "cmd_atr5_pct_threshold": 0.00058451066346192}}
def sl(k): return {"l_slMult": 3.0*k, "l_slMultDay": 3.0*k, "l_slMultNight": 3.0*k, "s_slMult": 2.5*k}
def al(k): return {"addLossL": 5.0*k, "addLossS": 4.5*k}
CASES = {"base": {}, "A_cmdSL_x0.8": sl(.8), "A_cmdSL_x0.9": sl(.9), "A_cmdSL_x1.2": sl(1.2),
         "B_addSL_x0.8": al(.8), "B_addSL_x0.9": al(.9), "B_addSL_x1.2": al(1.2),
         "C_longADX25": {"adxThresh": 25}, "C_longADX30": {"adxThresh": 30}, "C_shortOnly(診斷)": {"adxThresh": 1e9},
         "D_noG": {"opt_max_lots": 3},
         "C_longADX27": {"adxThresh": 27}, "C_longADX35": {"adxThresh": 35}, "B_addSL_x0.7": al(.7),
         "E_ADX30_addSL0.9": {"adxThresh": 30, **al(.9)}, "E_ADX30_addSL0.8": {"adxThresh": 30, **al(.8)},
         "C_longADX40": {"adxThresh": 40}, "C_longADX45": {"adxThresh": 45},
         **{f"v28_ADX{a}": {"_v28": True, "adxThresh": a} for a in (20, 25, 27, 30, 35, 40, 45)}}
def go(k):
    out = HERE / f"pay_trades_{k.replace('(診斷)','_diag')}.csv"
    if out.exists(): return pd.read_csv(out, parse_dates=["entry_ts", "exit_ts"]).assign(case=k)
    t = mlg.run(mlg.load_1min(DATA), p=({**V28, **GATE} if CASES[k].get("_v28") else BASE) | {x: y for x, y in CASES[k].items() if x != "_v28"}, intrabar_mode="1min")
    t["net"] = t.pnl.astype(float) - COST; t["case"] = k
    t["entry_ts"] = pd.to_datetime(t.entry_ts); t["exit_ts"] = pd.to_datetime(t.exit_ts)
    t.to_csv(out, index=False, encoding="utf-8"); return t
if __name__ == "__main__":
    with Pool(3) as pool: R = pool.map(go, list(CASES))
    print("done", [len(r) for r in R])
