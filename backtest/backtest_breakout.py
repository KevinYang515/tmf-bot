"""
TMF 波動突破策略回測（Cloud Shell 版）
讀取 mxf_1min.csv，不需要 Shioaji，不影響交易 bot

用法：
  1. 先在 VM 上跑 fetch_kbars.py 產生 mxf_1min.csv
  2. SCP 到 Cloud Shell：
     gcloud compute scp instance-20260515-172729:~/stock/backtest/mxf_1min.csv \
       ~/stock/backtest/mxf_1min.csv --zone=us-west1-b --tunnel-through-iap
  3. 在 Cloud Shell 跑本腳本：python backtest/backtest_breakout.py
"""

import os
import pandas as pd
import numpy as np
from pathlib import Path
from itertools import product

# ── 設定 ──────────────────────────────────────────────
DATA_PATH      = Path(__file__).parent / "mxf_1min.csv"
POINT_VAL      = 10    # TMF 每點 10 元
COMMISSION_PTS = 4.0   # 手續費 round-trip（NT$40 ÷ NT$10/點 = 4點，永豐實際：手續費NT$24+期交稅NT$16）

TRIGGER_TIMES = {
    "期貨開盤": "08:45",
    "現貨開盤": "09:00",
    "現貨收盤": "13:30",
    "期貨日盤收": "13:45",
}

OFFSETS   = [5, 10, 15, 20]
TARGETS   = [10, 20, 30, 40, 60, 80, 100]
STOPS     = [5, 10, 15, 20, 30, 40, 50]
TIME_LIMS = [5, 10, 15, 30, 60]
# ─────────────────────────────────────────────────────


def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)
    df["ts"]   = pd.to_datetime(df["ts"])
    df["date"] = df["ts"].dt.date
    df["time"] = df["ts"].dt.strftime("%H:%M")
    return df.sort_values("ts").reset_index(drop=True)


def simulate_trade(df_day: pd.DataFrame, trigger_time: str,
                   offset: int, target: int, stop: int, time_limit: int):
    snap = df_day[df_day["time"] == trigger_time]
    if snap.empty:
        return None

    snap_idx   = snap.index[0]
    snap_open  = float(snap.iloc[0]["Open"])

    buy_entry  = snap_open + offset
    sell_entry = snap_open - offset
    buy_tp     = buy_entry  + target
    buy_sl     = buy_entry  - stop
    sell_tp    = sell_entry - target
    sell_sl    = sell_entry + stop

    window    = df_day.loc[snap_idx: snap_idx + time_limit - 1]
    direction = None
    entry_price = None

    for _, bar in window.iterrows():
        hi = float(bar["High"])
        lo = float(bar["Low"])

        if direction is None:
            if hi >= buy_entry:
                direction, entry_price = "LONG", buy_entry
            elif lo <= sell_entry:
                direction, entry_price = "SHORT", sell_entry

        if direction == "LONG":
            if lo <= buy_sl:
                net = -stop - COMMISSION_PTS
                return {"direction": "LONG", "result": "STOP",
                        "pnl_pts": net, "pnl_twd": net * POINT_VAL}
            if hi >= buy_tp:
                net = target - COMMISSION_PTS
                return {"direction": "LONG", "result": "TP",
                        "pnl_pts": net, "pnl_twd": net * POINT_VAL}

        elif direction == "SHORT":
            if hi >= sell_sl:
                net = -stop - COMMISSION_PTS
                return {"direction": "SHORT", "result": "STOP",
                        "pnl_pts": net, "pnl_twd": net * POINT_VAL}
            if lo <= sell_tp:
                net = target - COMMISSION_PTS
                return {"direction": "SHORT", "result": "TP",
                        "pnl_pts": net, "pnl_twd": net * POINT_VAL}

    if direction is not None:
        last_close = float(window.iloc[-1]["Close"])
        raw = (last_close - entry_price) if direction == "LONG" else (entry_price - last_close)
        net = round(raw - COMMISSION_PTS, 1)
        return {"direction": direction, "result": "TIMEOUT",
                "pnl_pts": net, "pnl_twd": round(net * POINT_VAL, 0)}
    return None


