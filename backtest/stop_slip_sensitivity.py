"""停損額外滑價敏感度 — 0845 gap_night>=0.5% 甜蜜點 TP80/S30/5min"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
TICK_DIR = BASE / "gap_ticks"
POINT_VAL, COMMISSION, SLIPPAGE = 10, 5.6, 5

info = pd.read_csv(TICK_DIR / "gap_days_selected_2026.csv").set_index("date")
data = {}
for d in info.index:
    fp = TICK_DIR / f"MXF_{d}.csv"
    if not fp.exists(): continue
    t = pd.read_csv(fp)
    t["ts"] = pd.to_datetime(t["ts"])
    t = t[t["ts"].dt.strftime("%H:%M:%S") >= "08:45:00"].sort_values("ts")
    if len(t) < 100: continue
    data[d] = (t["close"].values.astype(np.float64),
               (t["ts"] - t["ts"].iloc[0]).dt.total_seconds().values)


def sim(px, sec, s, tp, stop, tmax_s, stop_slip):
    p = px[sec <= tmax_s]
    if len(p) < 2: return None
    be = p[0] + s * SLIPPAGE
    fav = s * (p - be)
    i_tp = (fav >= tp).argmax() if (fav >= tp).any() else len(p)
    i_st = (fav <= -stop).argmax() if (fav <= -stop).any() else len(p)
    if i_tp < i_st: return tp - COMMISSION
    if i_st < len(p): return -stop - stop_slip - COMMISSION
    return fav[-1] - COMMISSION


dl = [(d, int(np.sign(info.loc[d, "gap_night_pct"]))) for d in data
      if pd.notna(info.loc[d, "gap_night_pct"]) and abs(info.loc[d, "gap_night_pct"]) >= 0.5]
print(f"gap_night>=0.5%  n={len(dl)}   (0845 甜蜜點 TP80/S30/5min)")
print(f"{'停損額外滑價':<10s} {'EV':>8s} {'total':>9s} {'PF':>6s}")
for ss in [0, 2, 5, 10]:
    pnls = [sim(*data[d], s, 80, 30, 300, ss) for d, s in dl]
    p = np.array([x for x in pnls if x is not None]) * POINT_VAL
    wins = p[p > 0]; losses = p[p < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    print(f"  +{ss}pt      {p.mean():>+8,.0f} {p.sum():>+9,.0f} {pf:>6.2f}")
