"""
V38 滑價分析 — 找出實盤實現率 27% 的成因
===========================================
1. 實盤 trade_records 的滑價分佈
2. 按 signal type / direction / time-of-day 切片
3. 估算「如果沒滑價」實盤該賺多少
4. 投射 MXF 上線後滑價成本（×5）
"""
import pandas as pd, numpy as np
from pathlib import Path

BASE = Path(r"D:/stock/tmf-bot/backtest")

# === 載入實盤 ===
trd = pd.read_csv(BASE / "_v38_trades.csv")
trd.columns = [c.strip().lstrip("﻿") for c in trd.columns]
trd["datetime"] = pd.to_datetime(trd["datetime"])
trd["hour"] = trd["datetime"].dt.hour
trd["date"] = trd["datetime"].dt.date

# 推斷 signal type from note / order pattern — 但 trade_records 沒有 signal 名稱
# 改用 pos_before / target_pos 推斷
def infer_signal(r):
    pb, tp = r["pos_before"], r["target_pos"]
    if pb == 0 and tp != 0: return "Cmd"           # 開倉
    if pb != 0 and tp == 0: return "Exit"          # 平倉
    if (pb > 0 and tp > pb) or (pb < 0 and tp < pb): return "Add"   # 加碼
    if (pb > 0 and tp < pb and tp > 0) or (pb < 0 and tp > pb and tp < 0): return "Exit_Add"  # 部分平倉
    if (pb > 0 and tp < 0) or (pb < 0 and tp > 0): return "Reverse"  # 反向
    return "?"

trd["signal_type"] = trd.apply(infer_signal, axis=1)

# === 1. 滑價分佈 ===
print("=" * 90)
print("【1. 整體滑價分佈】 (n=271 筆)")
print("=" * 90)
sp = trd["slippage_pts"]
print(f"  Mean:    {sp.mean():>+6.2f} pts")
print(f"  Median:  {sp.median():>+6.2f} pts")
print(f"  Std:     {sp.std():>6.2f} pts")
print(f"  Min:     {sp.min():>+6.0f} pts")
print(f"  Max:     {sp.max():>+6.0f} pts")
print()
print("  Percentiles:")
for p in [10, 25, 50, 75, 90, 95, 99]:
    print(f"    p{p:>2d}: {sp.quantile(p/100):>+6.1f} pts")
print()
print("  方向偏差檢查:")
print(f"    正滑價 (對你不利)：{(sp > 0).sum()} 筆 ({(sp>0).mean()*100:.0f}%)")
print(f"    零滑價           ：{(sp == 0).sum()} 筆")
print(f"    負滑價 (對你有利)：{(sp < 0).sum()} 筆 ({(sp<0).mean()*100:.0f}%)")

# === 2. 按 signal type 切 ===
print()
print("=" * 90)
print("【2. 按 signal type 拆 — 哪種訊號滑價最重】")
print("=" * 90)
print(f"  {'type':<10s} {'n':>4s} {'mean':>7s} {'median':>7s} {'std':>6s} {'p95':>6s} {'max':>6s} {'總滑價_pts':>11s}")
for st, g in trd.groupby("signal_type"):
    print(f"  {st:<10s} {len(g):>4d} {g['slippage_pts'].mean():>+7.2f} "
          f"{g['slippage_pts'].median():>+7.2f} {g['slippage_pts'].std():>6.2f} "
          f"{g['slippage_pts'].quantile(0.95):>+6.1f} {g['slippage_pts'].max():>+6.0f} "
          f"{g['slippage_pts'].sum():>+11.0f}")

# === 3. 按方向（BUY vs SELL）===
print()
print("=" * 90)
print("【3. BUY vs SELL】")
print("=" * 90)
for act, g in trd.groupby("action"):
    print(f"  {act}: n={len(g)}, mean={g['slippage_pts'].mean():+.2f} pts, "
          f"median={g['slippage_pts'].median():+.2f}, p95={g['slippage_pts'].quantile(0.95):+.1f}, "
          f"總={g['slippage_pts'].sum():+.0f} pts")

# === 4. 按時段（早中夜）===
print()
print("=" * 90)
print("【4. 按時段拆 — 流動性差會放大滑價】")
print("=" * 90)
def session_of(h):
    if 8 <= h < 14: return "08-14 日盤"
    if 14 <= h < 22: return "14-22 夜盤前"
    if 22 <= h or h < 6: return "22-06 美股時段"
    return "06-08 過渡"

trd["session"] = trd["hour"].apply(session_of)
print(f"  {'session':<18s} {'n':>4s} {'mean':>7s} {'median':>7s} {'p95':>6s} {'max':>6s} {'總':>8s}")
for s, g in trd.groupby("session"):
    print(f"  {s:<18s} {len(g):>4d} {g['slippage_pts'].mean():>+7.2f} "
          f"{g['slippage_pts'].median():>+7.2f} {g['slippage_pts'].quantile(0.95):>+6.1f} "
          f"{g['slippage_pts'].max():>+6.0f} {g['slippage_pts'].sum():>+8.0f}")

