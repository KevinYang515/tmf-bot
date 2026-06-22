"""
1500 session 進階 exit 策略 sweep
目的：找出能讓 1500 EV / Sharpe 提高的 exit 設定

設定：
- threshold = 0.05% (新推薦)
- cutoff = 23:00
- 2 口進場

Sweep 三組：
1. D 不同 trail 寬度 (init hard stop fixed at 50)
2. A 不同 (TP1, TP2) 組合
3. E activation trailing — 進場後價格走 +X 點才開始 trail
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


# ─ 通用 D：pure trailing ─
def sim_D_param(entry, bars, direction, trail, init_stop):
    hi, lo, cl = bars
    n = len(hi)
    be = entry + direction * SLIPPAGE
    cur_stop = be - direction * init_stop
    peak = be
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


# ─ E: activation trailing — 走 +activation 點才開始 trail，否則用 hard stop ─
def sim_E_activation(entry, bars, direction, activation, trail, init_stop):
    """進場後要 close 達到 entry + direction * activation 才啟動 trailing
       啟動前用 hard stop。啟動後 stop 從 (peak - trail) 跟"""
    hi, lo, cl = bars
    n = len(hi)
    be = entry + direction * SLIPPAGE
    cur_stop = be - direction * init_stop
    peak = be
    activated = False
    exit_p = None
    activation_p = be + direction * activation
    for i in range(n):
        if direction == 1 and lo[i] <= cur_stop:
            exit_p = cur_stop; break
        if direction == -1 and hi[i] >= cur_stop:
            exit_p = cur_stop; break
        c = cl[i]
        # check activation
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


def run(sim_fn, **kw):
    pnls = []
    for d in intraday.index:
        sig = get_sig(d)
        if sig == 0: continue
        bars = build_bars(d, CUTOFF)
        if bars is None: continue
        entry = get_open(d)
        if entry is None: continue
        pnls.append(sim_fn(entry, bars, sig, **kw))
    return np.array(pnls)


def stats(pnls, label):
    if len(pnls) == 0: return None
    cum = np.cumsum(pnls); peak = np.maximum.accumulate(cum); dd = peak - cum
    sh = round(pnls.mean()/pnls.std()*np.sqrt(252), 2) if pnls.std() > 0 else 0
    return {
        "config": label,
        "n": len(pnls),
        "total": int(pnls.sum()),
        "EV": int(pnls.mean()),
        "win%": round((pnls > 0).mean()*100, 1),
        "Sharpe": sh,
        "maxDD": int(dd.max()),
        "maxLoss": int(pnls.min()),
        "maxGain": int(pnls.max()),
    }


ALL_RESULTS = []

# ============== 1. D trail 寬度 ==============
print("=" * 120)
print(f"【Sweep 1: D 純 trailing 不同 trail 寬度】 threshold={THRESHOLD}%, init_stop=50, 2 口")
print("=" * 120)
print(f"  {'config':<24s} {'n':>4s} {'total':>10s} {'EV':>7s} {'win%':>6s} {'Sharpe':>7s} {'maxDD':>9s} {'wrst':>7s} {'best':>7s}")
for trail in [15, 20, 25, 30, 40, 50, 60, 75, 100, 150]:
    pnls = run(sim_D_param, trail=trail, init_stop=50)
    s = stats(pnls, f"D trail={trail}")
    if s:
        ALL_RESULTS.append(s)
        print(f"  {s['config']:<24s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+7,d} "
              f"{s['win%']:>5.1f}% {s['Sharpe']:>+7.2f} {s['maxDD']:>+9,d} "
              f"{s['maxLoss']:>+7,d} {s['maxGain']:>+7,d}")

# ============== 1.5 D trail + 不同 init stop ==============
print()
print("=" * 120)
print("【Sweep 1.5: D trail=30/50 × init_stop=30/50/75】")
print("=" * 120)
print(f"  {'config':<24s} {'n':>4s} {'total':>10s} {'EV':>7s} {'win%':>6s} {'Sharpe':>7s} {'maxDD':>9s}")
for trail in [30, 50]:
    for stop in [30, 50, 75]:
        pnls = run(sim_D_param, trail=trail, init_stop=stop)
        s = stats(pnls, f"D trail={trail}/stop={stop}")
        if s:
            ALL_RESULTS.append(s)
            print(f"  {s['config']:<24s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+7,d} "
                  f"{s['win%']:>5.1f}% {s['Sharpe']:>+7.2f} {s['maxDD']:>+9,d}")

# ============== 2. A 不同 (TP1, TP2) ==============
print()
print("=" * 120)
print(f"【Sweep 2: A 固定 TP 不同 (TP1, TP2) 組合】 threshold={THRESHOLD}%, stop=50")
print("=" * 120)
print(f"  {'config':<24s} {'n':>4s} {'total':>10s} {'EV':>7s} {'win%':>6s} {'Sharpe':>7s} {'maxDD':>9s}")
for tp1, tp2 in [(30, 100), (50, 100), (50, 150), (50, 200),
                  (75, 150), (75, 200), (75, 250),
                  (100, 150), (100, 200), (100, 250), (100, 300),
                  (150, 300), (150, 400),
                  (200, 400)]:
    pnls = run(sim_A, tp1=tp1, tp2=tp2, stop=50)
    s = stats(pnls, f"A +{tp1}/+{tp2}")
    if s:
        ALL_RESULTS.append(s)
        print(f"  {s['config']:<24s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+7,d} "
              f"{s['win%']:>5.1f}% {s['Sharpe']:>+7.2f} {s['maxDD']:>+9,d}")

# ============== 3. E activation trailing ==============
print()
print("=" * 120)
print(f"【Sweep 3: E activation trailing — 走 +X 點才開始 trail】 threshold={THRESHOLD}%, init_stop=50")
print("=" * 120)
print(f"  {'config':<24s} {'n':>4s} {'total':>10s} {'EV':>7s} {'win%':>6s} {'Sharpe':>7s} {'maxDD':>9s}")
for activation in [0, 25, 50, 75, 100, 150]:
    for trail in [25, 30, 50, 75]:
        pnls = run(sim_E_activation, activation=activation, trail=trail, init_stop=50)
        s = stats(pnls, f"E act={activation}/trail={trail}")
        if s:
            ALL_RESULTS.append(s)
            print(f"  {s['config']:<24s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+7,d} "
                  f"{s['win%']:>5.1f}% {s['Sharpe']:>+7.2f} {s['maxDD']:>+9,d}")

# ============== Top by EV ==============
print()
print("=" * 120)
print("【全部組合按 EV 排序 — Top 15】")
print("=" * 120)
df = pd.DataFrame(ALL_RESULTS).sort_values("EV", ascending=False)
print(df.head(15).to_string(index=False))

print()
print("【全部組合按 Sharpe 排序 — Top 15】")
print(df.sort_values("Sharpe", ascending=False).head(15).to_string(index=False))

print()
print("【全部組合按 total 排序 — Top 15】")
print(df.sort_values("total", ascending=False).head(15).to_string(index=False))

df.to_csv(BASE / "sweep_1500_exit_optimize.csv", index=False, encoding="utf-8-sig")
print(f"\n結果存檔 → sweep_1500_exit_optimize.csv")
