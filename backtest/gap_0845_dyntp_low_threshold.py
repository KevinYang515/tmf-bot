# -*- coding: utf-8 -*-
"""
User 提案：跳空小 → TP 跟著縮緊，這樣門檻就可以降低，小跳空日（06/29 -0.45%
這種）也能吃。TP = clip(alpha × |gap點數|, 地板, 80)，80 = 現行大 gap 的 TP 上限。

之前 §3.1 D4 只在「>=0.5% 門檻內」測過動態 TP（結論：輸固定80）；
「降門檻 + 比例縮TP」的組合是新實驗，這裡補測。

資料限制（誠實聲明）：tick 資料只涵蓋「|gap_night|>=0.5% 或 |gap_day|>=1%」的
68 天。門檻降到 0.5% 以下時，樣本裡的小跳空日全都是「當天同時有大 gap_day」的
日子，缺少「純小跳空、前日也平靜」的日子 → 低門檻的結果會偏樂觀/偏誤，只能當方向參考。
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
POINT_VAL, COMMISSION, SLIPPAGE = 10, 5.6, 5

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


def load_tick(d, tick_dir="gap_ticks"):
    key = (d, tick_dir)
    if key in _CACHE:
        return _CACHE[key]
    fp = BASE / tick_dir / f"MXF_{d}.csv"
    if not fp.exists():
        _CACHE[key] = None
        return None
    t = pd.read_csv(fp)
    t["ts"] = pd.to_datetime(t["ts"])
    t = t[t["ts"].dt.strftime("%H:%M:%S") >= "08:45:00"].sort_values("ts")
    if len(t) < 50:
        _CACHE[key] = None
        return None
    r = (t["close"].values.astype(np.float64),
         (t["ts"] - t["ts"].iloc[0]).dt.total_seconds().values)
    _CACHE[key] = r
    return r


def sim(px, sec, s, tp, stop, tmax_s):
    p = px[sec <= tmax_s]
    if len(p) < 2: return None
    be = p[0] + s * SLIPPAGE
    fav = s * (p - be)
    i_tp = (fav >= tp).argmax() if tp is not None and (fav >= tp).any() else len(p)
    i_st = (fav <= -stop).argmax() if stop is not None and (fav <= -stop).any() else len(p)
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


def fmt(r, label, w=44):
    if r is None: return f"  {label:<{w}s}  (n=0)"
    return (f"  {label:<{w}s} n={r['n']:>3d} total={r['total']:>+9,.0f} EV={r['EV']:>+7,.0f} "
            f"win={r['win%']:>5.1f}% PF={r['PF']:>5.2f} worst={r['worst']:>+8,.0f}")


# rows: (date, gap_pct, gap_pts, tick_dir)
rows = []
for d in info.index:
    if load_tick(d, "gap_ticks") is None: continue
    g = info.loc[d, "gap_night_pct"]
    gpts = abs(info.loc[d, "open"] - info.loc[d, "night_close"])
    rows.append((d, g, gpts, "gap_ticks"))
for d, mi in MONDAY_INFO.items():
    if load_tick(d, "gap_ticks_monday") is None: continue
    g = (mi["open"] - mi["night_close"]) / mi["night_close"] * 100
    rows.append((d, g, abs(mi["open"] - mi["night_close"]), "gap_ticks_monday"))

CAP = 300

print("=" * 110)
print("基準：現行固定 TP80/S30, 門檻 0.5%")
print("=" * 110)
base = [(d, td, int(np.sign(g))) for d, g, gp, td in rows if abs(g) >= 0.5]
r = agg([sim(*load_tick(d, td), s, 80, 30, CAP) for d, td, s in base])
print(fmt(r, "門檻0.5% 固定TP80/S30 (現行)"))

print()
print("=" * 110)
print("實驗A：動態 TP = clip(alpha × gap點數, floor, 80)，停損固定30，門檻 sweep")
print("=" * 110)
for th in [0.15, 0.25, 0.35, 0.5]:
    dl = [(d, td, int(np.sign(g)), gp) for d, g, gp, td in rows if abs(g) >= th]
    print(f"--- 門檻 {th}% (n={len(dl)}) ---")
    for alpha in [0.2, 0.3, 0.4, 0.6]:
        for floor in [20, 30, 40]:
            pnls = []
            for d, td, s, gp in dl:
                tp = float(np.clip(alpha * gp, floor, 80))
                pnls.append(sim(*load_tick(d, td), s, tp, 30, CAP))
            r = agg(pnls)
            if r and r["EV"] > 0:
                print(fmt(r, f"  a={alpha} floor={floor}"))

print()
print("=" * 110)
print("實驗B：同 A 但停損也跟著縮 stop = max(0.4×TP, 15)")
print("=" * 110)
for th in [0.15, 0.25, 0.35, 0.5]:
    dl = [(d, td, int(np.sign(g)), gp) for d, g, gp, td in rows if abs(g) >= th]
    print(f"--- 門檻 {th}% (n={len(dl)}) ---")
    for alpha in [0.2, 0.3, 0.4, 0.6]:
        for floor in [20, 30, 40]:
            pnls = []
            for d, td, s, gp in dl:
                tp = float(np.clip(alpha * gp, floor, 80))
                stop = max(0.4 * tp, 15)
                pnls.append(sim(*load_tick(d, td), s, tp, stop, CAP))
            r = agg(pnls)
            if r and r["EV"] > 0:
                print(fmt(r, f"  a={alpha} floor={floor} stop=0.4TP"))

print()
print("=" * 110)
print("實驗C：最有希望組合的 walk-forward (H1 01-03 / H2 04-07) + 與基準對照")
print("=" * 110)


def run_combo(th, alpha, floor, stop_mode, half=None):
    dl = [(d, td, int(np.sign(g)), gp) for d, g, gp, td in rows if abs(g) >= th]
    if half == "H1": dl = [x for x in dl if x[0] <= "2026-03-31"]
    if half == "H2": dl = [x for x in dl if x[0] > "2026-03-31"]
    pnls = []
    for d, td, s, gp in dl:
        tp = float(np.clip(alpha * gp, floor, 80))
        stop = max(0.4 * tp, 15) if stop_mode == "scaled" else 30
        pnls.append(sim(*load_tick(d, td), s, tp, stop, CAP))
    return agg(pnls)


COMBOS = [
    (0.25, 0.3, 30, "fixed"),
    (0.25, 0.4, 30, "fixed"),
    (0.35, 0.3, 30, "fixed"),
    (0.35, 0.4, 30, "fixed"),
    (0.35, 0.4, 40, "fixed"),
]
for th, alpha, floor, sm in COMBOS:
    print(f"--- th={th}% a={alpha} floor={floor} stop={'0.4TP' if sm=='scaled' else '30'} ---")
    print(fmt(run_combo(th, alpha, floor, sm), "  全樣本"))
    print(fmt(run_combo(th, alpha, floor, sm, "H1"), "  H1"))
    print(fmt(run_combo(th, alpha, floor, sm, "H2"), "  H2"))

print()
print("=" * 110)
print("實驗D：新增的『0.15~0.5% 小跳空區間』單獨看（增量部分是賺是賠？含 user 三天中的 06/29, 07/02）")
print("=" * 110)
for alpha, floor in [(0.3, 20), (0.3, 30), (0.4, 20), (0.4, 30), (0.6, 20)]:
    dl = [(d, td, int(np.sign(g)), gp) for d, g, gp, td in rows if 0.15 <= abs(g) < 0.5]
    pnls = []
    for d, td, s, gp in dl:
        tp = float(np.clip(alpha * gp, floor, 80))
        pnls.append(sim(*load_tick(d, td), s, tp, 30, CAP))
    r = agg(pnls)
    print(fmt(r, f"僅小跳空日 a={alpha} floor={floor}"))

print()
print("小跳空日逐日明細 (a=0.4, floor=20):")
dl = [(d, td, int(np.sign(g)), gp, g) for d, g, gp, td in rows if 0.15 <= abs(g) < 0.5]
for d, td, s, gp, g in sorted(dl):
    tp = float(np.clip(0.4 * gp, 20, 80))
    pnl = sim(*load_tick(d, td), s, tp, 30, CAP)
    flag = "  <== user關注" if d in ("2026-06-29", "2026-07-02") else ""
    if pnl is not None:
        print(f"  {d}  gap={g:+.2f}% ({gp:.0f}點)  TP={tp:.0f}  pnl={pnl*POINT_VAL:+,.0f}{flag}")
