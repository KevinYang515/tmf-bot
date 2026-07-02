"""
在 TP+停損+時間上限 之上疊 trailing stop 是否更好?
====================================================
baseline: 0845 TP80/S30/5m (gap_night>=0.5%) | 1500 TP100/S80/3m (|gap|>=0.3%)
變體:
  (a) + trailing T (全程啟動: 從最有利點回檔 T 出場)
  (b) + trailing T, 但浮盈 >= A 後才啟動 (保本式)
同 tick 優先序: 停損 > TP > trailing (保守)
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


def sim(px, sec, s, tp, stop, tmax_s, trail=None, activate=0):
    p = px[sec <= tmax_s]
    if len(p) < 2: return None, None
    be = p[0] + s * SLIPPAGE
    fav = s * (p - be)
    runmax = 0.0
    for i in range(len(p)):
        f = fav[i]
        if f <= -stop:
            return -stop - COMMISSION, "stop"
        if f >= tp:
            return tp - COMMISSION, "tp"
        if trail is not None and runmax >= activate and (runmax - f) >= trail:
            return f - COMMISSION, "trail"
        if f > runmax: runmax = f
    return fav[-1] - COMMISSION, "cap"


def agg(results):
    pnls = [r[0] for r in results if r[0] is not None]
    kinds = [r[1] for r in results if r[0] is not None]
    p = np.array(pnls) * POINT_VAL
    wins = p[p > 0]; losses = p[p < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    from collections import Counter
    kc = Counter(kinds)
    return {"n": len(p), "total": p.sum(), "EV": p.mean(),
            "win%": (p > 0).mean() * 100, "PF": pf, "worst": p.min(),
            "exits": f"tp{kc.get('tp',0)}/st{kc.get('stop',0)}/tr{kc.get('trail',0)}/cap{kc.get('cap',0)}"}


def block(dl, data, tp, stop, tmax_s, title):
    print(f"\n◆ {title}  (n={len(dl)})")
    print(f"  {'變體':<26s} {'EV':>7s} {'win%':>6s} {'PF':>6s} {'worst':>8s} {'出場分布':>22s}")
    r = agg([sim(*data[d], s, tp, stop, tmax_s) for d, s in dl])
    print(f"  {'baseline (無 trailing)':<26s} {r['EV']:>+7,.0f} {r['win%']:>5.1f}% {r['PF']:>6.2f} "
          f"{r['worst']:>+8,.0f} {r['exits']:>22s}")
    for trail in [15, 20, 30, 40, 60]:
        r = agg([sim(*data[d], s, tp, stop, tmax_s, trail=trail) for d, s in dl])
        print(f"  {'(a) trail'+str(trail)+' 全程':<26s} {r['EV']:>+7,.0f} {r['win%']:>5.1f}% {r['PF']:>6.2f} "
              f"{r['worst']:>+8,.0f} {r['exits']:>22s}")
    for act in [20, 30, 40]:
        for trail in [15, 20, 30]:
            r = agg([sim(*data[d], s, tp, stop, tmax_s, trail=trail, activate=act) for d, s in dl])
            print(f"  {'(b) act'+str(act)+'+trail'+str(trail):<26s} {r['EV']:>+7,.0f} {r['win%']:>5.1f}% {r['PF']:>6.2f} "
                  f"{r['worst']:>+8,.0f} {r['exits']:>22s}")


info8, data8 = load("gap_ticks", "MXF_", "gap_days_selected_2026.csv", "08:45:00")
dl8 = [(d, int(np.sign(info8.loc[d, "gap_night_pct"]))) for d in data8
       if pd.notna(info8.loc[d, "gap_night_pct"]) and abs(info8.loc[d, "gap_night_pct"]) >= 0.5]
block(dl8, data8, 80, 30, 300, "0845 gap_night>=0.5%  TP80/S30/5min")

info15, data15 = load("gap_ticks_1500", "N1500_", "gap_1500_days_selected.csv")
dl15 = [(d, int(np.sign(info15.loc[d, "gap_1500_pct"]))) for d in data15
        if abs(info15.loc[d, "gap_1500_pct"]) >= 0.3]
block(dl15, data15, 100, 80, 180, "1500 |gap|>=0.3%  TP100/S80/3min")
