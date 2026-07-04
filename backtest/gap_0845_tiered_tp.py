# -*- coding: utf-8 -*-
"""
User 提案 v2：分段固定 TP（不是連續動態）。
  小跳空日（例如 0.15~0.3%、0.3~0.5%）固定用小 TP（30/40），
  大跳空日（>=0.5%）維持原本 TP80/S30。
把兩個小跳空區間各自單獨測：固定 TP 20~60 × 停損 10~30 全掃，
看有沒有任何一組能讓這段區間轉正。若有，再跟大跳空段合併看整體。
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
POINT_VAL, COMMISSION, SLIPPAGE = 10, 5.6, 5

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
    if key in _CACHE:
        return _CACHE[key]
    fp = BASE / tick_dir / f"MXF_{d}.csv"
    if not fp.exists():
        _CACHE[key] = None
        return None
    t = pd.read_csv(fp)
    t["ts"] = pd.to_datetime(t["ts"])
    t = t[t["ts"].dt.strftime("%H:%M:%S") >= "08:45:00"].sort_values("ts")
    if len(t) < 50:
        _CACHE[key] = None
        return None
    r = (t["close"].values.astype(np.float64),
         (t["ts"] - t["ts"].iloc[0]).dt.total_seconds().values)
    _CACHE[key] = r
    return r


def sim(px, sec, s, tp, stop, tmax_s):
    p = px[sec <= tmax_s]
    if len(p) < 2: return None
    be = p[0] + s * SLIPPAGE
    fav = s * (p - be)
    i_tp = (fav >= tp).argmax() if tp is not None and (fav >= tp).any() else len(p)
    i_st = (fav <= -stop).argmax() if stop is not None and (fav <= -stop).any() else len(p)
    if i_tp < i_st: return tp - COMMISSION
    if i_st < len(p): return -stop - COMMISSION
    return fav[-1] - COMMISSION


def agg(pnls):
    p = np.array([x for x in pnls if x is not None]) * POINT_VAL
    if len(p) == 0: return None
    wins = p[p > 0]; losses = p[p < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {"n": len(p), "total": p.sum(), "EV": p.mean(),
            "win%": (p > 0).mean() * 100, "PF": pf, "worst": p.min()}


def fmt(r, label, w=30):
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

CAP = 300

BUCKETS = [("0.15~0.3%", 0.15, 0.3), ("0.3~0.5%", 0.3, 0.5), ("0.15~0.5%(合併)", 0.15, 0.5)]
for name, lo, hi in BUCKETS:
    dl = [(d, td, int(np.sign(g))) for d, g, td in rows if lo <= abs(g) < hi]
    print("=" * 108)
    print(f"小跳空區間 {name}  (n={len(dl)})  — 固定 TP × 停損 全掃")
    print("=" * 108)
    best = []
    for tp in [15, 20, 25, 30, 40, 50, 60]:
        for stop in [10, 15, 20, 25, 30]:
            r = agg([sim(*load_tick(d, td), s, tp, stop, CAP) for d, td, s in dl])
            if r:
                best.append((r["EV"], tp, stop, r))
    best.sort(reverse=True)
    for ev, tp, stop, r in best[:6]:
        print(fmt(r, f"TP{tp}/S{stop}"))
    n_pos = sum(1 for ev, *_ in best if ev > 0)
    print(f"  ... 全部 {len(best)} 組合中 EV>0 的有 {n_pos} 組 ({n_pos/len(best)*100:.0f}%)")

# 若 0.3~0.5% 區間有正的組合，做 walk-forward 檢驗最好的那組
print()
print("=" * 108)
print("0.3~0.5% 區間最佳組合的 walk-forward 檢驗（H1 01-03 / H2 04-07）")
print("=" * 108)
dl_mid = [(d, td, int(np.sign(g))) for d, g, td in rows if 0.3 <= abs(g) < 0.5]
best_mid = []
for tp in [15, 20, 25, 30, 40, 50, 60]:
    for stop in [10, 15, 20, 25, 30]:
        r = agg([sim(*load_tick(d, td), s, tp, stop, CAP) for d, td, s in dl_mid])
        if r:
            best_mid.append((r["EV"], tp, stop))
best_mid.sort(reverse=True)
for ev, tp, stop in best_mid[:3]:
    h1 = [(d, td, s) for d, td, s in dl_mid if d <= "2026-03-31"]
    h2 = [(d, td, s) for d, td, s in dl_mid if d > "2026-03-31"]
    print(f"--- TP{tp}/S{stop} (全樣本EV {ev:+.0f}) ---")
    print(fmt(agg([sim(*load_tick(d, td), s, tp, stop, CAP) for d, td, s in h1]), "  H1"))
    print(fmt(agg([sim(*load_tick(d, td), s, tp, stop, CAP) for d, td, s in h2]), "  H2"))

print()
print("=" * 108)
print("0.3~0.5% 區間逐日明細（用區間內最佳 TP/停損）")
print("=" * 108)
ev0, tp0, stop0 = best_mid[0]
for d, g, td in sorted([(d, g, td) for d, g, td in rows if 0.3 <= abs(g) < 0.5]):
    s = int(np.sign(g))
    pnl = sim(*load_tick(d, td), s, tp0, stop0, CAP)
    flag = "  <== user關注" if d in ("2026-06-29",) else ""
    if pnl is not None:
        print(f"  {d}  gap={g:+.2f}%  dir={'多' if s==1 else '空'}  pnl={pnl*POINT_VAL:+,.0f}{flag}")
