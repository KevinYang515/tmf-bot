"""Pre-declared scan of G2 same-clock lookback {5,10,20,40,60}; threshold re-frozen per lookback at the
20th pct of v28 Cmd lots entered 2020-03..2023-12 (decision bars from ml_features_panel). Base v29+G2+ADX30."""
from pathlib import Path
from multiprocessing import Pool
import pandas as pd, numpy as np
import engine_g2lb_wrapper as mlg
HERE = Path(__file__).resolve().parent
DATA = HERE / "mxf_1min_2020_20261031.csv"
LBS = (5, 10, 20, 40, 60)
V = {**mlg.P, "opt_stale_hr": 10, "opt_cooldown_min": 30, "opt_short_pyramid_cap_mode": "hour4",
     "l_trailBase": 3.5, "l_trailBaseDay": 3.5, "l_trailBaseNight": 3.5, "adxThresh": 30}
def thresholds():
    df = mlg.load_1min(DATA); b5 = mlg.build_bars(df, 5)
    pan = pd.read_csv(HERE / "ml_features_panel.csv", usecols=["kind", "entry_ts", "decision_close_ts", "session_cum_vol_rel20"], parse_dates=["entry_ts", "decision_close_ts"])
    pan = pan[(pan.kind == "Cmd") & (pan.entry_ts >= "2020-03-02") & (pan.entry_ts <= "2023-12-31 23:59:59")]
    out = {}
    for lb in LBS:
        f = mlg._g2_vf(df, b5.copy(), lb)[["close_ts", "session_cum_vol_rel20"]].rename(columns={"close_ts": "decision_close_ts", "session_cum_vol_rel20": "rel"})
        m = pan.merge(f, on="decision_close_ts", how="left")
        if lb == 20: print("lb20 feature match:", np.allclose(m.rel, m.session_cum_vol_rel20, equal_nan=True))
        out[lb] = float(m.rel.quantile(0.20)); print(lb, "n", m.rel.notna().sum(), "threshold", round(out[lb], 6))
    return out
def go(arg):
    lb, th = arg
    t = mlg.run(mlg.load_1min(DATA), p={**V, "opt_ml_gate": {"variant": "G2", "session_cum_vol_rel20_threshold": th, "lookback": lb}}, intrabar_mode="1min")
    t["case"] = f"G2_lb{lb}"; return t
if __name__ == "__main__":
    th = thresholds(); pd.Series(th).to_csv(HERE / "g2lb_thresholds.csv")
    with Pool(3) as pool: T = pd.concat(pool.map(go, list(th.items())))
    T.to_csv(HERE / "g2lb_20261031_trades.csv", index=False, encoding="utf-8-sig"); print("done", T.groupby("case").size().to_dict())
