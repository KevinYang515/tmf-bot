"""
找「edge 隨年份穩定 / 上升」的配置
=====================================
對所有候選 config 計算：
- 5 半年的 EV / Sharpe
- Trend：EV 對時間（半年序號）的線性 slope
- Stability：std(EV), CV (coefficient of variation = std/mean)
- 最差期 EV（worst case）
- 全 5 期是否都正

最終 Rank：
- 找 slope > 0 (上升) 或 CV 低 (穩定) 的配置
"""
import pandas as pd, numpy as np
from pathlib import Path
import sys

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
exec(open(BASE / "sweep_cutoff_exit.py", encoding="utf-8").read().split('CUTOFFS =')[0])

THRESHOLD = 0.05
CUTOFF = (23, 0)


def get_sig(d, col, th):
    if d not in intraday.index: return 0
    raw = intraday.loc[d, col]
    if pd.isna(raw): return 0
    pct = float(raw) / 18000 * 100
    if abs(pct) < th: return 0
    return 1 if pct > 0 else -1


def sim_D_clean(entry, bars, direction, trail, init_stop):
    hi, lo, cl = bars
    n = len(hi); be = entry + direction * SLIPPAGE
    cur_stop = be - direction * init_stop; peak = be
    exit_p = None
    for i in range(n):
        if direction == 1 and lo[i] <= cur_stop: exit_p = cur_stop; break
        if direction == -1 and hi[i] >= cur_stop: exit_p = cur_stop; break
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


def sim_E_clean(entry, bars, direction, activation, trail, init_stop):
    hi, lo, cl = bars
    n = len(hi); be = entry + direction * SLIPPAGE
    cur_stop = be - direction * init_stop; peak = be
    activated = False; exit_p = None
    activation_p = be + direction * activation
    for i in range(n):
        if direction == 1 and lo[i] <= cur_stop: exit_p = cur_stop; break
        if direction == -1 and hi[i] >= cur_stop: exit_p = cur_stop; break
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


def run_pnl(sim_fn, **kw):
    rec = []
    for d in intraday.index:
        sig = get_sig(d, "nq_1500", THRESHOLD)
        if sig == 0: continue
        bars = build_bars(d, CUTOFF)
        if bars is None: continue
        entry = get_open(d)
        if entry is None: continue
        rec.append({"date": d, "pnl": sim_fn(entry, bars, sig, **kw)})
    df = pd.DataFrame(rec)
    df["half"] = df["date"].apply(lambda x: f"{x[:4]}H1" if x[5:7] <= "06" else f"{x[:4]}H2")
    return df


# 擴大候選 — 加入更多 stop / trail / TP 組合
CONFIGS = []
# A 系列：不同 stop
for tp1, tp2 in [(50, 150), (75, 150), (75, 200), (100, 200), (100, 300), (150, 300), (200, 400)]:
    for stop in [30, 50, 75]:
        CONFIGS.append((f"A +{tp1}/+{tp2} stop={stop}", sim_A, {"tp1": tp1, "tp2": tp2, "stop": stop}))
# D 系列
for trail in [30, 40, 50, 60, 75]:
    for stop in [25, 30, 50, 75]:
        CONFIGS.append((f"D trail={trail} stop={stop}", sim_D_clean, {"trail": trail, "init_stop": stop}))
# E 系列
for act in [25, 50, 75, 100, 150]:
    for trail in [30, 50, 75]:
        for stop in [30, 50]:
            CONFIGS.append((f"E act={act}/trail={trail}/stop={stop}", sim_E_clean,
                            {"activation": act, "trail": trail, "init_stop": stop}))

print(f"共 {len(CONFIGS)} 個候選配置", flush=True)

PERIODS = ["2024H1", "2024H2", "2025H1", "2025H2", "2026H1"]

records = []
for i, (label, fn, kw) in enumerate(CONFIGS, 1):
    if i % 20 == 0: print(f"  {i}/{len(CONFIGS)}", flush=True)
    df = run_pnl(fn, **kw)
    if df.empty: continue
    per_ev = []
    per_sh = []
    for p in PERIODS:
        sub = df[df["half"] == p]
        if len(sub) == 0: continue
        pnls = sub["pnl"].values
        per_ev.append(int(pnls.mean()))
        if pnls.std() > 0:
            per_sh.append(round(pnls.mean()/pnls.std()*np.sqrt(252), 2))
        else:
            per_sh.append(0)
    if len(per_ev) < 5: continue

    # trend: linear regression slope
    x = np.arange(len(per_ev))
    slope, intercept = np.polyfit(x, per_ev, 1)
    # 全部 5 期都正？
    all_pos = all(e > 0 for e in per_ev)
    # 穩定度 CV
    mean = np.mean(per_ev); std = np.std(per_ev)
    cv = std / mean if mean > 0 else 999

    # 整體
    full_pnls = df["pnl"].values
    full_total = int(full_pnls.sum())
    full_ev = int(full_pnls.mean())
    full_sh = round(full_pnls.mean()/full_pnls.std()*np.sqrt(252), 2) if full_pnls.std() > 0 else 0

    records.append({
        "config": label,
        "all_5pos": "Y" if all_pos else "N",
        "total": full_total,
        "EV_full": full_ev,
        "Sh_full": full_sh,
        "EV_24H1": per_ev[0],
        "EV_24H2": per_ev[1],
        "EV_25H1": per_ev[2],
        "EV_25H2": per_ev[3],
        "EV_26H1": per_ev[4],
        "EV_mean": int(mean),
        "EV_std": int(std),
        "EV_min": int(min(per_ev)),
        "CV": round(cv, 2),
        "slope": int(slope),  # EV/period 變化
    })

