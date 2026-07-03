"""
Verify pass: G(多空不對稱) 和 J(動態cap) 的發現，套用在『已部署的動態TP』設定上重新檢驗，
避免用舊的固定TP100基準得出的結論跟現在部署的東西對不上。
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


def sim_dyn(px, sec, s, gap_pts, alpha, lo, hi, stop, tmax_s):
    tp = float(np.clip(alpha * gap_pts, lo, hi))
    return sim(px, sec, s, tp, stop, tmax_s)


def agg(pnls):
    p = np.array([x for x in pnls if x is not None]) * POINT_VAL
    if len(p) == 0: return None
    wins = p[p > 0]; losses = p[p < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {"n": len(p), "total": p.sum(), "EV": p.mean(),
            "win%": (p > 0).mean() * 100, "PF": pf, "worst": p.min()}


def fmt(r, label, w=36):
    if r is None: return f"  {label:<{w}s}  (n=0)"
    return (f"  {label:<{w}s} n={r['n']:>3d} total={r['total']:>+9,.0f} EV={r['EV']:>+7,.0f} "
            f"win={r['win%']:>5.1f}% PF={r['PF']:>5.2f} worst={r['worst']:>+8,.0f}")


info15, data15 = load("gap_ticks_1500", "N1500_", "gap_1500_days_selected.csv")
dl15, gpts15 = [], {}
for d in data15:
    g = info15.loc[d, "gap_1500_pct"]
    if abs(g) >= 0.3:
        dl15.append((d, int(np.sign(g))))
        gpts15[d] = abs(info15.loc[d, "night_open"] - info15.loc[d, "day_close"])

longs = [(d, s) for d, s in dl15 if s == 1]
shorts = [(d, s) for d, s in dl15 if s == -1]
h1 = lambda dl: [(d, s) for d, s in dl if d <= "2026-03-31"]
h2 = lambda dl: [(d, s) for d, s in dl if d > "2026-03-31"]

print("#" * 100)
print("# K1 — 現行『已部署』動態TP設定(a=0.4,lo100,hi300,S80,cap180) 下的多空不對稱是否還在?")
print("#" * 100)
ALPHA, LO, HI, STOP, CAP = 0.4, 100, 300, 80, 180

for lab, dl in [("全部(混合多空,現行live設定)", dl15), ("只做多(上跳空)", longs), ("只做空(下跳空)", shorts)]:
    r = agg([sim_dyn(*data15[d], s, gpts15[d], ALPHA, LO, HI, STOP, CAP) for d, s in dl])
    print(fmt(r, lab))
    r1 = agg([sim_dyn(*data15[d], s, gpts15[d], ALPHA, LO, HI, STOP, CAP) for d, s in h1(dl)])
    r2 = agg([sim_dyn(*data15[d], s, gpts15[d], ALPHA, LO, HI, STOP, CAP) for d, s in h2(dl)])
    if r1: print(fmt(r1, "  H1"))
    if r2: print(fmt(r2, "  H2"))

print("\n" + "#" * 100)
print("# K2 — 只做空(下跳空) + 動態TP + cap sweep (更細)")
print("#" * 100)
for cap in [90, 100, 110, 120, 130, 150, 180, 210]:
    r = agg([sim_dyn(*data15[d], s, gpts15[d], ALPHA, LO, HI, STOP, cap) for d, s in shorts])
    r1 = agg([sim_dyn(*data15[d], s, gpts15[d], ALPHA, LO, HI, STOP, cap) for d, s in h1(shorts)])
    r2 = agg([sim_dyn(*data15[d], s, gpts15[d], ALPHA, LO, HI, STOP, cap) for d, s in h2(shorts)])
    print(fmt(r, f"cap={cap}s [全樣本]"))
    if r1: print(fmt(r1, "  H1"))
    if r2: print(fmt(r2, "  H2"))

print("\n" + "#" * 100)
print("# K3 — 只做多(上跳空)：能否用縮小TP/縮短cap把它從負救回正? (若不行=方向本身沒有edge，不是參數問題)")
print("#" * 100)
for tp in [30, 50, 80, 100]:
    for cap in [60, 90, 120, 180]:
        r = agg([sim(*data15[d], s, tp, STOP, cap) for d, s in longs])
        if r and r["EV"] > 0:
            print(fmt(r, f"TP{tp}/cap{cap}s"))
print("  (只列出 EV>0 的組合；若整段空白代表『做多這個方向』無論怎麼調參數都是負 EV)")

print("\n" + "#" * 100)
print("# K4 — 最終建議配方 vs 現行 walk-forward 對照：只做空 + 動態TP + cap130 vs 現行(多空都做+cap180)")
print("#" * 100)
def eval_recipe(dl, cap):
    return agg([sim_dyn(*data15[d], s, gpts15[d], ALPHA, LO, HI, STOP, cap) for d, s in dl])

print(fmt(eval_recipe(dl15, 180), "現行(多空都做, cap180) [全樣本]"))
print(fmt(eval_recipe(h1(dl15), 180), "  H1"))
print(fmt(eval_recipe(h2(dl15), 180), "  H2"))
print()
print(fmt(eval_recipe(shorts, 130), "建議(只做空, cap130) [全樣本]"))
print(fmt(eval_recipe(h1(shorts), 130), "  H1"))
print(fmt(eval_recipe(h2(shorts), 130), "  H2"))
