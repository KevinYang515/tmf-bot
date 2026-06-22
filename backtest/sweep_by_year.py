"""把 1500 D-strat 跟 0845 A-strat 按年度（半年）拆"""
import pandas as pd, numpy as np
from pathlib import Path
import sys

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

# 共用：複製 sweep_cutoff_exit 與 sweep_0845 的 sim 函數
exec(open(BASE / "sweep_cutoff_exit.py", encoding="utf-8").read().split('CUTOFFS =')[0])

# 額外：用每筆 trade record 而不是只回 stats
def run_record(sim_fn, cutoff_str, signal_col, threshold, **kw):
    ch, cm = int(cutoff_str[:2]), int(cutoff_str[3:])
    records = []
    for d in intraday.index:
        if d not in intraday.index: continue
        raw = intraday.loc[d, signal_col]
        if pd.isna(raw): continue
        pct = float(raw) / 18000 * 100
        if abs(pct) < threshold: continue
        sig = 1 if pct > 0 else -1
        # 0845 跟 1500 build_bars 不同，這裡用 1500 的 cross-day 版本
        if signal_col == "nq_0845":
            # 用日內版本（沒跨日）
            bd = by_date.get(d)
            if bd is None: continue
            cutoff_min = ch*60+cm
            mask = (bd["minute"] >= 8*60+46) & (bd["minute"] <= cutoff_min)
            if not mask.any(): continue
            bars = (bd["hi"][mask], bd["lo"][mask], bd["cl"][mask])
            bd_open = bd.get("open08", None)
            if bd_open is None:
                # 看 daily
                if d in daily_dict:
                    v = daily_dict[d].get("open_0845")
                    bd_open = float(v) if v is not None and not pd.isna(v) else None
            entry = bd_open
        else:
            bars = build_bars(d, (ch, cm))
            if bars is None: continue
            entry = get_open(d)
        if entry is None: continue
        p = sim_fn(entry, bars, sig, **kw)
        records.append({"date": d, "pnl": p})
    return pd.DataFrame(records)


# 補 open08 進 by_date
for d, bd in by_date.items():
    g = df_min[df_min["date"] == d]
    op = g[g["time"] == "08:46"]
    if not op.empty:
        bd["open08"] = float(op.iloc[0]["Open"])


def stats(pnls):
    if len(pnls) == 0: return None
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    return {
        "n": len(pnls),
        "total": int(pnls.sum()),
        "EV": int(pnls.mean()),
        "win%": round((pnls > 0).mean() * 100, 1),
        "Sharpe": round(pnls.mean() / pnls.std() * np.sqrt(252), 2) if pnls.std() > 0 else 0,
        "max_dd": int(dd.max()),
    }


# ==== 1500 D 策略 ====
print("=" * 100)
print("【1500 session — 策略 D 純 trailing 50, cutoff 23:00 — 按年度（半年）】")
print("=" * 100)
df_1500 = run_record(sim_D, "23:00", "nq_1500", 0.1)
df_1500["period"] = df_1500["date"].apply(lambda x:
    f"{x[:4]}H1" if x[5:7] <= "06" else f"{x[:4]}H2")
print(f"  {'period':<10s} {'n':>4s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>8s} {'maxDD':>10s}")
for p, g in df_1500.groupby("period"):
    s = stats(g["pnl"].values)
    print(f"  {p:<10s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+8,d} {s['win%']:>5.1f}% "
          f"{s['Sharpe']:>+8.2f} {s['max_dd']:>+10,d}")
# 整體
s = stats(df_1500["pnl"].values)
print(f"  {'TOTAL':<10s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+8,d} {s['win%']:>5.1f}% "
      f"{s['Sharpe']:>+8.2f} {s['max_dd']:>+10,d}")

# 對照組：1500 A 策略
print("\n>>> 對照 1500 A 固定 TP+100/+200 stop=-50 cutoff 23:00")
df_1500_A = run_record(sim_A, "23:00", "nq_1500", 0.1)
df_1500_A["period"] = df_1500_A["date"].apply(lambda x:
    f"{x[:4]}H1" if x[5:7] <= "06" else f"{x[:4]}H2")
print(f"  {'period':<10s} {'n':>4s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>8s}")
for p, g in df_1500_A.groupby("period"):
    s = stats(g["pnl"].values)
    print(f"  {p:<10s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+8,d} {s['win%']:>5.1f}% {s['Sharpe']:>+8.2f}")
s = stats(df_1500_A["pnl"].values)
print(f"  {'TOTAL':<10s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+8,d} {s['win%']:>5.1f}% {s['Sharpe']:>+8.2f}")

# ==== 0845 A 策略 ====
print("\n" + "=" * 100)
print("【0845 session — 策略 A 固定 TP+100/+200 stop=-150, cutoff 13:44 — 按年度】")
print("=" * 100)
# 0845 用 sim_A 但 stop 150
df_0845 = run_record(sim_A, "13:44", "nq_0845", 0.5, tp1=100, tp2=200, stop=150)
df_0845["period"] = df_0845["date"].apply(lambda x:
    f"{x[:4]}H1" if x[5:7] <= "06" else f"{x[:4]}H2")
print(f"  {'period':<10s} {'n':>4s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>8s} {'maxDD':>10s}")
for p, g in df_0845.groupby("period"):
    s = stats(g["pnl"].values)
    print(f"  {p:<10s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+8,d} {s['win%']:>5.1f}% "
          f"{s['Sharpe']:>+8.2f} {s['max_dd']:>+10,d}")
s = stats(df_0845["pnl"].values)
print(f"  {'TOTAL':<10s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+8,d} {s['win%']:>5.1f}% "
      f"{s['Sharpe']:>+8.2f} {s['max_dd']:>+10,d}")

# 對照 0845 D
print("\n>>> 對照 0845 D 純 trailing 50  (證實 trailing 在 0845 真的爛)")
df_0845_D = run_record(sim_D, "13:44", "nq_0845", 0.5, trail=50, init_stop=150)
df_0845_D["period"] = df_0845_D["date"].apply(lambda x:
    f"{x[:4]}H1" if x[5:7] <= "06" else f"{x[:4]}H2")
print(f"  {'period':<10s} {'n':>4s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>8s}")
for p, g in df_0845_D.groupby("period"):
    s = stats(g["pnl"].values)
    print(f"  {p:<10s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+8,d} {s['win%']:>5.1f}% {s['Sharpe']:>+8.2f}")
s = stats(df_0845_D["pnl"].values)
print(f"  {'TOTAL':<10s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+8,d} {s['win%']:>5.1f}% {s['Sharpe']:>+8.2f}")
