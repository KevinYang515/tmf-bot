# -*- coding: utf-8 -*-
"""
兩件事：
A) 6 個回填出的週一大gap日，過去只用舊 TP80/S30/cap300 測過(EV -173)，
   現在有新發現的「3秒出場+停損50」，重新驗證週一是否還是該排除。
B) 驗證 user 假設：「跳空幅度越大，開盤瞬間越容易先出現反向雜訊，
   才轉往真正方向」。用全部68天資料，量測「開盤後10秒內最大逆向偏移」
   跟 |gap| 的相關性。
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
COMM, SLIP, PV = 5.6, 5, 10

info = pd.read_csv(BASE / "gap_ticks" / "gap_days_selected_2026.csv").set_index("date")
MONDAY_INFO = {
    "2026-05-04": {"open": 40423.0, "night_close": 39389.0},
    "2026-05-11": {"open": 42216.0, "night_close": 42446.0},
    "2026-05-18": {"open": 40170.0, "night_close": 40700.0},
    "2026-05-25": {"open": 43183.0, "night_close": 42636.0},
    "2026-06-01": {"open": 45457.0, "night_close": 45079.0},
    "2026-06-15": {"open": 45709.0, "night_close": 44791.0},
    "2026-06-29": {"open": 44790.0, "night_close": 44994.0},
}

_CACHE = {}
def load_tick(fp, after_time="08:45:00"):
    if fp in _CACHE: return _CACHE[fp]
    if not fp.exists():
        _CACHE[fp] = None; return None
    t = pd.read_csv(fp)
    t["ts"] = pd.to_datetime(t["ts"])
    t = t[t["ts"].dt.strftime("%H:%M:%S") >= after_time].sort_values("ts")
    if len(t) < 50:
        _CACHE[fp] = None; return None
    r = (t["close"].values.astype(np.float64), (t["ts"]-t["ts"].iloc[0]).dt.total_seconds().values)
    _CACHE[fp] = r
    return r

def sim_tp(px, sec, s, tp, stop, tmax_s):
    p = px[sec <= tmax_s]
    if len(p) < 2: return None
    be = p[0] + s * SLIP
    fav = s * (p - be)
    i_tp = (fav >= tp).argmax() if (fav >= tp).any() else len(p)
    i_st = (fav <= -stop).argmax() if (fav <= -stop).any() else len(p)
    if i_tp < i_st: return tp - COMM
    if i_st < len(p): return -stop - COMM
    return fav[-1] - COMM

def sim_sec(px, sec, s, hold_s, stop):
    p = px[sec <= hold_s]
    if len(p) < 2: return None
    fav = s * (p - p[0])
    if stop is not None and (fav <= -stop).any():
        return -stop - SLIP - COMM
    idx = np.searchsorted(sec, hold_s)
    if idx >= len(px): idx = len(px)-1
    return s * (px[idx]-px[0]) - SLIP - COMM

def agg(pnls):
    p = np.array([x for x in pnls if x is not None]) * PV
    if len(p) == 0: return None
    wins = p[p>0]; losses = p[p<0]
    pf = wins.sum()/abs(losses.sum()) if losses.sum()!=0 else float("inf")
    return {"n": len(p), "total": p.sum(), "EV": p.mean(), "win%": (p>0).mean()*100, "PF": pf, "worst": p.min()}

def fmt(r, label, w=30):
    if r is None: return f"  {label:<{w}s}  (n=0)"
    return (f"  {label:<{w}s} n={r['n']:>3d} total={r['total']:>+9,.0f} EV={r['EV']:>+7,.0f} "
            f"win={r['win%']:>5.1f}% PF={r['PF']:>5.2f} worst={r['worst']:>+8,.0f}")

print("="*100)
print("A) 6個週一：新3秒出場+停損50 vs 舊TP80/S30/cap300")
print("="*100)
pnls_old, pnls_new = [], []
for d, mi in MONDAY_INFO.items():
    if d == "2026-06-29": continue  # 這天沒過0.5%門檻，原本就不在這6天名單
    fp = BASE / "gap_ticks_monday" / f"MXF_{d}.csv"
    tick = load_tick(fp)
    if tick is None:
        print(f"  {d}: 無tick"); continue
    gap_pct = (mi["open"]-mi["night_close"])/mi["night_close"]*100
    s = int(np.sign(gap_pct))
    old = sim_tp(*tick, s, 80, 30, 300)
    new = sim_sec(*tick, s, 3, 50)
    pnls_old.append(old); pnls_new.append(new)
    print(f"  {d}  gap={gap_pct:+.2f}%  dir={'多' if s==1 else '空'}  舊法={old*PV:+,.0f}  新法={new*PV:+,.0f}")

print()
print(fmt(agg(pnls_old), "6週一 舊TP80/S30/cap300"))
print(fmt(agg(pnls_new), "6週一 新3秒+停損50"))
print()
print("對照：現行25天(gap>=0.5%,非週一) 新3秒法 EV = +264 (前面已測過)")

print()
print("="*100)
print("B) user假設驗證：跳空幅度越大，開盤頭10秒是否越容易先出現逆向雜訊？")
print("="*100)
rows = []
for d in info.index:
    fp = BASE / "gap_ticks" / f"MXF_{d}.csv"
    tick = load_tick(fp)
    if tick is None: continue
    rows.append((d, info.loc[d,"gap_night_pct"], fp))
for d, mi in MONDAY_INFO.items():
    fp = BASE / "gap_ticks_monday" / f"MXF_{d}.csv"
    tick = load_tick(fp)
    if tick is None: continue
    gap_pct = (mi["open"]-mi["night_close"])/mi["night_close"]*100
    rows.append((d, gap_pct, fp))

records = []
for d, g, fp in rows:
    if g == 0 or abs(g) < 0.15: continue
    px, sec = load_tick(fp)
    s = int(np.sign(g))
    p10 = px[sec <= 10]
    if len(p10) < 2: continue
    be = px[0] + s*SLIP
    fav = s*(p10-be)
    max_adverse = -fav.min() if fav.min() < 0 else 0.0  # 最大逆向偏移(正數=真的有逆向)
    records.append({"date": d, "abs_gap": abs(g), "max_adverse_10s": max_adverse})

df = pd.DataFrame(records)
print(f"樣本數: {len(df)}")
print(f"相關係數 corr(|gap%|, 開盤10秒內最大逆向點數) = {df['abs_gap'].corr(df['max_adverse_10s']):.3f}")
print()
print("按 gap 大小分組看平均逆向幅度：")
df["bucket"] = pd.cut(df["abs_gap"], bins=[0.15,0.3,0.5,0.7,1.0,5.0])
print(df.groupby("bucket", observed=True)["max_adverse_10s"].agg(["count","mean","median","max"]))

print()
print("觸及-30停損(現行停損)的比例，按gap分組：")
for lo, hi in [(0.15,0.3),(0.3,0.5),(0.5,0.7),(0.7,5.0)]:
    sub = df[(df["abs_gap"]>=lo)&(df["abs_gap"]<hi)]
    if len(sub)==0: continue
    hit30 = (sub["max_adverse_10s"]>=30).mean()*100
    hit50 = (sub["max_adverse_10s"]>=50).mean()*100
    print(f"  gap {lo}~{hi}%: n={len(sub)}  觸及-30的比例={hit30:.0f}%  觸及-50的比例={hit50:.0f}%  平均逆向={sub['max_adverse_10s'].mean():.0f}pt")
