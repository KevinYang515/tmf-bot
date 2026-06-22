"""
針對 2026 / 2025H2 行情重跑 exit sweep
看「全期最佳」跟「2026 最佳」是否一致
"""
import pandas as pd, numpy as np
from pathlib import Path
import sys

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

exec(open(BASE / "sweep_cutoff_exit.py", encoding="utf-8").read().split('CUTOFFS =')[0])

THRESHOLD = 0.05
CUTOFF = (23, 0)


def get_sig(d):
    if d not in intraday.index: return 0
    raw = intraday.loc[d, "nq_1500"]
    if pd.isna(raw): return 0
    pct = float(raw) / 18000 * 100
    if abs(pct) < THRESHOLD: return 0
    return 1 if pct > 0 else -1


def sim_D_param(entry, bars, direction, trail, init_stop):
    hi, lo, cl = bars
    n = len(hi); be = entry + direction * SLIPPAGE
    cur_stop = be - direction * init_stop; peak = be
    exit_p = None
    for i in range(n):
        if direction == 1 and lo[i] <= cur_stop:
            exit_p = cur_stop; break
        if direction == -1 and hi[i] >= cur_stop:
            exit_p = cur_stop; break
        c = cl[i]
        if direction == 1:
            if c > peak:
                peak = c
                ns = peak - trail
                if ns > cur_stop: cur_stop = ns
        else:
            if c < peak:
                peak = c
                ns = peak + trail
                if ns < cur_stop: cur_stop = ns
    if exit_p is None: exit_p = cl[-1]
    return (2 * (direction * (exit_p - be)) - 2 * COMMISSION) * POINT_VAL


def sim_E_activation(entry, bars, direction, activation, trail, init_stop):
    hi, lo, cl = bars
    n = len(hi); be = entry + direction * SLIPPAGE
    cur_stop = be - direction * init_stop; peak = be
    activated = False; exit_p = None
    activation_p = be + direction * activation
    for i in range(n):
        if direction == 1 and lo[i] <= cur_stop:
            exit_p = cur_stop; break
        if direction == -1 and hi[i] >= cur_stop:
            exit_p = cur_stop; break
        c = cl[i]
        if not activated:
            if direction == 1 and c >= activation_p: activated = True; peak = c
            if direction == -1 and c <= activation_p: activated = True; peak = c
        if activated:
            if direction == 1:
                if c > peak:
                    peak = c
                    ns = peak - trail
                    if ns > cur_stop: cur_stop = ns
            else:
                if c < peak:
                    peak = c
                    ns = peak + trail
                    if ns < cur_stop: cur_stop = ns
    if exit_p is None: exit_p = cl[-1]
    return (2 * (direction * (exit_p - be)) - 2 * COMMISSION) * POINT_VAL


def run_with_dates(sim_fn, **kw):
    records = []
    for d in intraday.index:
        sig = get_sig(d)
        if sig == 0: continue
        bars = build_bars(d, CUTOFF)
        if bars is None: continue
        entry = get_open(d)
        if entry is None: continue
        p = sim_fn(entry, bars, sig, **kw)
        records.append({"date": d, "pnl": p})
    return pd.DataFrame(records)


def stats(pnls):
    if len(pnls) == 0: return None
    pnls = np.array(pnls)
    cum = np.cumsum(pnls); peak = np.maximum.accumulate(cum); dd = peak - cum
    sh = round(pnls.mean()/pnls.std()*np.sqrt(252), 2) if pnls.std() > 0 else 0
    return {
        "n": len(pnls),
        "total": int(pnls.sum()),
        "EV": int(pnls.mean()),
        "win%": round((pnls > 0).mean()*100, 1),
        "Sharpe": sh,
        "maxDD": int(dd.max()),
        "minD": int(pnls.min()),
        "maxD": int(pnls.max()),
    }


