"""
動態 TP 驗證 — TP 是否該隨 gap 大小放大？
1) gap 大小 vs cap 窗口內 MFE (最大有利波動) 的關係
2) TP = alpha * |gap_pts| (夾在 [tp_min, tp_max]) vs 固定 TP 的績效對照
0845: stop30/cap300s   1500: stop80/cap180s (現行 live 參數)
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


def mfe_mae(px, sec, s, tmax_s):
    p = px[sec <= tmax_s]
    if len(p) < 2: return None, None
    be = p[0] + s * SLIPPAGE
    fav = s * (p - be)
    return fav.max(), fav.min()


def agg(pnls):
    p = np.array([x for x in pnls if x is not None]) * POINT_VAL
    if len(p) == 0: return None
    wins = p[p > 0]; losses = p[p < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {"n": len(p), "total": p.sum(), "EV": p.mean(),
            "win%": (p > 0).mean() * 100, "PF": pf, "worst": p.min()}


def fmt(r, label):
    return (f"  {label:<28s} n={r['n']:>3d} total={r['total']:>+9,.0f} EV={r['EV']:>+7,.0f} "
            f"win={r['win%']:>5.1f}% PF={r['PF']:>5.2f} worst={r['worst']:>+8,.0f}")


def analyze(title, dl, data, gap_pts_map, fixed_tp, stop, cap_s):
    print(f"\n{'='*72}\n◆ {title}   n={len(dl)}   stop={stop} cap={cap_s}s")

    # --- 1) gap 大小 vs MFE ---
    rows = []
    for d, s in dl:
        mfe, mae = mfe_mae(*data[d], s, cap_s)
        if mfe is None: continue
        rows.append({"date": d, "gap_pts": gap_pts_map[d], "mfe": mfe, "mae": mae})
    df = pd.DataFrame(rows)
    corr = df["gap_pts"].corr(df["mfe"])
    print(f"\n[1] |gap| 點數 vs cap 內 MFE:  相關係數 = {corr:+.2f}")
    med = df["gap_pts"].median()
    for lab, sub in [(f"小 gap (<{med:.0f}pt 中位數)", df[df.gap_pts < med]),
                     (f"大 gap (>={med:.0f}pt)", df[df.gap_pts >= med])]:
        print(f"    {lab:<24s} n={len(sub):>3d}  gap中位={sub.gap_pts.median():>5.0f}pt  "
              f"MFE中位={sub.mfe.median():>5.0f}pt  MFE均={sub.mfe.mean():>5.0f}pt  "
              f"MFE>=固定TP{fixed_tp} 比例={(sub.mfe >= fixed_tp).mean()*100:.0f}%")

    # --- 2) 固定 TP vs 動態 TP ---
    print(f"\n[2] 固定 TP vs 動態 TP = alpha*|gap| (夾 [下限, 上限]):")
    r = agg([sim(*data[d], s, fixed_tp, stop, cap_s) for d, s in dl])
    print(fmt(r, f"固定 TP{fixed_tp} (現行)"))
    for alpha in [0.15, 0.2, 0.25, 0.3, 0.4, 0.5]:
        for lo, hi in [(30, 300), (fixed_tp, 300)]:
            pnls = []
            for d, s in dl:
                tp = float(np.clip(alpha * gap_pts_map[d], lo, hi))
                pnls.append(sim(*data[d], s, tp, stop, cap_s))
            r = agg(pnls)
            if r:
                print(fmt(r, f"動態 a={alpha} clip[{lo},{hi}]"))

    # --- 3) 大小 gap 分開找各自最佳固定 TP ---
    print(f"\n[3] 大/小 gap 分組各自最佳固定 TP (stop={stop}, cap={cap_s}s):")
    for lab, dsub in [("小 gap", [x for x in dl if gap_pts_map[x[0]] < med]),
                      ("大 gap", [x for x in dl if gap_pts_map[x[0]] >= med])]:
        best = []
        for tp in [30, 50, 80, 100, 150, 200, 250]:
            r = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in dsub])
            if r: best.append((tp, r))
        best.sort(key=lambda x: -x[1]["total"])
        print(f"  {lab} (n={len(dsub)}):")
        for tp, r in best[:3]:
            print(fmt(r, f"    TP{tp}"))
    return df


# ===== 0845 =====
info8, data8 = load("gap_ticks", "MXF_", "gap_days_selected_2026.csv", "08:45:00")
dl8, gpts8 = [], {}
for d in data8:
    g = info8.loc[d, "gap_night_pct"]
    if pd.notna(g) and abs(g) >= 0.5:
        dl8.append((d, int(np.sign(g))))
        gpts8[d] = abs(info8.loc[d, "open"] - info8.loc[d, "night_close"])
analyze("0845 |gap_night|>=0.5%", dl8, data8, gpts8, fixed_tp=80, stop=30, cap_s=300)

# ===== 1500 =====
info15, data15 = load("gap_ticks_1500", "N1500_", "gap_1500_days_selected.csv")
dl15, gpts15 = [], {}
for d in data15:
    g = info15.loc[d, "gap_1500_pct"]
    if abs(g) >= 0.3:
        dl15.append((d, int(np.sign(g))))
        gpts15[d] = abs(info15.loc[d, "night_open"] - info15.loc[d, "day_close"])
analyze("1500 |gap_1500|>=0.3%", dl15, data15, gpts15, fixed_tp=100, stop=80, cap_s=180)
