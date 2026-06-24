"""
複合訊號回測 — 用 NQ + Nikkei + KOSPI 三因子組合進場
====================================================
研究 gap_factor_research.py 發現:
- nkx_ret (前日 Nikkei 收盤變化): corr +0.64 with TX gap
- kospi_ret (前日 KOSPI 收盤變化): corr +0.59 with TX gap
- nq_0845_pct (現用): corr +0.26 only
→ 純 NQ 訊號漏掉很多大 gap 日

對照組:
  V0: 現行  |nq_0845| > 0.50%
  V1: |nq_0845| > 0.50%  OR  |nkx_ret| > 0.50%  OR  |kospi_ret| > 0.50%  (任一觸發)
  V2: 同 V1 + 方向必須跟 sign(nq_0845 + nkx_ret + kospi_ret) 一致 (任一觸發但要 majority 同向)
  V3: 純 |nkx_ret| > 0.50% (單因子實驗)
  V4: 純 |kospi_ret| > 0.50%
  V5: 雙條件 |nkx_ret|>0.5 AND |kospi_ret|>0.5  + 方向同
  V6: vote score >= 2 (ES/NKX/KOSPI/NDX 加權投票)
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

print("載入 K bar ...", end=" ", flush=True)
df_min = pd.read_csv(BASE / "mxf_1min.csv")
df_min["ts"] = pd.to_datetime(df_min["ts"])
df_min["date"] = df_min["ts"].dt.date.astype(str)
df_min["time"] = df_min["ts"].dt.strftime("%H:%M")
df_min["minute_int"] = df_min["ts"].dt.hour * 60 + df_min["ts"].dt.minute
print(f"{len(df_min)} 筆", flush=True)

intraday = pd.read_csv(BASE / "intraday_signals.csv").set_index("date")
intl = pd.read_csv(BASE / "intl_signals.csv").set_index("date")
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


# === 取每天的訊號 ===
def get_factors(d):
    """回傳 (nq_pct, nkx_ret, kospi_ret, es_pct, ndx_ret) 或 None"""
    if d not in intraday.index: return None
    nq = intraday.loc[d, "nq_0845"]
    es = intraday.loc[d, "es_0845"]
    if pd.isna(nq): return None
    nq_pct = float(nq) / 18000 * 100
    es_pct = float(es) / 4500 * 100 if not pd.isna(es) else 0
    nkx = intl.loc[d, "nkx_ret"] if d in intl.index else None
    kos = intl.loc[d, "kospi_ret"] if d in intl.index else None
    ndx = intl.loc[d, "ndx_ret"] if d in intl.index else None
    return {"nq": nq_pct, "es": es_pct,
            "nkx": float(nkx) if nkx is not None and not pd.isna(nkx) else 0,
            "kos": float(kos) if kos is not None and not pd.isna(kos) else 0,
            "ndx": float(ndx) if ndx is not None and not pd.isna(ndx) else 0}


# === 訊號定義 ===
def sig_V0(f):
    """純 NQ |%|>0.5"""
    if abs(f["nq"]) > 0.5: return 1 if f["nq"] > 0 else -1
    return 0

def sig_V1(f):
    """NQ or NKX or KOSPI 任一觸發 (各因子自己決定方向)"""
    if abs(f["nq"]) > 0.5: return 1 if f["nq"] > 0 else -1
    if abs(f["nkx"]) > 0.5: return 1 if f["nkx"] > 0 else -1
    if abs(f["kos"]) > 0.5: return 1 if f["kos"] > 0 else -1
    return 0

def sig_V2(f):
    """任一過門檻, 方向用 3 因子加總"""
    if abs(f["nq"]) > 0.5 or abs(f["nkx"]) > 0.5 or abs(f["kos"]) > 0.5:
        agg = f["nq"] + f["nkx"] + f["kos"]
        return 1 if agg > 0 else (-1 if agg < 0 else 0)
    return 0

def sig_V3(f):
    """純 Nikkei"""
    if abs(f["nkx"]) > 0.5: return 1 if f["nkx"] > 0 else -1
    return 0

def sig_V4(f):
    """純 KOSPI"""
    if abs(f["kos"]) > 0.5: return 1 if f["kos"] > 0 else -1
    return 0

def sig_V5(f):
    """雙保險: NKX 且 KOSPI 都過 0.5 且方向一致"""
    if abs(f["nkx"]) > 0.5 and abs(f["kos"]) > 0.5:
        if np.sign(f["nkx"]) == np.sign(f["kos"]):
            return int(np.sign(f["nkx"]))
    return 0

def sig_V6(f):
    """vote: nq/nkx/kos/ndx 各自分 ±1, sum >= 2 才進"""
    v = 0
    v += 1 if f["nq"] > 0.1 else (-1 if f["nq"] < -0.1 else 0)
    v += 1 if f["nkx"] > 0.3 else (-1 if f["nkx"] < -0.3 else 0)
    v += 1 if f["kos"] > 0.3 else (-1 if f["kos"] < -0.3 else 0)
    v += 1 if f["ndx"] > 0.3 else (-1 if f["ndx"] < -0.3 else 0)
    if abs(v) >= 2: return 1 if v > 0 else -1
    return 0


def run(sig_fn, label):
    trades = []
    for d in intraday.index:
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
        return {"label": label, "n": 0}
    pnls = np.array([t[2] for t in trades])
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum).max()
    wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {
        "label": label,
        "n": len(pnls),
        "total": round(pnls.sum(), 0),
        "EV": round(pnls.mean(), 0),
        "win%": round((pnls > 0).mean() * 100, 1),
        "sharpe": round(pnls.mean() / pnls.std() * np.sqrt(252), 2) if pnls.std() > 0 else 0,
        "PF": round(pf, 2),
        "maxDD": round(dd, 0),
        "trades": trades,
    }


print()
print("=" * 100)
print("【0845 複合訊號回測】cutoff=13:44 exit=A(TP+100/+200 stop=-150)")
print("=" * 100)
print(f"{'label':<30s} {'n':>5s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>7s} {'PF':>6s} {'maxDD':>10s}")

RESULTS = {}
for fn, lbl in [
    (sig_V0, "V0  |NQ|>0.5  (現行)"),
    (sig_V1, "V1  NQ/NKX/KOS 任一>0.5"),
    (sig_V2, "V2  V1 + 方向用加總"),
    (sig_V3, "V3  |NKX|>0.5 only"),
    (sig_V4, "V4  |KOSPI|>0.5 only"),
    (sig_V5, "V5  NKX & KOSPI 雙過且同向"),
    (sig_V6, "V6  vote sum>=2 (4因子)"),
]:
    r = run(fn, lbl)
    RESULTS[lbl] = r
    if r["n"] == 0:
        print(f"{lbl:<30s} {'(無訊號)':>10s}")
        continue
    print(f"{lbl:<30s} {r['n']:>5d} {r['total']:>+10,.0f} {r['EV']:>+8,.0f} "
          f"{r['win%']:>5.1f}% {r['sharpe']:>+7.2f} {r['PF']:>6.2f} {r['maxDD']:>+10,.0f}")

# === V5 vs V0 比較 by year (因為 V5 是雙保險最有可能穩定 edge) ===
print()
print("=" * 100)
print("【by year — V0 vs V5 vs V6】")
print("=" * 100)
for lbl in ["V0  |NQ|>0.5  (現行)", "V5  NKX & KOSPI 雙過且同向", "V6  vote sum>=2 (4因子)"]:
    r = RESULTS[lbl]
    if r["n"] == 0: continue
    print(f"\n>>> {lbl}")
    print(f"  {'year':<6s} {'n':>4s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'PF':>6s}")
    by_yr = {}
    for d, s, pnl, f in r["trades"]:
        yr = d[:4]
        by_yr.setdefault(yr, []).append(pnl)
    for yr in sorted(by_yr.keys()):
        pnls = np.array(by_yr[yr])
        wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
        pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
        print(f"  {yr:<6s} {len(pnls):>4d} {pnls.sum():>+10,.0f} {pnls.mean():>+8,.0f} "
              f"{(pnls>0).mean()*100:>5.1f}% {pf:>6.2f}")

# === V5 + V0 聯合: 兩個都觸發才進 (最嚴格但可能 Sharpe 最高) ===
print()
print("=" * 100)
print("【極嚴格組合 — V0 AND V5 兩個訊號同向都過】")
print("=" * 100)
trades = []
for d in intraday.index:
    f = get_factors(d)
    if f is None: continue
    s_v0 = sig_V0(f); s_v5 = sig_V5(f)
    if s_v0 == 0 or s_v5 == 0 or s_v0 != s_v5: continue
    bars = build_bars(d)
    if bars is None: continue
    entry = get_open(d)
    if entry is None: continue
    pnl = sim_A(entry, bars, s_v0)
    trades.append((d, s_v0, pnl, f))
if trades:
    pnls = np.array([t[2] for t in trades])
    print(f"n={len(pnls)}  total={pnls.sum():+,.0f}  EV={pnls.mean():+,.0f}  "
          f"win%={(pnls>0).mean()*100:.1f}%  PF={(pnls[pnls>0].sum()/abs(pnls[pnls<0].sum())):.2f}")
    print(f"\n明細:")
    print(f"{'date':<12s} {'dir':>4s} {'NQ%':>7s} {'NKX%':>7s} {'KOS%':>7s} {'pnl':>10s}")
    for d, s, pnl, f in trades:
        print(f"{d:<12s} {s:>+4d} {f['nq']:>+7.2f} {f['nkx']:>+7.2f} {f['kos']:>+7.2f} {pnl:>+10,.0f}")
else:
    print("(無訊號)")

# === V0 漏掉但 V5 抓到的 (純獲利提升估計) ===
print()
print("=" * 100)
print("【V5 抓到 而 V0 漏掉 — 06/24 style 的新訊號】")
print("=" * 100)
trades = []
for d in intraday.index:
    f = get_factors(d)
    if f is None: continue
    s_v0 = sig_V0(f); s_v5 = sig_V5(f)
    if s_v5 == 0: continue
    if s_v0 == s_v5: continue  # V0 也有的就跳過
    bars = build_bars(d)
    if bars is None: continue
    entry = get_open(d)
    if entry is None: continue
    pnl = sim_A(entry, bars, s_v5)
    trades.append((d, s_v5, pnl, f))
if trades:
    pnls = np.array([t[2] for t in trades])
    print(f"n={len(pnls)}  total={pnls.sum():+,.0f}  EV={pnls.mean():+,.0f}  "
          f"win%={(pnls>0).mean()*100:.1f}%  "
          f"PF={(pnls[pnls>0].sum()/abs(pnls[pnls<0].sum())):.2f}")
    print(f"\n明細 (最近 20 筆):")
    print(f"{'date':<12s} {'dir':>4s} {'NQ%':>7s} {'NKX%':>7s} {'KOS%':>7s} {'pnl':>10s}")
    for d, s, pnl, f in trades[-20:]:
        print(f"{d:<12s} {s:>+4d} {f['nq']:>+7.2f} {f['nkx']:>+7.2f} {f['kos']:>+7.2f} {pnl:>+10,.0f}")
