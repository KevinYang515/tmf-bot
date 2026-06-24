"""
TX 早盤跳空因子研究
====================
目標: 找出能預測 TX 08:46 開盤跳空方向/大小的訊號,
      建立比「NQ 單因子 |%|>0.5」更強的進場條件.

Gap 定義: gap_pct = (open_0845_today - close_13:44_prev) / close_13:44_prev * 100
         > +0.3% = gap up, < -0.3% = gap down, 其餘 = small

可用因子:
  intraday_signals:
    nq_0845  / nq_0845_dir    NQ 5:00→8:00 TW 變化
    es_0845  / es_0845_dir    ES 5:00→8:00 TW
    kospi_0845 / nkx_0845     亞洲市場 8:00 TW 變化
    *_1500 系列                前一天下午台股收盤後變化
  intl_signals (前一天收盤):
    ndx_ret, spx_ret, dji_ret      US 收盤
    nkx_ret, kospi_ret              Asia 收盤
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
POINT_VAL = 10

# === 載入 K bar 拿到開盤 / 前日收盤 ===
print("載入 mxf 1min ...", end=" ", flush=True)
df_min = pd.read_csv(BASE / "mxf_1min.csv")
df_min["ts"] = pd.to_datetime(df_min["ts"])
df_min["date"] = df_min["ts"].dt.date.astype(str)
df_min["time"] = df_min["ts"].dt.strftime("%H:%M")
print(f"{len(df_min)} 筆", flush=True)

# 每天 08:46 open + 13:44 close
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
        "close1500": None,
    }
    cl1500 = g2[(g2["time"] >= "13:44") & (g2["time"] <= "13:46")]
    if not cl1500.empty:
        by_date[d]["close1500"] = float(cl1500.iloc[-1]["Close"])

dates_sorted = sorted(by_date.keys())
print(f"日期範圍 {dates_sorted[0]} ~ {dates_sorted[-1]} ({len(dates_sorted)} 日)")

# === 計算 gap ===
rows = []
for i in range(1, len(dates_sorted)):
    d = dates_sorted[i]
    d_prev = dates_sorted[i - 1]
    op = by_date[d]["open08"]
    cl_prev = by_date[d_prev]["close1344"] or by_date[d_prev]["close1500"]
    if op is None or cl_prev is None: continue
    gap = op - cl_prev
    gap_pct = gap / cl_prev * 100
    rows.append({"date": d, "prev_date": d_prev, "open_today": op,
                 "close_prev": cl_prev, "gap_pt": gap, "gap_pct": gap_pct})

gap_df = pd.DataFrame(rows).set_index("date")
print(f"\nGap 統計: n={len(gap_df)}")
print(f"  gap_pct mean = {gap_df['gap_pct'].mean():.3f}%, std = {gap_df['gap_pct'].std():.3f}%")
print(f"  |gap| > 0.30%: {(gap_df['gap_pct'].abs() > 0.30).sum()} 日 "
      f"({(gap_df['gap_pct'].abs() > 0.30).mean()*100:.1f}%)")
print(f"  |gap| > 0.50%: {(gap_df['gap_pct'].abs() > 0.50).sum()} 日 "
      f"({(gap_df['gap_pct'].abs() > 0.50).mean()*100:.1f}%)")
print(f"  |gap| > 1.00%: {(gap_df['gap_pct'].abs() > 1.00).sum()} 日")

# === 合併因子 ===
intraday = pd.read_csv(BASE / "intraday_signals.csv").set_index("date")
intl = pd.read_csv(BASE / "intl_signals.csv").set_index("date")

# intraday 是當日 08:00 TW 對應的指標 (同日對齊)
# intl 是前一天收盤對應 (US 收盤 = TW 前一日深夜) → 同日對齊就是 "今天開盤前最新的 US 收盤"
df = gap_df.copy()
df = df.join(intraday[["nq_0845", "es_0845", "kospi_0845", "nkx_0845",
                       "nq_1500", "es_1500"]], how="left")
df = df.join(intl[["ndx_ret", "spx_ret", "nkx_ret", "kospi_ret"]], how="left")

# 把 NQ_0845/_1500 轉成 % (原始是點數)
df["nq_0845_pct"] = df["nq_0845"] / 18000 * 100
df["nq_1500_pct"] = df["nq_1500"] / 18000 * 100
df["es_0845_pct"] = df["es_0845"] / 4500 * 100
df["es_1500_pct"] = df["es_1500"] / 4500 * 100

# === 相關性分析 ===
print()
print("=" * 80)
print("【各因子 vs gap_pct 相關係數】(Pearson)")
print("=" * 80)
factors = ["nq_0845_pct", "nq_1500_pct", "es_0845_pct", "es_1500_pct",
           "kospi_0845", "nkx_0845", "ndx_ret", "spx_ret", "nkx_ret", "kospi_ret"]
corr_results = []
for f in factors:
    sub = df[[f, "gap_pct"]].dropna()
    if len(sub) < 50: continue
    c = sub[f].corr(sub["gap_pct"])
    corr_results.append((f, c, len(sub)))
corr_results.sort(key=lambda x: abs(x[1]), reverse=True)
print(f"{'factor':<18s} {'corr':>8s} {'n':>5s}")
for f, c, n in corr_results:
    print(f"{f:<18s} {c:>+8.3f} {n:>5d}")

# === 大 gap 日子的因子表現 ===
print()
print("=" * 80)
print("【|gap| > 0.50% 大跳空日的因子特性】")
print("=" * 80)
big = df[df["gap_pct"].abs() > 0.50].copy()
big_up = big[big["gap_pct"] > 0]
big_dn = big[big["gap_pct"] < 0]
print(f"Gap UP (>+0.50%): n={len(big_up)}  Gap DOWN (<-0.50%): n={len(big_dn)}")
print(f"\n{'factor':<18s} {'gap_up 中位':>12s} {'gap_dn 中位':>12s} {'方向一致率(up)':>15s} {'方向一致率(dn)':>15s}")
for f in ["nq_0845_pct", "es_0845_pct", "kospi_0845", "nkx_0845",
          "ndx_ret", "spx_ret", "nkx_ret", "kospi_ret"]:
    up_med = big_up[f].median()
    dn_med = big_dn[f].median()
    up_align = (big_up[f] > 0).mean() * 100 if not big_up[f].isna().all() else 0
    dn_align = (big_dn[f] < 0).mean() * 100 if not big_dn[f].isna().all() else 0
    print(f"{f:<18s} {up_med:>+12.3f} {dn_med:>+12.3f} "
          f"{up_align:>14.1f}% {dn_align:>14.1f}%")

# === 06/24 那種 |NQ|<0.5% 但 gap 很大的情境 ===
print()
print("=" * 80)
print("【NQ 訊號偏弱 (|nq_0845_pct|<0.5%) 但 |gap|>0.50% 的日子】")
print("=" * 80)
miss = df[(df["nq_0845_pct"].abs() < 0.5) & (df["gap_pct"].abs() > 0.50)].copy()
print(f"n = {len(miss)}  (= 純 NQ 規則被漏掉的大 gap 日子)")
print(f"當中 gap up: {(miss['gap_pct']>0).sum()}, gap down: {(miss['gap_pct']<0).sum()}")
print(f"\n{'factor':<18s} {'corr 與 gap_pct':>15s}")
for f in factors:
    sub = miss[[f, "gap_pct"]].dropna()
    if len(sub) < 20: continue
    c = sub[f].corr(sub["gap_pct"])
    print(f"{f:<18s} {c:>+15.3f}")

# === Composite signal: 多因子組合 ===
print()
print("=" * 80)
print("【複合 signal 建構: ES + KOSPI + NKX 投票】")
print("=" * 80)
# 把每個因子分 +1 (>+0.1)/ -1 (<-0.1)/ 0 (其他) 然後加總
def sign_strong(x, eps=0.1):
    if pd.isna(x): return 0
    if x > eps: return 1
    if x < -eps: return -1
    return 0

df["vote_es"] = df["es_0845_pct"].apply(lambda x: sign_strong(x, 0.05))
df["vote_kospi"] = df["kospi_0845"].apply(lambda x: 1 if x > 5 else (-1 if x < -5 else 0))
df["vote_nkx"] = df["nkx_0845"].apply(lambda x: 1 if x > 50 else (-1 if x < -50 else 0))
df["vote_ndx_prev"] = df["ndx_ret"].apply(lambda x: sign_strong(x, 0.3))
df["vote_composite"] = df[["vote_es", "vote_kospi", "vote_nkx", "vote_ndx_prev"]].sum(axis=1)

# 看 composite vote 跟 gap_pct 的關係
print(f"\n{'vote_total':<12s} {'n':>5s} {'gap_pct mean':>14s} {'gap_pct std':>13s} {'%(同向)':>10s}")
for v in sorted(df["vote_composite"].unique()):
    sub = df[df["vote_composite"] == v]
    if len(sub) < 10: continue
    mean_g = sub["gap_pct"].mean()
    std_g = sub["gap_pct"].std()
    same_dir = ((sub["gap_pct"] > 0) == (v > 0)).mean() * 100 if v != 0 else 0
    print(f"{v:<+12d} {len(sub):>5d} {mean_g:>+14.3f} {std_g:>13.3f} {same_dir:>9.1f}%")

# === 跟 NQ 純訊號比較 ===
print()
print("=" * 80)
print("【NQ 純訊號 (|nq|>0.5) vs 複合 vote (|vote|>=3) 對 gap 預測能力】")
print("=" * 80)
nq_sig = df[df["nq_0845_pct"].abs() > 0.5].copy()
vote_sig = df[df["vote_composite"].abs() >= 3].copy()

def metric(sub, sig_col):
    if len(sub) == 0: return None
    # sig vs gap_pct 同向?
    sign_pred = sub[sig_col].apply(lambda x: 1 if x > 0 else -1)
    sign_actual = sub["gap_pct"].apply(lambda x: 1 if x > 0 else -1)
    hit = (sign_pred == sign_actual).mean() * 100
    avg_abs_gap = sub["gap_pct"].abs().mean()
    return len(sub), hit, avg_abs_gap

n1, h1, a1 = metric(nq_sig, "nq_0845_pct")
print(f"NQ 純訊號  |nq|>0.5    n={n1:4d}  方向命中={h1:.1f}%  平均|gap|={a1:.3f}%")
n2, h2, a2 = metric(vote_sig, "vote_composite")
print(f"複合 vote |vote|>=3  n={n2:4d}  方向命中={h2:.1f}%  平均|gap|={a2:.3f}%")

# 兩個都符合 + 兩個都不符合
both = df[(df["nq_0845_pct"].abs() > 0.5) & (df["vote_composite"].abs() >= 3) &
          (np.sign(df["nq_0845_pct"]) == np.sign(df["vote_composite"]))]
print(f"\n兩個訊號同向且都過門檻  n={len(both):4d}  ", end="")
if len(both) > 0:
    sign_pred = both["nq_0845_pct"].apply(lambda x: 1 if x > 0 else -1)
    sign_actual = both["gap_pct"].apply(lambda x: 1 if x > 0 else -1)
    print(f"方向命中={((sign_pred == sign_actual).mean()*100):.1f}%  平均|gap|={both['gap_pct'].abs().mean():.3f}%")

# 06/24 案例分析 — NQ 弱但 vote 是否強?
print()
print("=" * 80)
print("【06/24 style: NQ 偏弱 (<0.5%) 但 vote 強 (|vote|>=3) → 可賺到的訊號】")
print("=" * 80)
catch = df[(df["nq_0845_pct"].abs() < 0.5) & (df["vote_composite"].abs() >= 3)].copy()
print(f"n = {len(catch)}")
if len(catch) > 0:
    sign_pred = catch["vote_composite"].apply(lambda x: 1 if x > 0 else -1)
    sign_actual = catch["gap_pct"].apply(lambda x: 1 if x > 0 else -1)
    print(f"vote 方向命中 gap 方向 = {((sign_pred == sign_actual).mean()*100):.1f}%")
    print(f"平均 |gap| = {catch['gap_pct'].abs().mean():.3f}%")
    print(f"gap_pct 平均 = {catch['gap_pct'].mean():+.3f}%")
    big_catch = catch[catch["gap_pct"].abs() > 0.5]
    print(f"當中 |gap|>0.5% 的 n = {len(big_catch)} ({len(big_catch)/max(len(catch),1)*100:.1f}%)")

# 存檔
df.to_csv(BASE / "gap_factor_data.csv", encoding="utf-8-sig")
print(f"\n資料 → {BASE / 'gap_factor_data.csv'}")
