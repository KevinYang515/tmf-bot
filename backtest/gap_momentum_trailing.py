"""
大跳空慣性策略 — trailing stop 版
==================================
User insight: 07/02 開盤 gap down -2% 後繼續走跌一大段, trailing stop 能吃到很多點。
之前 GAP_only 用固定 TP+100/+200 天花板太低, 吃不到 trend day 肥尾 → 改用 trailing。

進場: 08:45 開盤 (bar 08:46 Open) 順 gap 方向
出場: trailing stop T 點 (從進場後最有利價回檔 T 點) / 13:44 收盤強制平倉
gap 定義兩種:
  gap_day   = 開盤 vs 前日日盤收 (13:45 bar Close)   ← 今天 -2.03% 的那種
  gap_night = 開盤 vs 當日夜盤收 (05:00 bar Close)   ← 今天只 -0.17%
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
df["minute_int"] = df["ts"].dt.hour * 60 + df["ts"].dt.minute
df = df.sort_values("ts")

# 建每日資料
days = {}
for d, g in df.groupby("date"):
    days[d] = g

dates = sorted(days.keys())

# 每日: 開盤價(08:46 bar Open), 夜盤收(05:00 bar Close), 日盤收(13:45 bar Close)
recs = []
for i, d in enumerate(dates):
    g = days[d]
    ob = g[g["minute_int"] == 8 * 60 + 46]
    if ob.empty: continue
    open845 = float(ob.iloc[0]["Open"])
    nb = g[g["minute_int"] == 5 * 60 + 0]
    night_close = float(nb.iloc[0]["Close"]) if not nb.empty else np.nan
    prev_day_close = np.nan
    if i > 0:
        pg = days[dates[i - 1]]
        pb = pg[pg["minute_int"] == 13 * 60 + 45]
        if not pb.empty:
            prev_day_close = float(pb.iloc[0]["Close"])
    recs.append({"date": d, "open": open845,
                 "prev_close": prev_day_close, "night_close": night_close})

info = pd.DataFrame(recs).set_index("date")
info["gap_day_pct"] = (info["open"] - info["prev_close"]) / info["prev_close"] * 100
info["gap_night_pct"] = (info["open"] - info["night_close"]) / info["night_close"] * 100


def day_session_bars(d):
    g = days[d]
    m = g[(g["minute_int"] >= 8 * 60 + 46) & (g["minute_int"] <= CUTOFF_MIN)]
    if m.empty: return None
    return (m["High"].values.astype(float), m["Low"].values.astype(float),
            m["Close"].values.astype(float))


def sim_trailing(entry, bars, direction, trail, init_stop=None):
    """trailing stop: 從進場後最有利價回檔 trail 點出場。
    intrabar 近似: 先用該 bar 有利端更新 best, 再檢查不利端是否觸發
    (保守: 同一根先觸發 stop 再更新 best → 用上一根的 best 檢查本根 stop)"""
    hi, lo, cl = bars
    be = entry + direction * SLIPPAGE
    best = be
    stop_p = be - direction * (init_stop if init_stop else trail)
    for i in range(len(hi)):
        # 先用「上一根為止的 best」算 trail stop 檢查本根
        if direction == 1:
            if lo[i] <= stop_p:
                return (stop_p - be) * POINT_VAL - COMMISSION * POINT_VAL
            best = max(best, hi[i])
            stop_p = max(stop_p, best - trail)
        else:
            if hi[i] >= stop_p:
                return (be - stop_p) * POINT_VAL - COMMISSION * POINT_VAL
            best = min(best, lo[i])
            stop_p = min(stop_p, best + trail)
    return direction * (cl[-1] - be) * POINT_VAL - COMMISSION * POINT_VAL


def run(gap_col, gap_th, trail, init_stop=None, direction_filter=None):
    trades = []
    for d in info.index:
        gp = info.loc[d, gap_col]
        if not pd.notna(gp) or abs(gp) < gap_th: continue
        s = int(np.sign(gp))
        if direction_filter and s != direction_filter: continue
        bars = day_session_bars(d)
        if bars is None: continue
        entry = info.loc[d, "open"]
        pnl = sim_trailing(entry, bars, s, trail, init_stop)
        trades.append((d, s, gp, pnl))
    if not trades: return None
    pnls = np.array([t[3] for t in trades])
    cum = np.cumsum(pnls); peak = np.maximum.accumulate(cum)
    dd = (peak - cum).max()
    wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {"n": len(pnls), "total": pnls.sum(), "EV": pnls.mean(),
            "win%": (pnls > 0).mean() * 100,
            "sharpe": pnls.mean() / pnls.std() * np.sqrt(252) if pnls.std() > 0 else 0,
            "PF": pf, "maxDD": dd, "trades": trades}


print(f"資料範圍: {dates[0]} ~ {dates[-1]}  共 {len(info)} 個交易日")
print(f"|gap_day|>1% 天數: {(info['gap_day_pct'].abs() > 1).sum()}, "
      f">1.5%: {(info['gap_day_pct'].abs() > 1.5).sum()}, "
      f">2%: {(info['gap_day_pct'].abs() > 2).sum()}")
print()

for gap_col, tag in [("gap_day_pct", "gap vs 前日日盤收"), ("gap_night_pct", "gap vs 夜盤收")]:
    print("=" * 100)
    print(f"【{tag}】 順 gap 方向進場 @ 08:45 open, trailing stop")
    print("=" * 100)
    print(f"{'gap_th':>7s} {'trail':>6s} {'n':>5s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>7s} {'PF':>6s} {'maxDD':>10s}")
    for gap_th in [0.5, 1.0, 1.5, 2.0]:
        for trail in [60, 100, 150, 200, 300]:
            r = run(gap_col, gap_th, trail)
            if r is None: continue
            print(f"{gap_th:>6.1f}% {trail:>6d} {r['n']:>5d} {r['total']:>+10,.0f} {r['EV']:>+8,.0f} "
                  f"{r['win%']:>5.1f}% {r['sharpe']:>+7.2f} {r['PF']:>6.2f} {r['maxDD']:>10,.0f}")
        print()

# 方向拆開看 (gap up vs gap down)
print("=" * 100)
print("【gap_day 方向拆開】 trail=150")
print("=" * 100)
print(f"{'gap_th':>7s} {'dir':>5s} {'n':>5s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'PF':>6s}")
for gap_th in [1.0, 1.5, 2.0]:
    for df_, dl in [(1, "UP"), (-1, "DOWN")]:
        r = run("gap_day_pct", gap_th, 150, direction_filter=df_)
        if r is None: continue
        print(f"{gap_th:>6.1f}% {dl:>5s} {r['n']:>5d} {r['total']:>+10,.0f} {r['EV']:>+8,.0f} "
              f"{r['win%']:>5.1f}% {r['PF']:>6.2f}")
