"""V38 v26 實盤 5 週嚴格績效分析（for 評估是否升級 MXF）"""
import pandas as pd
import numpy as np

bal = pd.read_csv("D:/stock/tmf-bot/backtest/_v38_balance.csv")
trd = pd.read_csv("D:/stock/tmf-bot/backtest/_v38_trades.csv")
bal.columns = [c.strip().lstrip("﻿") for c in bal.columns]
trd.columns = [c.strip().lstrip("﻿") for c in trd.columns]

bal["datetime"] = pd.to_datetime(bal["datetime"])
bal["date"] = bal["datetime"].dt.date
trd["datetime"] = pd.to_datetime(trd["datetime"])
trd["date"] = trd["datetime"].dt.date

# === 帳戶曲線 (equity) ===
print("=" * 80)
print("【1. 帳戶曲線】")
print("=" * 80)
# 取每天最後一筆快照
daily = bal.sort_values("datetime").groupby("date").last()[["equity", "today_balance", "future_settle_profitloss"]]
print(f"  期間: {daily.index[0]} ~ {daily.index[-1]} ({(daily.index[-1] - daily.index[0]).days} 天)")
print(f"  起始 equity: {daily['equity'].iloc[0]:,.0f}")
print(f"  目前 equity: {daily['equity'].iloc[-1]:,.0f}")
print(f"  Peak equity: {daily['equity'].max():,.0f} ({daily['equity'].idxmax()})")
print(f"  Trough equity (peak 後): ", end="")
peak_idx = daily['equity'].idxmax()
after_peak = daily.loc[peak_idx:]
print(f"{after_peak['equity'].min():,.0f} ({after_peak['equity'].idxmin()})")

# Daily PnL series
print()
print("【日報 (5 週)】")
print(f"  {'date':<12s} {'equity':>10s} {'day_PnL':>9s} {'running %':>10s} {'DD from peak':>15s}")
running_peak = daily["equity"].iloc[0]
for d, row in daily.iterrows():
    eq = row["equity"]
    if eq > running_peak: running_peak = eq
    dd = eq - running_peak
    dd_pct = dd / running_peak * 100
    print(f"  {str(d):<12s} {eq:>10,.0f} {row['equity'] - daily['equity'].shift(1).loc[d] if d != daily.index[0] else 0:>+9,.0f} "
          f"{(eq/daily['equity'].iloc[0]-1)*100:>+10.1f}% {dd_pct:>+15.2f}%")

# === Max Drawdown ===
print()
print("=" * 80)
print("【2. MaxDD (intraday + daily)】")
print("=" * 80)
peak = bal["equity"].cummax()
dd = bal["equity"] - peak
dd_pct = dd / peak * 100
print(f"  MaxDD: {dd.min():,.0f} ({dd_pct.min():.2f}%)")
print(f"  發生於: {bal.loc[dd.idxmin(), 'datetime']}")
print(f"  當時 equity: {bal.loc[dd.idxmin(), 'equity']:,.0f}")
print(f"  Peak before that: {peak.loc[dd.idxmin()]:,.0f}")

# === Trade stats ===
print()
print("=" * 80)
print("【3. 交易筆數 / 行為】")
print("=" * 80)
print(f"  總成交筆數: {len(trd)}")
print(f"  Buy / Sell: {(trd['action']=='BUY').sum()} / {(trd['action']=='SELL').sum()}")
print(f"  平均每天: {len(trd) / (daily.index[-1] - daily.index[0]).days:.1f} 筆")

# 持倉變化（pos_before → target_pos）
print()
print("【部位範圍】")
print(f"  曾持有最大多單: +{trd['target_pos'].max()}  /  最大空單: {trd['target_pos'].min()}")
print(f"  正佔比: {(trd['target_pos'] > 0).mean()*100:.0f}% / 負佔比: {(trd['target_pos'] < 0).mean()*100:.0f}%")

# 滑價統計
print()
print("【滑價】")
print(f"  平均滑價: {trd['slippage_pts'].mean():.1f} 點 / {trd['slippage_twd'].mean():.1f} 元")
print(f"  最大滑價: {trd['slippage_pts'].abs().max():.0f} 點")

