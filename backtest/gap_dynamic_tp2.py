"""
PART D — 動態 TP/停損 scaling 延伸研究
  D1: 0845 的反直覺發現(gap 越大 MFE 越小)是否被少數極端 gap 日拉歪？排除離群值後重測
  D2: 用 5 等分位數(quintile)分組看 gap 大小 vs MFE/MAE 的完整輪廓（非只切兩半）
  D3: 停損也隨 gap scaling（而非只動 TP）
  D4: "反向" 動態 TP：0845 大 gap 用較小 TP（呼應 D1/D2 發現），1500 大 gap 用較大 TP
  D5: 綜合最佳配方 vs 現行固定參數，全樣本 + walk-forward H1/H2 對照
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


def fmt(r, label, w=30):
    if r is None: return f"  {label:<{w}s}  (n=0)"
    return (f"  {label:<{w}s} n={r['n']:>3d} total={r['total']:>+9,.0f} EV={r['EV']:>+7,.0f} "
            f"win={r['win%']:>5.1f}% PF={r['PF']:>5.2f} worst={r['worst']:>+8,.0f}")


info8, data8 = load("gap_ticks", "MXF_", "gap_days_selected_2026.csv", "08:45:00")
info15, data15 = load("gap_ticks_1500", "N1500_", "gap_1500_days_selected.csv")

dl8, gpts8 = [], {}
for d in data8:
    g = info8.loc[d, "gap_night_pct"]
    if pd.notna(g) and abs(g) >= 0.5:
        dl8.append((d, int(np.sign(g))))
        gpts8[d] = abs(info8.loc[d, "open"] - info8.loc[d, "night_close"])

dl15, gpts15 = [], {}
for d in data15:
    g = info15.loc[d, "gap_1500_pct"]
    if abs(g) >= 0.3:
        dl15.append((d, int(np.sign(g))))
        gpts15[d] = abs(info15.loc[d, "night_open"] - info15.loc[d, "day_close"])


# ============================================================
# D1: 排除離群值後 gap-MFE 相關性
# ============================================================
print("#" * 100)
print("# D1 — 排除極端 gap 日後, gap 大小 vs MFE 相關性是否還在？")
print("#" * 100)

def corr_ex_outlier(title, dl, data, gpts, cap_s, pct_trim):
    rows = []
    for d, s in dl:
        mfe, mae = mfe_mae(*data[d], s, cap_s)
        if mfe is None: continue
        rows.append({"date": d, "gap": gpts[d], "mfe": mfe, "mae": mae})
    df = pd.DataFrame(rows)
    full_corr = df["gap"].corr(df["mfe"])
    lo, hi = df["gap"].quantile(pct_trim), df["gap"].quantile(1 - pct_trim)
    trimmed = df[(df["gap"] >= lo) & (df["gap"] <= hi)]
    trim_corr = trimmed["gap"].corr(trimmed["mfe"])
    print(f"\n◆ {title}")
    print(f"  全樣本(n={len(df)}) corr={full_corr:+.3f}   去頭尾{pct_trim*100:.0f}%(n={len(trimmed)}) corr={trim_corr:+.3f}")
    print(f"  最大 3 個 gap 日: {df.nlargest(3,'gap')[['date','gap','mfe']].to_string(index=False)}")
    return df

df8 = corr_ex_outlier("0845", dl8, data8, gpts8, 300, 0.15)
df15 = corr_ex_outlier("1500", dl15, data15, gpts15, 180, 0.15)


# ============================================================
# D2: 五等分位數輪廓
# ============================================================
print("\n" + "#" * 100)
print("# D2 — Gap 五等分位數(quintile) vs MFE/MAE 完整輪廓")
print("#" * 100)

def quintile_profile(title, df, fixed_tp):
    df = df.copy()
    try:
        df["q"] = pd.qcut(df["gap"], 5, labels=False, duplicates="drop")
    except ValueError:
        df["q"] = pd.qcut(df["gap"], 3, labels=False, duplicates="drop")
    print(f"\n◆ {title}")
    print(f"  {'quintile':>9s} {'n':>3s} {'gap範圍':>18s} {'MFE中位':>8s} {'MFE均':>8s} {'MAE中位':>8s} {'MFE>=TP'+str(fixed_tp)+'比例':>14s}")
    for q, sub in df.groupby("q"):
        rng = f"{sub['gap'].min():.0f}~{sub['gap'].max():.0f}"
        print(f"  {q:>9d} {len(sub):>3d} {rng:>18s} {sub['mfe'].median():>8.0f} {sub['mfe'].mean():>8.0f} "
              f"{sub['mae'].median():>8.0f} {(sub['mfe']>=fixed_tp).mean()*100:>13.0f}%")

quintile_profile("0845 (fixed TP=80 参照)", df8, 80)
quintile_profile("1500 (fixed TP=100 参照)", df15, 100)


# ============================================================
# D3: 停損也隨 gap scaling
# ============================================================
print("\n" + "#" * 100)
print("# D3 — 停損隨 gap scaling (固定 TP, 停損 = beta * gap, clip)")
print("#" * 100)

def stop_scaling(title, dl, data, gpts, fixed_tp, base_stop, cap_s):
    print(f"\n◆ {title}  (TP{fixed_tp} 固定 vs S{base_stop} 現行)")
    r0 = agg([sim(*data[d], s, fixed_tp, base_stop, cap_s) for d, s in dl])
    print(fmt(r0, f"現行固定 S{base_stop}"))
    for beta in [0.1, 0.15, 0.2, 0.25, 0.3]:
        for lo, hi in [(15, 150), (20, 100), (base_stop, 150)]:
            pnls = []
            for d, s in dl:
                stop = float(np.clip(beta * gpts[d], lo, hi))
                pnls.append(sim(*data[d], s, fixed_tp, stop, cap_s))
            r = agg(pnls)
            if r: print(fmt(r, f"動態 S beta={beta} clip[{lo},{hi}]"))

stop_scaling("0845", dl8, data8, gpts8, 80, 30, 300)
stop_scaling("1500", dl15, data15, gpts15, 100, 80, 180)


# ============================================================
# D4: 反向動態 TP - 0845 大 gap 用小 TP
# ============================================================
print("\n" + "#" * 100)
print("# D4 — 反向動態 TP: 0845 大 gap 用『較小』TP (呼應 D1/D2 負相關發現)")
print("#" * 100)

def inverse_dynamic_tp(title, dl, data, gpts, stop, cap_s, base_tp, direction):
    """direction='inverse': tp = max_tp - alpha*gap (gap 越大 tp 越小)"""
    print(f"\n◆ {title}  (stop={stop}, cap={cap_s}s)")
    r0 = agg([sim(*data[d], s, base_tp, stop, cap_s) for d, s in dl])
    print(fmt(r0, f"現行固定 TP{base_tp}"))
    med = np.median(list(gpts.values()))
    for tp_small, tp_large, cutoff in [(50, 100, med), (30, 100, med), (50, 150, med),
                                        (30, 80, med), (50, 80, med)]:
        pnls = []
        for d, s in dl:
            tp = tp_small if gpts[d] >= cutoff else tp_large
            pnls.append(sim(*data[d], s, tp, stop, cap_s))
        r = agg(pnls)
        if r: print(fmt(r, f"反向: 大gap(>={cutoff:.0f})->TP{tp_small}, 小gap->TP{tp_large}"))

inverse_dynamic_tp("0845", dl8, data8, gpts8, 30, 300, 80, "inverse")

print("\n(1500 gap 越大 MFE 越大, 用正向動態 TP 已在 gap_dynamic_tp.py 驗證過 -> a=0.4 clip[100,300] EV+281 略優於固定+251)")


# ============================================================
# D5: 綜合最佳配方 vs 固定參數, walk-forward 對照
# ============================================================
print("\n" + "#" * 100)
print("# D5 — 綜合配方 walk-forward 對照 (H1<=03/31 找, H2 驗證)")
print("#" * 100)

def wf_split(dl, cutoff="2026-03-31"):
    h1 = [(d, s) for d, s in dl if d <= cutoff]
    h2 = [(d, s) for d, s in dl if d > cutoff]
    return h1, h2

def eval_recipe(dl, data, gpts, tp_fn, stop_fn, cap_s):
    pnls = []
    for d, s in dl:
        tp = tp_fn(gpts[d]); stop = stop_fn(gpts[d])
        pnls.append(sim(*data[d], s, tp, stop, cap_s))
    return agg(pnls)

h1_8, h2_8 = wf_split(dl8)
h1_15, h2_15 = wf_split(dl15)

print("\n◆ 0845 — 固定 TP80/S30 vs 反向動態 TP(大gap->50,小gap->100)/S30 固定")
for label, tp_fn in [("固定TP80", lambda g: 80),
                     ("反向 tp50/100 @med", lambda g, med=np.median(list(gpts8.values())): 50 if g>=med else 100)]:
    for lab2, dl_, tag in [("全樣本", dl8, ""), ("H1", h1_8, ""), ("H2", h2_8, "")]:
        r = eval_recipe(dl_, data8, gpts8, tp_fn, lambda g: 30, 300)
        print(fmt(r, f"{label} [{lab2}]"))

print("\n◆ 1500 — 固定 TP100/S80 vs 正向動態 TP(a=0.4 clip[100,300])/S80 固定")
def dyn_tp15(g, alpha=0.4, lo=100, hi=300):
    return float(np.clip(alpha*g, lo, hi))
for label, tp_fn in [("固定TP100", lambda g: 100), ("動態 a=0.4 clip[100,300]", dyn_tp15)]:
    for lab2, dl_ in [("全樣本", dl15), ("H1", h1_15), ("H2", h2_15)]:
        r = eval_recipe(dl_, data15, gpts15, tp_fn, lambda g: 80, 180)
        print(fmt(r, f"{label} [{lab2}]"))
