"""Fine scans on v29+G2+ADX30 (pre-declared): short trail/pyramid peak width, long/short 5m EMA lengths,
and decoupled 60m MTF EMA lengths (mtf_long_len / mtf_short_len; default = 5m length, as in engine/Pine)."""
from pathlib import Path
from multiprocessing import Pool
import inspect, pandas as pd
import engine_lastbar_wrapper as mlg
_src = inspect.getsource(mlg._base.prepare)
for a, b in (('pine_ema(b60["close"], p["l_emaLenLong"])', 'pine_ema(b60["close"], p.get("mtf_long_len", p["l_emaLenLong"]))'),
             ('pine_ema(b60["close"], p["l_emaLenShort"])', 'pine_ema(b60["close"], p.get("mtf_short_len", p["l_emaLenShort"]))')):
    assert _src.count(a) == 1; _src = _src.replace(a, b)
exec(compile(_src, "prepare_mtf", "exec"), vars(mlg))   # overrides mlg.prepare used by the compiled run()
HERE = Path(__file__).resolve().parent
DATA = HERE / "mxf_1min_2020_20261031.csv"
BASE = {**mlg.P, "opt_stale_hr": 10, "opt_cooldown_min": 30, "opt_short_pyramid_cap_mode": "hour4",
        "l_trailBase": 3.5, "l_trailBaseDay": 3.5, "l_trailBaseNight": 3.5, "adxThresh": 30,
        "opt_ml_gate": {"variant": "G2", "session_cum_vol_rel20_threshold": 0.7277710401830155}}
CASES = {"base_mtfpatch": {}}
CASES.update({f"s_trailMult={v}": {"s_trailMult": v} for v in (2.7, 2.85, 3.15, 3.3)})
CASES.update({f"s_pyramid_dist={v}": {"s_pyramid_dist": v} for v in (0.9, 0.95, 1.05, 1.1)})
CASES.update({f"l_emaLenShort={v}": {"l_emaLenShort": v} for v in (110, 115, 120, 130, 135, 140)})
CASES.update({f"l_emaLenLong={v}": {"l_emaLenLong": v} for v in (115, 120, 125, 135, 140, 145)})
CASES.update({f"mtf_long_len={v}": {"mtf_long_len": v} for v in (80, 100, 160, 200)})
CASES.update({f"mtf_short_len={v}": {"mtf_short_len": v} for v in (80, 100, 150, 200)})
def go(name):
    out = HERE / "fine" / f"{name}.csv"
    if out.exists(): return
    t = mlg.run(mlg.load_1min(DATA), p={**BASE, **CASES[name]}, intrabar_mode="1min"); t["case"] = name
    t.to_csv(out, index=False, encoding="utf-8")
if __name__ == "__main__":
    (HERE / "fine").mkdir(exist_ok=True)
    with Pool(3) as pool: pool.map(go, list(CASES))
    print("done", len(CASES))
