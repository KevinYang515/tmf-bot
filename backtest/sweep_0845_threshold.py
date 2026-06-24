"""
0845 session — threshold sweep
==============================
固定: cutoff=13:44, exit=A 兩口 (TP+100/+200, stop=-150)
變數: NQ% threshold = 0.20 / 0.25 / 0.30 / 0.35 / 0.40 / 0.50 / 0.60
目的: 06/24 那種 NQ +0.38% (低於 0.5% 被 SKIP) 究竟是 +EV 還是雜訊?
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
daily = pd.read_csv(BASE / "daily_open.csv")
daily_dict = {row["date"]: row for _, row in daily.iterrows()}

print("預分組 ...", end=" ", flush=True)
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
print(f"{len(by_date)} 日", flush=True)


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


def get_signal_pct(d):
    if d not in intraday.index: return None
    raw = intraday.loc[d, "nq_0845"]
    if pd.isna(raw): return None
    return float(raw) / 18000 * 100


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


def run(threshold):
    """跑單一 threshold，回傳 trades list of (date, nq_pct, pnl)"""
    trades = []
    for d in intraday.index:
        pct = get_signal_pct(d)
        if pct is None: continue
        if abs(pct) < threshold: continue
        bars = build_bars(d)
        if bars is None: continue
        entry = get_open(d)
        if entry is None: continue
        direction = 1 if pct > 0 else -1
        pnl = sim_A(entry, bars, direction)
        trades.append((d, pct, pnl))
    return trades


def summarize(trades, label):
    if not trades:
        return {"th": label, "n": 0, "total": 0, "EV": 0, "win%": 0,
                "sharpe": 0, "maxDD": 0, "PF": 0}
    pnls = np.array([t[2] for t in trades])
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum).max()
    wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {
        "th": label,
        "n": len(pnls),
        "total": round(pnls.sum(), 0),
        "EV": round(pnls.mean(), 0),
        "win%": round((pnls > 0).mean() * 100, 1),
        "sharpe": round(pnls.mean() / pnls.std() * np.sqrt(252), 2) if pnls.std() > 0 else 0,
        "maxDD": round(dd, 0),
        "PF": round(pf, 2),
    }


THRESHOLDS = [0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60]
RESULTS = []

print()
print("=" * 90)
print("【0845 session - threshold sweep】 cutoff=13:44 exit=A(TP+100/+200 stop=-150)")
print("=" * 90)
print(f"{'threshold':<10s} {'n':>4s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>7s} {'PF':>6s} {'maxDD':>10s}")

all_trades = {}
for th in THRESHOLDS:
    tr = run(th)
    all_trades[th] = tr
    s = summarize(tr, f"{th:.2f}%")
    RESULTS.append(s)
    print(f"{s['th']:<10s} {s['n']:>4d} {s['total']:>+10,.0f} {s['EV']:>+8,.0f} "
          f"{s['win%']:>5.1f}% {s['sharpe']:>+7.2f} {s['PF']:>6.2f} {s['maxDD']:>+10,.0f}")

# 比較 marginal layer: 例如 0.35%~0.50% 之間的 trades 單獨表現
print()
print("=" * 90)
print("【邊際區間獨立看 — 不同門檻會新增的訊號表現】")
print("=" * 90)
print(f"{'區間':<15s} {'n':>4s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'PF':>6s}")
bands = [(0.20, 0.25), (0.25, 0.30), (0.30, 0.35), (0.35, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 99.0)]
for lo, hi in bands:
    tr = [t for t in all_trades[0.20] if lo <= abs(t[1]) < hi]
    s = summarize(tr, f"{lo:.2f}~{hi:.2f}%")
    print(f"{s['th']:<15s} {s['n']:>4d} {s['total']:>+10,.0f} {s['EV']:>+8,.0f} "
          f"{s['win%']:>5.1f}% {s['PF']:>6.2f}")

# 各門檻 by year 看 edge stability
print()
print("=" * 90)
print("【門檻 0.30 vs 0.40 vs 0.50 — by year】")
print("=" * 90)
for th in [0.30, 0.40, 0.50]:
    tr = all_trades[th]
    print(f"\n>>> threshold = {th:.2f}%")
    print(f"  {'year':<6s} {'n':>4s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'PF':>6s}")
    for yr in sorted({t[0][:4] for t in tr}):
        sub = [t for t in tr if t[0].startswith(yr)]
        s = summarize(sub, yr)
        print(f"  {s['th']:<6s} {s['n']:>4d} {s['total']:>+10,.0f} {s['EV']:>+8,.0f} "
              f"{s['win%']:>5.1f}% {s['PF']:>6.2f}")

# 存檔
out_df = pd.DataFrame(RESULTS)
out_df.to_csv(BASE / "sweep_0845_threshold.csv", index=False, encoding="utf-8-sig")
print(f"\n結果存檔 → {BASE / 'sweep_0845_threshold.csv'}")

# 06/24 那種 0.38% 的訊號歷史上長相
print()
print("=" * 90)
print("【NQ% 在 0.35~0.45 區間的所有歷史交易明細】")
print("=" * 90)
band = [t for t in all_trades[0.20] if 0.35 <= abs(t[1]) < 0.45]
print(f"共 {len(band)} 筆")
print(f"{'date':<12s} {'NQ%':>8s} {'pnl':>10s}")
for d, p, pnl in band:
    print(f"{d:<12s} {p:>+8.3f} {pnl:>+10,.0f}")
