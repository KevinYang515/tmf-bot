# -*- coding: utf-8 -*-
"""
實作細節驗證：純「3秒後市價全出」vs「掛好TP躺簿限價單(零延遲) + 3秒逾時強制平倉 +
tick停損監控」的混合方案。

背景：Shioaji 沒有觸價單/智慧單API(見GAP_STRATEGY.md §4)，TP只能用「躺簿LMT」
(掛在簿上，價格穿過時交易所自動撮合，我方零延遲)；停損只能靠自建tick監控+
反應式送MKP(~0.2秒延遲，已用5pt滑價假設吸收)。3秒出場原本是「不論賺賠，時間到
就送MKP出場」——這裡測試如果額外掛一張躺簿TP，是否能在盤中價格衝很快時提早零延遲
入袋，比等到3秒整才送MKP出場更好。
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

def agg(pnls):
    p = np.array([x for x in pnls if x is not None]) * PV
    if len(p) == 0: return None
    wins = p[p>0]; losses = p[p<0]
    pf = wins.sum()/abs(losses.sum()) if losses.sum()!=0 else float("inf")
    return {"n": len(p), "total": p.sum(), "EV": p.mean(), "win%": (p>0).mean()*100, "PF": pf, "worst": p.min()}

def fmt(r, label, w=36):
    if r is None: return f"  {label:<{w}s}  (n=0)"
    return (f"  {label:<{w}s} n={r['n']:>3d} total={r['total']:>+9,.0f} EV={r['EV']:>+7,.0f} "
            f"win={r['win%']:>5.1f}% PF={r['PF']:>5.2f} worst={r['worst']:>+8,.0f}")

rows = []
for d in info.index:
    fp = BASE / "gap_ticks" / f"MXF_{d}.csv"
    if load_tick(fp) is None: continue
    rows.append((d, info.loc[d,"gap_night_pct"], fp))
for d, mi in MONDAY_INFO.items():
    fp = BASE / "gap_ticks_monday" / f"MXF_{d}.csv"
    if load_tick(fp) is None: continue
    rows.append((d, (mi["open"]-mi["night_close"])/mi["night_close"]*100, fp))

DL = [(d, fp, int(np.sign(g))) for d, g, fp in rows if abs(g) >= 0.5]
H1 = [x for x in DL if x[0] <= "2026-03-31"]
H2 = [x for x in DL if x[0] > "2026-03-31"]


def sim_pure_time(px, sec, s, hold_s, stop):
    """基準：純3秒後市價全出，中途只有停損(反應式，含5pt滑價)"""
    p = px[sec <= hold_s]
    if len(p) < 2: return None
    fav = s * (p - p[0])
    if stop is not None and (fav <= -stop).any():
        return -stop - SLIP - COMM
    idx = np.searchsorted(sec, hold_s)
    if idx >= len(px): idx = len(px)-1
    return s * (px[idx]-px[0]) - SLIP - COMM


def sim_hybrid(px, sec, s, hold_s, stop, tp_lmt):
    """
    混合：躺簿TP(價格穿過即撮合，零延遲、不扣滑價只扣手續費) + 停損(反應式,扣滑價)
    + hold_s秒逾時市價平倉(扣滑價)。三者按tick順序，誰先發生算誰的。
    """
    mask = sec <= hold_s
    p = px[mask]
    if len(p) < 2: return None
    fav = s * (p - p[0])  # TP判斷不扣滑價(躺簿單，價格本身就是成交價)
    fav_stop = s * (p - p[0])  # 停損判斷用同樣路徑，但成交要扣滑價
    i_tp = (fav >= tp_lmt).argmax() if (fav >= tp_lmt).any() else len(p)
    i_st = (fav_stop <= -stop).argmax() if stop is not None and (fav_stop <= -stop).any() else len(p)
    if i_tp < i_st:
        return tp_lmt - COMM  # 躺簿成交，無滑價
    if i_st < len(p):
        return -stop - SLIP - COMM  # 停損，反應式，扣滑價
    idx = np.searchsorted(sec, hold_s)
    if idx >= len(px): idx = len(px)-1
    return s * (px[idx]-px[0]) - SLIP - COMM  # 逾時市價平倉，扣滑價


print("="*100)
print("基準：純3秒後市價全出 (停損50，無TP)")
print("="*100)
r = agg([sim_pure_time(*load_tick(fp), s, 3.0, 50) for d, fp, s in DL])
print(fmt(r, "純3秒版(基準)"))
r1 = agg([sim_pure_time(*load_tick(fp), s, 3.0, 50) for d, fp, s in H1])
r2 = agg([sim_pure_time(*load_tick(fp), s, 3.0, 50) for d, fp, s in H2])
print(fmt(r1, "  H1")); print(fmt(r2, "  H2"))

print()
print("="*100)
print("混合方案：躺簿TP(不同距離) + 3秒逾時平倉 + 停損50")
print("="*100)
for tp in [30, 40, 50, 60, 80, 100]:
    r = agg([sim_hybrid(*load_tick(fp), s, 3.0, 50, tp) for d, fp, s in DL])
    r1 = agg([sim_hybrid(*load_tick(fp), s, 3.0, 50, tp) for d, fp, s in H1])
    r2 = agg([sim_hybrid(*load_tick(fp), s, 3.0, 50, tp) for d, fp, s in H2])
    print(fmt(r, f"TP={tp}pt躺簿"))
    if r1: print(fmt(r1, "  H1"))
    if r2: print(fmt(r2, "  H2"))

print()
print("="*100)
print("延遲敏感度：出場滑價從5pt惡化到10/15/20pt，純3秒版還剩多少EV")
print("(模擬0.2秒反應延遲若比預期更差時的影響)")
print("="*100)
def sim_pure_time_slip(px, sec, s, hold_s, stop, slip):
    p = px[sec <= hold_s]
    if len(p) < 2: return None
    fav = s * (p - p[0])
    if stop is not None and (fav <= -stop).any():
        return -stop - slip - COMM
    idx = np.searchsorted(sec, hold_s)
    if idx >= len(px): idx = len(px)-1
    return s * (px[idx]-px[0]) - slip - COMM

for slip in [5, 8, 10, 15, 20]:
    r = agg([sim_pure_time_slip(*load_tick(fp), s, 3.0, 50, slip) for d, fp, s in DL])
    print(fmt(r, f"出場滑價={slip}pt"))
