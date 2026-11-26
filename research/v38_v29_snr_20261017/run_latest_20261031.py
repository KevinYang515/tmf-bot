"""Core V38 versions on data to 2026-10-31 00:30 (night session in progress)."""
from pathlib import Path
from multiprocessing import Pool
import pandas as pd
import engine_ml_gate4_wrapper as mlg
import engine_ml_gate_wrapper as mlg1
HERE = Path(__file__).resolve().parent
DATA = HERE / "mxf_1min_2020_20261031.csv"
V27 = {**mlg.P, "opt_stale_hr": 10, "opt_cooldown_min": 30}
V28 = {**V27, "opt_short_pyramid_cap_mode": "hour4"}
V29 = {**V28, "l_trailBase": 3.5, "l_trailBaseDay": 3.5, "l_trailBaseNight": 3.5}
G2 = {"opt_ml_gate": {"variant": "G2", "session_cum_vol_rel20_threshold": 0.7277710401830155}}
H1 = {"opt_ml_gate": {"variant": "H1", "session_cum_vol_rel20_threshold": 0.7277710401830155, "cmd_atr5_pct_threshold": 0.00058451066346192}}
CASES = {"v27": V27, "v28": V28, "v29": V29, "v29+G2": {**V29, **G2}, "v28+G2+H1": {**V28, **H1}, "v29+G2+H1": {**V29, **H1},
         "v28+G2+H1+ADX30": {**V28, **H1, "adxThresh": 30},
         **{f"v29+G2+H1+ADX{a}": {**V29, **H1, "adxThresh": a} for a in (27, 30, 35)}}
def go(k):
    eng = mlg if "opt_ml_gate" in CASES[k] else mlg1
    t = eng.run(mlg.load_1min(DATA), p=CASES[k], intrabar_mode="1min"); t["case"] = k; return t
if __name__ == "__main__":
    with Pool(3) as pool: T = pd.concat(pool.map(go, list(CASES)))
    T.to_csv(HERE / "latest_20261031_trades.csv", index=False, encoding="utf-8-sig"); print("done", T.groupby("case").size().to_dict())
