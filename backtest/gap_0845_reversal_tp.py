"""
0845 深挖：延續 vs 反轉 分組，各自找最佳 TP/停損，walk-forward 驗證
(user 提問：1500 是「多空不同 TP」有效，0845 是不是「延續/反轉不同 TP」也有效？)

兩種「反轉」定義都測，因為可能捕捉到不同/重疊的資訊：
  L1 = gap_day(舊聞,vs前日收) 方向 vs gap_night(意外,vs夜盤收) 方向 是否一致
  L2 = 前一天 1500 場的 gap 方向 vs 今天 0845 方向 是否一致
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
POINT_VAL, COMMISSION, SLIPPAGE = 10, 5.6, 5


def load(tick_dir, prefix, info_file, after_time=None):
    info = pd.read_csv(BASE / tick_dir / info_file).set_index("date")
    data = {}
    for d in info.index:
        fp = BASE / tick_dir / f"{prefix}{d}.csv"
        if not fp.exists(): continue
        t = pd.read_csv(fp)
        t["ts"] = pd.to_datetime(t["ts"])
        if after_time:
            t = t[t["ts"].dt.strftime("%H:%M:%S") >= after_time]
        t = t.sort_values("ts")
        if len(t) < 50: continue
        data[d] = (t["close"].values.astype(np.float64),
                   (t["ts"] - t["ts"].iloc[0]).dt.total_seconds().values)
    return info, data


def sim(px, sec, s, tp, stop, tmax_s):
    p = px[sec <= tmax_s]
    if len(p) < 2: return None
    be = p[0] + s * SLIPPAGE
    fav = s * (p - be)
    i_tp = (fav >= tp).argmax() if (fav >= tp).any() else len(p)
    i_st = (fav <= -stop).argmax() if (fav <= -stop).any() else len(p)
    if i_tp < i_st: return tp - COMMISSION
    if i_st < len(p): return -stop - COMMISSION
    return fav[-1] - COMMISSION


def agg(pnls):
    p = np.array([x for x in pnls if x is not None]) * POINT_VAL
    if len(p) == 0: return None
    wins = p[p > 0]; losses = p[p < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {"n": len(p), "total": p.sum(), "EV": p.mean(),
            "win%": (p > 0).mean() * 100, "PF": pf, "worst": p.min()}


def fmt(r, label, w=34):
    if r is None: return f"  {label:<{w}s}  (n=0)"
    return (f"  {label:<{w}s} n={r['n']:>3d} total={r['total']:>+9,.0f} EV={r['EV']:>+7,.0f} "
            f"win={r['win%']:>5.1f}% PF={r['PF']:>5.2f} worst={r['worst']:>+8,.0f}")


info8, data8 = load("gap_ticks", "MXF_", "gap_days_selected_2026.csv", "08:45:00")
all15 = pd.read_csv(BASE / "gap_ticks_1500" / "gap_1500_days_all.csv").set_index("date")

dl8 = []
for d in data8:
    g = info8.loc[d, "gap_night_pct"]
    if pd.notna(g) and abs(g) >= 0.5:
        dl8.append((d, int(np.sign(g))))

h1 = lambda dl: [(d, s) for d, s in dl if d <= "2026-03-31"]
h2 = lambda dl: [(d, s) for d, s in dl if d > "2026-03-31"]

STOP, CAP = 30, 300
TP_GRID = [30, 50, 80, 100, 150, 200, 250]


def best_tp_report(label, dl):
    """對這個子集掃 TP，回傳(全樣本最佳, 該TP在H1, 該TP在H2)，並印出全部TP的表(不是只印最佳)方便看穩不穩"""
    print(f"\n  --- {label} (n={len(dl)}) TP 全掃描 ---")
    rows = []
    for tp in TP_GRID:
        r = agg([sim(*data8[d], s, tp, STOP, CAP) for d, s in dl])
        if r is None: continue
        r1 = agg([sim(*data8[d], s, tp, STOP, CAP) for d, s in h1(dl)])
        r2 = agg([sim(*data8[d], s, tp, STOP, CAP) for d, s in h2(dl)])
        rows.append((tp, r, r1, r2))
        h1s = f"EV{r1['EV']:+.0f}(n{r1['n']},win{r1['win%']:.0f}%)" if r1 else "n/a"
        h2s = f"EV{r2['EV']:+.0f}(n{r2['n']},win{r2['win%']:.0f}%)" if r2 else "n/a"
        print(f"    TP{tp:<4d} 全樣本EV={r['EV']:>+6.0f} win={r['win%']:>5.1f}%  | H1: {h1s}  | H2: {h2s}")
    return rows


# ============================================================
# 基準：現行固定 TP80，不分組
# ============================================================
print("#" * 100)
print("# 基準：現行 0845 固定 TP80/S30/cap300s，不分組")
print("#" * 100)
r0 = agg([sim(*data8[d], s, 80, STOP, CAP) for d, s in dl8])
r0_1 = agg([sim(*data8[d], s, 80, STOP, CAP) for d, s in h1(dl8)])
r0_2 = agg([sim(*data8[d], s, 80, STOP, CAP) for d, s in h2(dl8)])
print(fmt(r0, "全樣本")); print(fmt(r0_1, "H1")); print(fmt(r0_2, "H2"))


# ============================================================
# L1: gap_day(舊聞) vs gap_night(意外) 方向一致性分組
# ============================================================
print("\n" + "#" * 100)
print("# L1 分組：意外方向 vs 舊聞(前日收)方向 — 一致(延續) vs 不一致(反轉)")
print("#" * 100)

confirm, contrarian = [], []
for d, s in dl8:
    old_g = info8.loc[d, "gap_day_pct"]
    if pd.isna(old_g) or old_g == 0: continue
    old_dir = int(np.sign(old_g))
    (confirm if old_dir == s else contrarian).append((d, s))

best_tp_report("延續 (confirm)", confirm)
best_tp_report("反轉 (contrarian)", contrarian)


# ============================================================
# L2: 前一天 1500 方向 vs 今天 0845 方向
# ============================================================
print("\n" + "#" * 100)
print("# L2 分組：今天 0845 方向 vs 昨天 1500 方向 — 同向(延續) vs 反向(反轉)")
print("#" * 100)

all15_idx = list(all15.index)
same_dir_dl, opp_dir_dl = [], []
for d, s in dl8:
    d_ts = pd.Timestamp(d)
    prior_days = [x for x in all15_idx if pd.Timestamp(x) < d_ts]
    if not prior_days: continue
    prev_day = prior_days[-1]
    prev_gap = all15.loc[prev_day, "gap_1500_pct"]
    if pd.isna(prev_gap) or abs(prev_gap) < 0.05: continue
    prev_dir = int(np.sign(prev_gap))
    (same_dir_dl if prev_dir == s else opp_dir_dl).append((d, s))

best_tp_report("同向(延續, vs 昨1500)", same_dir_dl)
best_tp_report("反向(反轉, vs 昨1500)", opp_dir_dl)


# ============================================================
# 兩個反轉定義是否指向同一批日子？(交叉表)
# ============================================================
print("\n" + "#" * 100)
print("# 交叉檢查：L1的反轉日 與 L2的反轉日 重疊程度 (若高度重疊=同一個現象，不是兩個獨立訊號)")
print("#" * 100)
l1_contrarian_dates = {d for d, s in contrarian}
l2_opp_dates = {d for d, s in opp_dir_dl}
overlap = l1_contrarian_dates & l2_opp_dates
print(f"L1反轉(舊聞vs意外不一致) 日期集合 n={len(l1_contrarian_dates)}: {sorted(l1_contrarian_dates)}")
print(f"L2反轉(vs昨1500不一致)   日期集合 n={len(l2_opp_dates)}: {sorted(l2_opp_dates)}")
print(f"兩者交集 n={len(overlap)}: {sorted(overlap)}")


# ============================================================
# 綜合：只在「兩種定義都判定為反轉」的日子交易，看訊號疊加是否更強
# ============================================================
print("\n" + "#" * 100)
print("# 綜合：L1與L2都判定為反轉的日子 (雙重確認) — 找最佳TP")
print("#" * 100)
double_confirm_dl = [(d, s) for d, s in dl8 if d in overlap]
best_tp_report("雙重反轉確認", double_confirm_dl)
