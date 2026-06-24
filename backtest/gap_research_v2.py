"""
Gap factor research v2 — 用無 lookahead feature
================================================
Feature 純度標籤:
  [CLEAN] = 100% 無 lookahead (TX 08:44 cutoff 前完全可觀察)
  [WARM]  = 小 leak (~14min, KOSPI 09:00 TW close vs TX 08:46 open)
  [HOT]   = 重 leak (>30min)

對照組:
  V0 = NQ 5:00→8:00 pct (CLEAN)
  Vk = kospi_open_gap_pct (CLEAN, 46min lead)
  Vn = nkx_open_gap_pct (CLEAN, 46min lead)
  Vk1h = kospi_first1h_pct (WARM, ~14min leak after TX open)
  Vn1h = nkx_first1h_pct (WARM)

目標: 找出純 CLEAN feature 的 corr 跟 backtest edge
       對照 WARM 看 leak 是否誇大原本估計
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent

print("載入 mxf 1min ...", end=" ", flush=True)
df_min = pd.read_csv(BASE / "mxf_1min.csv")
df_min["ts"] = pd.to_datetime(df_min["ts"])
df_min["date"] = df_min["ts"].dt.date.astype(str)
df_min["time"] = df_min["ts"].dt.strftime("%H:%M")
print(f"{len(df_min)} 筆")

# 重建 gap_pct (跟 v1 一樣)
by_date = {}
for d, g in df_min.groupby("date"):
    g2 = g.sort_values("ts")
    op_row = g2[g2["time"] == "08:46"]
    cl_row = g2[g2["time"] == "13:44"]
    cl45 = g2[g2["time"] == "13:45"]
    by_date[d] = {
        "open08": float(op_row.iloc[0]["Open"]) if not op_row.empty else None,
        "close1344": float(cl_row.iloc[0]["Close"]) if not cl_row.empty else (
            float(cl45.iloc[0]["Close"]) if not cl45.empty else None),
    }

dates_sorted = sorted(by_date.keys())
rows = []
for i in range(1, len(dates_sorted)):
    d = dates_sorted[i]
    d_prev = dates_sorted[i - 1]
    op = by_date[d]["open08"]
    cl_prev = by_date[d_prev]["close1344"]
    if op is None or cl_prev is None: continue
    gap = op - cl_prev
    rows.append({"date": d, "gap_pt": gap, "gap_pct": gap / cl_prev * 100})

gap_df = pd.DataFrame(rows).set_index("date")
print(f"Gap 統計: n={len(gap_df)}")

# 載入新 features
sig = pd.read_csv(BASE / "intraday_signals_v2.csv").set_index("date")
df = gap_df.join(sig, how="left")

# === 相關性: clean 因子 vs gap_pct ===
print()
print("=" * 90)
print("【因子 vs TX gap_pct 相關係數】(已修正 lookahead)")
print("=" * 90)
groups = [
    ("CLEAN (no leak)", [
        ("nq_0845_pct        (NQ 05→08 TW)", "nq_0845_pct"),
        ("es_0845_pct        (ES 05→08 TW)", "es_0845_pct"),
        ("kospi_open_gap_pct (KOSPI 開盤 vs 前收)", "kospi_open_gap_pct"),
        ("nkx_open_gap_pct   (NKX 開盤 vs 前收)",    "nkx_open_gap_pct"),
    ]),
    ("WARM (14min leak)", [
        ("kospi_first1h_pct  (08:00→09:00 TW close-open)", "kospi_first1h_pct"),
        ("nkx_first1h_pct    (08:00→09:00 TW close-open)", "nkx_first1h_pct"),
        ("kospi_first1h_h_pct(高點 vs 開盤)",                "kospi_first1h_h_pct"),
        ("kospi_first1h_l_pct(低點 vs 開盤)",                "kospi_first1h_l_pct"),
    ]),
]
for tag, items in groups:
    print(f"\n--- {tag} ---")
    print(f"{'factor':<55s} {'corr':>8s} {'n':>5s} {'方向 hit (>0.3% 訊號)':>22s}")
    for label, col in items:
        if col not in df.columns: continue
        sub = df[[col, "gap_pct"]].dropna()
        if len(sub) < 50:
            print(f"{label:<55s}  (n={len(sub)} 太少)")
            continue
        c = sub[col].corr(sub["gap_pct"])
        # 方向命中率 (|factor|>0.3% 時 sign matches sign(gap))
        thresh = 0.3
        strong = sub[sub[col].abs() > thresh]
        if len(strong) > 0:
            hit = ((strong[col] > 0) == (strong["gap_pct"] > 0)).mean() * 100
            hit_str = f"{hit:.1f}% (n={len(strong)})"
        else:
            hit_str = "—"
        print(f"{label:<55s} {c:>+8.3f} {len(sub):>5d}  {hit_str:>20s}")

# === 06/24 case analysis (用新 feature) ===
print()
print("=" * 90)
print("【06/24 case: 新 feature 在那天的數字】")
print("=" * 90)
if "2026-06-12" in df.index:  # 我們最近一筆是 06-12
    print("(注: backtest 資料只到 2026-06-12, 06/24 沒有歷史資料)")
print("\n查最近幾日 KOSPI open gap 跟 TX gap 對照:")
recent = df.dropna(subset=["kospi_open_gap_pct"]).tail(20)
print(f"{'date':<12s} {'gap_pct':>9s} {'kospi_open_gap%':>17s} {'nkx_open_gap%':>15s} {'nq_0845_pct':>13s}")
for d, row in recent.iterrows():
    print(f"{d:<12s} {row['gap_pct']:>+9.3f} {row['kospi_open_gap_pct']:>+17.3f} "
          f"{row.get('nkx_open_gap_pct', np.nan):>+15.3f} {row.get('nq_0845_pct', np.nan):>+13.3f}")

# === 訊號組合: pure CLEAN ===
print()
print("=" * 90)
print("【純 CLEAN feature 訊號組合】|factor| > X% → 進場方向預測 gap 方向命中率")
print("=" * 90)
print(f"{'rule':<60s} {'n':>5s} {'hit%':>7s} {'avg|gap|':>10s} {'avg gap (同向加總)':>20s}")
clean = df.dropna(subset=["nq_0845_pct", "kospi_open_gap_pct", "nkx_open_gap_pct"]).copy()
print(f"\n樣本 n={len(clean)}")

def rule_metric(mask, sign_col, label):
    sub = clean[mask].copy()
    if len(sub) == 0:
        print(f"{label:<60s} {0:>5d}")
        return
    if sign_col is None:
        # 不關心方向, 只看 |gap| 大小
        avg_g = sub["gap_pct"].abs().mean()
        print(f"{label:<60s} {len(sub):>5d} {'—':>7s} {avg_g:>9.3f}% {'—':>20s}")
    else:
        sign_pred = np.sign(sub[sign_col])
        sign_act = np.sign(sub["gap_pct"])
        hit = (sign_pred == sign_act).mean() * 100
        avg_g = sub["gap_pct"].abs().mean()
        edge = (sign_pred * sub["gap_pct"]).mean()  # 平均同向收穫
        print(f"{label:<60s} {len(sub):>5d} {hit:>6.1f}% {avg_g:>9.3f}% {edge:>+19.3f}%")

# baseline: 整池
rule_metric(clean.index == clean.index, None, "all")

# V0
rule_metric(clean["nq_0845_pct"].abs() > 0.5, "nq_0845_pct", "V0  |NQ|>0.5%")

# Vk
rule_metric(clean["kospi_open_gap_pct"].abs() > 0.3, "kospi_open_gap_pct", "Vk  |KOSPI_open_gap|>0.3%")
rule_metric(clean["kospi_open_gap_pct"].abs() > 0.5, "kospi_open_gap_pct", "Vk  |KOSPI_open_gap|>0.5%")
rule_metric(clean["kospi_open_gap_pct"].abs() > 1.0, "kospi_open_gap_pct", "Vk  |KOSPI_open_gap|>1.0%")

# Vn
rule_metric(clean["nkx_open_gap_pct"].abs() > 0.3, "nkx_open_gap_pct", "Vn  |NKX_open_gap|>0.3%")
rule_metric(clean["nkx_open_gap_pct"].abs() > 0.5, "nkx_open_gap_pct", "Vn  |NKX_open_gap|>0.5%")
rule_metric(clean["nkx_open_gap_pct"].abs() > 1.0, "nkx_open_gap_pct", "Vn  |NKX_open_gap|>1.0%")

# Combined: KOSPI + NKX 雙過同向
combo = ((clean["kospi_open_gap_pct"].abs() > 0.3) &
         (clean["nkx_open_gap_pct"].abs() > 0.3) &
         (np.sign(clean["kospi_open_gap_pct"]) == np.sign(clean["nkx_open_gap_pct"])))
rule_metric(combo, "kospi_open_gap_pct", "Vkn  KOSPI+NKX 同向, 各>0.3%")

combo5 = ((clean["kospi_open_gap_pct"].abs() > 0.5) &
          (clean["nkx_open_gap_pct"].abs() > 0.5) &
          (np.sign(clean["kospi_open_gap_pct"]) == np.sign(clean["nkx_open_gap_pct"])))
rule_metric(combo5, "kospi_open_gap_pct", "Vkn  KOSPI+NKX 同向, 各>0.5%")

# Vote: 3 因子加總
clean["vote"] = (np.sign(clean["nq_0845_pct"]) * (clean["nq_0845_pct"].abs() > 0.2) +
                 np.sign(clean["kospi_open_gap_pct"]) * (clean["kospi_open_gap_pct"].abs() > 0.2) +
                 np.sign(clean["nkx_open_gap_pct"]) * (clean["nkx_open_gap_pct"].abs() > 0.2))
rule_metric(clean["vote"].abs() >= 2, "vote", "Vvote |vote|>=2 (3 因子 >0.2% 投票)")
rule_metric(clean["vote"].abs() >= 3, "vote", "Vvote |vote|>=3 (3 因子全同向)")

# WARM feature (for comparison, biased upward)
print()
print("--- WARM feature 用於對照 (高估真實 edge): ---")
warm = df.dropna(subset=["kospi_first1h_pct", "nkx_first1h_pct"]).copy()
print(f"樣本 n={len(warm)}")
def rule_metric_warm(mask, sign_col, label):
    sub = warm[mask].copy()
    if len(sub) == 0:
        print(f"{label:<60s} {0:>5d}")
        return
    sign_pred = np.sign(sub[sign_col])
    sign_act = np.sign(sub["gap_pct"])
    hit = (sign_pred == sign_act).mean() * 100
    avg_g = sub["gap_pct"].abs().mean()
    edge = (sign_pred * sub["gap_pct"]).mean()
    print(f"{label:<60s} {len(sub):>5d} {hit:>6.1f}% {avg_g:>9.3f}% {edge:>+19.3f}%")
rule_metric_warm(warm["kospi_first1h_pct"].abs() > 0.3, "kospi_first1h_pct", "WARM |KOSPI_1h|>0.3%")
rule_metric_warm(warm["kospi_first1h_pct"].abs() > 0.5, "kospi_first1h_pct", "WARM |KOSPI_1h|>0.5%")
rule_metric_warm(warm["nkx_first1h_pct"].abs() > 0.5,   "nkx_first1h_pct",   "WARM |NKX_1h|>0.5%")

# Save
df.to_csv(BASE / "gap_research_v2.csv", encoding="utf-8-sig")
print(f"\n資料 → {BASE / 'gap_research_v2.csv'}")
