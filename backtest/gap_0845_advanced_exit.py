# -*- coding: utf-8 -*-
"""
延續「秒級出場」的優化方向。核心洞察(見GAP_STRATEGY.md §3.4補充驗證2)：
不管gap大小，開盤瞬間約有一半的日子會先隨機洗一輪(~40pt)才決定真正方向，
3秒出場能贏是因為「縮短曝險時間跳過雜訊窗」，不是靠拉寬停損硬扛。

順著這個邏輯往下測三個新方向：
E) 精細 hold 秒數 sweep (1~5秒每0.5秒一格)，把峰值找精確
F) 延遲武裝停損：開盤前 X 秒不判斷停損（讓雜訊過去），X秒後才開始監控停損，
   固定 hold 3秒出場 —— 直接對應「洗盤是開盤瞬間的固定現象」這個發現
G) 確認進場：開盤後等 Y 秒，若價格已經是逆向(不利)超過某個小閾值，
   當天直接不進場（跳過會被雜訊坑到的那些日子）
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

def fmt(r, label, w=34):
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
print(f"門檻0.5% n={len(DL)} (H1={len(H1)}/H2={len(H2)})")


def sim_sec(px, sec, s, hold_s, stop, arm_delay=0.0):
    """arm_delay: 前 arm_delay 秒不檢查停損"""
    p = px[sec <= hold_s]
    s_sec = sec[sec <= hold_s]
    if len(p) < 2: return None
    fav = s * (p - p[0])
    if stop is not None:
        mask = s_sec >= arm_delay
        if mask.any() and (fav[mask] <= -stop).any():
            return -stop - SLIP - COMM
    idx = np.searchsorted(sec, hold_s)
    if idx >= len(px): idx = len(px)-1
    return s * (px[idx]-px[0]) - SLIP - COMM


def sim_confirm(px, sec, s, hold_s, stop, confirm_s, confirm_thresh):
    """
    修正版：集合競價進場無法事後取消，開盤那一刻已經強制成交。
    confirm_s秒後若逆向超過confirm_thresh，是『提前認賠出場』，不是『當作沒進場』。
    這裡回傳的是真實出場的虧損(用confirm_s當下的價格認賠+出場滑價+成本)，
    不是 None。若沒觸發提前出場，正常跑到 hold_s 或原本的停損/續抱邏輯。
    """
    idx_c = np.searchsorted(sec, confirm_s)
    if idx_c >= len(px): idx_c = len(px) - 1
    check_px = px[idx_c]
    adverse = -(s * (check_px - px[0]))
    if adverse > confirm_thresh:
        return -adverse - SLIP - COMM  # 提前認賠出場，真實虧損，不是0
    return sim_sec(px, sec, s, hold_s, stop)


print()
print("="*100)
print("E) 精細 hold 秒數 sweep (停損固定50)")
print("="*100)
for hold in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]:
    r = agg([sim_sec(*load_tick(fp), s, hold, 50) for d, fp, s in DL])
    r1 = agg([sim_sec(*load_tick(fp), s, hold, 50) for d, fp, s in H1])
    r2 = agg([sim_sec(*load_tick(fp), s, hold, 50) for d, fp, s in H2])
    print(fmt(r, f"hold={hold}s"))
    if r1: print(fmt(r1, "  H1"))
    if r2: print(fmt(r2, "  H2"))

print()
print("="*100)
print("F) 延遲武裝停損：前 X 秒不判斷停損，hold固定3秒出場，停損50")
print("="*100)
for arm in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]:
    r = agg([sim_sec(*load_tick(fp), s, 3.0, 50, arm_delay=arm) for d, fp, s in DL])
    r1 = agg([sim_sec(*load_tick(fp), s, 3.0, 50, arm_delay=arm) for d, fp, s in H1])
    r2 = agg([sim_sec(*load_tick(fp), s, 3.0, 50, arm_delay=arm) for d, fp, s in H2])
    print(fmt(r, f"arm_delay={arm}s"))
    if r1: print(fmt(r1, "  H1"))
    if r2: print(fmt(r2, "  H2"))

print()
print("="*100)
print("G) 修正版-提前認賠：開盤後 confirm_s 秒，逆向超過 thresh 就認賠出場(不是跳過不進場)")
print("   集合競價entry無法取消，這裡是『提早停損』不是『當作沒進場』")
print("="*100)
for confirm_s in [1.0, 2.0]:
    for thresh in [15, 25, 35, 50]:
        pnls = [sim_confirm(*load_tick(fp), s, 3.0, 50, confirm_s, thresh) for d, fp, s in DL]
        n_early = sum(1 for d, fp, s in DL
                      if -(s * (load_tick(fp)[0][np.searchsorted(load_tick(fp)[1], confirm_s)] - load_tick(fp)[0][0])) > thresh)
        r = agg(pnls)
        print(fmt(r, f"confirm@{confirm_s}s>{thresh}pt提前出場(觸發{n_early}天)"))

print()
print("="*100)
print("F+G 混合：延遲武裝(1s) + hold3s + 停損50，跟純3s版對照")
print("="*100)
r_base = agg([sim_sec(*load_tick(fp), s, 3.0, 50) for d, fp, s in DL])
r_arm1 = agg([sim_sec(*load_tick(fp), s, 3.0, 50, arm_delay=1.0) for d, fp, s in DL])
print(fmt(r_base, "純3秒出場+停損50(基準)"))
print(fmt(r_arm1, "延遲武裝1秒+3秒出場+停損50"))
r1 = agg([sim_sec(*load_tick(fp), s, 3.0, 50, arm_delay=1.0) for d, fp, s in H1])
r2 = agg([sim_sec(*load_tick(fp), s, 3.0, 50, arm_delay=1.0) for d, fp, s in H2])
print(fmt(r1, "  H1")); print(fmt(r2, "  H2"))