CONFIGS = [
    # (label, sim_fn, kwargs)
    ("A +100/+200 stop=50", sim_A, {}),
    ("A +100/+200 stop=30", sim_A, {"stop": 30}),
    ("A +150/+300 stop=50", sim_A, {"tp1": 150, "tp2": 300, "stop": 50}),
    ("A +200/+400 stop=50", sim_A, {"tp1": 200, "tp2": 400, "stop": 50}),
    ("D trail=30 stop=30", sim_D_param, {"trail": 30, "init_stop": 30}),
    ("D trail=50 stop=30 ★", sim_D_param, {"trail": 50, "init_stop": 30}),
    ("D trail=50 stop=50", sim_D_param, {"trail": 50, "init_stop": 50}),
    ("D trail=75 stop=50", sim_D_param, {"trail": 75, "init_stop": 50}),
    ("E act=50 trail=50 stop=50", sim_E_activation, {"activation": 50, "trail": 50, "init_stop": 50}),
    ("E act=75 trail=50 stop=50", sim_E_activation, {"activation": 75, "trail": 50, "init_stop": 50}),
    ("E act=150 trail=50 stop=50", sim_E_activation, {"activation": 150, "trail": 50, "init_stop": 50}),
]

# 跑全部 config，拿到 per-trade pnl，再按期間切
ALL = {}
for label, fn, kw in CONFIGS:
    df = run_with_dates(fn, **kw)
    df["half"] = df["date"].apply(lambda x: f"{x[:4]}H1" if x[5:7] <= "06" else f"{x[:4]}H2")
    ALL[label] = df

# 對每個 period 排名
PERIODS = ["全期", "2024H1", "2024H2", "2025H1", "2025H2", "2026H1", "2025H2+2026H1"]

print("=" * 130)
print(f"【1500 D/A/E 在不同期間的 EV/Sharpe — threshold={THRESHOLD}%, cutoff=23:00】")
print("=" * 130)

for period in PERIODS:
    print(f"\n>>> {period}")
    print(f"  {'config':<32s} {'n':>4s} {'total':>9s} {'EV':>7s} {'win%':>6s} {'Sharpe':>7s} {'maxDD':>8s}")
    rows = []
    for label, df in ALL.items():
        if period == "全期":
            sub = df
        elif period == "2025H2+2026H1":
            sub = df[df["date"] >= "2025-07"]
        else:
            sub = df[df["half"] == period]
        s = stats(sub["pnl"].values)
        if s is None: continue
        rows.append((label, s))
        print(f"  {label:<32s} {s['n']:>4d} {s['total']:>+9,d} {s['EV']:>+7,d} "
              f"{s['win%']:>5.1f}% {s['Sharpe']:>+7.2f} {s['maxDD']:>+8,d}")
    # mark top by Sharpe and by EV
    if rows:
        best_sh = max(rows, key=lambda r: r[1]["Sharpe"])
        best_ev = max(rows, key=lambda r: r[1]["EV"])
        print(f"  ★ best Sharpe: {best_sh[0]} ({best_sh[1]['Sharpe']:+.2f})")
        print(f"  ★ best EV:     {best_ev[0]} ({best_ev[1]['EV']:+,d})")

# 額外：每期前 3 名一覽
print()
print("=" * 130)
print("【每期 EV Top 3 + Sharpe Top 3 對照】")
print("=" * 130)
print(f"  {'period':<18s} {'EV Top 3':<60s} {'Sharpe Top 3'}")
for period in PERIODS:
    rows = []
    for label, df in ALL.items():
        if period == "全期":
            sub = df
        elif period == "2025H2+2026H1":
            sub = df[df["date"] >= "2025-07"]
        else:
            sub = df[df["half"] == period]
        s = stats(sub["pnl"].values)
        if s: rows.append((label, s))
    if not rows: continue
    top_ev = sorted(rows, key=lambda r: -r[1]["EV"])[:3]
    top_sh = sorted(rows, key=lambda r: -r[1]["Sharpe"])[:3]
    ev_s = " | ".join(f"{r[0].split('+')[0].split(' ')[0]}={r[1]['EV']:+d}" for r in top_ev)
    sh_s = " | ".join(f"{r[0].split('+')[0].split(' ')[0]}={r[1]['Sharpe']:+.2f}" for r in top_sh)
    print(f"  {period:<18s} {ev_s:<60s} {sh_s}")
