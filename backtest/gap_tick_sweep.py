"""
Tick 級參數全掃描 — 2026 大 gap 日開盤 scalp (61 天)
=====================================================
進場: 08:45 第一筆成交價 + 滑價, 順 gap 方向
掃: TP × 停損 × 時間上限 (tick 級, 先後順序精確)
     + trailing × 時間上限
成本: 滑價 5pt (進場), 手續費稅 5.6pt/回合
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
TICK_DIR = BASE / "gap_ticks"
POINT_VAL = 10
COMMISSION = 5.6
SLIPPAGE = 5

info = pd.read_csv(TICK_DIR / "gap_days_selected_2026.csv").set_index("date")

# 預載每日 tick price/time array
data = {}
for d in info.index:
    fp = TICK_DIR / f"MXF_{d}.csv"
    if not fp.exists(): continue
    t = pd.read_csv(fp)
    t["ts"] = pd.to_datetime(t["ts"])
    t = t[t["ts"].dt.strftime("%H:%M:%S") >= "08:45:00"].sort_values("ts")
    if len(t) < 100: continue
    px = t["close"].values.astype(np.float64)
    sec = (t["ts"] - t["ts"].iloc[0]).dt.total_seconds().values
    data[d] = (px, sec)

print(f"載入 {len(data)} 天 tick")


def sim_tp_stop_day(px, sec, s, tp, stop, tmax_s):
    """回傳 pnl(pt)。tick 序列精確次序。stop=None → 無停損"""
    mask = sec <= tmax_s
    p = px[mask]
    if len(p) < 2: return None
    be = p[0] + s * SLIPPAGE
    fav = s * (p - be)          # 有利方向的 excursion
    tp_hit = fav >= tp
    stop_hit = fav <= -stop if stop is not None else np.zeros(len(p), bool)
    i_tp = tp_hit.argmax() if tp_hit.any() else len(p)
    i_st = stop_hit.argmax() if stop_hit.any() else len(p)
    if i_tp < i_st:
        return tp - COMMISSION
    if i_st < len(p):
        return -stop - COMMISSION
    return fav[-1] - COMMISSION  # 時間到平倉


def sim_trail_day(px, sec, s, trail, tmax_s):
    mask = sec <= tmax_s
    p = px[mask]
    if len(p) < 2: return None
    be = p[0] + s * SLIPPAGE
    fav = s * (p - be)
    runmax = np.maximum.accumulate(fav)
    dd = runmax - fav
    hit = dd >= trail
    if hit.any():
        i = hit.argmax()
        return runmax[i] - trail - COMMISSION
    return fav[-1] - COMMISSION


def agg(pnls):
    p = np.array([x for x in pnls if x is not None]) * POINT_VAL
    if len(p) == 0: return None
    wins = p[p > 0]; losses = p[p < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {"n": len(p), "total": p.sum(), "EV": p.mean(),
            "win%": (p > 0).mean() * 100, "PF": pf, "worst": p.min()}


def day_list(gap_col, gth):
    out = []
    for d in data:
        gp = info.loc[d, gap_col]
        if pd.notna(gp) and abs(gp) >= gth:
            out.append((d, int(np.sign(gp))))
    return out


TPS = [20, 30, 50, 80, 100, 150]
STOPS = [20, 30, 50, 80, 100, 150, 300, None]
TMAXS = [(60, "1m"), (180, "3m"), (300, "5m"), (600, "10m"), (1860, "31m")]
TRAILS = [15, 20, 30, 40, 60, 80, 100]

for gap_col, gth in [("gap_day_pct", 1.0), ("gap_day_pct", 1.5),
                     ("gap_night_pct", 0.3), ("gap_night_pct", 0.5)]:
    dl = day_list(gap_col, gth)
    if len(dl) < 5: continue
    print()
    print("=" * 108)
    print(f"◆ {gap_col} >= {gth}%   n={len(dl)} 天 (2026-01 ~ 2026-07-02)")
    print("=" * 108)

    # --- 全組合, 收集後排序 ---
    rows = []
    for tp in TPS:
        for stop in STOPS:
            for tmax_s, tlab in TMAXS:
                pnls = [sim_tp_stop_day(*data[d], s, tp, stop, tmax_s) for d, s in dl]
                r = agg(pnls)
                if r is None: continue
                rows.append({"exit": f"TP{tp}/S{stop if stop else '∞'}/{tlab}", **r})
    for trail in TRAILS:
        for tmax_s, tlab in TMAXS:
            pnls = [sim_trail_day(*data[d], s, trail, tmax_s) for d, s in dl]
            r = agg(pnls)
            if r is None: continue
            rows.append({"exit": f"trail{trail}/{tlab}", **r})

    res = pd.DataFrame(rows).sort_values("total", ascending=False)
    print(f"\n  Top 12 (by total):")
    print(f"  {'exit':<22s} {'n':>4s} {'total':>9s} {'EV':>7s} {'win%':>6s} {'PF':>6s} {'worst':>8s}")
    for _, r in res.head(12).iterrows():
        print(f"  {r['exit']:<22s} {r['n']:>4d} {r['total']:>+9,.0f} {r['EV']:>+7,.0f} "
              f"{r['win%']:>5.1f}% {r['PF']:>6.2f} {r['worst']:>+8,.0f}")
    print(f"\n  Bottom 5:")
    for _, r in res.tail(5).iterrows():
        print(f"  {r['exit']:<22s} {r['n']:>4d} {r['total']:>+9,.0f} {r['EV']:>+7,.0f} "
              f"{r['win%']:>5.1f}% {r['PF']:>6.2f} {r['worst']:>+8,.0f}")

    n_pos = (res["total"] > 0).sum()
    print(f"\n  全 {len(res)} 組合中 {n_pos} 個正 EV ({n_pos/len(res)*100:.0f}%)  "
          f"[若 <30% → 大概率是雜訊撿到的]")

    # EV 矩陣 @ tmax=5m
    print(f"\n  EV 矩陣 (NT$/筆) @ 時間上限 5min:  (欄=停損, 列=TP)")
    hdr = "  TP\\S   " + "".join(f"{('S'+str(s)) if s else 'S∞':>8s}" for s in STOPS)
    print(hdr)
    for tp in TPS:
        line = f"  TP{tp:<5d}"
        for stop in STOPS:
            pnls = [sim_tp_stop_day(*data[d], s, tp, stop, 300) for d, s in dl]
            r = agg(pnls)
            line += f"{r['EV']:>+8,.0f}" if r else f"{'—':>8s}"
        print(line)
