"""v29 / v29+G2 / v29+G2+ADX30, with and without the session-last-bar rule, under a realistic cost model."""
from pathlib import Path
from multiprocessing import Pool
import pandas as pd
import engine_lastbar_wrapper as mlg
HERE = Path(__file__).resolve().parent
DATA = HERE / "mxf_1min_2020_20261031.csv"
V29 = {**mlg.P, "opt_stale_hr": 10, "opt_cooldown_min": 30, "opt_short_pyramid_cap_mode": "hour4",
       "l_trailBase": 3.5, "l_trailBaseDay": 3.5, "l_trailBaseNight": 3.5}
def gate(th, lb): return {"opt_ml_gate": {"variant": "G2", "session_cum_vol_rel20_threshold": th, "block_last_bar": lb}}
G2, OFF = 0.7277710401830155, -1e18   # OFF: G2 never true -> plain engine
CASES = {}
for lb in (False, True):
    sfx = "+末K" if lb else ""
    CASES["v29" + sfx] = {**V29, **gate(OFF, lb)}
    CASES["v29+G2" + sfx] = {**V29, **gate(G2, lb)}
    CASES["v29+G2+ADX30" + sfx] = {**V29, **gate(G2, lb), "adxThresh": 30}
def go(k):
    t = mlg.run(mlg.load_1min(DATA), p=CASES[k], intrabar_mode="1min"); t["case"] = k; return t
if __name__ == "__main__":
    with Pool(3) as pool: T = pd.concat(pool.map(go, list(CASES)))
    T.to_csv(HERE / "realcost_20261031_trades.csv", index=False, encoding="utf-8-sig"); print("done", T.groupby("case").size().to_dict())
