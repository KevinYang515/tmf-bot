"""
TV 回測加上真實 bid-ask spread cost 後的修正評估
================================================
1. 原 TV vs 扣 2pt / 4pt spread 後對照
2. 按年拆，看每年 edge 跟 DD
3. 對齊實盤同期，驗證解釋力
4. MXF 升級風險評估
"""
import pandas as pd, numpy as np
from pathlib import Path

CSV = Path(r"D:/stock/tmf-bot/tv/result/V38.0519_v26_Session_TAIFEX_MXF1!_2026-06-23.csv")
df = pd.read_csv(CSV, encoding="utf-8-sig")
df.columns = [c.strip() for c in df.columns]

exits = df[df["類型"].astype(str).str.contains("出場", na=False)].copy()
exits["dt"] = pd.to_datetime(exits["日期和時間"])
exits["pnl_raw"] = exits["淨損益 TWD"]
exits["year"] = exits["dt"].dt.year
exits = exits.sort_values("dt").reset_index(drop=True)

# MXF 1 pt = NT$50
POINT_VAL = 50

# 扣 spread: 一筆 round-trip 扣 X 點
def apply_spread(pnl_series, spread_pts):
    return pnl_series - spread_pts * POINT_VAL


def calc(pnls):
    p = np.array(pnls, dtype=float)
    wins = p[p > 0]; losses = p[p <= 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float('inf')
    cum = np.cumsum(p)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    return {
        "n": len(p),
        "total": int(p.sum()),
        "EV": int(p.mean()),
        "WR%": round((p > 0).mean()*100, 1),
        "PF": round(pf, 2),
        "max_dd": int(dd.min()),
        "avg_win": int(wins.mean()) if len(wins) > 0 else 0,
        "avg_loss": int(losses.mean()) if len(losses) > 0 else 0,
    }


print("=" * 100)
print("【1. TV 回測 — 不同 spread 假設下的全期指標】 4.4 yr / 6,247 trades / MXF1!")
print("=" * 100)
print(f"  {'spread':<14s} {'total PnL':>13s} {'EV':>8s} {'WR%':>6s} {'PF':>6s} {'maxDD':>10s} {'avg_win':>8s} {'avg_loss':>9s}")
for spread, label in [(0, "0 pt (原始)"), (2, "2 pt (1tick 來回)"), (3, "3 pt (中位)"), (4, "4 pt (保守)")]:
    s = calc(apply_spread(exits["pnl_raw"], spread))
    print(f"  {label:<14s} {s['total']:>+13,d} {s['EV']:>+8,d} {s['WR%']:>5.1f}% "
          f"{s['PF']:>6.2f} {s['max_dd']:>+10,d} {s['avg_win']:>+8,d} {s['avg_loss']:>+9,d}")

# ====== 按年扣 spread ======
print()
print("=" * 100)
print("【2. 按年 — 扣 2 pt spread 後】 (符合「BUY 吃 ask, SELL 吃 bid」最低 spread)")
print("=" * 100)
print(f"  {'year':<6s} {'n':>5s} {'total':>12s} {'EV':>8s} {'WR%':>6s} {'PF':>6s} {'maxDD_yr':>10s}")
for y, g in exits.groupby("year"):
    adj = apply_spread(g["pnl_raw"], 2)
    s = calc(adj)
    print(f"  {y:<6d} {s['n']:>5d} {s['total']:>+12,d} {s['EV']:>+8,d} "
          f"{s['WR%']:>5.1f}% {s['PF']:>6.2f} {s['max_dd']:>+10,d}")

print()
print("=" * 100)
print("【3. 按年 — 扣 4 pt spread 後】 (保守 — 流動性差或快市場)")
print("=" * 100)
print(f"  {'year':<6s} {'n':>5s} {'total':>12s} {'EV':>8s} {'WR%':>6s} {'PF':>6s} {'maxDD_yr':>10s}")
for y, g in exits.groupby("year"):
    adj = apply_spread(g["pnl_raw"], 4)
    s = calc(adj)
    print(f"  {y:<6d} {s['n']:>5d} {s['total']:>+12,d} {s['EV']:>+8,d} "
          f"{s['WR%']:>5.1f}% {s['PF']:>6.2f} {s['max_dd']:>+10,d}")

# ====== 對齊實盤期間 ======
print()
print("=" * 100)
print("【4. 對齊實盤同期 (05/19 ~ 06/06) — 扣 spread 後 vs 實盤】")
print("=" * 100)
match = exits[(exits["dt"] >= "2026-05-19") & (exits["dt"] <= "2026-06-06")]
for spread in [0, 2, 3, 4]:
    s = calc(apply_spread(match["pnl_raw"], spread))
    print(f"  TV {spread}pt: n={s['n']}, total=NT$ {s['total']:>+9,d}, "
          f"EV=NT$ {s['EV']:>+5,d}, PF={s['PF']:.2f}")
print(f"  實盤同期: n=171, total=NT$ +177,010 (PLAYBOOK), EV/單=NT$ +1,035")
print()
print("  >> 關鍵 gap 分析（用 2pt spread 對齊）:")
adj_match_2 = calc(apply_spread(match["pnl_raw"], 2))
tv_total_adj = adj_match_2["total"]
print(f"     TV 2pt 修正: +NT$ {tv_total_adj:,}")
print(f"     實盤:        +NT$ 177,010")
print(f"     gap (TV - 實盤): NT$ {tv_total_adj - 177010:,}")
print(f"     -- 如果 spread 是主因，gap 應該接近 0")
print(f"     -- 實際 gap NT$ {tv_total_adj - 177010:,} -> 還有別的差異 (e.g. 實盤多打了 93 筆稀釋 EV)")

# ====== 2026 H1 重點 (近期實況) ======
print()
print("=" * 100)
print("【5. 2026 H1 (今年至今) — 扣 spread 後是否仍有 edge】")
print("=" * 100)
h1 = exits[(exits["dt"] >= "2026-01-01") & (exits["dt"] <= "2026-06-06")]
print(f"  期間: {h1['dt'].min()} ~ {h1['dt'].max()}")
for spread in [0, 2, 4]:
    s = calc(apply_spread(h1["pnl_raw"], spread))
    print(f"  spread {spread}pt: n={s['n']}, total=NT$ {s['total']:>+9,d}, "
          f"EV=NT$ {s['EV']:>+5,d}, WR={s['WR%']}%, PF={s['PF']:.2f}")

# ====== MXF 升級評估 ======
print()
print("=" * 100)
print("【6. MXF 升級評估 — 修正後年化預期】")
print("=" * 100)
# 取 2024+2025+2026H1 平均化（穩定期）
recent = exits[exits["dt"] >= "2024-01-01"]
days = (recent["dt"].max() - recent["dt"].min()).days
years = days / 365.25
print(f"  以 2024 起 ({recent['dt'].min().date()} ~ {recent['dt'].max().date()}, {years:.1f} 年) 為基準:")
print()
print(f"  {'spread':<14s} {'年化 PnL':>12s} {'年化 maxDD':>12s} {'比例':>6s} {'PF':>6s}")
for spread, label in [(0, "0pt（原始）"), (2, "2pt（spread）"), (3, "3pt"), (4, "4pt 保守")]:
    s = calc(apply_spread(recent["pnl_raw"], spread))
    annual_pnl = s["total"] / years
    annual_dd_ratio = abs(s["max_dd"]) / annual_pnl if annual_pnl > 0 else 0
    print(f"  {label:<14s} {annual_pnl:>+12,.0f} {s['max_dd']:>+12,d} {annual_dd_ratio:>6.2f}x {s['PF']:>6.2f}")

print()
print("  → 規模建議 (按修正後預期):")
worst_dd_4pt = calc(apply_spread(recent["pnl_raw"], 4))["max_dd"]
print(f"     最差情境 (4pt spread)：MaxDD = NT$ {worst_dd_4pt:,}")
print(f"     若帳戶要承受 5% 帳戶 DD: 帳戶須 > NT$ {abs(worst_dd_4pt) / 0.05:,.0f}")
print(f"     若帳戶要承受 10% 帳戶 DD: 帳戶須 > NT$ {abs(worst_dd_4pt) / 0.10:,.0f}")
print(f"     若帳戶要承受 20% 帳戶 DD: 帳戶須 > NT$ {abs(worst_dd_4pt) / 0.20:,.0f}")
print(f"     + 4 口 MXF 保證金 ~NT$ 180K")
print(f"     -> 推薦帳戶 size：NT$ {abs(worst_dd_4pt) / 0.10 + 180000:,.0f} (10% DD + margin)")

# ====== 對 PF / edge 是否還有 ======
print()
print("=" * 100)
print("【7. 結論摘要】")
print("=" * 100)
recent_2pt = calc(apply_spread(recent["pnl_raw"], 2))
recent_4pt = calc(apply_spread(recent["pnl_raw"], 4))
print(f"  TV 回測扣 spread 後：")
print(f"  - 全期 PF (4.4yr 6247 筆):")
for sp in [0, 2, 4]:
    s = calc(apply_spread(exits["pnl_raw"], sp))
    print(f"    {sp}pt spread → PF {s['PF']:.2f}, 累計 NT$ {s['total']:,}, EV/單 NT$ {s['EV']:,}")
print()
print(f"  - 近 2.4 年 (穩定期):")
for sp in [0, 2, 4]:
    s = calc(apply_spread(recent["pnl_raw"], sp))
    print(f"    {sp}pt spread → PF {s['PF']:.2f}, 年化 NT$ {s['total']/years:,.0f}")
