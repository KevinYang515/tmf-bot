"""Pre-declared: (1) 5m bars shifted by 1/2/3 minutes (strategy unchanged); (2) 4/6/10-minute bars with all bar-count
lengths scaled by 5/TF and all ATR multipliers scaled by sqrt(5/TF) (keeps time horizon and point distances ~equal).
Base v29+G2+ADX30. 60m MTF bars unchanged. G2 volume bins follow the same bars."""
from pathlib import Path
from multiprocessing import Pool
import inspect, math, pandas as pd
import engine_g2lb_wrapper as mlg
G = vars(mlg); G["_TF"], G["_OFF"] = 5, 0
def _sc(n): return max(2, int(round(n * 5 / G["_TF"])))
G["_sc"] = _sc
def build_bars(df1m, minutes):
    if minutes != 60:
        t = df1m["open_ts"]; off = pd.Timedelta(minutes=G["_OFF"])
        g = df1m.groupby((t - off).dt.floor(f"{G['_TF']}min") + off)
        bars = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                             "close": g["close"].last(), "close_ts": g["ts"].max()})
        bars.index.name = "open_ts"; return bars.reset_index()
    return mlg._base.build_bars(df1m, 60)
G["build_bars"] = build_bars
src = inspect.getsource(mlg._base.prepare)
for a, b in (('build_bars(df1m, 5)', 'build_bars(df1m, _TF)'), ('pine_ema(b5["close"], 10)', 'pine_ema(b5["close"], _sc(10))'),
             ('pine_ema(b5["close"], 30)', 'pine_ema(b5["close"], _sc(30))'), ('atr(b5, 14)', 'atr(b5, _sc(14))'),
             ('b5["high"].rolling(20)', 'b5["high"].rolling(_sc(20))'), ('b5["low"].rolling(20)', 'b5["low"].rolling(_sc(20))')):
    assert src.count(a) == 1, a; src = src.replace(a, b)
exec(compile(src, "prepare_tf", "exec"), G)
gsrc = inspect.getsource(mlg._g2_vf).replace('    if lb == 20:\n        return volume_features(df1, b5)\n', '')
gsrc = gsrc.replace('minute["bin"] = minute["open_ts"].dt.floor("5min")',
                    'minute["bin"] = (minute["open_ts"] - pd.Timedelta(minutes=_OFF)).dt.floor(f"{_TF}min") + pd.Timedelta(minutes=_OFF)')
assert "_OFF" in gsrc; exec(compile(gsrc, "g2vf_tf", "exec"), G)
HERE = Path(__file__).resolve().parent
DATA = HERE / "mxf_1min_2020_20261031.csv"
BASE = {**mlg.P, "opt_stale_hr": 10, "opt_cooldown_min": 30, "opt_short_pyramid_cap_mode": "hour4",
        "l_trailBase": 3.5, "l_trailBaseDay": 3.5, "l_trailBaseNight": 3.5, "adxThresh": 30,
        "opt_ml_gate": {"variant": "G2", "session_cum_vol_rel20_threshold": 0.7277710401830155, "lookback": 20}}
LENS = ["l_emaLenLong", "l_emaLenShort", "fastEmaLen", "l_cmdExitLen", "s_cmdExitLen", "adxLen"]
MULTS = ["l_slMult", "l_slMultDay", "l_slMultNight", "l_trailBase", "l_trailBaseDay", "l_trailBaseNight", "l_trailAdd",
         "l_pyramid_dist", "be_trigger", "s_slMult", "s_trailMult", "s_pyramid_dist", "addLossL", "addLossS", "g_trailMultDay", "g_trailMultNight"]
def params(tf):
    if tf == 5: return dict(BASE)
    p = dict(BASE); f = math.sqrt(5 / tf)
    for k in LENS: p[k] = max(2, int(round(BASE[k] * 5 / tf)))
    for k in MULTS: p[k] = BASE[k] * f
    return p
CASES = {"tf5_off0": (5, 0), "tf5_off1": (5, 1), "tf5_off2": (5, 2), "tf5_off3": (5, 3), "tf4": (4, 0), "tf6": (6, 0), "tf10": (10, 0)}
def go(name):
    out = HERE / "tfo" / f"{name}.csv"
    if out.exists(): return
    G["_TF"], G["_OFF"] = CASES[name]
    t = mlg.run(mlg.load_1min(DATA), p=params(CASES[name][0]), intrabar_mode="1min"); t["case"] = name
    t.to_csv(out, index=False, encoding="utf-8")
if __name__ == "__main__":
    (HERE / "tfo").mkdir(exist_ok=True)
    with Pool(3) as pool: pool.map(go, list(CASES))
    print("done")
