"""
降 threshold 增加單量的 sweep
=================================
1500: 用 D 純 trailing 50, cutoff 23:00; 掃 |NQ%| in [0.00, 0.05, 0.10, 0.15, 0.20, 0.30]
0845: 用 A 固定 TP+100/+200 stop=-150, cutoff 13:44; 掃 [0.00, 0.10, 0.20, 0.30, 0.50]
"""
import pandas as pd, numpy as np
from pathlib import Path
import sys

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

# 套用 sweep_cutoff_exit 的 sim/build/get_open 函數
exec(open(BASE / "sweep_cutoff_exit.py", encoding="utf-8").read().split('CUTOFFS =')[0])

# 補 open08 進 by_date
for d, bd in by_date.items():
    g = df_min[df_min["date"] == d]
    op = g[g["time"] == "08:46"]
    if not op.empty:
        bd["open08"] = float(op.iloc[0]["Open"])
    if "open08" not in bd:
        bd["open08"] = None


def build_bars_0845(d, cutoff_hm):
    ch, cm = cutoff_hm
    cutoff_min = ch*60+cm
    bd = by_date.get(d)
    if bd is None: return None
    mask = (bd["minute"] >= 8*60+46) & (bd["minute"] <= cutoff_min)
    if not mask.any(): return None
    return bd["hi"][mask], bd["lo"][mask], bd["cl"][mask]


def get_open_0845(d):
    bd = by_date.get(d)
    if bd is None: return None
    bo = bd["open08"]
    if d in daily_dict:
        v = daily_dict[d].get("open_0845")
        if v is not None and not pd.isna(v) and bo is not None:
            if abs(float(v) - bo) <= 200:
                return float(v)
    return bo


def get_signal_with_th(d, col, th):
    if d not in intraday.index: return 0
    raw = intraday.loc[d, col]
    if pd.isna(raw): return 0
    pct = float(raw) / 18000 * 100
    if abs(pct) < th: return 0
    return 1 if pct > 0 else (-1 if pct < 0 else 0)


def stats(pnls):
    if len(pnls) == 0: return None
    pnls = np.array(pnls)
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    sh = round(pnls.mean()/pnls.std()*np.sqrt(252), 2) if pnls.std() > 0 else 0
    return {
        "n": len(pnls),
        "total": int(pnls.sum()),
        "EV": int(pnls.mean()),
        "win%": round((pnls > 0).mean()*100, 1),
        "Sharpe": sh,
        "max_dd": int(dd.max()),
        "max_loss": int(pnls.min()),
    }


# ============== 1500 D ==============
print("=" * 110)
print("【1500 session — 策略 D 純 trailing 50, cutoff 23:00 — threshold sweep】")
print("=" * 110)
print(f"  {'thr%':<6s} {'n':>4s} {'/year':>6s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>7s} {'maxDD':>10s} {'wrst':>8s}")

YEARS = 2.5
RESULTS_1500 = []
for th in [0.00, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50]:
    pnls = []
    for d in intraday.index:
        sig = get_signal_with_th(d, "nq_1500", th)
        if sig == 0: continue
        bars = build_bars(d, (23, 0))
        if bars is None: continue
        entry = get_open(d)
        if entry is None: continue
        pnls.append(sim_D(entry, bars, sig))
    s = stats(pnls)
    if s is None: continue
    s["thr"] = th
    RESULTS_1500.append(s)
    print(f"  {th:<6.2f} {s['n']:>4d} {s['n']/YEARS:>6.0f} {s['total']:>+10,d} {s['EV']:>+8,d} "
          f"{s['win%']:>5.1f}% {s['Sharpe']:>+7.2f} {s['max_dd']:>+10,d} {s['max_loss']:>+8,d}")

# ============== 0845 A ==============
print()
print("=" * 110)
print("【0845 session — 策略 A 固定 TP+100/+200 stop=-150, cutoff 13:44 — threshold sweep】")
print("=" * 110)
print(f"  {'thr%':<6s} {'n':>4s} {'/year':>6s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>7s} {'maxDD':>10s} {'wrst':>8s}")

RESULTS_0845 = []
for th in [0.00, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50]:
    pnls = []
    for d in intraday.index:
        sig = get_signal_with_th(d, "nq_0845", th)
        if sig == 0: continue
        bars = build_bars_0845(d, (13, 44))
        if bars is None: continue
        entry = get_open_0845(d)
        if entry is None: continue
        pnls.append(sim_A(entry, bars, sig, tp1=100, tp2=200, stop=150))
    s = stats(pnls)
    if s is None: continue
    s["thr"] = th
    RESULTS_0845.append(s)
    print(f"  {th:<6.2f} {s['n']:>4d} {s['n']/YEARS:>6.0f} {s['total']:>+10,d} {s['EV']:>+8,d} "
          f"{s['win%']:>5.1f}% {s['Sharpe']:>+7.2f} {s['max_dd']:>+10,d} {s['max_loss']:>+8,d}")

# 也順便看 0845 用 D 在低 threshold 是否變好
print()
print("=" * 110)
print("【0845 session — 策略 D 純 trailing 50 stop=-150 — threshold sweep（看會不會翻盤）】")
print("=" * 110)
print(f"  {'thr%':<6s} {'n':>4s} {'/year':>6s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>7s} {'maxDD':>10s}")

for th in [0.00, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50]:
    pnls = []
    for d in intraday.index:
        sig = get_signal_with_th(d, "nq_0845", th)
        if sig == 0: continue
        bars = build_bars_0845(d, (13, 44))
        if bars is None: continue
        entry = get_open_0845(d)
        if entry is None: continue
        pnls.append(sim_D(entry, bars, sig, trail=50, init_stop=150))
    s = stats(pnls)
    if s is None: continue
    print(f"  {th:<6.2f} {s['n']:>4d} {s['n']/YEARS:>6.0f} {s['total']:>+10,d} {s['EV']:>+8,d} "
          f"{s['win%']:>5.1f}% {s['Sharpe']:>+7.2f} {s['max_dd']:>+10,d}")

# 1500 也順便看 A
print()
print("=" * 110)
print("【1500 session — 策略 A 固定 TP+100/+200 stop=-50 — threshold sweep（對照）】")
print("=" * 110)
print(f"  {'thr%':<6s} {'n':>4s} {'/year':>6s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>7s} {'maxDD':>10s}")
for th in [0.00, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50]:
    pnls = []
    for d in intraday.index:
        sig = get_signal_with_th(d, "nq_1500", th)
        if sig == 0: continue
        bars = build_bars(d, (23, 0))
        if bars is None: continue
        entry = get_open(d)
        if entry is None: continue
        pnls.append(sim_A(entry, bars, sig))
    s = stats(pnls)
    if s is None: continue
    print(f"  {th:<6.2f} {s['n']:>4d} {s['n']/YEARS:>6.0f} {s['total']:>+10,d} {s['EV']:>+8,d} "
          f"{s['win%']:>5.1f}% {s['Sharpe']:>+7.2f} {s['max_dd']:>+10,d}")
