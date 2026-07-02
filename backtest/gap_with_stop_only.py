"""
強制帶停損版 — 0845 (gap_night>=0.5%) 與 1500 (|gap|>=0.3%) 最佳有停損組合
無停損組合全部排除。1500 補掃 S100/S150。
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
POINT_VAL, COMMISSION, SLIPPAGE = 10, 5.6, 5


def load(tick_dir, prefix, info_file, after_time=None):
    info = pd.read_csv(BASE / tick_dir / info_file).set_index("date")
    data = {}
    for d in info.index:
        fp = BASE / tick_dir / f"{prefix}{d}.csv"
        if not fp.exists(): continue
        t = pd.read_csv(fp)
        t["ts"] = pd.to_datetime(t["ts"])
        if after_time:
            t = t[t["ts"].dt.strftime("%H:%M:%S") >= after_time]
        t = t.sort_values("ts")
        if len(t) < 50: continue
        data[d] = (t["close"].values.astype(np.float64),
                   (t["ts"] - t["ts"].iloc[0]).dt.total_seconds().values)
    return info, data


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


TMAXS = [(60, "1m"), (180, "3m"), (300, "5m"), (600, "10m"), (1860, "31m")]


def report(dl, data, tps, stops, title):
    rows = []
    for tp in tps:
        for stop in stops:  # 全部有停損
            for tmax_s, tlab in TMAXS:
                r = agg([sim(*data[d], s, tp, stop, tmax_s) for d, s in dl])
                if r: rows.append({"exit": f"TP{tp}/S{stop}/{tlab}", "stop": stop, **r})
    res = pd.DataFrame(rows).sort_values("total", ascending=False)
    n_pos = (res["total"] > 0).mean() * 100
    print(f"\n◆ {title}   n={len(dl)} 天, 帶停損組合 {len(res)} 個, 正 EV {n_pos:.0f}%")
    print(f"  {'exit':<20s} {'n':>4s} {'total':>9s} {'EV':>7s} {'win%':>6s} {'PF':>6s} {'worst':>8s}")
    for _, r in res.head(10).iterrows():
        print(f"  {r['exit']:<20s} {r['n']:>4d} {r['total']:>+9,.0f} {r['EV']:>+7,.0f} "
              f"{r['win%']:>5.1f}% {r['PF']:>6.2f} {r['worst']:>+8,.0f}")
    return res


# 0845
info8, data8 = load("gap_ticks", "MXF_", "gap_days_selected_2026.csv", "08:45:00")
dl8 = [(d, int(np.sign(info8.loc[d, "gap_night_pct"]))) for d in data8
       if pd.notna(info8.loc[d, "gap_night_pct"]) and abs(info8.loc[d, "gap_night_pct"]) >= 0.5]
report(dl8, data8, tps=[30, 50, 80, 100, 150], stops=[15, 20, 30, 50, 80, 100],
       title="0845 gap_night>=0.5%")

# 1500
info15, data15 = load("gap_ticks_1500", "N1500_", "gap_1500_days_selected.csv")
dl15 = [(d, int(np.sign(info15.loc[d, "gap_1500_pct"]))) for d in data15
        if abs(info15.loc[d, "gap_1500_pct"]) >= 0.3]
res15 = report(dl15, data15, tps=[20, 30, 50, 80, 100], stops=[15, 20, 30, 50, 80, 100, 150],
               title="1500 |gap|>=0.3%")

# 1500 的「幾乎無敵版 TP50/S∞/31m」 vs 帶停損最佳版逐日對照
print("\n1500 TP50 各停損 @ 31min 上限 (看停損從寬到緊 EV 怎麼變):")
print(f"  {'stop':>6s} {'EV':>7s} {'win%':>6s} {'PF':>6s} {'worst':>8s}")
for stop in [150, 100, 80, 50, 30, 20]:
    r = agg([sim(*data15[d], s, 50, stop, 1860) for d, s in dl15])
    if r:
        print(f"  S{stop:<5d} {r['EV']:>+7,.0f} {r['win%']:>5.1f}% {r['PF']:>6.2f} {r['worst']:>+8,.0f}")
