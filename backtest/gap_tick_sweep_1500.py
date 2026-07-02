"""
Tick 級參數掃描 — 15:00 夜盤開盤 gap scalp (2026)
==================================================
gap_1500 = 15:00 開盤 vs 同日 13:45 日盤收 (75min surprise)
進場: 15:00 第一筆成交價 + 滑價, 順 gap 方向

v2: + 點數門檻 vs % 門檻對照
    + NQ (13:00→15:00) 當 filter 的三種模式
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
TICK_DIR = BASE / "gap_ticks_1500"
POINT_VAL = 10
COMMISSION = 5.6
SLIPPAGE = 5

info = pd.read_csv(TICK_DIR / "gap_1500_days_selected.csv").set_index("date")
info["gap_pt"] = info["night_open"] - info["day_close"]

# NQ 1500 訊號 (13:00→15:00 TW)
sig = pd.read_csv(BASE / "intraday_signals_v2.csv").set_index("date")
info["nq_pct"] = sig["nq_1500_pct"].reindex(info.index)

data = {}
for d in info.index:
    fp = TICK_DIR / f"N1500_{d}.csv"
    if not fp.exists(): continue
    t = pd.read_csv(fp)
    t["ts"] = pd.to_datetime(t["ts"])
    t = t.sort_values("ts")
    if len(t) < 50: continue
    px = t["close"].values.astype(np.float64)
    sec = (t["ts"] - t["ts"].iloc[0]).dt.total_seconds().values
    data[d] = (px, sec)

print(f"載入 {len(data)} 天 15:00 tick")
have_nq = info.loc[[d for d in data], "nq_pct"].notna().sum()
print(f"其中 {have_nq} 天有 NQ 資料 (06/13 前)")

# gap vs NQ 相關性
sub = info.loc[[d for d in data]].dropna(subset=["nq_pct"])
if len(sub) > 5:
    corr = np.corrcoef(sub["gap_1500_pct"], sub["nq_pct"])[0, 1]
    same_dir = (np.sign(sub["gap_1500_pct"]) == np.sign(sub["nq_pct"])).mean()
    print(f"corr(gap_1500, nq_1500) = {corr:+.3f},  方向一致率 = {same_dir*100:.0f}%")


def sim_tp_stop_day(px, sec, s, tp, stop, tmax_s):
    mask = sec <= tmax_s
    p = px[mask]
    if len(p) < 2: return None
    be = p[0] + s * SLIPPAGE
    fav = s * (p - be)
    tp_hit = fav >= tp
    stop_hit = fav <= -stop if stop is not None else np.zeros(len(p), bool)
    i_tp = tp_hit.argmax() if tp_hit.any() else len(p)
    i_st = stop_hit.argmax() if stop_hit.any() else len(p)
    if i_tp < i_st: return tp - COMMISSION
    if i_st < len(p): return -stop - COMMISSION
    return fav[-1] - COMMISSION


def sim_trail_day(px, sec, s, trail, tmax_s):
    mask = sec <= tmax_s
    p = px[mask]
    if len(p) < 2: return None
    be = p[0] + s * SLIPPAGE
    fav = s * (p - be)
    runmax = np.maximum.accumulate(fav)
    dd = runmax - fav
    hit = dd >= trail
    if hit.any():
        i = hit.argmax()
        return runmax[i] - trail - COMMISSION
    return fav[-1] - COMMISSION


def agg(pnls):
    p = np.array([x for x in pnls if x is not None]) * POINT_VAL
    if len(p) == 0: return None
    wins = p[p > 0]; losses = p[p < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {"n": len(p), "total": p.sum(), "EV": p.mean(),
            "win%": (p > 0).mean() * 100, "PF": pf, "worst": p.min()}


TPS = [10, 15, 20, 30, 50, 80, 100]
STOPS = [10, 15, 20, 30, 50, 80, None]
TMAXS = [(60, "1m"), (180, "3m"), (300, "5m"), (600, "10m"), (1860, "31m")]
TRAILS = [10, 15, 20, 30, 40, 60]


def day_list(kind, th, nq_mode="none"):
    out = []
    for d in data:
        r = info.loc[d]
        v = abs(r["gap_1500_pct"]) if kind == "pct" else abs(r["gap_pt"])
        if v < th: continue
        s = int(np.sign(r["gap_1500_pct"]))
        if nq_mode != "none":
            if not pd.notna(r["nq_pct"]): continue
            nq_s = int(np.sign(r["nq_pct"])) if abs(r["nq_pct"]) > 0.02 else 0
            if nq_mode == "same" and nq_s != s: continue
            if nq_mode == "not_opp" and nq_s == -s: continue
        out.append((d, s))
    return out


def sweep(dl):
    rows = []
    for tp in TPS:
        for stop in STOPS:
            for tmax_s, tlab in TMAXS:
                r = agg([sim_tp_stop_day(*data[d], s, tp, stop, tmax_s) for d, s in dl])
                if r: rows.append({"exit": f"TP{tp}/S{stop if stop else '∞'}/{tlab}", **r})
    for trail in TRAILS:
        for tmax_s, tlab in TMAXS:
            r = agg([sim_trail_day(*data[d], s, trail, tmax_s) for d, s in dl])
            if r: rows.append({"exit": f"trail{trail}/{tlab}", **r})
    return pd.DataFrame(rows)


# ============ Phase A: 篩選形式總覽 ============
print()
print("=" * 108)
print("Phase A: 各種篩選形式 × NQ filter — 穩健度總覽")
print("=" * 108)
print(f"{'篩選':<28s} {'n天':>4s} {'正EV組合':>9s} {'EV中位數':>9s} {'最佳 exit':<20s} {'最佳EV':>8s} {'最佳PF':>7s}")

filters = []
for kind, ths in [("pct", [0.1, 0.15, 0.2, 0.3]), ("pt", [30, 50, 80, 100])]:
    for th in ths:
        for nq_mode in ["none", "same", "not_opp"]:
            filters.append((kind, th, nq_mode))

summary = []
for kind, th, nq_mode in filters:
    dl = day_list(kind, th, nq_mode)
    if len(dl) < 8: continue
    res = sweep(dl)
    if res.empty: continue
    pos_pct = (res["total"] > 0).mean() * 100
    best = res.sort_values("total", ascending=False).iloc[0]
    lbl = f"{'%' if kind=='pct' else 'pt'}>={th}" + \
          {"none": "", "same": " +NQ同向", "not_opp": " +NQ非反向"}[nq_mode]
    summary.append({"lbl": lbl, "kind": kind, "th": th, "nq": nq_mode,
                    "n": len(dl), "pos%": pos_pct,
                    "medEV": res["EV"].median(),
                    "best_exit": best["exit"], "bestEV": best["EV"], "bestPF": best["PF"]})
    print(f"{lbl:<28s} {len(dl):>4d} {pos_pct:>8.0f}% {res['EV'].median():>+9,.0f} "
          f"{best['exit']:<20s} {best['EV']:>+8,.0f} {best['PF']:>7.2f}")

# ============ Phase B: 最穩健的 2 組 詳細矩陣 ============
sdf = pd.DataFrame(summary).sort_values(["pos%", "medEV"], ascending=False)
print()
print("=" * 108)
print("Phase B: 最穩健 2 組的 EV 矩陣 @ 5min")
print("=" * 108)
for _, row in sdf.head(2).iterrows():
    dl = day_list(row["kind"], row["th"], row["nq"])
    print(f"\n◆ {row['lbl']}  n={len(dl)}")
    print("  TP\\S   " + "".join(f"{('S'+str(s)) if s else 'S∞':>8s}" for s in STOPS))
    for tp in TPS:
        line = f"  TP{tp:<5d}"
        for stop in STOPS:
            r = agg([sim_tp_stop_day(*data[d], s, tp, stop, 300) for d, s in dl])
            line += f"{r['EV']:>+8,.0f}" if r else f"{'—':>8s}"
        print(line)
    res = sweep(dl).sort_values("total", ascending=False)
    print(f"\n  Top 8:")
    print(f"  {'exit':<20s} {'n':>4s} {'total':>9s} {'EV':>7s} {'win%':>6s} {'PF':>6s} {'worst':>8s}")
    for _, r in res.head(8).iterrows():
        print(f"  {r['exit']:<20s} {r['n']:>4d} {r['total']:>+9,.0f} {r['EV']:>+7,.0f} "
              f"{r['win%']:>5.1f}% {r['PF']:>6.2f} {r['worst']:>+8,.0f}")
