# -*- coding: utf-8 -*-
"""
User 提案 v3：不是「無門檻」，是「把 0.5% 門檻放寬（調低）」，同時用新發現的
3秒出場+停損50。之前門檻 sweep 用的是舊 TP80/S30/cap300，秒級出場沒有配過
不同門檻測試 —— 這是真正的空白，補上。
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent

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


def load_tick(fp, after_time="08:45:00"):
    if fp in _CACHE:
        return _CACHE[fp]
    if not fp.exists():
        _CACHE[fp] = None
        return None
    t = pd.read_csv(fp)
    t["ts"] = pd.to_datetime(t["ts"])
    t = t[t["ts"].dt.strftime("%H:%M:%S") >= after_time].sort_values("ts")
    if len(t) < 50:
        _CACHE[fp] = None
        return None
    r = (t["close"].values.astype(np.float64),
         (t["ts"] - t["ts"].iloc[0]).dt.total_seconds().values)
    _CACHE[fp] = r
    return r


COMM, SLIP = 5.6, 5
POINT_VAL = 10


def sim(px, sec, s, hold_s, stop):
    mask = sec <= hold_s
    p = px[mask]
    if len(p) < 2: return None
    fav = s * (p - p[0])
    if stop is not None and (fav <= -stop).any():
        return -stop - SLIP - COMM
    idx = np.searchsorted(sec, hold_s)
    if idx >= len(px): idx = len(px) - 1
    return s * (px[idx] - px[0]) - SLIP - COMM


def agg(pnls):
    p = np.array([x for x in pnls if x is not None]) * POINT_VAL
    if len(p) == 0: return None
    wins = p[p > 0]; losses = p[p < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {"n": len(p), "total": p.sum(), "EV": p.mean(),
            "win%": (p > 0).mean() * 100, "PF": pf, "worst": p.min()}


def fmt(r, label, w=34):
    if r is None: return f"  {label:<{w}s}  (n=0)"
    return (f"  {label:<{w}s} n={r['n']:>3d} total={r['total']:>+9,.0f} EV={r['EV']:>+7,.0f} "
            f"win={r['win%']:>5.1f}% PF={r['PF']:>5.2f} worst={r['worst']:>+8,.0f}")


rows = []
for d in info.index:
    fp = BASE / "gap_ticks" / f"MXF_{d}.csv"
    if load_tick(fp) is None: continue
    rows.append((d, info.loc[d, "gap_night_pct"], fp))
for d, mi in MONDAY_INFO.items():
    fp = BASE / "gap_ticks_monday" / f"MXF_{d}.csv"
    if load_tick(fp) is None: continue
    rows.append((d, (mi["open"] - mi["night_close"]) / mi["night_close"] * 100, fp))

print("=" * 108)
print("門檻 sweep × 3秒出場+停損50 (完整區間, 0.15%~0.7%)")
print("=" * 108)
for th in [0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6, 0.7]:
    dl = [(d, fp, int(np.sign(g))) for d, g, fp in rows if abs(g) >= th and g != 0]
    r = agg([sim(*load_tick(fp), s, 3, 50, ) for d, fp, s in dl])
    print(fmt(r, f"th={th}%"))

print()
print("=" * 108)
print("同上，但門檻只放寬到 0.3%/0.35%/0.4%（不是全開），逐日看新增進來的那些日子表現")
print("=" * 108)
for th in [0.3, 0.35, 0.4]:
    print(f"--- 門檻 {th}%，跟現行0.5%相比新增的日子 ---")
    dl_new = [(d, g, fp) for d, g, fp in rows if th <= abs(g) < 0.5 and g != 0]
    for d, g, fp in sorted(dl_new):
        s = int(np.sign(g))
        pnl = sim(*load_tick(fp), s, 3, 50)
        flag = "  <== user關注" if d in ("2026-06-29",) else ""
        if pnl is not None:
            print(f"    {d}  gap={g:+.2f}%  dir={'多' if s==1 else '空'}  pnl={pnl*POINT_VAL:+,.0f}{flag}")
    r = agg([sim(*load_tick(fp), int(np.sign(g)), 3, 50) for d, g, fp in dl_new])
    print(fmt(r, f"  僅新增日子小計"))
    print()

print("=" * 108)
print("Walk-forward: 門檻 0.3%/0.35%/0.4%/0.5% 在 3秒出場下的 H1/H2 穩定性")
print("=" * 108)
for th in [0.3, 0.35, 0.4, 0.5]:
    dl = [(d, fp, int(np.sign(g))) for d, g, fp in rows if abs(g) >= th and g != 0]
    h1 = [x for x in dl if x[0] <= "2026-03-31"]
    h2 = [x for x in dl if x[0] > "2026-03-31"]
    print(f"--- th={th}% ---")
    print(fmt(agg([sim(*load_tick(fp), s, 3, 50) for d, fp, s in dl]), "  全樣本"))
    print(fmt(agg([sim(*load_tick(fp), s, 3, 50) for d, fp, s in h1]), "  H1"))
    print(fmt(agg([sim(*load_tick(fp), s, 3, 50) for d, fp, s in h2]), "  H2"))