# === FIFO 配對 PnL ===
print()
print("=" * 80)
print("【4. FIFO 配對 PnL (粗算 — 順序簡化版)】")
print("=" * 80)
# 簡單 FIFO: 每天的 trade list, 用 queue 配對
from collections import deque
queue_long = deque()   # (entry_price, qty)
queue_short = deque()
realized = []
for _, t in trd.iterrows():
    p = t["fill_price"]; q = t["quantity"]
    if t["action"] == "BUY":
        # 先平空，剩下加多
        rem = q
        while rem > 0 and queue_short:
            sp, sq = queue_short[0]
            use = min(rem, sq)
            realized.append({
                "exit_date": t["date"], "side": "S->L close", "entry": sp, "exit": p,
                "qty": use, "pnl_pts": sp - p,
                "pnl_twd": (sp - p) * use * 10  # TMF 1 點 NT$10
            })
            if sq > use: queue_short[0] = (sp, sq - use)
            else: queue_short.popleft()
            rem -= use
        if rem > 0: queue_long.append((p, rem))
    else:  # SELL
        rem = q
        while rem > 0 and queue_long:
            lp, lq = queue_long[0]
            use = min(rem, lq)
            realized.append({
                "exit_date": t["date"], "side": "L->S close", "entry": lp, "exit": p,
                "qty": use, "pnl_pts": p - lp,
                "pnl_twd": (p - lp) * use * 10
            })
            if lq > use: queue_long[0] = (lp, lq - use)
            else: queue_long.popleft()
            rem -= use
        if rem > 0: queue_short.append((p, rem))

r = pd.DataFrame(realized)
print(f"  共 {len(r)} round-trips")
print(f"  總 realized PnL: NT${r['pnl_twd'].sum():,.0f}")
print(f"  Win Rate: {(r['pnl_twd']>0).mean()*100:.1f}%  ({(r['pnl_twd']>0).sum()} W / {(r['pnl_twd']<=0).sum()} L)")
wins = r[r['pnl_twd'] > 0]; losses = r[r['pnl_twd'] <= 0]
print(f"  均勝: {wins['pnl_twd'].mean():,.0f} / 均敗: {losses['pnl_twd'].mean():,.0f}")
pf = wins['pnl_twd'].sum() / abs(losses['pnl_twd'].sum()) if losses['pnl_twd'].sum() != 0 else 999
print(f"  Profit Factor: {pf:.2f}")
print(f"  最大單筆獲利: NT${r['pnl_twd'].max():,.0f}")
print(f"  最大單筆損失: NT${r['pnl_twd'].min():,.0f}")

# 按週分析
r["exit_date"] = pd.to_datetime(r["exit_date"])
r["week"] = r["exit_date"].dt.strftime("%Y-W%U")
print()
print("【按週 PnL】")
weekly = r.groupby("week")["pnl_twd"].agg(["sum", "count"])
weekly.columns = ["週PnL", "筆數"]
for w, row in weekly.iterrows():
    print(f"  {w}: {row['筆數']:>3.0f} 筆  PnL NT$ {row['週PnL']:>+12,.0f}")

# === MXF 換算 5 倍 ===
print()
print("=" * 80)
print("【5. 假設換 MXF (5x 槓桿) — 同樣行為下的損益】")
print("=" * 80)
print(f"  TMF 實際 realized: NT${r['pnl_twd'].sum():,.0f}")
print(f"  MXF 換算 (×5): NT${r['pnl_twd'].sum() * 5:,.0f}")
print(f"  TMF 單日最大 DD: NT${dd.min():,.0f} ({dd_pct.min():.2f}%)")
print(f"  MXF 換算單日最大 DD: NT${dd.min() * 5:,.0f} (絕對金額) -> 帳戶若維持原規模: {dd_pct.min()*5:.1f}% (爆倉風險)")
print()
print(f"  最大單筆 TMF 損失: NT${r['pnl_twd'].min():,.0f}")
print(f"  最大單筆 MXF 換算: NT${r['pnl_twd'].min() * 5:,.0f}")

# === 評估 MXF 升級 ===
print()
print("=" * 80)
print("【6. 升級 MXF 的具體評估】")
print("=" * 80)
print(f"  TMF 1 口保證金: ~NT$11K  /  MXF 1 口保證金: ~NT$45K (4倍)")
print(f"  V38 最大同時持倉: {trd['target_pos'].abs().max()} 口")
print(f"    TMF 全部進場保證金需求: ~NT${trd['target_pos'].abs().max() * 11000:,.0f}")
print(f"    MXF 全部進場保證金需求: ~NT${trd['target_pos'].abs().max() * 45000:,.0f}")
print(f"  目前帳戶 equity: NT${daily['equity'].iloc[-1]:,.0f}")
print(f"  MXF 所需保證金/帳戶: {trd['target_pos'].abs().max() * 45000 / daily['equity'].iloc[-1] * 100:.0f}%")
