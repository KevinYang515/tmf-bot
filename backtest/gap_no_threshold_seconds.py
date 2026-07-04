# -*- coding: utf-8 -*-
"""
「只要跳空就做」(無門檻) × 秒級出場 × 三種合約成本結構 的完整回測。
0845 (68天) 與 1500 (71天) 兩場都測。

成本假設（點數，單位=指數點，來回合計）：
  TMF 微台 (點值 NT$10):  手續費+稅 5.6pt, 出場市價滑價 5pt   (現行回測假設)
  MXF 小台 (點值 NT$50):  手續費+稅 3.6pt, 出場市價滑價 3pt   (估)
  TXF 大台 (點值 NT$200): 手續費+稅 2.3pt, 出場市價滑價 1pt   (估,簿最厚)
進場 = 集合競價撮合價，無滑價（真實交易者成交明細已證實此假設）。

資料偏差聲明：tick 資料只涵蓋「大波動日」(0845: |gap_night|>=0.5% 或 |gap_day|>=1%；
1500 同類篩選)。真正的「無門檻」會多出幾十個更安靜的日子，那些日子 gap≈0、
方向≈擲硬幣、EV≈-成本。所以本測試的「無門檻」結果是【偏樂觀的上界】。
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent

COSTS = {
    "TMF(點值10)":  {"pv": 10,  "comm": 5.6, "slip": 5},
    "MXF(點值50)":  {"pv": 50,  "comm": 3.6, "slip": 3},
    "TXF(點值200)": {"pv": 200, "comm": 2.3, "slip": 1},
}

_CACHE = {}


def load_tick(fp, after_time):
    if fp in _CACHE:
        return _CACHE[fp]
    if not fp.exists():
        _CACHE[fp] = None
        return None
    t = pd.read_csv(fp)
    t["ts"] = pd.to_datetime(t["ts"])
    t = t[t["ts"].dt.strftime("%H:%M:%S") >= after_time].sort_values("ts")
    if len(t) < 50:
        _CACHE[fp] = None
        return None
    r = (t["close"].values.astype(np.float64),
         (t["ts"] - t["ts"].iloc[0]).dt.total_seconds().values)
    _CACHE[fp] = r
    return r


def sim(px, sec, s, hold_s, stop, comm, slip):
    mask = sec <= hold_s
    p = px[mask]
    if len(p) < 2: return None
    fav = s * (p - p[0])
    if stop is not None and (fav <= -stop).any():
        return -stop - slip - comm
    idx = np.searchsorted(sec, hold_s)
    if idx >= len(px): idx = len(px) - 1
    return s * (px[idx] - px[0]) - slip - comm


def agg(pnls, pv):
    p = np.array([x for x in pnls if x is not None]) * pv
    if len(p) == 0: return None
    wins = p[p > 0]; losses = p[p < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {"n": len(p), "total": p.sum(), "EV": p.mean(),
            "win%": (p > 0).mean() * 100, "PF": pf, "worst": p.min()}


def fmt(r, label, w=40):
    if r is None: return f"  {label:<{w}s}  (n=0)"
    return (f"  {label:<{w}s} n={r['n']:>3d} total={r['total']:>+11,.0f} EV={r['EV']:>+8,.0f} "
            f"win={r['win%']:>5.1f}% PF={r['PF']:>5.2f} worst={r['worst']:>+9,.0f}")


# ---------- 0845 ----------
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
rows845 = []
for d in info.index:
    fp = BASE / "gap_ticks" / f"MXF_{d}.csv"
    if load_tick(fp, "08:45:00") is None: continue
    rows845.append((d, info.loc[d, "gap_night_pct"], fp))
for d, mi in MONDAY_INFO.items():
    fp = BASE / "gap_ticks_monday" / f"MXF_{d}.csv"
    if load_tick(fp, "08:45:00") is None: continue
    rows845.append((d, (mi["open"] - mi["night_close"]) / mi["night_close"] * 100, fp))

print("#" * 112)
print("# 0845 場 — 3秒全出+停損50, 無門檻(全68天) vs 現行門檻0.5%(25天), 三種合約成本")
print("#" * 112)
for cname, c in COSTS.items():
    print(f"--- {cname}: 成本{c['comm']}pt + 出場滑價{c['slip']}pt ---")
    for label, th in [("無門檻(只要跳空就做)", 0.0), ("門檻0.5%(現行)", 0.5)]:
        dl = [(d, fp, int(np.sign(g))) for d, g, fp in rows845 if abs(g) >= th and g != 0]
        pnls = [sim(*load_tick(fp, "08:45:00"), s, 3, 50, c["comm"], c["slip"]) for d, fp, s in dl]
        r = agg(pnls, c["pv"])
        print(fmt(r, f"{label}"))
        for half, lo_d, hi_d in [("H1", "", "2026-03-31"), ("H2", "2026-03-31", "9999")]:
            sub = [(d, fp, s) for d, fp, s in dl if (d <= hi_d if half == "H1" else d > lo_d)]
            rh = agg([sim(*load_tick(fp, "08:45:00"), s, 3, 50, c["comm"], c["slip"]) for d, fp, s in sub], c["pv"])
            if rh: print(fmt(rh, f"    {half}"))
    print()

# ---------- 1500 ----------
info15 = pd.read_csv(BASE / "gap_ticks_1500" / "gap_1500_days_selected.csv").set_index("date")
rows15 = []
for d in info15.index:
    fp = BASE / "gap_ticks_1500" / f"N1500_{d}.csv"
    if load_tick(fp, "15:00:00") is None: continue
    rows15.append((d, info15.loc[d, "gap_1500_pct"], fp))

print("#" * 112)
print("# 1500 場 — 秒級出場測試（現行部署: 只做空+動態TP/S80/cap180, 回測EV+725）")
print("#" * 112)
print(f"1500 tick 天數: {len(rows15)}")
c = COSTS["TMF(點值10)"]
for label, filt in [
    ("無門檻,多空都做", lambda g: g != 0),
    ("無門檻,只做空", lambda g: g < 0),
    ("門檻0.3%,多空都做", lambda g: abs(g) >= 0.3),
    ("門檻0.3%,只做空(現行方向濾網)", lambda g: g <= -0.3),
]:
    print(f"--- {label} (TMF成本) ---")
    dl = [(d, fp, int(np.sign(g))) for d, g, fp in rows15 if filt(g)]
    for hold in [2, 3, 5, 10]:
        pnls = [sim(*load_tick(fp, "15:00:00"), s, hold, 50, c["comm"], c["slip"]) for d, fp, s in dl]
        r = agg(pnls, c["pv"])
        print(fmt(r, f"  hold={hold}s stop=50"))

# 現行1500設定的對照（動態TP/S80/cap180）需要 gap 點數
print()
print("--- 對照: 現行1500部署設定(只做空+動態TP clip(0.4g,100,300)/S80/cap180) ---")


def sim_cur1500(px, sec, s, gap_pts):
    COMM, SLIP = 5.6, 5
    p = px[sec <= 180]
    if len(p) < 2: return None
    tp = float(np.clip(0.4 * gap_pts, 100, 300))
    be = p[0] + s * SLIP
    fav = s * (p - be)
    i_tp = (fav >= tp).argmax() if (fav >= tp).any() else len(p)
    i_st = (fav <= -80).argmax() if (fav <= -80).any() else len(p)
    if i_tp < i_st: return tp - COMM
    if i_st < len(p): return -80 - COMM
    return fav[-1] - COMM


dl = [(d, fp, -1, abs(info15.loc[d, "night_open"] - info15.loc[d, "day_close"]))
      for d, g, fp in rows15 if g <= -0.3]
r = agg([sim_cur1500(*load_tick(fp, "15:00:00"), s, gp) for d, fp, s, gp in dl], 10)
print(fmt(r, "  現行設定"))
