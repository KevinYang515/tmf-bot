"""
1500 D 在 threshold = 0.00% / 0.05% / 0.10% 三個下完整對照
- 年度/半年拆分
- walk-forward train→test 4 期
- 連虧最長
- 月度盈虧穩定度
- 月平均交易筆數
"""
import pandas as pd, numpy as np
from pathlib import Path
import sys

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

exec(open(BASE / "sweep_cutoff_exit.py", encoding="utf-8").read().split('CUTOFFS =')[0])


def run_record(threshold, sim_fn=sim_D, cutoff=(23, 0)):
    records = []
    for d in intraday.index:
        if d not in intraday.index: continue
        raw = intraday.loc[d, "nq_1500"]
        if pd.isna(raw): continue
        pct = float(raw) / 18000 * 100
        if abs(pct) < threshold: continue
        sig = 1 if pct > 0 else (-1 if pct < 0 else 0)
        if sig == 0: continue
        bars = build_bars(d, cutoff)
        if bars is None: continue
        entry = get_open(d)
        if entry is None: continue
        p = sim_fn(entry, bars, sig)
        records.append({"date": d, "pnl": p})
    df = pd.DataFrame(records)
    if df.empty: return df
    df["month"] = df["date"].str[:7]
    df["half"] = df["date"].apply(lambda x: f"{x[:4]}H1" if x[5:7] <= "06" else f"{x[:4]}H2")
    return df


def stats(pnls):
    if len(pnls) == 0: return None
    pnls = np.array(pnls)
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    # 最長連虧 days
    loss_mask = (pnls < 0)
    longest_losing = 0
    cur = 0
    for x in loss_mask:
        if x:
            cur += 1
            longest_losing = max(longest_losing, cur)
        else:
            cur = 0
    return {
        "n": len(pnls),
        "total": int(pnls.sum()),
        "EV": int(pnls.mean()),
        "win%": round((pnls > 0).mean()*100, 1),
        "Sharpe": round(pnls.mean()/pnls.std()*np.sqrt(252), 2) if pnls.std() > 0 else 0,
        "max_dd": int(dd.max()),
        "max_loss_day": int(pnls.min()),
        "max_win_day": int(pnls.max()),
        "longest_losing_streak": longest_losing,
    }


THRESHOLDS = [0.00, 0.05, 0.10]
DATAS = {t: run_record(t) for t in THRESHOLDS}

print("=" * 110)
print("【1. 整體統計】")
print("=" * 110)
print(f"  {'thr%':<6s} {'n':>4s} {'/年':>5s} {'total':>10s} {'EV':>7s} {'win%':>6s} {'Sharpe':>7s} "
      f"{'maxDD':>9s} {'wrstD':>7s} {'bestD':>7s} {'longLoseStreak':>15s}")
for t in THRESHOLDS:
    s = stats(DATAS[t]["pnl"].values)
    print(f"  {t:<6.2f} {s['n']:>4d} {s['n']/2.5:>5.0f} {s['total']:>+10,d} {s['EV']:>+7,d} "
          f"{s['win%']:>5.1f}% {s['Sharpe']:>+7.2f} {s['max_dd']:>+9,d} "
          f"{s['max_loss_day']:>+7,d} {s['max_win_day']:>+7,d} {s['longest_losing_streak']:>15d}")

print()
print("=" * 110)
print("【2. 半年拆分（看 2026H1 衰退趨勢）】")
print("=" * 110)
print(f"  {'thr%':<6s} {'period':<8s} {'n':>4s} {'total':>10s} {'EV':>7s} {'win%':>6s} {'Sharpe':>7s}")
for t in THRESHOLDS:
    for h, g in DATAS[t].groupby("half"):
        s = stats(g["pnl"].values)
        print(f"  {t:<6.2f} {h:<8s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+7,d} "
              f"{s['win%']:>5.1f}% {s['Sharpe']:>+7.2f}")
    print()

print("=" * 110)
print("【3. Walk-forward 4 期 (train 半年 → test 半年)】")
print("=" * 110)
WINDOWS = [
    ("2024-01", "2024-06", "2024-07", "2024-12"),
    ("2024-07", "2024-12", "2025-01", "2025-06"),
    ("2025-01", "2025-06", "2025-07", "2025-12"),
    ("2025-07", "2025-12", "2026-01", "2026-06"),
]
print(f"  {'thr%':<6s} {'window':<35s} {'train_n':>8s} {'train_EV':>9s} {'train_Sh':>9s} "
      f"{'test_n':>7s} {'test_EV':>8s} {'test_Sh':>8s} {'test_total':>11s}")
