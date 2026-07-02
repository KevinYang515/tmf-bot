"""
TP-only 詳細拆帳 — 為什麼高勝率還是 EV 負
每個 config: 贏家/輸家分布、最慘 5 筆、EV 恆等式、損益平衡點、by year
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


def sim(entry, bars, s, tp):
    hi, lo, cl = bars
    be = entry + s * SLIPPAGE
    tp_p = be + s * tp
    for i in range(len(hi)):
        hit = (hi[i] >= tp_p) if s == 1 else (lo[i] <= tp_p)
        if hit:
            return tp - COMMISSION, i, True
    return s * (cl[-1] - be) - COMMISSION, len(hi) - 1, False


def detail(gap_col, gth, tp):
    trades = []
    for d, r in info[(info[gap_col].abs() >= gth) & info[gap_col].notna()].iterrows():
        bars = session_bars(d)
        if bars is None: continue
        s = int(np.sign(r[gap_col]))
        pnl_pt, ei, hit = sim(r["open"], bars, s, tp)
        trades.append({"date": d, "dir": s, "gap": r[gap_col],
                       "pnl": pnl_pt * POINT_VAL, "hit_tp": hit, "exit_min": ei})
    t = pd.DataFrame(trades)
    wins = t[t["pnl"] > 0]; losses = t[t["pnl"] <= 0]
    win_amt = (tp - COMMISSION) * POINT_VAL

    print("=" * 100)
    print(f"◆ {gap_col} >= {gth}%  TP={tp}  (共 {len(t)} 筆, {t['date'].min()} ~ {t['date'].max()})")
    print("=" * 100)
    wr = len(wins) / len(t)
    print(f"  勝率: {wr*100:.1f}%  ({len(wins)} 勝 / {len(losses)} 敗)")
    print(f"  每筆贏固定:  +{win_amt:,.0f} NT$ (TP {tp}pt - 手續費稅 {COMMISSION}pt, 滑價已含)")
    print(f"  贏家合計:    {wins['pnl'].sum():+,.0f}")
    print(f"  輸家平均:    {losses['pnl'].mean():+,.0f}   中位數: {losses['pnl'].median():+,.0f}")
    print(f"  輸家合計:    {losses['pnl'].sum():+,.0f}")
    print(f"  ─────────────────────────")
    print(f"  總計:        {t['pnl'].sum():+,.0f}   EV: {t['pnl'].mean():+,.0f}/筆")
    print()
    print(f"  EV 恆等式:  {wr*100:.1f}% × (+{win_amt:,.0f}) + {(1-wr)*100:.1f}% × ({losses['pnl'].mean():,.0f})")
    print(f"           =  {wr*win_amt:+,.0f} + {(1-wr)*losses['pnl'].mean():+,.0f}  =  {wr*win_amt+(1-wr)*losses['pnl'].mean():+,.0f}")
    be_loss = wr * win_amt / (1 - wr) if wr < 1 else float("inf")
    print(f"  → 要打平, 輸家平均只能虧 {be_loss:,.0f} NT$ ({be_loss/POINT_VAL:.0f}pt), 實際虧 {abs(losses['pnl'].mean()):,.0f} ({abs(losses['pnl'].mean())/POINT_VAL:.0f}pt)")
    print()
    print(f"  輸家分布 (NT$): min={losses['pnl'].min():+,.0f}  p25={losses['pnl'].quantile(.25):+,.0f}  "
          f"p50={losses['pnl'].median():+,.0f}  p75={losses['pnl'].quantile(.75):+,.0f}  max={losses['pnl'].max():+,.0f}")
    print()
    print("  最慘 8 筆:")
    worst = t.nsmallest(8, "pnl")
    for _, w in worst.iterrows():
        print(f"    {w['date']}  dir={w['dir']:+d}  gap={w['gap']:+.2f}%  {w['pnl']:>+9,.0f} NT$  "
              f"({'TP' if w['hit_tp'] else '凹到收盤'})")
    print()
    t["year"] = t["date"].str[:4]
    print("  by year:")
    for y, g in t.groupby("year"):
        wr_y = (g["pnl"] > 0).mean()
        print(f"    {y}: n={len(g):>3d}  WR={wr_y*100:>5.1f}%  total={g['pnl'].sum():>+10,.0f}  EV={g['pnl'].mean():>+7,.0f}")
    print()
    # TP 有掃到但後來還走更遠的量 (機會成本) 不算, 專注輸家
    # 輸家當天實際上最多曾經浮虧多少 (若有停損能救嗎?)
    return t


for gap_col, gth, tp in [
    ("gap_day_pct", 1.0, 50),
    ("gap_day_pct", 1.0, 100),
    ("gap_day_pct", 2.0, 100),
    ("gap_night_pct", 0.5, 50),
]:
    detail(gap_col, gth, tp)
