"""
Overnight research pass (2026-07-04):
  重要發現：Shioaji 歷史 api.ticks() 不保留開盤前試撮(simtrade)資料
  （已用 probe_preopen_ticks.py 對 2026-06-15 / 2026-07-03 驗證：
   08:30-08:45 與 14:50-15:00 窗口筆數皆為 0，且回傳欄位根本沒有 simtrade 欄位）。
  => 無法回測「試撮讀值」本身的準確度，只能：
     (a) 用『實際 gap』(kbars 算出的 open vs ref close) 做門檻/TP掃描 —— 這是可回測的部分
     (b) 用 noise-injection 模擬試撮讀值誤差，測試門檻對誤差的敏感度（穩健性）
     (c) 用 walk-forward (H1 vs H2) 檢查現有最佳參數是否穩健、有沒有 overfit 275 組合的風險
     (d) 動態 TP/停損 scaling 延伸測試（含 0845 的反直覺發現：gap 越大 MFE 越小）

真實試撮誤差目前只有 2 個 live 樣本 (0845: 5pt, 1500: 53pt) — 持續累積中 (task #46)。
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
POINT_VAL, COMMISSION, SLIPPAGE = 10, 5.6, 5
RNG = np.random.default_rng(42)


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


def fmt(r, label, w=30):
    if r is None: return f"  {label:<{w}s}  (n=0)"
    return (f"  {label:<{w}s} n={r['n']:>3d} total={r['total']:>+9,.0f} EV={r['EV']:>+7,.0f} "
            f"win={r['win%']:>5.1f}% PF={r['PF']:>5.2f} worst={r['worst']:>+8,.0f}")


# ============================================================
# 1) 載入資料
# ============================================================
info8, data8 = load("gap_ticks", "MXF_", "gap_days_selected_2026.csv", "08:45:00")
info15, data15 = load("gap_ticks_1500", "N1500_", "gap_1500_days_selected.csv")

gpts8 = {d: info8.loc[d, "open"] - info8.loc[d, "night_close"] for d in data8}
gpts15 = {d: info15.loc[d, "night_open"] - info15.loc[d, "day_close"] for d in data15}
gpct8 = {d: info8.loc[d, "gap_night_pct"] for d in data8}
gpct15 = {d: info15.loc[d, "gap_1500_pct"] for d in data15}


def dl_for(data, gpct, gth):
    return [(d, int(np.sign(gpct[d]))) for d in data if pd.notna(gpct[d]) and abs(gpct[d]) >= gth]


print("#" * 100)
print("# PART A — 門檻 sweep (實際 gap, 全樣本 + walk-forward H1/H2 穩健性)")
print("#" * 100)

def threshold_sweep(title, data, gpct, gth_list, tp, stop, cap_s):
    print(f"\n◆ {title}  (TP{tp}/S{stop}/cap{cap_s}s 固定, 只變門檻)")
    print(f"  {'gth':>6s} {'n':>4s} {'total':>9s} {'EV':>7s} {'win%':>6s} {'PF':>6s} {'worst':>8s}   H1(<=03/31) EV / H2 EV")
    for gth in gth_list:
        dl = dl_for(data, gpct, gth)
        r = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in dl])
        if r is None:
            print(f"  {gth:>6.2f}  (n=0)")
            continue
        h1 = [(d, s) for d, s in dl if d <= "2026-03-31"]
        h2 = [(d, s) for d, s in dl if d > "2026-03-31"]
        r1 = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in h1])
        r2 = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in h2])
        ev1 = f"{r1['EV']:+.0f}(n{r1['n']})" if r1 else "n/a"
        ev2 = f"{r2['EV']:+.0f}(n{r2['n']})" if r2 else "n/a"
        print(f"  {gth:>6.2f}  {r['n']:>4d} {r['total']:>+9,.0f} {r['EV']:>+7,.0f} "
              f"{r['win%']:>5.1f}% {r['PF']:>6.2f} {r['worst']:>+8,.0f}   {ev1} / {ev2}")

threshold_sweep("0845 gap_night", data8, gpct8,
                 [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 0.80, 1.00],
                 tp=80, stop=30, cap_s=300)
threshold_sweep("1500 gap_1500", data15, gpct15,
                 [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70],
                 tp=100, stop=80, cap_s=180)


print("\n" + "#" * 100)
print("# PART B — Walk-forward: H1 找最佳 TP/S，H2 驗證 (避免 275 組合 overfit)")
print("#" * 100)

def walk_forward(title, data, gpct, gth, tps, stops, cap_s):
    dl = dl_for(data, gpct, gth)
    h1 = [(d, s) for d, s in dl if d <= "2026-03-31"]
    h2 = [(d, s) for d, s in dl if d > "2026-03-31"]
    print(f"\n◆ {title}  gth={gth}%  H1 n={len(h1)}  H2 n={len(h2)}")
    rows = []
    for tp in tps:
        for stop in stops:
            r1 = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in h1])
            if r1: rows.append({"tp": tp, "stop": stop, "H1_EV": r1["EV"], "H1_total": r1["total"]})
    if not rows:
        print("  (H1 樣本不足)")
        return
    res = pd.DataFrame(rows).sort_values("H1_total", ascending=False)
    print("  H1 最佳 5 組合 → 對照 H2 表現 (樣本外驗證):")
    print(f"  {'TP/S':<10s} {'H1_EV':>8s} {'H1_n':>5s} | {'H2_EV':>8s} {'H2_n':>5s} {'H2_PF':>6s}")
    for _, row in res.head(5).iterrows():
        tp, stop = int(row.tp), int(row.stop)
        r2 = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in h2])
        h1n = agg([sim(*data[d], s, tp, stop, cap_s) for d, s in h1])["n"]
        if r2:
            print(f"  TP{tp}/S{stop:<5d} {row.H1_EV:>+8,.0f} {h1n:>5d} | {r2['EV']:>+8,.0f} {r2['n']:>5d} {r2['PF']:>6.2f}")
        else:
            print(f"  TP{tp}/S{stop:<5d} {row.H1_EV:>+8,.0f} {h1n:>5d} | (n=0)")
    # 現行 live 參數在兩半年的對照 (基準線)
    print(f"\n  現行 live 參數 (TP80/S30 for 0845, TP100/S80 for 1500) 分段對照見上 Part A")


walk_forward("0845", data8, gpct8, 0.5, [30, 50, 80, 100, 150], [15, 20, 30, 50, 80], 300)
walk_forward("1500", data15, gpct15, 0.3, [30, 50, 80, 100, 150], [30, 50, 80, 100, 150], 180)


print("\n" + "#" * 100)
print("# PART C — Noise-injection 穩健性: 決策時試撮讀值若有誤差, 門檻策略還撐得住嗎？")
print("# (試撮 vs 實際開盤誤差目前僅 2 個 live 樣本: 0845=5pt, 1500=53pt；用合成雜訊做敏感度分析)")
print("#" * 100)

def noise_test(title, data, gpts, gpct, gth_pts, tp, stop, cap_s, noise_stds):
    """
    決策時看到的 gap_pts_noisy = 真實開盤 gap_pts + N(0, noise_std)。
    若 |noisy| >= gth_pts 才觸發；方向用 noisy 的正負號 (試撮讀值決定方向)。
    重複多次抽樣求穩健 EV 分布。
    """
    all_days = list(data.keys())
    print(f"\n◆ {title}  門檻={gth_pts}pt  TP{tp}/S{stop}/cap{cap_s}s")
    print(f"  {'noise_std':>10s} {'觸發率':>7s} {'方向翻轉率':>10s} {'EV(mean)':>10s} {'EV(p10)':>10s} {'EV(p90)':>10s}")
    N_REPEAT = 300
    for nstd in noise_stds:
        ev_samples = []
        trig_rates = []
        flip_rates = []
        for _ in range(N_REPEAT):
            trig, flip = 0, 0
            pnls = []
            for d in all_days:
                true_gap = gpts[d]
                noisy_gap = true_gap + RNG.normal(0, nstd)
                if abs(noisy_gap) >= gth_pts:
                    trig += 1
                    s = int(np.sign(noisy_gap))
                    if s != int(np.sign(true_gap)):
                        flip += 1
                    pnl = sim(*data[d], s, tp, stop, cap_s)
                    if pnl is not None:
                        pnls.append(pnl)
            r = agg(pnls)
            ev_samples.append(r["EV"] if r else 0.0)
            trig_rates.append(trig / len(all_days))
            flip_rates.append(flip / max(trig, 1))
        ev_samples = np.array(ev_samples)
        print(f"  {nstd:>9.0f}pt {np.mean(trig_rates)*100:>6.1f}% {np.mean(flip_rates)*100:>9.1f}% "
              f"{ev_samples.mean():>+10,.0f} {np.percentile(ev_samples,10):>+10,.0f} {np.percentile(ev_samples,90):>+10,.0f}")


gth8_pts = np.median([abs(gpts8[d]) for d, s in dl_for(data8, gpct8, 0.5)])  # 約當 0.5% 的點數門檻中位數，改用固定門檻更直觀
# 改用「以昨夜收盤中位數換算」的固定點數門檻，較貼近實務（策略是用 % 但下面用點數雜訊模擬更直覺）
ref8 = np.median([info8.loc[d, "night_close"] for d in data8])
ref15 = np.median([info15.loc[d, "day_close"] for d in data15])
gth8_pts_fixed = ref8 * 0.005
gth15_pts_fixed = ref15 * 0.003
print(f"\n(0845 門檻 0.5% ~= {gth8_pts_fixed:.0f}pt @ 參考價中位數 {ref8:.0f} ; "
      f"1500 門檻 0.3% ~= {gth15_pts_fixed:.0f}pt @ 參考價中位數 {ref15:.0f})")

noise_test("0845 gap_night", data8, gpts8, gpct8, gth8_pts_fixed, 80, 30, 300,
           noise_stds=[0, 10, 20, 30, 50, 80, 120])
noise_test("1500 gap_1500", data15, gpts15, gpct15, gth15_pts_fixed, 100, 80, 180,
           noise_stds=[0, 10, 20, 30, 53, 80, 120, 150])
