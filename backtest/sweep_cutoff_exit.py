"""
1500 session - cutoff & exit strategy sweep (optimised)
================================================
A = fixed TP +100/+200, stop -50（兩口配置）
C = TP1+100 拿走 1 口，剩 1 口 break-even stop + trailing 50 ticks
D = 純 trailing 50 ticks 兩口一起，初始 hard stop -50
× 4 cutoffs: 21:30 / 23:00 / 03:00 / 05:00
"""
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

BASE = Path(__file__).parent
POINT_VAL = 10
COMMISSION = 5.6
SLIPPAGE = 5
THRESHOLD = 0.1

print("載入 K bar ...", end=" ", flush=True)
df_min = pd.read_csv(BASE / "mxf_1min.csv")
df_min["ts"] = pd.to_datetime(df_min["ts"])
df_min["date"] = df_min["ts"].dt.date.astype(str)
df_min["time"] = df_min["ts"].dt.strftime("%H:%M")
df_min["minute_int"] = df_min["ts"].dt.hour * 60 + df_min["ts"].dt.minute
print(f"{len(df_min)} 筆", flush=True)

intraday = pd.read_csv(BASE / "intraday_signals.csv").set_index("date")
daily = pd.read_csv(BASE / "daily_open.csv")
daily_dict = {row["date"]: row for _, row in daily.iterrows()}

# Pre-group by date (一次性，之後 O(1) lookup)
print("預分組 K bar by date ...", end=" ", flush=True)
by_date = {}
for d, g in df_min.groupby("date"):
    g2 = g.sort_values("ts")
    by_date[d] = {
        "minute": g2["minute_int"].values,
        "hi": g2["High"].values.astype(np.float64),
        "lo": g2["Low"].values.astype(np.float64),
        "cl": g2["Close"].values.astype(np.float64),
        "open15": None,
    }
    op = g2[g2["time"] == "15:01"]
    if not op.empty:
        by_date[d]["open15"] = float(op.iloc[0]["Open"])
print(f"{len(by_date)} 個日子", flush=True)


def get_open(d):
    bd = by_date.get(d)
    if bd is None: return None
    bo = bd["open15"]
    if d in daily_dict:
        v = daily_dict[d].get("open_1500")
        if v is not None and not pd.isna(v) and bo is not None:
            if abs(float(v) - bo) <= 200:
                return float(v)
    return bo


def build_bars(d, cutoff):
    """
    回 (hi, lo, cl) numpy arrays，1500 進場到 cutoff
    cutoff = (hour, minute)
    """
    ch, cm = cutoff
    cutoff_min = ch * 60 + cm

    bd = by_date.get(d)
    if bd is None: return None
    # 當日 15:01 起
    mask_same = bd["minute"] >= (15 * 60 + 1)
    if ch >= 15:
        mask_same &= bd["minute"] <= cutoff_min

    hi = bd["hi"][mask_same]
    lo = bd["lo"][mask_same]
    cl = bd["cl"][mask_same]

    if ch < 15:
        # 跨日：next 曆日 00:00 ~ cutoff
        next_d = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        nbd = by_date.get(next_d)
        if nbd is not None:
            mask_nxt = nbd["minute"] <= cutoff_min
            hi = np.concatenate([hi, nbd["hi"][mask_nxt]])
            lo = np.concatenate([lo, nbd["lo"][mask_nxt]])
            cl = np.concatenate([cl, nbd["cl"][mask_nxt]])

    if len(hi) == 0: return None
    return hi, lo, cl


def get_signal(d):
    if d not in intraday.index: return 0
    raw = intraday.loc[d, "nq_1500"]
    if pd.isna(raw): return 0
    pct = float(raw) / 18000 * 100
    if abs(pct) < THRESHOLD: return 0
    return 1 if pct > 0 else -1


# ==== 策略 A: fixed TP +100/+200 stop=-50 (兩口) ====
def sim_A(entry, bars, direction, tp1=100, tp2=200, stop=50):
    hi, lo, cl = bars
    n = len(hi)
    be = entry + direction * SLIPPAGE
    tp1_p = be + direction * tp1
    tp2_p = be + direction * tp2
    stop_p = be - direction * stop

    stop_mask = (lo <= stop_p) if direction == 1 else (hi >= stop_p)
    stop_idx = stop_mask.argmax() if stop_mask.any() else n

    pnl = 0
    for tp_p in [tp1_p, tp2_p]:
        tp_mask = (hi >= tp_p) if direction == 1 else (lo <= tp_p)
        tp_idx = tp_mask.argmax() if tp_mask.any() else n
        if stop_idx < n and stop_idx <= tp_idx:
            fill = stop_p
        elif tp_idx < n:
            fill = tp_p
        else:
            fill = cl[-1]
        pnl += direction * (fill - be) - COMMISSION
    return pnl * POINT_VAL


