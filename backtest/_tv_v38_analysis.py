"""V38 TV backtest 完整分析 + 對齊實盤 5 週"""
import pandas as pd, numpy as np
from pathlib import Path

CSV = Path(r"D:/stock/tmf-bot/tv/result/V38.0519_v26_Session_TAIFEX_MXF1!_2026-06-23.csv")
df = pd.read_csv(CSV, encoding="utf-8-sig")
df.columns = [c.strip() for c in df.columns]

# 只取出場 row（每筆 trade 出場 row 帶最終 PnL）
exits = df[df["類型"].astype(str).str.contains("出場", na=False)].copy()
exits["dt"] = pd.to_datetime(exits["日期和時間"])
exits["pnl"] = exits["淨損益 TWD"]
exits["mae"] = exits["不利波動 TWD"]
exits["mfe"] = exits["有利波動 TWD"]
exits["year"] = exits["dt"].dt.year
exits["month"] = exits["dt"].dt.strftime("%Y-%m")
exits = exits.sort_values("dt").reset_index(drop=True)

print("=" * 90)
print(f"【TV 回測完整數據】 {CSV.name}")
print("=" * 90)
print(f"  期間: {exits['dt'].min()} ~ {exits['dt'].max()}")
print(f"  總交易筆數: {len(exits)}")
print(f"  總天數: {(exits['dt'].max() - exits['dt'].min()).days}")
print(f"  累計 PnL: NT$ {exits['pnl'].sum():,.0f}")

# 整體 stats
def stats(p, label="ALL"):
    p = np.array(p, dtype=float)
    if len(p) == 0: return None
    wins = p[p > 0]; losses = p[p <= 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float('inf')
    cum = np.cumsum(p)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    return {
        "label": label,
        "n": len(p),
        "total": int(p.sum()),
        "EV": int(p.mean()),
        "win%": round((p > 0).mean()*100, 1),
        "PF": round(pf, 2),
        "avg_win": int(wins.mean()) if len(wins) > 0 else 0,
        "avg_loss": int(losses.mean()) if len(losses) > 0 else 0,
        "max_win": int(p.max()),
        "max_loss": int(p.min()),
        "max_dd": int(dd.min()),
        "max_dd_pct_of_cum_peak": round(dd.min() / peak.max() * 100, 1) if peak.max() > 0 else 0,
    }

s = stats(exits["pnl"], "ALL")
print()
print(f"  WR: {s['win%']}%  ({(exits['pnl']>0).sum()} W / {(exits['pnl']<=0).sum()} L)")
print(f"  PF: {s['PF']}")
print(f"  EV/單: NT$ {s['EV']:,}")
print(f"  均勝 / 均敗: {s['avg_win']:,} / {s['avg_loss']:,}")
print(f"  最大單筆獲利: {s['max_win']:,}")
print(f"  最大單筆損失: {s['max_loss']:,}")
print(f"  MaxDD (從 cumulative peak): {s['max_dd']:,}")

# 按年拆
print()
print("=" * 90)
print("【按年拆分 — 看 edge 是否穩定 / 衰退】")
print("=" * 90)
print(f"  {'year':<6s} {'n':>5s} {'total':>12s} {'EV':>8s} {'WR%':>6s} {'PF':>6s} {'max_loss':>10s}")
for y, g in exits.groupby("year"):
    s = stats(g["pnl"].values, str(y))
    print(f"  {y:<6d} {s['n']:>5d} {s['total']:>+12,d} {s['EV']:>+8,d} "
          f"{s['win%']:>5.1f}% {s['PF']:>6.2f} {s['max_loss']:>+10,d}")

# 按月拆（最近 6 個月）
print()
print("=" * 90)
print("【最近 12 個月 PnL】")
print("=" * 90)
print(f"  {'month':<10s} {'n':>4s} {'total':>10s} {'EV':>7s} {'WR%':>6s} {'PF':>6s}")
m_grp = exits.groupby("month")["pnl"].agg(["sum", "count"])
for m, row in m_grp.tail(12).iterrows():
    sub = exits[exits["month"] == m]
    s = stats(sub["pnl"].values, m)
    print(f"  {m:<10s} {s['n']:>4d} {s['total']:>+10,d} {s['EV']:>+7,d} {s['win%']:>5.1f}% {s['PF']:>6.2f}")

# Equity curve MaxDD details
print()
print("=" * 90)
print("【MaxDD 詳細】")
print("=" * 90)
exits["cum"] = exits["pnl"].cumsum()
exits["peak"] = exits["cum"].cummax()
exits["dd"] = exits["cum"] - exits["peak"]
max_dd_idx = exits["dd"].idxmin()
print(f"  MaxDD 觸底時間: {exits.loc[max_dd_idx, 'dt']}")
print(f"  MaxDD 金額: NT$ {exits['dd'].min():,.0f}")
print(f"  累計 PnL 當時: NT$ {exits.loc[max_dd_idx, 'cum']:,.0f}")
print(f"  Peak 之前: NT$ {exits.loc[max_dd_idx, 'peak']:,.0f}")

# 找 Top 3 DD periods
exits["dd_pct"] = exits["dd"] / exits["peak"].replace(0, np.nan) * 100
sorted_dd = exits.nsmallest(5, "dd")[["dt", "cum", "peak", "dd", "dd_pct"]]
print()
print("  前 5 大 DD 時點:")
for _, r in sorted_dd.iterrows():
    print(f"    {r['dt']}  cum={r['cum']:>+12,.0f}  dd={r['dd']:>+12,.0f}  dd%={r['dd_pct']:>+6.1f}%")

# 對齊實盤期間
print()
print("=" * 90)
print("【對齊實盤 2026-05-19 ~ 2026-06-06】 (V26 上線 ~ PLAYBOOK 截止)")
print("=" * 90)
live_match = exits[(exits["dt"] >= "2026-05-19") & (exits["dt"] <= "2026-06-06")]
s = stats(live_match["pnl"].values, "LIVE_MATCH")
if s:
    print(f"  TV 回測該期: n={s['n']}, total=NT$ {s['total']:,}, EV=NT$ {s['EV']:,}, "
          f"WR={s['win%']}%, PF={s['PF']}")
    print(f"  vs 實盤 (PLAYBOOK): n=88, total=NT$ +177,010, WR=73.9%, PF=3.44")
    if s['total'] != 0:
        ratio = 177010 / s['total']
        print(f"  實盤/回測 PnL 比例: {ratio:.2f}x  (>1 = 實盤好過回測)")

print()
print("【對齊到 06/22 (今天)】")
live_full = exits[(exits["dt"] >= "2026-05-19")]
s = stats(live_full["pnl"].values, "LIVE_FULL")
if s:
    print(f"  TV 回測該期 (05/19 ~ 06/06): n={s['n']}, total=NT$ {s['total']:,}, "
          f"EV=NT$ {s['EV']:,}, WR={s['win%']}%, PF={s['PF']}")
    print(f"  (TV 回測只有到 06/06，所以後續 16 天無法對齊)")
    print(f"  vs 實盤完整: n=143, total=NT$ +32,308, WR=53.1%, PF=1.11")

# 平均 PnL 對比
print()
print("=" * 90)
print("【EV 對比】")
print("=" * 90)
print(f"  TV 回測全期 EV/單: NT$ {int(exits['pnl'].mean()):,}")
print(f"  實盤 5 週 EV/單: NT$ {32308 // 143:,}")
print(f"  比例 (實盤/回測): {(32308/143) / exits['pnl'].mean():.2f}")
