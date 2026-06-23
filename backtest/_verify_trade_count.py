"""驗證 TV 78 pairs vs 實盤 171 actions 怎麼對齊 + 找可能的手動單"""
import pandas as pd
from pathlib import Path

BASE = Path(r"D:/stock/tmf-bot/backtest")

# TV
df = pd.read_csv(r"D:/stock/tmf-bot/tv/result/V38.0519_v26_Session_TAIFEX_MXF1!_2026-06-23.csv",
                 encoding="utf-8-sig")
df.columns = [c.strip() for c in df.columns]
df["dt"] = pd.to_datetime(df["日期和時間"])
tv = df[(df["dt"] >= "2026-05-19") & (df["dt"] <= "2026-06-06")].copy()

# 看 TV 在這期間每天有幾個 "actions" (entry + exit 都算)
tv["date"] = tv["dt"].dt.date
tv["action_type"] = tv["類型"]  # 進場/出場
print("=" * 90)
print(f"【TV 在 05/19~06/06 期間】 共 {len(tv)} rows = {len(tv)//2} pairs")
print("=" * 90)
print(f"  進場類: {tv['類型'].str.contains('進場').sum()} 筆")
print(f"  出場類: {tv['類型'].str.contains('出場').sum()} 筆")
print()
print("  訊號類型分佈:")
print(tv["訊號"].value_counts().to_string())

# 實盤
trd = pd.read_csv(BASE / "_v38_trades.csv")
trd.columns = [c.strip().lstrip("﻿") for c in trd.columns]
trd["datetime"] = pd.to_datetime(trd["datetime"])
trd["date"] = trd["datetime"].dt.date

live = trd[(trd["date"] >= pd.Timestamp("2026-05-19").date()) &
           (trd["date"] <= pd.Timestamp("2026-06-06").date())].copy()

print()
print("=" * 90)
print(f"【實盤 trade_records 在 05/19~06/06】 共 {len(live)} actions (每 row = 1 BUY 或 SELL)")
print("=" * 90)
print(f"  BUY: {(live['action']=='BUY').sum()}")
print(f"  SELL: {(live['action']=='SELL').sum()}")

# 配對成 round-trips（簡單：position 從 0 回到 0 算一個 round-trip）
live = live.sort_values("datetime").reset_index(drop=True)
trips = 0
last_pos = 0
for _, r in live.iterrows():
    pb, tp = r["pos_before"], r["target_pos"]
    if last_pos == 0 and pb == 0 and tp != 0:
        trips += 1   # 新開倉
    last_pos = tp
print(f"  從 pos=0 重新開倉次數 = {trips} (= round-trips)")
print(f"  → 平均每 round-trip 動作: {len(live) / max(trips, 1):.1f} actions")
print()

# 按 ticker 拆（看是否所有都標 MXF1!）
print(f"  Ticker 分佈:")
print(live["ticker"].value_counts().to_string())
print()
print(f"  Note 欄是否有東西？{(live['note'].fillna('').str.len() > 0).sum()} 筆有 note")
print(f"  Status 分佈: {live['order_status'].value_counts().to_dict()}")

# 看 contract / delivery_month
print(f"  Contract 分佈: {live['contract'].value_counts().to_dict()}")

# === 真正的對比：用「Cmd / Exit」筆數 (一進一出視為一單) ===
print()
print("=" * 90)
print("【對齊：TV Cmd (進場) vs 實盤 pos=0→非 0 (新開倉)】")
print("=" * 90)
tv_new = tv[tv["訊號"].isin(["L_Cmd", "S_Cmd"])]
print(f"  TV 新開倉 (L_Cmd + S_Cmd): {len(tv_new)} 筆")

live_new = live[(live["pos_before"] == 0) & (live["target_pos"] != 0)]
print(f"  實盤新開倉 (pos=0 → 非0): {len(live_new)} 筆")
print()
print(f"  TV 加碼 (L_Add + S_Add): {len(tv[tv['訊號'].isin(['L_Add', 'S_Add'])])} 筆")
live_add = live[((live['pos_before'] > 0) & (live['target_pos'] > live['pos_before'])) |
                ((live['pos_before'] < 0) & (live['target_pos'] < live['pos_before']))]
print(f"  實盤加碼: {len(live_add)} 筆")
print()
print(f"  TV 平倉 (L_Exit*+S_Exit*): {len(tv[tv['訊號'].astype(str).str.contains('Exit')])} 筆")
live_exit = live[(live['pos_before'] != 0) & (live['target_pos'] == 0)]
print(f"  實盤平倉 (pos!=0 → 0): {len(live_exit)} 筆")
print()
print(f"  TV 部分平倉 (L_Exit_Add+S_Exit_Add): "
      f"{len(tv[tv['訊號'].isin(['L_Exit_Add', 'S_Exit_Add'])])} 筆")
live_partial_exit = live[((live['pos_before'] > 0) & (live['target_pos'] < live['pos_before']) & (live['target_pos'] > 0)) |
                          ((live['pos_before'] < 0) & (live['target_pos'] > live['pos_before']) & (live['target_pos'] < 0))]
print(f"  實盤部分平倉: {len(live_partial_exit)} 筆")

# === 找可能手動單：時間排序看是否有「離 V38 邏輯異常」的單 ===
print()
print("=" * 90)
print("【找可能的手動單 — 看時間 cluster / 訊號邏輯】")
print("=" * 90)
# 簡單啟發：V38 通常在訊號出現時下單，連續快速下單 (< 5 秒間隔) 可能是
# 同一訊號的 leg。但如果一筆單之後 > 5 分鐘才有下一個動作，可能是新訊號
live["delta_min"] = live["datetime"].diff().dt.total_seconds() / 60
print(f"  動作間距分佈:")
print(f"    < 1 min: {(live['delta_min'] < 1).sum()} 筆 (同訊號 leg)")
print(f"    1-5 min: {((live['delta_min'] >= 1) & (live['delta_min'] < 5)).sum()} 筆")
print(f"    5-30 min: {((live['delta_min'] >= 5) & (live['delta_min'] < 30)).sum()} 筆")
print(f"    > 30 min: {(live['delta_min'] >= 30).sum()} 筆 (新事件)")

# 嘗試以「signal_price 與最近 V38 訊號是否能匹配」識別
# 比較笨：列出所有 trade 給用戶肉眼識別
print()
print("【實盤 05/19~06/06 全部 trades — 你可以肉眼比對哪些不在 TV 上】")
print("(用 datetime + signal_price 跟 TV CSV 對照)")
for _, r in live.head(20).iterrows():
    print(f"  {r['datetime']}  {r['action']:<4s}  q={r['quantity']}  "
          f"sig={r['signal_price']:.0f}  fill={r['fill_price']:.0f}  "
          f"pos {r['pos_before']:+d}→{r['target_pos']:+d}")
print(f"  ... (還有 {len(live)-20} 筆，存到 _live_period_trades.csv)")
live.to_csv(BASE / "_live_period_trades.csv", index=False, encoding="utf-8-sig")

# 同樣存 TV
tv.to_csv(BASE / "_tv_period_trades.csv", index=False, encoding="utf-8-sig")
print(f"\n→ _live_period_trades.csv ({len(live)} rows)")
print(f"→ _tv_period_trades.csv  ({len(tv)} rows = {len(tv)//2} pairs)")