# ==== 策略 C: TP1 +100 鎖 1 口 + 剩 1 口 BE+trailing 50 ====
def sim_C(entry, bars, direction, tp1=100, trail=50, init_stop=50):
    hi, lo, cl = bars
    n = len(hi)
    be = entry + direction * SLIPPAGE
    tp1_p = be + direction * tp1
    is_p = be - direction * init_stop

    # Phase 1 — 等 TP1 或初始 stop
    tp1_mask = (hi >= tp1_p) if direction == 1 else (lo <= tp1_p)
    stop_mask = (lo <= is_p) if direction == 1 else (hi >= is_p)
    tp1_idx = tp1_mask.argmax() if tp1_mask.any() else n
    stop_idx = stop_mask.argmax() if stop_mask.any() else n

    if stop_idx < tp1_idx and stop_idx < n:
        # 兩口 stop 出
        return (2 * (direction * (is_p - be)) - 2 * COMMISSION) * POINT_VAL

    if tp1_idx >= n:
        # 兩口 cutoff 平
        last = cl[-1]
        return (2 * (direction * (last - be)) - 2 * COMMISSION) * POINT_VAL

    # 1 口 +tp1 出，剩 1 口進 Phase 2
    pnl_l1 = tp1
    rem_hi = hi[tp1_idx:]
    rem_lo = lo[tp1_idx:]
    rem_cl = cl[tp1_idx:]
    n2 = len(rem_hi)

    cur_stop = be
    peak = tp1_p
    exit_p = None
    for i in range(n2):
        if direction == 1 and rem_lo[i] <= cur_stop:
            exit_p = cur_stop; break
        if direction == -1 and rem_hi[i] >= cur_stop:
            exit_p = cur_stop; break
        c = rem_cl[i]
        if direction == 1:
            if c > peak:
                peak = c
                ns = peak - trail
                if ns > cur_stop: cur_stop = ns
        else:
            if c < peak:
                peak = c
                ns = peak + trail
                if ns < cur_stop: cur_stop = ns
    if exit_p is None: exit_p = rem_cl[-1]

    pnl_l2 = direction * (exit_p - be)
    return (pnl_l1 + pnl_l2 - 2 * COMMISSION) * POINT_VAL


# ==== 策略 D: 純 trailing 50 兩口一起 ====
def sim_D(entry, bars, direction, trail=50, init_stop=50):
    hi, lo, cl = bars
    n = len(hi)
    be = entry + direction * SLIPPAGE
    cur_stop = be - direction * init_stop
    peak = be
    exit_p = None
    for i in range(n):
        if direction == 1 and lo[i] <= cur_stop:
            exit_p = cur_stop; break
        if direction == -1 and hi[i] >= cur_stop:
            exit_p = cur_stop; break
        c = cl[i]
        if direction == 1:
            if c > peak:
                peak = c
                ns = peak - trail
                if ns > cur_stop: cur_stop = ns
        else:
            if c < peak:
                peak = c
                ns = peak + trail
                if ns < cur_stop: cur_stop = ns
    if exit_p is None: exit_p = cl[-1]
    pnl_per_lot = direction * (exit_p - be)
    return (2 * pnl_per_lot - 2 * COMMISSION) * POINT_VAL


def run(sim_fn, cutoff_str, **kw):
    ch, cm = int(cutoff_str[:2]), int(cutoff_str[3:])
    pnls = []
    for d in intraday.index:
        sig = get_signal(d)
        if sig == 0: continue
        bars = build_bars(d, (ch, cm))
        if bars is None: continue
        entry = get_open(d)
        if entry is None: continue
        p = sim_fn(entry, bars, sig, **kw)
        pnls.append(p)
    pnls = np.array(pnls)
    if len(pnls) == 0: return None
    # MDD
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    return {
        "n": len(pnls),
        "total": round(pnls.sum(), 0),
        "EV": round(pnls.mean(), 0),
        "win%": round((pnls > 0).mean() * 100, 1),
        "sharpe": round(pnls.mean() / pnls.std() * np.sqrt(252), 2) if pnls.std() > 0 else 0,
        "max_dd": round(dd.max(), 0),
        "min": round(pnls.min(), 0),
        "max": round(pnls.max(), 0),
    }


CUTOFFS = ["21:30", "23:00", "03:00", "05:00"]
RESULTS = []

print()
print("=" * 110)
print(f"【1500 session - cutoff & exit sweep】 |NQ%|>{THRESHOLD}% 2 口  slip={SLIPPAGE}  comm={COMMISSION}")
print("=" * 110)

for label, fn in [("A 固定 TP+100/+200 stop=-50", sim_A),
                  ("C TP1 鎖 + 剩 1 口 BE+trail50", sim_C),
                  ("D 純 trailing 50 兩口", sim_D)]:
    print(f"\n>>> {label}")
    print(f"  {'cutoff':<8s} {'n':>4s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>7s} {'maxDD':>8s} {'min':>8s} {'max':>8s}")
    for c in CUTOFFS:
        r = run(fn, c)
        if r is None: continue
        r["strat"] = label[0]
        r["cutoff"] = c
        RESULTS.append(r)
        print(f"  {c:<8s} {r['n']:>4d} {r['total']:>+10,.0f} {r['EV']:>+8,.0f} {r['win%']:>5.1f}% "
              f"{r['sharpe']:>+7.2f} {r['max_dd']:>+8,.0f} {r['min']:>+8,.0f} {r['max']:>+8,.0f}")

print("\n" + "=" * 110)
print("【按 Sharpe 排序】")
print("=" * 110)
out = pd.DataFrame(RESULTS).sort_values("sharpe", ascending=False)
print(out.to_string(index=False))

print("\n【按 total PnL 排序】")
print(pd.DataFrame(RESULTS).sort_values("total", ascending=False).to_string(index=False))

out.to_csv(BASE / "sweep_cutoff_exit_results.csv", index=False, encoding="utf-8-sig")
print(f"\n結果存檔 → {BASE / 'sweep_cutoff_exit_results.csv'}")
