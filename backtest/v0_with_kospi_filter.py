"""
KOSPI 當 V0 的 filter 試試看
=============================
觀察: KOSPI 開盤 gap 對 TX gap 預測 hit 92%, 但 entry @ 08:46 太晚, 沒 PnL edge
       但也許可以用 KOSPI 作為「方向確認」filter ─ 只在 NQ 訊號方向跟 KOSPI gap 同向時進場

對照:
  V0 純 NQ            (baseline)
  V0_kc 只在 KOSPI 同向時進
  V0_kc_strict 只在 KOSPI 同向且 |kos|>0.3% 時進
  V0_kc_anti 在 KOSPI 反向時不進  (跟 V0_kc 等效)
  V0_nc_anti 在 NQ 跟 KOSPI 反向時用 KOSPI 方向  (反轉)
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
    return {
        "nq":  row.get("nq_0845_pct", np.nan),
        "kos": row.get("kospi_open_gap_pct", np.nan),
        "nkx": row.get("nkx_open_gap_pct", np.nan),
    }


def base_nq_sig(f):
    if not pd.notna(f["nq"]): return 0
    return int(np.sign(f["nq"])) if abs(f["nq"]) > 0.5 else 0


def run(sig_fn, label):
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
    if not trades: return {"label": label, "n": 0}
    pnls = np.array([t[2] for t in trades])
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum).max()
    wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {
        "label": label, "n": len(pnls),
        "total": round(pnls.sum(), 0), "EV": round(pnls.mean(), 0),
        "win%": round((pnls > 0).mean() * 100, 1),
        "sharpe": round(pnls.mean() / pnls.std() * np.sqrt(252), 2) if pnls.std() > 0 else 0,
        "PF": round(pf, 2), "maxDD": round(dd, 0), "trades": trades,
    }


# Strategies
def s_v0(f):
    return base_nq_sig(f)

def s_v0_kc(f):
    """V0 but only when KOSPI gap is same direction"""
    s = base_nq_sig(f)
    if s == 0: return 0
    if not pd.notna(f["kos"]): return s  # KOSPI missing: trust V0
    if np.sign(f["kos"]) == s or f["kos"] == 0: return s
    return 0  # 反向 → 不進

def s_v0_kc_strict(f):
    """V0 but require KOSPI same direction AND |kos|>0.3%"""
    s = base_nq_sig(f)
    if s == 0: return 0
    if not pd.notna(f["kos"]): return 0
    if np.sign(f["kos"]) == s and abs(f["kos"]) > 0.3: return s
    return 0

def s_v0_knc(f):
    """V0 + KOSPI + NKX 三者都同向才進"""
    s = base_nq_sig(f)
    if s == 0: return 0
    if not (pd.notna(f["kos"]) and pd.notna(f["nkx"])): return 0
    if np.sign(f["kos"]) == s and np.sign(f["nkx"]) == s: return s
    return 0

def s_v0_anti_kn(f):
    """V0 but skip when KOSPI AND NKX both oppose"""
    s = base_nq_sig(f)
    if s == 0: return 0
    if not (pd.notna(f["kos"]) and pd.notna(f["nkx"])): return s
    if np.sign(f["kos"]) == -s and np.sign(f["nkx"]) == -s and abs(f["kos"]) > 0.3:
        return 0  # 兩個都反 → 跳過
    return s

def s_v0_lowth(f):
    """放寬 NQ 門檻 0.3% + 必須 KOSPI 同向 +0.3%"""
    if not pd.notna(f["nq"]): return 0
    if abs(f["nq"]) < 0.3: return 0
    s = int(np.sign(f["nq"]))
    if not pd.notna(f["kos"]): return 0
    if np.sign(f["kos"]) == s and abs(f["kos"]) > 0.3: return s
    return 0

def s_v0_lowth_03(f):
    """NQ 門檻放到 0.3% 但無 KOSPI filter"""
    if not pd.notna(f["nq"]): return 0
    return int(np.sign(f["nq"])) if abs(f["nq"]) > 0.3 else 0


print()
print("=" * 105)
print("【V0 + KOSPI filter 各種組合】 cutoff=13:44 exit=A")
print("=" * 105)
print(f"{'label':<45s} {'n':>5s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>7s} {'PF':>6s} {'maxDD':>10s}")

for fn, lbl in [
    (s_v0,           "V0          純 NQ |%|>0.5  (baseline)"),
    (s_v0_kc,        "V0_kc       V0 + KOSPI 同向 (KOSPI 缺時 trust V0)"),
    (s_v0_kc_strict, "V0_kc_strict V0 + KOSPI 同向 + |kos|>0.3%"),
    (s_v0_knc,       "V0_knc      V0 + KOSPI + NKX 三者同向"),
    (s_v0_anti_kn,   "V0_anti_kn  V0 但 KOSPI/NKX 雙反向時跳過"),
    (s_v0_lowth,     "V0_lowth    NQ>0.3% + KOSPI>0.3% 同向"),
    (s_v0_lowth_03,  "V0_loose_03 NQ>0.3% only (對照組)"),
]:
    r = run(fn, lbl)
    if r["n"] == 0:
        print(f"{lbl:<45s} 0")
        continue
    print(f"{lbl:<45s} {r['n']:>5d} {r['total']:>+10,.0f} {r['EV']:>+8,.0f} "
          f"{r['win%']:>5.1f}% {r['sharpe']:>+7.2f} {r['PF']:>6.2f} {r['maxDD']:>+10,.0f}")

print()
print("結論判讀規則:")
print("  - 比 baseline V0 (Sharpe +3.33, PF 1.57) 顯著好 才值得換")
print("  - n 太少 (<30) 不可靠")
print("  - by year 也要穩定才能上線")
