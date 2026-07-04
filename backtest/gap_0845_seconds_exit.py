# -*- coding: utf-8 -*-
"""
驗證圖中交易者的出場風格：進場=集合競價(同我們)，但 1~10 秒內就全部出光，
不抱到分鐘級。他 06/29(-0.45%)、07/02(夜盤gap只有-0.17%)這種小跳空日也做。

測試：全部 68 天，方向=sign(gap_night)，進場=開盤第一筆(集合競價價,不加滑價,
因為預掛市價單跟所有人拿同一個撮合價；出場加 5pt 市價滑價)，
出場=固定 N 秒後全出，N = 2/3/5/10/20/30/60。
分三個 gap 大小區間看：<0.3% / 0.3~0.5% / >=0.5%。
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
POINT_VAL, COMMISSION = 10, 5.6
EXIT_SLIP = 5  # 出場市價滑價；進場集合競價不加

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


def sim_time_exit(px, sec, s, hold_s):
    """進場=第一筆(無滑價)，hold_s 秒後第一筆 tick 市價出場(扣出場滑價與成本)"""
    idx = np.searchsorted(sec, hold_s)
    if idx >= len(px): idx = len(px) - 1
    if idx < 1: return None
    raw = s * (px[idx] - px[0])
    return raw - EXIT_SLIP - COMMISSION


def agg(pnls):
    p = np.array([x for x in pnls if x is not None]) * POINT_VAL
    if len(p) == 0: return None
    wins = p[p > 0]; losses = p[p < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {"n": len(p), "total": p.sum(), "EV": p.mean(),
            "win%": (p > 0).mean() * 100, "PF": pf, "worst": p.min()}


def fmt(r, label, w=26):
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

BUCKETS = [("<0.3%", 0.0, 0.3), ("0.3~0.5%", 0.3, 0.5), (">=0.5%", 0.5, 99.0), ("全部", 0.0, 99.0)]

for name, lo, hi in BUCKETS:
    dl = [(d, td, int(np.sign(g))) for d, g, td in rows if lo <= abs(g) < hi and g != 0]
    print("=" * 100)
    print(f"gap 區間 {name}  (n={len(dl)})  — 固定 N 秒後全出（進場無滑價、出場滑價5pt、成本5.6pt）")
    print("=" * 100)
    for hold in [2, 3, 5, 10, 20, 30, 60]:
        r = agg([sim_time_exit(*load_tick(d, td), s, hold) for d, td, s in dl])
        print(fmt(r, f"hold={hold}s"))

# TXF 成本結構對照：一回合約 2.3 點、出場滑價假設 1 點（大台流動性厚）
print()
print("=" * 100)
print("同樣的秒級出場，換成 TXF 成本結構（成本2.3pt+出場滑價1pt, 點值200）— 圖中交易者的世界")
print("=" * 100)


def sim_txf(px, sec, s, hold_s):
    idx = np.searchsorted(sec, hold_s)
    if idx >= len(px): idx = len(px) - 1
    if idx < 1: return None
    raw = s * (px[idx] - px[0])
    return raw - 1 - 2.3


for name, lo, hi in BUCKETS:
    dl = [(d, td, int(np.sign(g))) for d, g, td in rows if lo <= abs(g) < hi and g != 0]
    print(f"--- gap {name} (n={len(dl)}) ---")
    for hold in [3, 5, 10]:
        p = np.array([x for x in [sim_txf(*load_tick(d, td), s, hold) for d, td, s in dl] if x is not None]) * 200
        if len(p) == 0: continue
        wins = p[p > 0]; losses = p[p < 0]
        pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
        print(f"  hold={hold}s  n={len(p)}  total={p.sum():>+10,.0f}  EV={p.mean():>+8,.0f}  win={(p>0).mean()*100:.1f}%  PF={pf:.2f}  worst={p.min():+,.0f}")