for t in THRESHOLDS:
    test_sharpes = []
    test_totals = []
    for tr_s, tr_e, te_s, te_e in WINDOWS:
        df = DATAS[t]
        tr = df[(df["date"] >= tr_s) & (df["date"] < tr_e + "-32")]
        te = df[(df["date"] >= te_s) & (df["date"] < te_e + "-32")]
        ts = stats(tr["pnl"].values) if len(tr) > 0 else None
        es = stats(te["pnl"].values) if len(te) > 0 else None
        if ts is None or es is None: continue
        test_sharpes.append(es["Sharpe"])
        test_totals.append(es["total"])
        print(f"  {t:<6.2f} {tr_s}~{tr_e} → {te_s}~{te_e}  {ts['n']:>4d}  {ts['EV']:>+9,d} "
              f"{ts['Sharpe']:>+9.2f}  {es['n']:>4d}  {es['EV']:>+8,d} {es['Sharpe']:>+8.2f} "
              f"{es['total']:>+11,d}")
    if test_sharpes:
        avg = sum(test_sharpes) / len(test_sharpes)
        neg = sum(1 for s in test_sharpes if s < 0)
        print(f"        平均 test Sharpe: {avg:+.2f}  ({'全正 robust' if neg==0 else f'{neg} 期負'}) "
              f"  總 test total: {sum(test_totals):+,d}")
        print()

print("=" * 110)
print("【4. 月度盈虧穩定度（賺錢月 / 賠錢月比例）】")
print("=" * 110)
print(f"  {'thr%':<6s} {'months':>7s} {'win_mo':>7s} {'lose_mo':>8s} {'best_mo':>9s} {'worst_mo':>10s} {'avg_mo':>8s}")
for t in THRESHOLDS:
    df = DATAS[t]
    monthly = df.groupby("month")["pnl"].sum()
    print(f"  {t:<6.2f} {len(monthly):>7d} {(monthly > 0).sum():>7d} {(monthly < 0).sum():>8d} "
          f"{int(monthly.max()):>+9,d} {int(monthly.min()):>+10,d} {int(monthly.mean()):>+8,d}")

print()
print("=" * 110)
print("【5. 對照組 — 也跑 0845 cutoff 13:25 vs 13:44 確認改 cutoff 沒問題】")
print("=" * 110)
# 補 open08
for d, bd in by_date.items():
    if "open08" not in bd:
        g = df_min[df_min["date"] == d]
        op = g[g["time"] == "08:46"]
        bd["open08"] = float(op.iloc[0]["Open"]) if not op.empty else None

def build_bars_0845(d, cutoff_hm):
    ch, cm = cutoff_hm; cm_t = ch*60+cm
    bd = by_date.get(d)
    if bd is None: return None
    mask = (bd["minute"] >= 8*60+46) & (bd["minute"] <= cm_t)
    if not mask.any(): return None
    return bd["hi"][mask], bd["lo"][mask], bd["cl"][mask]

def get_open_0845(d):
    bd = by_date.get(d)
    if bd is None: return None
    bo = bd["open08"]
    if d in daily_dict:
        v = daily_dict[d].get("open_0845")
        if v is not None and not pd.isna(v) and bo is not None:
            if abs(float(v) - bo) <= 200:
                return float(v)
    return bo

print(f"  {'cutoff':<8s} {'n':>4s} {'total':>10s} {'EV':>7s} {'win%':>6s} {'Sharpe':>7s} {'maxDD':>9s}")
for cf in [(13, 25), (13, 44)]:
    pnls = []
    for d in intraday.index:
        raw = intraday.loc[d, "nq_0845"]
        if pd.isna(raw): continue
        pct = float(raw) / 18000 * 100
        if abs(pct) < 0.5: continue
        sig = 1 if pct > 0 else -1
        bars = build_bars_0845(d, cf)
        if bars is None: continue
        entry = get_open_0845(d)
        if entry is None: continue
        pnls.append(sim_A(entry, bars, sig, tp1=100, tp2=200, stop=150))
    s = stats(pnls)
    label = f"{cf[0]:02d}:{cf[1]:02d}"
    print(f"  {label:<8s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+7,d} {s['win%']:>5.1f}% "
          f"{s['Sharpe']:>+7.2f} {s['max_dd']:>+9,d}")
