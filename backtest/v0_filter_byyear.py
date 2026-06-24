"""
V0 + KOSPI filter — by year breakdown (stability check)
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
POINT_VAL = 10
COMMISSION = 5.6
SLIPPAGE = 5
STOP_TICKS = 150
CUTOFF = (13, 44)

df_min = pd.read_csv(BASE / "mxf_1min.csv")
df_min["ts"] = pd.to_datetime(df_min["ts"])
df_min["date"] = df_min["ts"].dt.date.astype(str)
df_min["time"] = df_min["ts"].dt.strftime("%H:%M")
df_min["minute_int"] = df_min["ts"].dt.hour * 60 + df_min["ts"].dt.minute
sig = pd.read_csv(BASE / "intraday_signals_v2.csv").set_index("date")
daily = pd.read_csv(BASE / "daily_open.csv")
daily_dict = {row["date"]: row for _, row in daily.iterrows()}

by_date = {}
for d, g in df_min.groupby("date"):
    g2 = g.sort_values("ts")
    by_date[d] = {
        "minute": g2["minute_int"].values,
        "hi": g2["High"].values.astype(np.float64),
        "lo": g2["Low"].values.astype(np.float64),
        "cl": g2["Close"].values.astype(np.float64),
        "open08": None,
    }
    op = g2[g2["time"] == "08:46"]
    if not op.empty:
        by_date[d]["open08"] = float(op.iloc[0]["Open"])


def get_open(d):
    bd = by_date.get(d)
    if bd is None: return None
    bo = bd["open08"]
    if d in daily_dict:
        v = daily_dict[d].get("open_0845")
        if v is not None and not pd.isna(v) and bo is not None:
            if abs(float(v) - bo) <= 200:
                return float(v)
    return bo


def build_bars(d):
    ch, cm = CUTOFF
    cutoff_min = ch * 60 + cm
    bd = by_date.get(d)
    if bd is None: return None
    mask = (bd["minute"] >= (8 * 60 + 46)) & (bd["minute"] <= cutoff_min)
    hi = bd["hi"][mask]
    if len(hi) == 0: return None
    return hi, bd["lo"][mask], bd["cl"][mask]


def sim_A(entry, bars, direction, tp1=100, tp2=200, stop=STOP_TICKS):
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
        if stop_idx < n and stop_idx <= tp_idx: fill = stop_p
        elif tp_idx < n: fill = tp_p
        else: fill = cl[-1]
        pnl += direction * (fill - be) - COMMISSION
    return pnl * POINT_VAL


def get_factors(d):
    if d not in sig.index: return None
    row = sig.loc[d]
    return {"nq": row.get("nq_0845_pct", np.nan),
            "kos": row.get("kospi_open_gap_pct", np.nan),
            "nkx": row.get("nkx_open_gap_pct", np.nan)}


def s_v0(f):
    if not pd.notna(f["nq"]): return 0
    return int(np.sign(f["nq"])) if abs(f["nq"]) > 0.5 else 0

def s_v0_kc_strict(f):
    s = s_v0(f)
    if s == 0: return 0
    if not pd.notna(f["kos"]): return 0
    if np.sign(f["kos"]) == s and abs(f["kos"]) > 0.3: return s
    return 0

def s_v0_anti_kn(f):
    s = s_v0(f)
    if s == 0: return 0
    if not (pd.notna(f["kos"]) and pd.notna(f["nkx"])): return s
    if np.sign(f["kos"]) == -s and np.sign(f["nkx"]) == -s and abs(f["kos"]) > 0.3:
        return 0
    return s

def s_v0_lowth(f):
    if not pd.notna(f["nq"]): return 0
    if abs(f["nq"]) < 0.3: return 0
    s = int(np.sign(f["nq"]))
    if not pd.notna(f["kos"]): return 0
    if np.sign(f["kos"]) == s and abs(f["kos"]) > 0.3: return s
    return 0


def by_year_report(sig_fn, label):
    trades = []
    for d in sig.index:
        f = get_factors(d)
        if f is None: continue
        s = sig_fn(f)
        if s == 0: continue
        bars = build_bars(d)
        if bars is None: continue
        entry = get_open(d)
        if entry is None: continue
        pnl = sim_A(entry, bars, s)
        trades.append((d, s, pnl, f))
    if not trades:
        print(f">>> {label}: 0 trades")
        return
    print(f"\n>>> {label}")
    print(f"  {'year':<6s} {'n':>4s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'PF':>6s} {'Sharpe':>7s}")
    by_yr = {}
    for d, s, pnl, f in trades:
        yr = d[:4]
        by_yr.setdefault(yr, []).append(pnl)
    for yr in sorted(by_yr.keys()):
        pnls = np.array(by_yr[yr])
        wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
        pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
        sharpe = pnls.mean() / pnls.std() * np.sqrt(252) if pnls.std() > 0 else 0
        print(f"  {yr:<6s} {len(pnls):>4d} {pnls.sum():>+10,.0f} {pnls.mean():>+8,.0f} "
              f"{(pnls>0).mean()*100:>5.1f}% {pf:>6.2f} {sharpe:>+7.2f}")

    # 半年 split (檢查近期表現)
    print(f"\n  By half-year:")
    print(f"  {'period':<10s} {'n':>4s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'PF':>6s}")
    by_h = {}
    for d, s, pnl, f in trades:
        y = d[:4]; m = int(d[5:7])
        h = f"{y}H{1 if m <= 6 else 2}"
        by_h.setdefault(h, []).append(pnl)
    for h in sorted(by_h.keys()):
        pnls = np.array(by_h[h])
        wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
        pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
        print(f"  {h:<10s} {len(pnls):>4d} {pnls.sum():>+10,.0f} {pnls.mean():>+8,.0f} "
              f"{(pnls>0).mean()*100:>5.1f}% {pf:>6.2f}")

    # 明細
    print(f"\n  最近 20 筆明細:")
    print(f"  {'date':<12s} {'dir':>4s} {'NQ%':>7s} {'KOS%':>7s} {'NKX%':>7s} {'pnl':>10s} {'cum':>10s}")
    cum = 0
    for d, s, pnl, f in trades[-20:]:
        cum += pnl
        print(f"  {d:<12s} {s:>+4d} {f['nq']:>+7.2f} {f['kos']:>+7.2f} {f['nkx']:>+7.2f} "
              f"{pnl:>+10,.0f} {cum:>+10,.0f}")


print("=" * 110)
print("by year + by half-year stability")
print("=" * 110)
by_year_report(s_v0,          "V0          baseline 純 NQ |%|>0.5")
by_year_report(s_v0_kc_strict,"V0_kc_strict V0 + KOSPI 同向 + |kos|>0.3%  ★")
by_year_report(s_v0_anti_kn,  "V0_anti_kn   V0 但 KOSPI+NKX 雙反向跳過")
by_year_report(s_v0_lowth,    "V0_lowth     NQ>0.3% + KOSPI>0.3% 同向")
