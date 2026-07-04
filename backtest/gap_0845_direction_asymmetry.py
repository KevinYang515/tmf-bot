# -*- coding: utf-8 -*-
"""
0845 場的多空不對稱測試 -- 目前 1500 場已證實「只做空」有效(見 GAP_STRATEGY.md §3.2)，
但 0845 場從未做過同樣的測試(現行 0845 仍是多空都做)。

起因：user 觀察到 06/29, 06/30, 07/02 三個 0845『跳空開低』的日子，覺得應該順勢做空。
用現有 61 天 + 回填的 6 個週一，共 67 天的 tick 資料，依 gap_night_pct 正負分兩組，
分別看多空兩個方向獨立的 EV/勝率/PF，並做 threshold sweep 找每個方向各自的甜蜜點。
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
    "2026-06-29": {"open": 44790.0, "night_close": 44994.0},  # 補: 沒過門檻但user關注, gap=-0.45%
}

_CACHE = {}


def load_tick(d, tick_dir="gap_ticks", after_time="08:45:00"):
    key = (d, tick_dir)
    if key in _CACHE:
        return _CACHE[key]
    fp = BASE / tick_dir / f"MXF_{d}.csv"
    if not fp.exists():
        _CACHE[key] = None
        return None
    t = pd.read_csv(fp)
    t["ts"] = pd.to_datetime(t["ts"])
    t = t[t["ts"].dt.strftime("%H:%M:%S") >= after_time].sort_values("ts")
    if len(t) < 50:
        _CACHE[key] = None
        return None
    result = (t["close"].values.astype(np.float64), (t["ts"] - t["ts"].iloc[0]).dt.total_seconds().values)
    _CACHE[key] = result
    return result


def sim(px, sec, s, tp, stop, tmax_s):
    p = px[sec <= tmax_s]
    if len(p) < 2: return None
    be = p[0] + s * SLIPPAGE
    fav = s * (p - be)
    i_tp = (fav >= tp).argmax() if (fav >= tp).any() else len(p)
    i_st = (fav <= -stop).argmax() if (fav <= -stop).any() else len(p)
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


def fmt(r, label, w=34):
    if r is None: return f"  {label:<{w}s}  (n=0)"
    return (f"  {label:<{w}s} n={r['n']:>3d} total={r['total']:>+9,.0f} EV={r['EV']:>+7,.0f} "
            f"win={r['win%']:>5.1f}% PF={r['PF']:>5.2f} worst={r['worst']:>+8,.0f}")


# 建立完整資料集: 61 天(gap_ticks) + 7 個週一(gap_ticks_monday, 含06-29)
all_rows = []  # (date, gap_night_pct, tick_dir)
for d in info.index:
    if load_tick(d, "gap_ticks") is None: continue
    all_rows.append((d, info.loc[d, "gap_night_pct"], "gap_ticks"))
for d, mi in MONDAY_INFO.items():
    if load_tick(d, "gap_ticks_monday") is None: continue
    gap_pct = (mi["open"] - mi["night_close"]) / mi["night_close"] * 100
    all_rows.append((d, gap_pct, "gap_ticks_monday"))

print(f"總天數(含週一回填): {len(all_rows)}")

TP, STOP, CAP = 80, 30, 300

print("\n" + "#" * 100)
print("# 現行門檻 0.5%, TP80/S30/cap300 -- 多空分開看")
print("#" * 100)
dl = [(d, td, int(np.sign(g))) for d, g, td in all_rows if abs(g) >= 0.5]
longs = [(d, td, s) for d, td, s in dl if s == 1]
shorts = [(d, td, s) for d, td, s in dl if s == -1]
for lab, group in [("全部(混合多空,現行live設定)", dl), ("只做多(跳空向上)", longs), ("只做空(跳空向下)", shorts)]:
    r = agg([sim(*load_tick(d, td), s, TP, STOP, CAP) for d, td, s in group])
    print(fmt(r, lab))
    h1 = [(d, td, s) for d, td, s in group if d <= "2026-03-31"]
    h2 = [(d, td, s) for d, td, s in group if d > "2026-03-31"]
    r1 = agg([sim(*load_tick(d, td), s, TP, STOP, CAP) for d, td, s in h1])
    r2 = agg([sim(*load_tick(d, td), s, TP, STOP, CAP) for d, td, s in h2])
    if r1: print(fmt(r1, "  H1(01-03)"))
    if r2: print(fmt(r2, "  H2(04-07)"))

print("\n" + "#" * 100)
print("# Threshold sweep: 只做空(下跳空), 門檻 0.2%~0.6%, 看降低門檻是否還有效(對照06-29/07-02這種小gap)")
print("#" * 100)
for th in [0.15, 0.2, 0.3, 0.4, 0.5, 0.6]:
    grp = [(d, td, int(np.sign(g))) for d, g, td in all_rows if g <= -th]
    r = agg([sim(*load_tick(d, td), s, TP, STOP, CAP) for d, td, s in grp])
    print(fmt(r, f"th=-{th}% (只做空)"))

print("\n" + "#" * 100)
print("# Threshold sweep: 只做多(上跳空), 門檻 0.2%~0.6%, 對照組")
print("#" * 100)
for th in [0.15, 0.2, 0.3, 0.4, 0.5, 0.6]:
    grp = [(d, td, int(np.sign(g))) for d, g, td in all_rows if g >= th]
    r = agg([sim(*load_tick(d, td), s, TP, STOP, CAP) for d, td, s in grp])
    print(fmt(r, f"th=+{th}% (只做多)"))

print("\n" + "#" * 100)
print("# 逐日明細: 只做空, 門檻 0.2% (含 user 關注的 06-29/06-30/07-02)")
print("#" * 100)
for d, g, td in sorted(all_rows):
    if g <= -0.2:
        s = -1
        pnl = sim(*load_tick(d, td), s, TP, STOP, CAP)
        flag = "  <== user關注" if d in ("2026-06-29", "2026-06-30", "2026-07-02") else ""
        print(f"  {d}  gap_night={g:+.2f}%  pnl={pnl*POINT_VAL:+.0f}{flag}" if pnl is not None else f"  {d}  no tick{flag}")
