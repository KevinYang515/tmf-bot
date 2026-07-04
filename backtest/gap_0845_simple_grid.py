# -*- coding: utf-8 -*-
"""
0845 跳空順勢策略 — 乾淨的完整網格，直接回答四個問題：
  Q1 跳空多大才進場（門檻）
  Q2 停利 TP 設多少（含「不設TP純時間出場」）
  Q3 停損設多少（含「不設停損純時間出場」）
  Q4 時間上限多久（60s/120s/180s/300s）
資料：2026-01~07 的開盤 tick（61 天 + 7 個週一回填 = 68 天）。
進場 = 開盤第一筆成交價 + 5pt 滑價，成本 5.6pt/回合（同現行回測假設）。
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
    """tp=None 代表不設停利, stop=None 代表不設停損；時間到強制平倉"""
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


def fmt(r, label, w=38):
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

def build(th):
    return [(d, td, int(np.sign(g))) for d, g, td in rows if abs(g) >= th]

print("=" * 105)
print("Q1) 門檻：跳空多大才進場（其餘固定 TP80 / 停損30 / 300秒）")
print("=" * 105)
for th in [0.3, 0.4, 0.5, 0.6, 0.7]:
    dl = build(th)
    r = agg([sim(*load_tick(d, td), s, 80, 30, 300) for d, td, s in dl])
    print(fmt(r, f"|gap| >= {th}%"))

DL = build(0.5)

print()
print("=" * 105)
print("Q2) 停利 TP：多少點（門檻固定0.5% / 停損30 / 300秒）。None=不設TP,時間到才出")
print("=" * 105)
for tp in [40, 60, 80, 100, 120, 150, None]:
    r = agg([sim(*load_tick(d, td), s, tp, 30, 300) for d, td, s in DL])
    print(fmt(r, f"TP={tp}"))

print()
print("=" * 105)
print("Q3) 停損：多少點（門檻0.5% / TP80 / 300秒）。None=不設停損,靠時間上限保護")
print("=" * 105)
for stop in [15, 20, 30, 40, 50, 80, None]:
    r = agg([sim(*load_tick(d, td), s, 80, stop, 300) for d, td, s in DL])
    print(fmt(r, f"stop={stop}"))

print()
print("=" * 105)
print("Q4) 時間上限：幾秒強制平倉（門檻0.5% / TP80 / 停損30）")
print("=" * 105)
for cap in [30, 60, 120, 180, 300, 600]:
    r = agg([sim(*load_tick(d, td), s, 80, 30, cap) for d, td, s in DL])
    print(fmt(r, f"cap={cap}s"))

print()
print("=" * 105)
print("Q2+Q4 變體) 你說的『過一分鐘沒碰到TP就平倉』：TP80+無停損+不同時間上限")
print("=" * 105)
for cap in [30, 60, 120, 180, 300]:
    r = agg([sim(*load_tick(d, td), s, 80, None, cap) for d, td, s in DL])
    print(fmt(r, f"TP80/無停損/{cap}s強制出"))

print()
print("=" * 105)
print("純時間出場對照組：不設TP不設停損，進場後固定 N 秒出場（看慣性本身活多久）")
print("=" * 105)
for cap in [10, 30, 60, 120, 180, 300, 600]:
    r = agg([sim(*load_tick(d, td), s, None, None, cap) for d, td, s in DL])
    print(fmt(r, f"進場後{cap}s出場"))
