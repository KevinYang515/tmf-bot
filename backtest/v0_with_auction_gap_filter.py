"""
試撮 gap 當 filter / 訊號 — 對照現行 V4 (KOSPI filter)
======================================================
User insight: 08:44:30 的最後試撮價已經告訴你會不會跳空、往哪跳。
不用看日韓/NQ 拼因子 — 市場自己聚合好了。

Proxy: 實際 08:46 開盤 gap ≈ 最後試撮 gap (決策 08:44 時試撮可見, 無 lookahead)
       注意 proxy 是「完美資訊」— 實際試撮 vs 真開盤會有一點差, 真實表現略遜於此

對照組:
  V0            純 NQ>0.5% (baseline)
  V0_kc_strict  現行 live V4 (KOSPI 同向 |kos|>0.3%)
  V0_gap        V0 + 試撮 gap 同向 (任何幅度)
  V0_gap_XX     V0 + 試撮 gap 同向 + |gap|>XX%
  GAP_only_XX   純試撮 gap >XX% 當訊號 (不看 NQ) — 測試「跳空後會不會續走」
  V0_gap_or_kc  V0 + (gap 同向 OR KOSPI 同向)
  NQ03_gap      NQ>0.3% + gap 同向 >0.2% (放寬 NQ 門檻版)
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

sig = pd.read_csv(BASE / "gap_research_v2.csv").set_index("date")  # 含 gap_pct
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
            "gap": row.get("gap_pct", np.nan)}


def base_nq_sig(f, th=0.5):
    if not pd.notna(f["nq"]): return 0
    return int(np.sign(f["nq"])) if abs(f["nq"]) > th else 0


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
    if not trades: return {"label": label, "n": 0, "trades": []}
    pnls = np.array([t[2] for t in trades])
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum).max()
    wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {
        "label": label, "n": len(pnls),
        "total": pnls.sum(), "EV": pnls.mean(),
        "win%": (pnls > 0).mean() * 100,
        "sharpe": pnls.mean() / pnls.std() * np.sqrt(252) if pnls.std() > 0 else 0,
        "PF": pf, "maxDD": dd, "trades": trades,
    }


# === 策略定義 ===
def s_v0(f):
    return base_nq_sig(f)

def s_v0_kc_strict(f):
    s = base_nq_sig(f)
    if s == 0: return 0
    if not pd.notna(f["kos"]): return 0
    if np.sign(f["kos"]) == s and abs(f["kos"]) > 0.3: return s
    return 0

def make_v0_gap(th):
    def fn(f):
        s = base_nq_sig(f)
        if s == 0: return 0
        if not pd.notna(f["gap"]): return 0
        if np.sign(f["gap"]) == s and abs(f["gap"]) >= th: return s
        return 0
    return fn

def make_gap_only(th):
    def fn(f):
        if not pd.notna(f["gap"]): return 0
        if abs(f["gap"]) >= th: return int(np.sign(f["gap"]))
        return 0
    return fn

def make_gap_fade(th):
    """跳空反向 (fade the gap) 對照"""
    def fn(f):
        if not pd.notna(f["gap"]): return 0
        if abs(f["gap"]) >= th: return -int(np.sign(f["gap"]))
        return 0
    return fn

def s_v0_gap_or_kc(f):
    s = base_nq_sig(f)
    if s == 0: return 0
    ok_gap = pd.notna(f["gap"]) and np.sign(f["gap"]) == s and abs(f["gap"]) >= 0.2
    ok_kos = pd.notna(f["kos"]) and np.sign(f["kos"]) == s and abs(f["kos"]) > 0.3
    return s if (ok_gap or ok_kos) else 0

def s_v0_gap_and_kc(f):
    s = base_nq_sig(f)
    if s == 0: return 0
    ok_gap = pd.notna(f["gap"]) and np.sign(f["gap"]) == s and abs(f["gap"]) >= 0.2
    ok_kos = pd.notna(f["kos"]) and np.sign(f["kos"]) == s and abs(f["kos"]) > 0.3
    return s if (ok_gap and ok_kos) else 0

def make_nq03_gap(th):
    def fn(f):
        s = base_nq_sig(f, th=0.3)
        if s == 0: return 0
        if not pd.notna(f["gap"]): return 0
        if np.sign(f["gap"]) == s and abs(f["gap"]) >= th: return s
        return 0
    return fn


strategies = [
    (s_v0,               "V0            NQ>0.5% (baseline)"),
    (s_v0_kc_strict,     "V0_kc_strict  現行 live V4 (KOSPI filter)"),
    (make_v0_gap(0.0),   "V0_gap_00     V0 + 試撮同向 (任意幅度)"),
    (make_v0_gap(0.1),   "V0_gap_01     V0 + 試撮同向 |gap|>0.1%"),
    (make_v0_gap(0.2),   "V0_gap_02     V0 + 試撮同向 |gap|>0.2%"),
    (make_v0_gap(0.3),   "V0_gap_03     V0 + 試撮同向 |gap|>0.3%"),
    (make_v0_gap(0.5),   "V0_gap_05     V0 + 試撮同向 |gap|>0.5%"),
    (s_v0_gap_or_kc,     "V0_gap_or_kc  V0 + (試撮>0.2% OR KOSPI>0.3%)"),
    (s_v0_gap_and_kc,    "V0_gap_and_kc V0 + (試撮>0.2% AND KOSPI>0.3%)"),
    (make_nq03_gap(0.2), "NQ03_gap_02   NQ>0.3% + 試撮同向 >0.2%"),
    (make_nq03_gap(0.3), "NQ03_gap_03   NQ>0.3% + 試撮同向 >0.3%"),
    (make_gap_only(0.3), "GAP_only_03   純試撮 >0.3% 順向 (不看NQ)"),
    (make_gap_only(0.5), "GAP_only_05   純試撮 >0.5% 順向"),
    (make_gap_only(1.0), "GAP_only_10   純試撮 >1.0% 順向"),
    (make_gap_fade(0.5), "GAP_fade_05   純試撮 >0.5% 反向 (fade)"),
    (make_gap_fade(1.0), "GAP_fade_10   純試撮 >1.0% 反向 (fade)"),
]

print("=" * 112)
print("【試撮 gap filter vs 現行 V4】 proxy: 實際 08:46 開盤 gap | cutoff=13:44 exit=A TP+100/+200 stop=-150")
print("=" * 112)
print(f"{'label':<48s} {'n':>5s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>7s} {'PF':>6s} {'maxDD':>10s}")

results = {}
for fn, lbl in strategies:
    r = run(fn, lbl)
    results[lbl] = r
    if r["n"] == 0:
        print(f"{lbl:<48s} {0:>5d}")
        continue
    print(f"{lbl:<48s} {r['n']:>5d} {r['total']:>+10,.0f} {r['EV']:>+8,.0f} "
          f"{r['win%']:>5.1f}% {r['sharpe']:>+7.2f} {r['PF']:>6.2f} {r['maxDD']:>10,.0f}")

# === by half-year for top candidates ===
def halfyear_report(label):
    r = results.get(label)
    if not r or r["n"] == 0: return
    print(f"\n>>> {label}  by half-year:")
    by_h = {}
    for d, s, pnl, f in r["trades"]:
        h = f"{d[:4]}H{1 if int(d[5:7]) <= 6 else 2}"
        by_h.setdefault(h, []).append(pnl)
    print(f"  {'period':<8s} {'n':>4s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'PF':>6s}")
    for h in sorted(by_h.keys()):
        pnls = np.array(by_h[h])
        wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
        pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
        print(f"  {h:<8s} {len(pnls):>4d} {pnls.sum():>+10,.0f} {pnls.mean():>+8,.0f} "
              f"{(pnls>0).mean()*100:>5.1f}% {pf:>6.2f}")

print()
print("=" * 112)
for lbl in results:
    r = results[lbl]
    if r["n"] >= 15 and r.get("PF", 0) and r["PF"] > 1.8:
        halfyear_report(lbl)
