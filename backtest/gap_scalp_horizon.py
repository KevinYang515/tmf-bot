"""
大跳空開盤 burst scalp — 慣性壽命 + exit 結構 (TP vs trailing)
==============================================================
User: 慣性本來就秒級~分鐘級, 停利停損都迅速。問: TP 還是 trailing?

Part 1: 慣性壽命 — 順 gap 方向的 signed drift @ 開盤後 k 分鐘 + MFE/MAE
Part 2: exit 掃描 — 限定前 N 分鐘內: fixed TP+stop vs tight trailing
  (1-min bar 近似, intrabar 同根碰 TP 與 stop 時保守算 stop 先)
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
POINT_VAL = 10
COMMISSION = 5.6
SLIPPAGE = 5

df = pd.read_csv(BASE / "mxf_1min.csv")
df["ts"] = pd.to_datetime(df["ts"])
df["date"] = df["ts"].dt.date.astype(str)
df["mi"] = df["ts"].dt.hour * 60 + df["ts"].dt.minute
df = df.sort_values("ts")

days = {d: g for d, g in df.groupby("date")}
dates = sorted(days.keys())

recs = []
for i, d in enumerate(dates):
    g = days[d]
    ob = g[g["mi"] == 8 * 60 + 46]
    if ob.empty: continue
    open845 = float(ob.iloc[0]["Open"])
    nb = g[g["mi"] == 5 * 60 + 0]
    night_close = float(nb.iloc[0]["Close"]) if not nb.empty else np.nan
    prev_close = np.nan
    if i > 0:
        pb = days[dates[i - 1]]
        pb = pb[pb["mi"] == 13 * 60 + 45]
        if not pb.empty: prev_close = float(pb.iloc[0]["Close"])
    recs.append({"date": d, "open": open845, "prev_close": prev_close, "night_close": night_close})

info = pd.DataFrame(recs).set_index("date")
info["gap_day_pct"] = (info["open"] - info["prev_close"]) / info["prev_close"] * 100
info["gap_night_pct"] = (info["open"] - info["night_close"]) / info["night_close"] * 100


def first_bars(d, n=35):
    g = days[d]
    m = g[(g["mi"] >= 8 * 60 + 46) & (g["mi"] < 8 * 60 + 46 + n)].sort_values("ts")
    if m.empty: return None
    return (m["High"].values.astype(float), m["Low"].values.astype(float),
            m["Close"].values.astype(float))


# ============ Part 1: 慣性壽命 ============
print("=" * 100)
print("Part 1: 順 gap 方向 signed drift (pt) @ 開盤後 k 分鐘  (未扣成本, 正 = 慣性方向續走)")
print("=" * 100)
KS = [1, 2, 3, 5, 10, 15, 30]
for gap_col, gth_list in [("gap_day_pct", [1.0, 1.5, 2.0]), ("gap_night_pct", [0.3, 0.5])]:
    for gth in gth_list:
        sel = info[(info[gap_col].abs() >= gth) & info[gap_col].notna()]
        rows = []
        mfe3, mae3, mfe5, mae5 = [], [], [], []
        for d, r in sel.iterrows():
            bars = first_bars(d)
            if bars is None: continue
            hi, lo, cl = bars
            if len(cl) < 31: continue
            s = np.sign(r[gap_col])
            drift = [s * (cl[k - 1] - r["open"]) for k in KS]
            rows.append(drift)
            fav3 = (hi[:3] - r["open"]).max() if s == 1 else (r["open"] - lo[:3]).max()
            adv3 = (r["open"] - lo[:3]).max() if s == 1 else (hi[:3] - r["open"]).max()
            fav5 = (hi[:5] - r["open"]).max() if s == 1 else (r["open"] - lo[:5]).max()
            adv5 = (r["open"] - lo[:5]).max() if s == 1 else (hi[:5] - r["open"]).max()
            mfe3.append(fav3); mae3.append(adv3); mfe5.append(fav5); mae5.append(adv5)
        if not rows: continue
        arr = np.array(rows)
        n = len(arr)
        print(f"\n{gap_col} |gap|>={gth}%  n={n}")
        print("  k(min):   " + "  ".join(f"{k:>6d}" for k in KS))
        print("  mean:     " + "  ".join(f"{arr[:, i].mean():>+6.0f}" for i in range(len(KS))))
        print("  median:   " + "  ".join(f"{np.median(arr[:, i]):>+6.0f}" for i in range(len(KS))))
        print("  win%:     " + "  ".join(f"{(arr[:, i] > 0).mean()*100:>5.0f}%" for i in range(len(KS))))
        print(f"  MFE/MAE 3min: {np.mean(mfe3):+.0f} / -{np.mean(mae3):.0f}   "
              f"5min: {np.mean(mfe5):+.0f} / -{np.mean(mae5):.0f}")

# ============ Part 2: exit 結構掃描 ============
def sim_tp_stop(entry, bars, s, tp, stop, tmax):
    hi, lo, cl = bars
    be = entry + s * SLIPPAGE
    tp_p = be + s * tp
    stop_p = be - s * stop
    n = min(len(hi), tmax)
    for i in range(n):
        hit_stop = (lo[i] <= stop_p) if s == 1 else (hi[i] >= stop_p)
        hit_tp = (hi[i] >= tp_p) if s == 1 else (lo[i] <= tp_p)
        if hit_stop:  # 保守: 同根先算 stop
            return (-stop - COMMISSION) * POINT_VAL
        if hit_tp:
            return (tp - COMMISSION) * POINT_VAL
    return (s * (cl[n - 1] - be) - COMMISSION) * POINT_VAL


def sim_trail(entry, bars, s, trail, tmax, init_stop=None):
    hi, lo, cl = bars
    be = entry + s * SLIPPAGE
    best = be
    stop_p = be - s * (init_stop if init_stop else trail)
    n = min(len(hi), tmax)
    for i in range(n):
        hit = (lo[i] <= stop_p) if s == 1 else (hi[i] >= stop_p)
        if hit:
            return (s * (stop_p - be) - COMMISSION) * POINT_VAL
        best = max(best, hi[i]) if s == 1 else min(best, lo[i])
        new_stop = best - s * trail
        stop_p = max(stop_p, new_stop) if s == 1 else min(stop_p, new_stop)
    return (s * (cl[n - 1] - be) - COMMISSION) * POINT_VAL


def run_exit(gap_col, gth, sim_fn, **kw):
    pnls = []
    for d, r in info[(info[gap_col].abs() >= gth) & info[gap_col].notna()].iterrows():
        bars = first_bars(d)
        if bars is None or len(bars[0]) < 31: continue
        s = int(np.sign(r[gap_col]))
        pnls.append(sim_fn(r["open"], bars, s, **kw))
    if not pnls: return None
    p = np.array(pnls)
    wins = p[p > 0]; losses = p[p < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {"n": len(p), "total": p.sum(), "EV": p.mean(),
            "win%": (p > 0).mean() * 100, "PF": pf,
            "sharpe": p.mean() / p.std() * np.sqrt(252) if p.std() > 0 else 0}


print()
print("=" * 100)
print("Part 2: exit 掃描 — gap_day >= 2.0% (今天這種)  與 1.5%")
print("=" * 100)
for gth in [1.5, 2.0]:
    print(f"\n--- |gap_day| >= {gth}% ---")
    print(f"{'exit':<38s} {'n':>4s} {'total':>9s} {'EV':>7s} {'win%':>6s} {'PF':>6s} {'Sharpe':>7s}")
    for tp in [50, 80, 100, 150, 200]:
        for stop in [50, 80, 100]:
            for tmax in [3, 5, 10]:
                r = run_exit("gap_day_pct", gth, sim_tp_stop, tp=tp, stop=stop, tmax=tmax)
                if r is None: continue
                if r["PF"] > 1.25 or (tp == 100 and stop == 80 and tmax == 5):
                    print(f"TP+{tp:<4d} stop-{stop:<4d} tmax={tmax:<3d}          "
                          f"{r['n']:>4d} {r['total']:>+9,.0f} {r['EV']:>+7,.0f} {r['win%']:>5.1f}% {r['PF']:>6.2f} {r['sharpe']:>+7.2f}")
    for trail in [40, 60, 80, 100, 150]:
        for tmax in [3, 5, 10, 30]:
            r = run_exit("gap_day_pct", gth, sim_trail, trail=trail, tmax=tmax)
            if r is None: continue
            if r["PF"] > 1.25 or (trail == 100 and tmax == 5):
                print(f"trail={trail:<4d} tmax={tmax:<3d}                   "
                      f"{r['n']:>4d} {r['total']:>+9,.0f} {r['EV']:>+7,.0f} {r['win%']:>5.1f}% {r['PF']:>6.2f} {r['sharpe']:>+7.2f}")

print()
print("--- 對照: gap_night >= 0.5% (亞洲時段 surprise) ---")
print(f"{'exit':<38s} {'n':>4s} {'total':>9s} {'EV':>7s} {'win%':>6s} {'PF':>6s} {'Sharpe':>7s}")
for tp in [50, 80, 100, 150]:
    for stop in [50, 80]:
        for tmax in [3, 5, 10]:
            r = run_exit("gap_night_pct", 0.5, sim_tp_stop, tp=tp, stop=stop, tmax=tmax)
            if r and r["PF"] > 1.3:
                print(f"TP+{tp:<4d} stop-{stop:<4d} tmax={tmax:<3d}          "
                      f"{r['n']:>4d} {r['total']:>+9,.0f} {r['EV']:>+7,.0f} {r['win%']:>5.1f}% {r['PF']:>6.2f} {r['sharpe']:>+7.2f}")
for trail in [40, 60, 80, 100, 150]:
    for tmax in [3, 5, 10, 30]:
        r = run_exit("gap_night_pct", 0.5, sim_trail, trail=trail, tmax=tmax)
        if r and r["PF"] > 1.3:
            print(f"trail={trail:<4d} tmax={tmax:<3d}                   "
                  f"{r['n']:>4d} {r['total']:>+9,.0f} {r['EV']:>+7,.0f} {r['win%']:>5.1f}% {r['PF']:>6.2f} {r['sharpe']:>+7.2f}")
