"""
User idea: 確定會跳空 → 開盤市價順向進 → 固定 TP (如100點) → 不停損(或災難停損)
勝率會很高, 但要看「沒掃到 TP 的日子」虧多少 — 高勝率負偏態結構的誠實檢驗
持有到 13:44 強制平倉 (或災難停損)
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
POINT_VAL = 10
COMMISSION = 5.6
SLIPPAGE = 5
CUTOFF_MIN = 13 * 60 + 44

df = pd.read_csv(BASE / "mxf_1min.csv")
df["ts"] = pd.to_datetime(df["ts"])
df["date"] = df["ts"].dt.date.astype(str)
df["mi"] = df["ts"].dt.hour * 60 + df["ts"].dt.minute
df = df.sort_values("ts")
days = {d: g for d, g in df.groupby("date")}
dates = sorted(days.keys())

recs = []
for i, d in enumerate(dates):
    g = days[d]
    ob = g[g["mi"] == 8 * 60 + 46]
    if ob.empty: continue
    open845 = float(ob.iloc[0]["Open"])
    nb = g[g["mi"] == 5 * 60 + 0]
    night_close = float(nb.iloc[0]["Close"]) if not nb.empty else np.nan
    prev_close = np.nan
    if i > 0:
        pb = days[dates[i - 1]]
        pb = pb[pb["mi"] == 13 * 60 + 45]
        if not pb.empty: prev_close = float(pb.iloc[0]["Close"])
    recs.append({"date": d, "open": open845, "prev_close": prev_close, "night_close": night_close})

info = pd.DataFrame(recs).set_index("date")
info["gap_day_pct"] = (info["open"] - info["prev_close"]) / info["prev_close"] * 100
info["gap_night_pct"] = (info["open"] - info["night_close"]) / info["night_close"] * 100


def session_bars(d):
    g = days[d]
    m = g[(g["mi"] >= 8 * 60 + 46) & (g["mi"] <= CUTOFF_MIN)].sort_values("ts")
    if m.empty: return None
    return (m["High"].values.astype(float), m["Low"].values.astype(float),
            m["Close"].values.astype(float))


def sim_tponly(entry, bars, s, tp, dstop=None):
    """TP-only: 掃到 tp 出場, 否則收盤平倉。dstop = 災難停損 (None = 無)"""
    hi, lo, cl = bars
    be = entry + s * SLIPPAGE
    tp_p = be + s * tp
    stop_p = be - s * dstop if dstop else None
    for i in range(len(hi)):
        hit_stop = stop_p is not None and ((lo[i] <= stop_p) if s == 1 else (hi[i] >= stop_p))
        hit_tp = (hi[i] >= tp_p) if s == 1 else (lo[i] <= tp_p)
        if hit_stop and hit_tp:   # 同根都碰: 保守算停損
            return -dstop - COMMISSION, i
        if hit_stop:
            return -dstop - COMMISSION, i
        if hit_tp:
            return tp - COMMISSION, i
    return s * (cl[-1] - be) - COMMISSION, len(hi) - 1


def run(gap_col, gth, tp, dstop=None, year_from=None):
    out = []
    for d, r in info[(info[gap_col].abs() >= gth) & info[gap_col].notna()].iterrows():
        if year_from and d < year_from: continue
        bars = session_bars(d)
        if bars is None: continue
        s = int(np.sign(r[gap_col]))
        pnl_pt, exit_i = sim_tponly(r["open"], bars, s, tp, dstop)
        out.append((d, s, pnl_pt, exit_i))
    if not out: return None
    p = np.array([t[2] for t in out]) * POINT_VAL
    wins = p[p > 0]; losses = p[p < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    exit_min = np.array([t[3] for t in out])
    tp_hits = p >= (tp - COMMISSION) * POINT_VAL - 1
    return {"n": len(p), "total": p.sum(), "EV": p.mean(), "win%": (p > 0).mean() * 100,
            "PF": pf, "worst": p.min(), "avg_loss": losses.mean() if len(losses) else 0,
            "med_exit_min": int(np.median(exit_min[tp_hits])) if tp_hits.any() else -1,
            "trades": out}


print("=" * 108)
print("【TP-only 不停損】 順 gap 開盤進場, TP 掃到出場, 否則 13:44 平倉  (全期間 2024-01~2026-06)")
print("=" * 108)
print(f"{'篩選':<26s} {'TP':>4s} {'n':>4s} {'total':>9s} {'EV':>7s} {'win%':>6s} {'PF':>6s} {'worst':>8s} {'avgLoss':>8s} {'TP中位耗時':>8s}")
for gap_col, gth_list, tag in [("gap_day_pct", [1.0, 1.5, 2.0], "gap_day"),
                                ("gap_night_pct", [0.3, 0.5], "gap_night")]:
    for gth in gth_list:
        for tp in [50, 100, 150]:
            r = run(gap_col, gth, tp)
            if r is None: continue
            print(f"{tag}>={gth:<4.1f}%{'':<12s} {tp:>4d} {r['n']:>4d} {r['total']:>+9,.0f} {r['EV']:>+7,.0f} "
                  f"{r['win%']:>5.1f}% {r['PF']:>6.2f} {r['worst']:>+8,.0f} {r['avg_loss']:>+8,.0f} {r['med_exit_min']:>6d}min")
        print()

print("=" * 108)
print("【TP-only + 災難停損 300】")
print("=" * 108)
print(f"{'篩選':<26s} {'TP':>4s} {'n':>4s} {'total':>9s} {'EV':>7s} {'win%':>6s} {'PF':>6s} {'worst':>8s}")
for gap_col, gth_list, tag in [("gap_day_pct", [1.0, 2.0], "gap_day"),
                                ("gap_night_pct", [0.5], "gap_night")]:
    for gth in gth_list:
        for tp in [50, 100]:
            r = run(gap_col, gth, tp, dstop=300)
            if r is None: continue
            print(f"{tag}>={gth:<4.1f}%{'':<12s} {tp:>4d} {r['n']:>4d} {r['total']:>+9,.0f} {r['EV']:>+7,.0f} "
                  f"{r['win%']:>5.1f}% {r['PF']:>6.2f} {r['worst']:>+8,.0f}")

print()
print("=" * 108)
print("【只看 2026 (指數放大後)】 TP-only 不停損")
print("=" * 108)
print(f"{'篩選':<26s} {'TP':>4s} {'n':>4s} {'total':>9s} {'EV':>7s} {'win%':>6s} {'PF':>6s} {'worst':>8s}")
for gap_col, gth_list, tag in [("gap_day_pct", [1.0, 1.5, 2.0], "gap_day"),
                                ("gap_night_pct", [0.3, 0.5], "gap_night")]:
    for gth in gth_list:
        for tp in [50, 100, 150]:
            r = run(gap_col, gth, tp, year_from="2026-01-01")
            if r is None: continue
            print(f"{tag}>={gth:<4.1f}%{'':<12s} {tp:>4d} {r['n']:>4d} {r['total']:>+9,.0f} {r['EV']:>+7,.0f} "
                  f"{r['win%']:>5.1f}% {r['PF']:>6.2f} {r['worst']:>+8,.0f}")
        print()

# 2026 gap_day>=1.5% TP100 的逐筆
print("2026 gap_day>=1.5% TP=100 逐筆:")
r = run("gap_day_pct", 1.5, 100, year_from="2026-01-01")
if r:
    for d, s, pnl_pt, ei in r["trades"]:
        print(f"  {d}  dir={s:+d}  {pnl_pt*POINT_VAL:>+8,.0f} NT$  (exit @ 開盤後 {ei} min)")
