"""
Factor research pass (2026-07-04, part 2) — 找更多因子/優化方向
  E: 星期幾效應 (週一累積週末消息 vs 週二~五)
  F: 假日後效應 (前一交易日距今 >=2 天 = 長假後)
  G: 多空不對稱 (上跳空 vs 下跳空 分開統計 + 各自最佳TP/停損)
  H: gap_day(舊聞) 與 gap_night/gap_1500(意外) 方向是否一致 → confirmation vs contrarian
  I: 前一場(1500)的 gap 大小/方向 對下一場(0845) 有沒有預測力 (跨 session 因子)
  J: 動態時間上限 — cap_seconds 隨 gap 大小調整
全部含 walk-forward (H1<=03/31 / H2>03/31) 驗證，避免又是雜訊。
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


def fmt(r, label, w=32):
    if r is None: return f"  {label:<{w}s}  (n=0)"
    return (f"  {label:<{w}s} n={r['n']:>3d} total={r['total']:>+9,.0f} EV={r['EV']:>+7,.0f} "
            f"win={r['win%']:>5.1f}% PF={r['PF']:>5.2f} worst={r['worst']:>+8,.0f}")


info8, data8 = load("gap_ticks", "MXF_", "gap_days_selected_2026.csv", "08:45:00")
info15, data15 = load("gap_ticks_1500", "N1500_", "gap_1500_days_selected.csv")
all8 = pd.read_csv(BASE / "gap_ticks" / "gap_days_all_2026.csv").set_index("date")
all15 = pd.read_csv(BASE / "gap_ticks_1500" / "gap_1500_days_all.csv").set_index("date")

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


def wf(dl, data, tp, stop, cap_s):
    h1 = [(d, s) for d, s in dl if d <= "2026-03-31"]
    h2 = [(d, s) for d, s in dl if d > "2026-03-31"]
    r = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in dl])
    r1 = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in h1])
    r2 = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in h2])
    return r, r1, r2


# ============================================================
# E: 星期幾效應
# ============================================================
print("#" * 100)
print("# E — 星期幾效應")
print("#" * 100)

def dow_effect(title, dl, data, tp, stop, cap_s):
    print(f"\n◆ {title}")
    dows = {}
    for d, s in dl:
        dow = pd.Timestamp(d).day_name()
        dows.setdefault(dow, []).append((d, s))
    for dow in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
        sub = dows.get(dow, [])
        if not sub: continue
        r = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in sub])
        print(fmt(r, dow))

dow_effect("0845 (TP80/S30/cap300)", dl8, data8, 80, 30, 300)
dow_effect("1500 (TP100/S80/cap180)", dl15, data15, 100, 80, 180)


# ============================================================
# F: 假日後效應
# ============================================================
print("\n" + "#" * 100)
print("# F — 距上一交易日天數 (長假後 gap 是否更大/更可靠?)")
print("#" * 100)

def gap_days_since(all_info, d):
    idx = list(all_info.index)
    if d not in idx: return None
    pos = idx.index(d)
    if pos == 0: return None
    prev = pd.Timestamp(idx[pos - 1])
    cur = pd.Timestamp(d)
    return (cur - prev).days

def holiday_effect(title, dl, data, all_info, tp, stop, cap_s):
    print(f"\n◆ {title}")
    normal, longgap = [], []
    for d, s in dl:
        gd = gap_days_since(all_info, d)
        if gd is None: continue
        (longgap if gd >= 3 else normal).append((d, s))
    print(fmt(agg([sim(*data[d], s, tp, stop, cap_s) for d, s in normal]), f"一般間隔(<=2天) n={len(normal)}"))
    print(fmt(agg([sim(*data[d], s, tp, stop, cap_s) for d, s in longgap]), f"長假後(>=3天) n={len(longgap)}"))

holiday_effect("0845", dl8, data8, all8, 80, 30, 300)
holiday_effect("1500", dl15, data15, all15, 100, 80, 180)


# ============================================================
# G: 多空不對稱
# ============================================================
print("\n" + "#" * 100)
print("# G — 多空不對稱 (上跳空做多 vs 下跳空做空)")
print("#" * 100)

def long_short_asym(title, dl, data, tp, stop, cap_s):
    print(f"\n◆ {title}  (基準 TP{tp}/S{stop})")
    longs = [(d, s) for d, s in dl if s == 1]
    shorts = [(d, s) for d, s in dl if s == -1]
    print(fmt(agg([sim(*data[d], s, tp, stop, cap_s) for d, s in longs]), f"做多(上跳空) n={len(longs)}"))
    print(fmt(agg([sim(*data[d], s, tp, stop, cap_s) for d, s in shorts]), f"做空(下跳空) n={len(shorts)}"))
    print("  分開找各自最佳 TP (walk-forward H1/H2 對照):")
    for lab, sub in [("多", longs), ("空", shorts)]:
        h1 = [(d, s) for d, s in sub if d <= "2026-03-31"]
        h2 = [(d, s) for d, s in sub if d > "2026-03-31"]
        best = []
        for t in [30, 50, 80, 100, 150, 200]:
            r = agg([sim(*data[d], s, t, stop, cap_s) for d, s in sub])
            if r: best.append((t, r))
        best.sort(key=lambda x: -x[1]["EV"])
        if best:
            t, r = best[0]
            r1 = agg([sim(*data[d], s, t, stop, cap_s) for d, s in h1])
            r2 = agg([sim(*data[d], s, t, stop, cap_s) for d, s in h2])
            print(fmt(r, f"    {lab}方最佳 TP{t} [全樣本]"))
            if r1: print(fmt(r1, f"      H1"))
            if r2: print(fmt(r2, f"      H2"))

long_short_asym("0845", dl8, data8, 80, 30, 300)
long_short_asym("1500", dl15, data15, 100, 80, 180)


# ============================================================
# H: gap_day (舊聞) 與 gap_night (意外) 方向一致性 — 只有 0845 有對照欄位
# ============================================================
print("\n" + "#" * 100)
print("# H — 舊聞 gap (vs前日收) 與 意外 gap (vs夜盤收) 方向一致(confirm) vs 不一致(contrarian)")
print("#" * 100)

def confirm_vs_contrarian(title, dl, data, info, old_col, tp, stop, cap_s):
    print(f"\n◆ {title}")
    confirm, contrarian = [], []
    for d, s in dl:
        old_g = info.loc[d, old_col]
        if pd.isna(old_g) or old_g == 0: continue
        old_dir = int(np.sign(old_g))
        (confirm if old_dir == s else contrarian).append((d, s))
    print(fmt(agg([sim(*data[d], s, tp, stop, cap_s) for d, s in confirm]), f"意外方向=舊聞方向(confirm) n={len(confirm)}"))
    print(fmt(agg([sim(*data[d], s, tp, stop, cap_s) for d, s in contrarian]), f"意外方向!=舊聞方向(contrarian) n={len(contrarian)}"))

confirm_vs_contrarian("0845 (gap_day vs gap_night)", dl8, data8, info8, "gap_day_pct", 80, 30, 300)


# ============================================================
# I: 跨 session — 前一場 1500 的 gap 對隔天 0845 有沒有預測力
# ============================================================
print("\n" + "#" * 100)
print("# I — 昨天 1500 的 gap 方向，對今天 0845 是否有訊號?")
print("#" * 100)

rows = []
all15_idx = list(all15.index)
for d, s in dl8:
    d_ts = pd.Timestamp(d)
    prior_days = [x for x in all15_idx if pd.Timestamp(x) < d_ts]
    if not prior_days: continue
    prev_day = prior_days[-1]
    prev_gap = all15.loc[prev_day, "gap_1500_pct"]
    if pd.isna(prev_gap): continue
    rows.append({"date": d, "dir_0845": s, "prev_1500_gap_pct": prev_gap,
                 "prev_1500_dir": int(np.sign(prev_gap)) if abs(prev_gap) >= 0.05 else 0})
df_cross = pd.DataFrame(rows)
if len(df_cross):
    same_dl = [(r.date, r.dir_0845) for r in df_cross.itertuples() if r.dir_0845 == r.prev_1500_dir and r.prev_1500_dir != 0]
    opp_dl = [(r.date, r.dir_0845) for r in df_cross.itertuples() if r.dir_0845 == -r.prev_1500_dir and r.prev_1500_dir != 0]
    flat_n = (df_cross["prev_1500_dir"] == 0).sum()
    print(f"\n0845 觸發日(n={len(df_cross)})：與前一場1500方向同向 n={len(same_dl)}、反向 n={len(opp_dl)}、前場gap太小 n={flat_n}")
    print(fmt(agg([sim(*data8[d], s, 80, 30, 300) for d, s in same_dl]), f"同向"))
    print(fmt(agg([sim(*data8[d], s, 80, 30, 300) for d, s in opp_dl]), f"反向"))


# ============================================================
# J: 動態時間上限
# ============================================================
print("\n" + "#" * 100)
print("# J — 動態時間上限：cap_seconds 隨 gap 大小或整體固定調整")
print("#" * 100)

def dynamic_cap_test(title, dl, data, gpts, tp, stop, base_cap):
    print(f"\n◆ {title}  (TP{tp}/S{stop}, base_cap={base_cap}s)")
    r0, r0_1, r0_2 = wf(dl, data, tp, stop, base_cap)
    print(fmt(r0, f"固定 cap={base_cap}s [全樣本]"))
    med = np.median(list(gpts.values()))
    for lo_cap, hi_cap in [(base_cap, base_cap*2), (int(base_cap*0.5), base_cap),
                            (int(base_cap*0.5), base_cap*2)]:
        pnls = []
        for d, s in dl:
            cap = hi_cap if gpts[d] >= med else lo_cap
            pnls.append(sim(*data[d], s, tp, stop, cap))
        r = agg(pnls)
        if r: print(fmt(r, f"大gap->{hi_cap}s / 小gap->{lo_cap}s"))
    for mult in [0.5, 0.75, 1.5, 2.0]:
        cap2 = int(base_cap * mult)
        r, r1, r2 = wf(dl, data, tp, stop, cap2)
        if r:
            print(fmt(r, f"固定 cap={cap2}s (x{mult}) [全樣本]"))
            if r1: print(fmt(r1, f"  H1"))
            if r2: print(fmt(r2, f"  H2"))

dynamic_cap_test("0845", dl8, data8, gpts8, 80, 30, 300)
dynamic_cap_test("1500", dl15, data15, gpts15, 100, 80, 180)