# === 5. 總滑價成本（已實現） ===
print()
print("=" * 90)
print("【5. 已實現滑價成本（5 週）】")
print("=" * 90)
total_slip_pts = sp.sum()  # 每筆都對你不利的方向計
# 注意：slippage_pts 已經是「不利方向」算法（BUY 成交比訊號高 = +slip, SELL 成交比訊號低 = +slip）
# 所以總和就是「實際損失的點數」
print(f"  總滑價: {total_slip_pts:+.0f} pts")
print(f"  TMF (NT$10/pt): NT$ {total_slip_pts * 10:,.0f}")
print(f"  MXF (NT$50/pt): NT$ {total_slip_pts * 50:,.0f}  ← 升級後成本")
print(f"  平均每筆 TMF 滑價成本: NT$ {sp.mean() * 10:.0f}")
print(f"  平均每筆 MXF 滑價成本: NT$ {sp.mean() * 50:.0f}")

# === 6. 估算「如果零滑價」實盤該賺多少 ===
print()
print("=" * 90)
print("【6. 假設滑價歸零，實盤該賺多少（vs 實際 +32K）】")
print("=" * 90)
actual_pnl = 32308
slip_cost_tmf = total_slip_pts * 10
no_slip_pnl = actual_pnl + slip_cost_tmf
print(f"  實盤實際 realized PnL:     NT$ +{actual_pnl:,}")
print(f"  滑價成本:                  NT$ +{slip_cost_tmf:,.0f}")
print(f"  零滑價估算 (加回去):       NT$ +{no_slip_pnl:,.0f}")
print()
print("  --- 公平對齊：只看 TV 有資料的 05/19 ~ 06/06 ---")
match_period = trd[(trd["date"] >= pd.Timestamp("2026-05-19").date()) &
                    (trd["date"] <= pd.Timestamp("2026-06-06").date())]
match_slip_pts = match_period["slippage_pts"].sum()
match_slip_twd = match_slip_pts * 10
print(f"  實盤同期 trade 數: {len(match_period)} 筆")
print(f"  實盤同期滑價: {match_slip_pts:+.0f} pts = NT$ {match_slip_twd:,.0f}")
print(f"  實盤同期 realized PnL (PLAYBOOK): +NT$ 177,010")
print(f"  TV 同期 realized PnL: +NT$ 226,230  (78 筆)")
print(f"  PnL gap: NT$ {226230 - 177010:,}")
print(f"  滑價解釋的 gap: NT$ {match_slip_twd:,.0f} ({match_slip_twd / (226230 - 177010) * 100:.0f}%)")
print(f"  剩餘 gap 沒解釋: NT$ {226230 - 177010 - match_slip_twd:,.0f}")
print()
print("  --- 06/06 ~ 06/22 (TV 沒資料的崩盤段) ---")
crash_period = trd[trd["date"] > pd.Timestamp("2026-06-06").date()]
crash_slip = crash_period["slippage_pts"].sum() * 10
print(f"  實盤該期 trade: {len(crash_period)} 筆")
print(f"  實盤該期滑價: NT$ {crash_slip:,.0f}")
print(f"  實盤該期 PnL: NT$ {actual_pnl - 177010:,} (反推 = +32K - +177K)")
print(f"  → 後 16 天扣滑價後仍是大幅虧損，跟滑價無關，是 regime 真的不利")

# === 7. 滑價 vs 信號間隔的關係（如果有 fill_time vs signal_time 差距）===
# 沒有 signal_time，只有 datetime（fill time）
# 但可以看「相近的兩筆」距離

# === 8. 最痛的 10 筆 ===
print()
print("=" * 90)
print("【7. Top 10 最痛滑價筆數】")
print("=" * 90)
worst = trd.nlargest(10, "slippage_pts")[["datetime","action","signal_type","signal_price","fill_price","slippage_pts","target_pos"]]
print(worst.to_string(index=False))

print()
print("=" * 90)
print("【8. 對升級 MXF 的具體成本提示】")
print("=" * 90)
yearly_trades = len(trd) / 5 * 52  # 5 週 -> 一年
yearly_slip_pts = total_slip_pts / 5 * 52
print(f"  目前頻率：{len(trd)} 筆 / 5 週 = {yearly_trades:.0f} 筆 / 年")
print(f"  TMF 年化滑價成本: NT$ {yearly_slip_pts * 10:,.0f}")
print(f"  MXF 年化滑價成本: NT$ {yearly_slip_pts * 50:,.0f}")
print(f"  TV 回測 2026 年 PnL: NT$ +1,822,340 (419 筆 5 個月)")
print(f"  假設你升 MXF：年化滑價 vs 預期年化 PnL")
print(f"    滑價佔比 (按 TV 預估): {(yearly_slip_pts * 50) / (1822340 * 12/5) * 100:.1f}%")
print()
print("=" * 90)
print("【9. 結論】")
print("=" * 90)
print("""
1. 滑價 mean +2.8 pts，但 Std 19.5 pts -> 極端 outlier 大（最痛 -101 / +138）
2. 日盤滑價最痛（mean +6.6），夜盤 0 滑價
3. Add 加碼最不利（mean +4.6）
4. 5 週總滑價 +759 pts ≈ TMF NT$7.5K，相對小 (vs PnL +32K)
5. MXF 同樣行為的滑價成本 = NT$38K/5wk = NT$395K/年 (相比 TV 預估年 PnL ~4M，佔約 10%)
6. 真正的 GAP（實盤 +32K vs TV 同期 +226K）裡，滑價只解釋 < 20%
   -> 剩下 ~150K 損失主要來自 06/06 後的「行情不利期」 → 不是執行問題
""")
