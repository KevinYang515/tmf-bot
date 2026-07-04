# -*- coding: utf-8 -*-
"""秒級出場(2s/3s/5s)在 gap>=0.5% 上的 walk-forward + 加停損保護的混合版檢驗。"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
POINT_VAL, COMMISSION, EXIT_SLIP = 10, 5.6, 5

info = pd.read_csv(BASE / "gap_ticks" / "gap_days_selected_2026.csv").set_index("date")
MONDAY_INFO = {
    "2026-05-04": {"open": 40423.0, "night_close": 39389.0},
    "2026-05-11": {"open": 42216.0, "night_close": 42446.0},
    "2026-05-18": {"open": 40170.0, "night_close": 40700.0},
    "2026-05-25": {"open": 43183.0, "night_close": 42636.0},
    "2026-06-01": {"open": 45457.0, "night_close": 45079.0},
    "2026-06-15": {"open": 45709.0, "night_close": 44791.0},
    "2026-06-29": {"open": 44790.0, "night_close": 44994.0},
}
_CACHE = {}


def load_tick(d, tick_dir="gap_ticks"):
    key = (d, tick_dir)
    if key in _CACHE: return _CACHE[key]
    fp = BASE / tick_dir / f"MXF_{d}.csv"
    if not fp.exists():
        _CACHE[key] = None; return None
    t = pd.read_csv(fp)
    t["ts"] = pd.to_datetime(t["ts"])
    t = t[t["ts"].dt.strftime("%H:%M:%S") >= "08:45:00"].sort_values("ts")
    if len(t) < 50:
        _CACHE[key] = None; return None
    r = (t["close"].values.astype(np.float64), (t["ts"] - t["ts"].iloc[0]).dt.total_seconds().values)
    _CACHE[key] = r
    return r


def sim_hold(px, sec, s, hold_s, stop=None):
    """N 秒後全出；可選 tick 停損（同現行策略的監控邏輯）。進場無滑價、出場滑價5pt。"""
    mask = sec <= hold_s
    p = px[mask]
    if len(p) < 2: return None
    fav = s * (p - p[0])
    if stop is not None and (fav <= -stop).any():
        return -stop - EXIT_SLIP - COMMISSION
    idx = np.searchsorted(sec, hold_s)
    if idx >= len(px): idx = len(px) - 1
    return s * (px[idx] - px[0]) - EXIT_SLIP - COMMISSION


def agg(pnls):
    p = np.array([x for x in pnls if x is not None]) * POINT_VAL
    if len(p) == 0: return None
    wins = p[p > 0]; losses = p[p < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {"n": len(p), "total": p.sum(), "EV": p.mean(), "win%": (p > 0).mean() * 100, "PF": pf, "worst": p.min()}


def fmt(r, label, w=34):
    if r is None: return f"  {label:<{w}s}  (n=0)"
    return (f"  {label:<{w}s} n={r['n']:>3d} total={r['total']:>+9,.0f} EV={r['EV']:>+7,.0f} "
            f"win={r['win%']:>5.1f}% PF={r['PF']:>5.2f} worst={r['worst']:>+8,.0f}")


rows = []
for d in info.index:
    if load_tick(d, "gap_ticks") is None: continue
    rows.append((d, info.loc[d, "gap_night_pct"], "gap_ticks"))
for d, mi in MONDAY_INFO.items():
    if load_tick(d, "gap_ticks_monday") is None: continue
    rows.append((d, (mi["open"] - mi["night_close"]) / mi["night_close"] * 100, "gap_ticks_monday"))

DL = [(d, td, int(np.sign(g))) for d, g, td in rows if abs(g) >= 0.5]
h1 = [x for x in DL if x[0] <= "2026-03-31"]
h2 = [x for x in DL if x[0] > "2026-03-31"]

print(f"gap>=0.5% n={len(DL)} (H1 {len(h1)} / H2 {len(h2)})")
print()
print("基準: TP80/S30/cap300 全樣本 EV+172 (H1+524/H2+84)")
print()
for hold in [2, 3, 5]:
    for stop in [None, 30, 50]:
        r = agg([sim_hold(*load_tick(d, td), s, hold, stop) for d, td, s in DL])
        r1 = agg([sim_hold(*load_tick(d, td), s, hold, stop) for d, td, s in h1])
        r2 = agg([sim_hold(*load_tick(d, td), s, hold, stop) for d, td, s in h2])
        lab = f"hold={hold}s stop={stop}"
        print(fmt(r, lab))
        print(fmt(r1, "  H1"))
        print(fmt(r2, "  H2"))
        print()

print("逐日: hold=3s 無停損 (找出 worst -1056 那天)")
for d, td, s in sorted(DL):
    pnl = sim_hold(*load_tick(d, td), s, 3, None)
    if pnl is not None:
        print(f"  {d}  dir={'多' if s==1 else '空'}  pnl={pnl*POINT_VAL:+,.0f}")
