"""
把因 ref_close bug 被藏起來、後來回填出的 6 個週一大 gap 日
(05-04, 05-11, 05-18, 05-25, 06-01, 06-15) 加入 0845 回測，
跟原本 19 天的結果合併，看規模變大後結論有沒有變。
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
POINT_VAL, COMMISSION, SLIPPAGE = 10, 5.6, 5

# 回填出的正確 ref_close / gap
MONDAY_INFO = {
    "2026-05-04": {"open": 40423.0, "night_close": 39389.0},
    "2026-05-11": {"open": 42216.0, "night_close": 42446.0},
    "2026-05-18": {"open": 40170.0, "night_close": 40700.0},
    "2026-05-25": {"open": 43183.0, "night_close": 42636.0},
    "2026-06-01": {"open": 45457.0, "night_close": 45079.0},
    "2026-06-15": {"open": 45709.0, "night_close": 44791.0},
}


def load_tick(fp, after_time="08:45:00"):
    t = pd.read_csv(fp)
    t["ts"] = pd.to_datetime(t["ts"])
    t = t[t["ts"].dt.strftime("%H:%M:%S") >= after_time].sort_values("ts")
    if len(t) < 50: return None
    return (t["close"].values.astype(np.float64), (t["ts"] - t["ts"].iloc[0]).dt.total_seconds().values)


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


def fmt(r, label, w=30):
    if r is None: return f"  {label:<{w}s}  (n=0)"
    return (f"  {label:<{w}s} n={r['n']:>3d} total={r['total']:>+9,.0f} EV={r['EV']:>+7,.0f} "
            f"win={r['win%']:>5.1f}% PF={r['PF']:>5.2f} worst={r['worst']:>+8,.0f}")


TP, STOP, CAP = 80, 30, 300

print("#" * 100)
print("# 新發現的 6 個週一大 gap 日 — 逐日結果")
print("#" * 100)
monday_pnls = []
monday_dl = []
for d, info in MONDAY_INFO.items():
    fp = BASE / "gap_ticks_monday" / f"MXF_{d}.csv"
    tick = load_tick(fp)
    if tick is None:
        print(f"  {d}: 沒有足夠 tick"); continue
    gap_pct = (info["open"] - info["night_close"]) / info["night_close"] * 100
    s = int(np.sign(gap_pct))
    pnl = sim(*tick, s, TP, STOP, CAP)
    monday_pnls.append(pnl)
    monday_dl.append((d, s))
    px, sec = tick
    p300 = px[sec <= 300]
    mfe = (s * (p300 - (px[0] + s*SLIPPAGE))).max()
    print(f"  {d}  gap={gap_pct:+.2f}%({'多' if s==1 else '空'})  "
          f"open={info['open']:.0f} night_close={info['night_close']:.0f}  "
          f"pnl(TP{TP}/S{STOP})={pnl*POINT_VAL:+.0f}  MFE(300s)={mfe:.0f}pt")

r_monday = agg(monday_pnls)
print(f"\n6 個週一合計:")
print(fmt(r_monday, "週一新樣本 (TP80/S30/cap300)"))

# ============================================================
# 合併原本 19 天，看規模擴大後結論
# ============================================================
print("\n" + "#" * 100)
print("# 合併回原本 19 天 0845 樣本 (n=19+6=25)，重新檢查穩健度")
print("#" * 100)

info8 = pd.read_csv(BASE / "gap_ticks" / "gap_days_selected_2026.csv").set_index("date")
data8 = {}
for d in info8.index:
    fp = BASE / "gap_ticks" / f"MXF_{d}.csv"
    if not fp.exists(): continue
    tick = load_tick(fp)
    if tick: data8[d] = tick

dl8_orig = [(d, int(np.sign(info8.loc[d, "gap_night_pct"]))) for d in data8
            if pd.notna(info8.loc[d, "gap_night_pct"]) and abs(info8.loc[d, "gap_night_pct"]) >= 0.5]

# 合併資料
data8_all = dict(data8)
for d in MONDAY_INFO:
    fp = BASE / "gap_ticks_monday" / f"MXF_{d}.csv"
    tick = load_tick(fp)
    if tick: data8_all[d] = tick

dl8_new = dl8_orig + monday_dl
print(f"原本: n={len(dl8_orig)}  加入週一後: n={len(dl8_new)}")

r_orig = agg([sim(*data8[d], s, TP, STOP, CAP) for d, s in dl8_orig])
r_new = agg([sim(*data8_all[d], s, TP, STOP, CAP) for d, s in dl8_new])
print(fmt(r_orig, "原本 19 天 (TP80/S30/cap300)"))
print(fmt(r_new, "加入週一後 25 天"))

h1 = lambda dl: [(d, s) for d, s in dl if d <= "2026-03-31"]
h2 = lambda dl: [(d, s) for d, s in dl if d > "2026-03-31"]
r1 = agg([sim(*data8_all[d], s, TP, STOP, CAP) for d, s in h1(dl8_new)])
r2 = agg([sim(*data8_all[d], s, TP, STOP, CAP) for d, s in h2(dl8_new)])
print(fmt(r1, "  H1 (含新週一)"))
print(fmt(r2, "  H2 (含新週一)"))

# 週一(累積2.5天資訊) vs 平日 分開統計
print("\n" + "#" * 100)
print("# 週一(累積週末) vs 平日 分開統計 — 週一的 gap 是不是系統性更大/更可靠?")
print("#" * 100)
weekday_r = agg([sim(*data8[d], s, TP, STOP, CAP) for d, s in dl8_orig])
monday_r = agg([sim(*data8_all[d], s, TP, STOP, CAP) for d, s in monday_dl])
print(fmt(weekday_r, "平日(週二~五, 原19天)"))
print(fmt(monday_r, "週一(新發現6天)"))
print(f"\n平日 gap 幅度: 中位數約 0.7-0.8% (見先前分析)")
gaps_monday = [(info["open"]-info["night_close"])/info["night_close"]*100 for info in MONDAY_INFO.values()]
print(f"週一 gap 幅度: {[f'{g:+.2f}%' for g in gaps_monday]}  中位數={np.median(np.abs(gaps_monday)):.2f}%")
