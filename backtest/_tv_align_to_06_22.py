"""
用新的 TV 截止 06/22 CSV vs 實盤 — 對齊 06/06 ~ 06/22 那段
判斷 -145K 是 regime 問題還是執行問題
"""
import pandas as pd, numpy as np
from pathlib import Path

BASE = Path(r"D:/stock/tmf-bot/backtest")
CSV = Path(r"D:/stock/tmf-bot/tv/result/V38.0519_v26_Session_TAIFEX_MXF1!_2026-06-23-1606.csv")
POINT_VAL = 50

df = pd.read_csv(CSV, encoding="utf-8-sig")
df.columns = [c.strip() for c in df.columns]
exits = df[df["類型"].astype(str).str.contains("出場", na=False)].copy()
exits["dt"] = pd.to_datetime(exits["日期和時間"])
exits["pnl_raw"] = exits["淨損益 TWD"]
exits = exits.sort_values("dt").reset_index(drop=True)


def apply_spread(s, sp): return s - sp * POINT_VAL


def calc(p, label=""):
    p = np.array(p, dtype=float)
    if len(p) == 0: return None
    wins = p[p > 0]; losses = p[p <= 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float('inf')
    cum = np.cumsum(p)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    return {"n": len(p), "total": int(p.sum()), "EV": int(p.mean()),
            "WR%": round((p > 0).mean()*100, 1), "PF": round(pf, 2),
            "maxDD": int(dd.min())}


print("=" * 100)
print(f"【TV CSV 範圍】 {exits['dt'].min()} ~ {exits['dt'].max()} ({len(exits)} 筆)")
print("=" * 100)

# ---- 對齊 05/19 ~ 06/06 (順風期) ----
print()
print("=" * 100)
print("【1. 對齊 05/19 ~ 06/06 (前段順風)】")
print("=" * 100)
seg1 = exits[(exits["dt"] >= "2026-05-19") & (exits["dt"] <= "2026-06-06")]
for sp in [0, 2, 4]:
    s = calc(apply_spread(seg1["pnl_raw"], sp))
    print(f"  TV {sp}pt spread: n={s['n']}, PnL=NT$ {s['total']:>+9,d}, EV=NT$ {s['EV']:>+5,d}, PF={s['PF']}")
print(f"  實盤: n=171 actions = 78 round-trips, PnL=NT$ +177,010, EV/單=NT$ +1,035")

# ---- 對齊 06/07 ~ 06/22 (關鍵 — 那段虧 145K) ----
print()
print("=" * 100)
print("【2. 對齊 06/07 ~ 06/22 (關鍵段 — 實盤虧 145K！)】")
print("=" * 100)
seg2 = exits[(exits["dt"] >= "2026-06-07") & (exits["dt"] <= "2026-06-22")]
for sp in [0, 2, 4]:
    s = calc(apply_spread(seg2["pnl_raw"], sp))
    print(f"  TV {sp}pt spread: n={s['n']}, PnL=NT$ {s['total']:>+9,d}, EV=NT$ {s['EV']:>+5,d}, "
          f"PF={s['PF']}, maxDD={s['maxDD']:+,d}")
print(f"  實盤同期: n=100 actions = ?? round-trips, PnL=NT$ -145,000 ")

print()
print("=" * 100)
print("【3. 對齊 05/19 ~ 06/22 全期 (完整實盤期)】")
print("=" * 100)
seg3 = exits[(exits["dt"] >= "2026-05-19") & (exits["dt"] <= "2026-06-22")]
for sp in [0, 2, 4]:
    s = calc(apply_spread(seg3["pnl_raw"], sp))
    print(f"  TV {sp}pt spread: n={s['n']}, PnL=NT$ {s['total']:>+9,d}, EV=NT$ {s['EV']:>+5,d}, "
          f"PF={s['PF']}, maxDD={s['maxDD']:+,d}")
print(f"  實盤完整: n=271 actions, PnL=NT$ +32,308, EV/單(per action)=NT$ +119")

# 算實現率
seg3_tv_2pt = calc(apply_spread(seg3["pnl_raw"], 2))
ratio = 32308 / seg3_tv_2pt["total"] if seg3_tv_2pt["total"] != 0 else 0
print(f"  >> 實現率 (實盤 / TV 2pt): {ratio*100:.0f}%")

# ---- 按日 PnL bar chart 文字版 ----
print()
print("=" * 100)
print("【4. 06/07 ~ 06/22 TV 每日 PnL】 (看 TV 在這段是賺還是賠)")
print("=" * 100)
seg2 = seg2.copy()
seg2["date"] = seg2["dt"].dt.date
daily = seg2.groupby("date")["pnl_raw"].agg(["sum", "count"])
print(f"  {'date':<12s} {'n':>3s} {'TV_PnL':>10s} {'TV_扣2pt':>10s}")
for d, row in daily.iterrows():
    sub = seg2[seg2["date"] == d]
    pnl_2pt = (sub["pnl_raw"] - 2 * POINT_VAL).sum()
    print(f"  {str(d):<12s} {int(row['count']):>3d} {int(row['sum']):>+10,d} {int(pnl_2pt):>+10,d}")
print(f"  {'TOTAL':<12s} {int(daily['count'].sum()):>3d} {int(daily['sum'].sum()):>+10,d} "
      f"{int(daily['sum'].sum() - 2 * POINT_VAL * daily['count'].sum()):>+10,d}")

# ---- 結論 ----
print()
print("=" * 100)
print("【5. 結論】")
print("=" * 100)
tv_seg2_2pt = (seg2["pnl_raw"] - 2 * POINT_VAL).sum()
print(f"  06/07 ~ 06/22 對比:")
print(f"    TV (2pt spread): NT$ {tv_seg2_2pt:+,.0f}")
print(f"    實盤: NT$ -145,000")
print(f"    差距: NT$ {tv_seg2_2pt - (-145000):+,.0f}")
print()
if tv_seg2_2pt > 0:
    print("  >> TV 賺 / 實盤虧 -> 那段有特殊執行問題 (ManualClose, ERROR, regime mismatch)")
elif tv_seg2_2pt < -50000:
    print("  >> TV 也大虧 -> 是 regime 問題，策略本身在那段就會虧")
else:
    print("  >> TV 持平 / 小虧 -> 介於兩者之間，部分執行部分 regime")