def run_backtest(df, trigger_name, trigger_time, offset, target, stop, time_limit):
    trades = []
    for date, day_df in df.groupby("date"):
        day_df = day_df.reset_index(drop=True)
        r = simulate_trade(day_df, trigger_time, offset, target, stop, time_limit)
        if r:
            r["date"]    = str(date)
            r["month"]   = str(date)[:7]
            r["trigger"] = trigger_name
            trades.append(r)

    if not trades:
        return {}

    tdf   = pd.DataFrame(trades)
    wins  = (tdf["pnl_pts"] > 0).sum()
    total = len(tdf)
    total_pnl = tdf["pnl_twd"].sum()
    avg_pnl   = tdf["pnl_twd"].mean()
    std       = tdf["pnl_pts"].std()
    sharpe    = tdf["pnl_pts"].mean() / std * np.sqrt(252) if std > 0 else 0

    return {
        "trigger":    trigger_name,
        "offset":     offset,
        "target":     target,
        "stop":       stop,
        "time_limit": time_limit,
        "trades":     total,
        "win_rate":   round(wins / total * 100, 1),
        "total_pnl":  int(total_pnl),
        "avg_pnl":    round(avg_pnl, 0),
        "sharpe":     round(sharpe, 2),
        "_trades_df": tdf,
    }


def monthly_breakdown(tdf: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for month, mdf in tdf.groupby("month"):
        wins = (mdf["pnl_pts"] > 0).sum()
        rows.append({
            "month":     month,
            "trades":    len(mdf),
            "win_rate":  round(wins / len(mdf) * 100, 1),
            "pnl_twd":   int(mdf["pnl_twd"].sum()),
            "avg_pnl":   round(mdf["pnl_twd"].mean(), 0),
        })
    return pd.DataFrame(rows)


def main():
    if not DATA_PATH.exists():
        print(f"找不到資料檔：{DATA_PATH}")
        print("請先在 VM 上執行 fetch_kbars.py")
        return

    print(f"=== 讀取資料 {DATA_PATH} ===")
    df = load_data()
    print(f"  {len(df)} 筆, {df['date'].nunique()} 個交易日")
    print(f"  範圍: {df['ts'].min()} ~ {df['ts'].max()}")

    print("\n=== 參數掃描 ===")
    combos = list(product(TRIGGER_TIMES.items(), OFFSETS, TARGETS, STOPS, TIME_LIMS))
    print(f"  共 {len(combos)} 組")

    results, trades_store = [], {}
    for i, ((t_name, t_time), off, tgt, stp, tlim) in enumerate(combos):
        if i % 500 == 0:
            print(f"  進度: {i}/{len(combos)}")
        r = run_backtest(df, t_name, t_time, off, tgt, stp, tlim)
        if r:
            key = (t_name, off, tgt, stp, tlim)
            trades_store[key] = r.pop("_trades_df")
            results.append(r)

    if not results:
        print("無結果")
        return

    rdf = pd.DataFrame(results)

    # Top 20
    print("\n=== Top 20（Sharpe） ===")
    top20 = rdf.sort_values("sharpe", ascending=False).head(20)
    print(top20.to_string(index=False))

    # 各觸發最佳
    print("\n=== 各觸發時間最佳組合 ===")
    best_configs = {}
    for t in TRIGGER_TIMES:
        sub = rdf[rdf["trigger"] == t].sort_values("sharpe", ascending=False).head(1)
        if not sub.empty:
            r = sub.iloc[0]
            best_configs[t] = r
            print(f"  {t}: offset={r.offset} target={r.target} stop={r.stop} "
                  f"tlim={r.time_limit} | WR={r.win_rate}% EV={r.avg_pnl:.0f} Sharpe={r.sharpe}")

    # 月份穩定性（針對各觸發最佳組合）
    print("\n=== 月份穩定性分析 ===")
    for t_name, r in best_configs.items():
        key = (t_name, r.offset, r.target, r.stop, r.time_limit)
        if key in trades_store:
            mdf = monthly_breakdown(trades_store[key])
            print(f"\n{t_name} (offset={r.offset} target={r.target} stop={r.stop}):")
            print(mdf.to_string(index=False))

    # 儲存
    out = Path(__file__).parent / "results.csv"
    rdf.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n完整結果 → {out}")


if __name__ == "__main__":
    main()
