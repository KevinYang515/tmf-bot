"""
2026-07-09: user 問「0.5% 門檻要不要放寬成 0.49%/0.48%」——用 0.01% 級距細掃，
搭配 walk-forward (H1<=03/31 / H2>03/31) 檢查邊際新增的交易到底是不是好交易，
還是稀釋整體 EV。同時做「距門檻遠近」分桶分析，直接回答「放寬會不會拉近爛單」。

沿用 gap_overnight_research.py 的 load/sim/agg 邏輯與資料（無新增資料需求）。
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


def dl_for(data, gpct, gth):
    return [(d, int(np.sign(gpct[d]))) for d in data if pd.notna(gpct[d]) and abs(gpct[d]) >= gth]


info8, data8 = load("gap_ticks", "MXF_", "gap_days_selected_2026.csv", "08:45:00")
info15, data15 = load("gap_ticks_1500", "N1500_", "gap_1500_days_selected.csv")
gpct8 = {d: info8.loc[d, "gap_night_pct"] for d in data8}
gpct15 = {d: info15.loc[d, "gap_1500_pct"] for d in data15}


def fine_sweep(title, data, gpct, gth_list, tp, stop, cap_s, cur):
    print(f"\n◆ {title}  (TP{tp}/S{stop}/cap{cap_s}s 固定, 0.01% 級距細掃；現行門檻={cur}%)")
    print(f"  {'gth':>6s} {'n':>4s} {'total':>9s} {'EV':>7s} {'win%':>6s} {'PF':>6s} {'worst':>8s}  H1 EV(n) / H2 EV(n)  新增天(vs現行)")
    dl_cur = set(d for d, s in dl_for(data, gpct, cur))
    for gth in gth_list:
        dl = dl_for(data, gpct, gth)
        r = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in dl])
        if r is None:
            print(f"  {gth:>6.3f}  (n=0)")
            continue
        h1 = [(d, s) for d, s in dl if d <= "2026-03-31"]
        h2 = [(d, s) for d, s in dl if d > "2026-03-31"]
        r1 = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in h1])
        r2 = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in h2])
        ev1 = f"{r1['EV']:+.0f}({r1['n']})" if r1 else "n/a"
        ev2 = f"{r2['EV']:+.0f}({r2['n']})" if r2 else "n/a"
        new_days = sorted(set(d for d, s in dl) - dl_cur)
        marker = " <== 現行" if abs(gth - cur) < 1e-9 else ""
        print(f"  {gth:>6.3f}  {r['n']:>4d} {r['total']:>+9,.0f} {r['EV']:>+7,.0f} "
              f"{r['win%']:>5.1f}% {r['PF']:>6.2f} {r['worst']:>+8,.0f}  {ev1} / {ev2}  "
              f"+{len(new_days)}天{marker}")
        if new_days and gth < cur:
            for d in new_days:
                s = int(np.sign(gpct[d]))
                pnl = sim(*data[d], s, tp, stop, cap_s)
                pnl_twd = pnl * POINT_VAL if pnl is not None else None
                print(f"        └ 新增邊際交易日 {d}: gap={gpct[d]:+.3f}% dir={'多' if s>0 else '空'} pnl={pnl_twd:+.0f}")


print("#" * 100)
print("# 0845 gap_night 門檻細掃 (0.40% ~ 0.60%, 0.01% 級距)")
print("#" * 100)
fine_sweep("0845", data8, gpct8,
           [round(x, 2) for x in np.arange(0.40, 0.61, 0.01)],
           tp=80, stop=30, cap_s=300, cur=0.50)

print("\n" + "#" * 100)
print("# 1500 gap_1500 門檻細掃 (0.20% ~ 0.40%, 0.01% 級距) — 只做空方向")
print("#" * 100)


def fine_sweep_short_only(title, data, gpct, gth_list, tp_lo, tp_hi, alpha, stop, cap_s, cur):
    print(f"\n◆ {title}  (只做空, 動態TP clip({alpha}*|gap_pts|,{tp_lo},{tp_hi})/S{stop}/cap{cap_s}s；現行門檻={cur}%)")
    print(f"  {'gth':>6s} {'n':>4s} {'total':>9s} {'EV':>7s} {'win%':>6s} {'PF':>6s} {'worst':>8s}  H1 EV(n) / H2 EV(n)  新增天")
    dl_cur = set(d for d, s in dl_for(data, gpct, cur) if s < 0)
    for gth in gth_list:
        dl = [(d, s) for d, s in dl_for(data, gpct, gth) if s < 0]
        pnls = []
        for d, s in dl:
            ref = info15.loc[d, "day_close"]
            px, sec = data[d]
            gap_pts_now = abs(px[0] - ref)
            tp = min(max(alpha * gap_pts_now, tp_lo), tp_hi)
            pnls.append(sim(px, sec, s, tp, stop, cap_s))
        r = agg(pnls)
        if r is None:
            print(f"  {gth:>6.3f}  (n=0)")
            continue
        h1 = [(d, s) for d, s in dl if d <= "2026-03-31"]
        h2 = [(d, s) for d, s in dl if d > "2026-03-31"]
        def _agg_sub(lst):
            pn = []
            for d, s in lst:
                ref = info15.loc[d, "day_close"]
                px, sec = data[d]
                gap_pts_now = abs(px[0] - ref)
                tp = min(max(alpha * gap_pts_now, tp_lo), tp_hi)
                pn.append(sim(px, sec, s, tp, stop, cap_s))
            return agg(pn)
        r1, r2 = _agg_sub(h1), _agg_sub(h2)
        ev1 = f"{r1['EV']:+.0f}({r1['n']})" if r1 else "n/a"
        ev2 = f"{r2['EV']:+.0f}({r2['n']})" if r2 else "n/a"
        new_days = sorted(set(d for d, s in dl) - dl_cur)
        marker = " <== 現行" if abs(gth - cur) < 1e-9 else ""
        print(f"  {gth:>6.3f}  {r['n']:>4d} {r['total']:>+9,.0f} {r['EV']:>+7,.0f} "
              f"{r['win%']:>5.1f}% {r['PF']:>6.2f} {r['worst']:>+8,.0f}  {ev1} / {ev2}  +{len(new_days)}天{marker}")
        if new_days and gth < cur:
            for d in new_days:
                ref = info15.loc[d, "day_close"]
                px, sec = data[d]
                gap_pts_now = abs(px[0] - ref)
                tp = min(max(alpha * gap_pts_now, tp_lo), tp_hi)
                pnl = sim(px, sec, -1, tp, stop, cap_s)
                pnl_twd = pnl * POINT_VAL if pnl is not None else None
                print(f"        └ 新增邊際交易日 {d}: gap={gpct[d]:+.3f}% pnl={pnl_twd:+.0f}")


fine_sweep_short_only("1500", data15, gpct15,
                      [round(x, 2) for x in np.arange(0.20, 0.41, 0.01)],
                      tp_lo=100, tp_hi=300, alpha=0.4, stop=80, cap_s=180, cur=0.30)

print("\n" + "#" * 100)
print("# 距門檻遠近分桶：放寬門檻拉進來的『邊際單』本質上是不是比較爛的單？")
print("#" * 100)


def bucket_by_distance(title, data, gpct, base_th, buckets, tp, stop, cap_s):
    print(f"\n◆ {title}  基準門檻={base_th}%，依『超過門檻多少』分桶")
    for lo, hi, label in buckets:
        dl = [(d, int(np.sign(gpct[d]))) for d in data
              if pd.notna(gpct[d]) and lo <= abs(gpct[d]) < hi]
        r = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in dl])
        print(f"  {label:<20s} " + (fmt_short(r) if r else "(n=0)"))


def fmt_short(r):
    return (f"n={r['n']:>3d} EV={r['EV']:>+7,.0f} win={r['win%']:>5.1f}% "
            f"PF={r['PF']:>5.2f} worst={r['worst']:>+8,.0f}")


bucket_by_distance("0845", data8, gpct8, 0.50,
                    [(0.40, 0.50, "0.40~0.50% (低於現行門檻)"),
                     (0.50, 0.60, "0.50~0.60% (剛過門檻)"),
                     (0.60, 0.80, "0.60~0.80% (中等)"),
                     (0.80, 99, "0.80%+ (大gap)")],
                    tp=80, stop=30, cap_s=300)

dl15_short = [(d, s) for d, s in [(d, int(np.sign(gpct15[d]))) for d in data15 if pd.notna(gpct15[d])] if s < 0]
print(f"\n◆ 1500 (只看做空方向) 距門檻遠近分桶，基準門檻=0.30%")
for lo, hi, label in [(0.20, 0.30, "0.20~0.30% (低於現行門檻)"),
                      (0.30, 0.40, "0.30~0.40% (剛過門檻)"),
                      (0.40, 0.60, "0.40~0.60% (中等)"),
                      (0.60, 99, "0.60%+ (大gap)")]:
    sub = [(d, s) for d, s in dl15_short if lo <= abs(gpct15[d]) < hi]
    pnls = []
    for d, s in sub:
        ref = info15.loc[d, "day_close"]
        px, sec = data15[d]
        gap_pts_now = abs(px[0] - ref)
        tp = min(max(0.4 * gap_pts_now, 100), 300)
        pnls.append(sim(px, sec, s, tp, 80, 180))
    r = agg(pnls)
    print(f"  {label:<20s} " + (fmt_short(r) if r else "(n=0)"))

print("\n" + "#" * 100)
print("# 追加：0845 大gap端是否也有『太大反而更差』的天花板效應？(細分大gap桶)")
print("#" * 100)
bucket_by_distance("0845 大gap細分", data8, gpct8, 0.50,
                    [(0.50, 0.65, "0.50~0.65%"),
                     (0.65, 0.80, "0.65~0.80%"),
                     (0.80, 1.00, "0.80~1.00%"),
                     (1.00, 1.50, "1.00~1.50%"),
                     (1.50, 99, "1.50%+ (極端)")],
                    tp=80, stop=30, cap_s=300)

print("\n# 對照：把極端大gap (>=1.5%) 排除，看整體EV是否改善")
dl_capped = [(d, int(np.sign(gpct8[d]))) for d in data8 if pd.notna(gpct8[d]) and 0.5 <= abs(gpct8[d]) < 1.5]
r_capped = agg([sim(*data8[d], s, 80, 30, 300) for d, s in dl_capped])
print("  0.5%<=gap<1.5% (排除極端): " + fmt_short(r_capped))
dl_all = [(d, int(np.sign(gpct8[d]))) for d in data8 if pd.notna(gpct8[d]) and abs(gpct8[d]) >= 0.5]
r_all = agg([sim(*data8[d], s, 80, 30, 300) for d, s in dl_all])
print("  現行(0.5%+全部):          " + fmt_short(r_all))
extreme = [d for d in data8 if pd.notna(gpct8[d]) and abs(gpct8[d]) >= 1.5]
print(f"  被排除的極端日: {extreme}")
for d in extreme:
    s = int(np.sign(gpct8[d]))
    pnl = sim(*data8[d], s, 80, 30, 300)
    print(f"    {d}: gap={gpct8[d]:+.3f}% pnl={pnl*POINT_VAL if pnl is not None else None:+.0f}")