res = pd.DataFrame(records)

# ============ 報告 ============
print()
print("=" * 150)
print("【Top 10 by SLOPE — edge 隨時間上升的配置】")
print("=" * 150)
print(f"  {'config':<28s} {'pos5?':>5s} {'EVfull':>7s} {'24H1':>6s} {'24H2':>6s} {'25H1':>6s} {'25H2':>6s} {'26H1':>6s} {'EVmin':>6s} {'CV':>5s} {'slope':>6s} {'Sh_full':>7s}")
for _, r in res.sort_values("slope", ascending=False).head(10).iterrows():
    print(f"  {r['config']:<28s} {r['all_5pos']:>5s} {r['EV_full']:>+7,d} {r['EV_24H1']:>+6,d} "
          f"{r['EV_24H2']:>+6,d} {r['EV_25H1']:>+6,d} {r['EV_25H2']:>+6,d} {r['EV_26H1']:>+6,d} "
          f"{r['EV_min']:>+6,d} {r['CV']:>5.2f} {r['slope']:>+6,d} {r['Sh_full']:>+7.2f}")

print()
print("=" * 150)
print("【Top 10 by CV (最穩定) — 篩 all_5pos=Y 且 EV_full > 300】")
print("=" * 150)
filt = res[(res["all_5pos"] == "Y") & (res["EV_full"] > 300)]
for _, r in filt.sort_values("CV").head(10).iterrows():
    print(f"  {r['config']:<28s} {r['all_5pos']:>5s} {r['EV_full']:>+7,d} {r['EV_24H1']:>+6,d} "
          f"{r['EV_24H2']:>+6,d} {r['EV_25H1']:>+6,d} {r['EV_25H2']:>+6,d} {r['EV_26H1']:>+6,d} "
          f"{r['EV_min']:>+6,d} {r['CV']:>5.2f} {r['slope']:>+6,d} {r['Sh_full']:>+7.2f}")

print()
print("=" * 150)
print("【Top 10 by EV_min (最差期最高) — 篩 all_5pos=Y】")
print("=" * 150)
filt = res[res["all_5pos"] == "Y"]
for _, r in filt.sort_values("EV_min", ascending=False).head(10).iterrows():
    print(f"  {r['config']:<28s} {r['all_5pos']:>5s} {r['EV_full']:>+7,d} {r['EV_24H1']:>+6,d} "
          f"{r['EV_24H2']:>+6,d} {r['EV_25H1']:>+6,d} {r['EV_25H2']:>+6,d} {r['EV_26H1']:>+6,d} "
          f"{r['EV_min']:>+6,d} {r['CV']:>5.2f} {r['slope']:>+6,d} {r['Sh_full']:>+7.2f}")

print()
print("=" * 150)
print("【「上升 OR 不衰退」 — slope >= 0 的全部配置】")
print("=" * 150)
filt = res[res["slope"] >= 0]
for _, r in filt.sort_values("slope", ascending=False).iterrows():
    print(f"  {r['config']:<28s} {r['all_5pos']:>5s} {r['EV_full']:>+7,d} {r['EV_24H1']:>+6,d} "
          f"{r['EV_24H2']:>+6,d} {r['EV_25H1']:>+6,d} {r['EV_25H2']:>+6,d} {r['EV_26H1']:>+6,d} "
          f"{r['EV_min']:>+6,d} {r['CV']:>5.2f} {r['slope']:>+6,d} {r['Sh_full']:>+7.2f}")

print()
print("=" * 150)
print("【EV_26H1 Top 10 — 最近半年表現最佳】")
print("=" * 150)
for _, r in res.sort_values("EV_26H1", ascending=False).head(10).iterrows():
    print(f"  {r['config']:<28s} {r['all_5pos']:>5s} {r['EV_full']:>+7,d} {r['EV_24H1']:>+6,d} "
          f"{r['EV_24H2']:>+6,d} {r['EV_25H1']:>+6,d} {r['EV_25H2']:>+6,d} {r['EV_26H1']:>+6,d} "
          f"{r['EV_min']:>+6,d} {r['CV']:>5.2f} {r['slope']:>+6,d} {r['Sh_full']:>+7.2f}")

# 存檔
res.to_csv(BASE / "sweep_edge_stability.csv", index=False, encoding="utf-8-sig")
print(f"\n結果 → sweep_edge_stability.csv ({len(res)} 配置)")
