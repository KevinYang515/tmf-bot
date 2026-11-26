"""One-at-a-time +-20% sensitivity of untested core params on v29+G2+ADX30 (fragility check, not optimisation).
Hard-coded in engine (not scanned): EMA10/30 trigger, 20-bar breakout, ATR length 14, toxic hours."""
from pathlib import Path
from multiprocessing import Pool
import pandas as pd
import engine_lastbar_wrapper as mlg
HERE = Path(__file__).resolve().parent
DATA = HERE / "mxf_1min_2020_20261031.csv"
BASE = {**mlg.P, "opt_stale_hr": 10, "opt_cooldown_min": 30, "opt_short_pyramid_cap_mode": "hour4",
        "l_trailBase": 3.5, "l_trailBaseDay": 3.5, "l_trailBaseNight": 3.5, "adxThresh": 30,
        "opt_ml_gate": {"variant": "G2", "session_cum_vol_rel20_threshold": 0.7277710401830155}}
INTS = {"l_emaLenLong", "l_emaLenShort", "l_cmdExitLen", "s_cmdExitLen", "fastEmaLen", "adxLen"}
PARAMS = ["l_emaLenLong", "l_emaLenShort", "l_cmdExitLen", "s_cmdExitLen", "fastEmaLen", "adxLen",
          "l_trailBase", "s_trailMult", "l_trailAdd", "g_trailMultDay", "g_trailMultNight",
          "l_pyramid_dist", "s_pyramid_dist", "be_trigger"]
CASES = {}
for k in PARAMS:
    for f, tag in ((0.8, "-20%"), (1.2, "+20%")):
        v = BASE[k] * f; v = int(round(v)) if k in INTS else round(v, 4)
        ov = {k: v}
        if k == "l_trailBase": ov.update(l_trailBaseDay=v, l_trailBaseNight=v)
        CASES[f"{k}{tag}={v}"] = ov
def go(name):
    out = HERE / "sens" / f"{name}.csv"
    if out.exists(): return
    t = mlg.run(mlg.load_1min(DATA), p={**BASE, **CASES[name]}, intrabar_mode="1min"); t["case"] = name
    t.to_csv(out, index=False, encoding="utf-8")
if __name__ == "__main__":
    (HERE / "sens").mkdir(exist_ok=True)
    with Pool(3) as pool: pool.map(go, list(CASES))
    print("done", len(CASES))
