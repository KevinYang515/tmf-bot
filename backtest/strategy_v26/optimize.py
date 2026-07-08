# -*- coding: utf-8 -*-
"""v26 優化變體 A/B 測試 (2024-01 ~ 2026-06, 1min intrabar)"""
import pandas as pd
import numpy as np
import sys, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r"D:\stock\tmf-bot\backtest\strategy_v26")
from engine_v26 import load_1min, run, POINT_VALUE

OUT = r"D:\stock\tmf-bot\backtest\strategy_v26\opt_results.csv"

V27 = {"opt_cooldown_min": 30, "opt_stale_hr": 10}
VARIANTS = {
    "v27_py4":           {**V27},
    "v27_py3":           {**V27, "opt_max_lots": 3},
    "v27_py2":           {**V27, "opt_max_lots": 2},
}


def metrics(tr):
    if tr.empty:
        return {}
    w = tr[tr.pnl > 0]
    lo = tr[tr.pnl <= 0]
    pf = w.pnl.sum() / abs(lo.pnl.sum()) if len(lo) and lo.pnl.sum() != 0 else np.inf
    cum = tr.pnl.cumsum()
    mdd = (cum - cum.cummax()).min()
    daily = tr.groupby(tr.exit_ts.dt.date)["pnl"].sum()
    sharpe = daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else np.nan
    res = dict(trades=len(tr), wr=round(len(w) / len(tr) * 100, 1),
               net=round(tr.pnl.sum()), pf=round(pf, 3), mdd=round(mdd),
               sharpe=round(sharpe, 2))
    for y in sorted(tr.exit_ts.dt.year.unique()):
        res[f"net_{y}"] = round(tr[tr.exit_ts.dt.year == y].pnl.sum())
    return res


def main():
    df1m = load_1min(r"D:\stock\tmf-bot\backtest\mxf_1min.csv")
    rows = []
    for name, over in VARIANTS.items():
        t0 = time.time()
        tr = run(df1m, p=over, intrabar_mode="1min")
        m = metrics(tr)
        m["variant"] = name
        rows.append(m)
        print(f"{name:16s} net {m['net']:+12,} PF {m['pf']:.2f} MDD {m['mdd']:+10,} "
              f"trades {m['trades']:4d} WR {m['wr']}% sharpe {m['sharpe']} ({time.time()-t0:.0f}s)", flush=True)
        pd.DataFrame(rows).to_csv(OUT, index=False)
    print("\ndone ->", OUT)


if __name__ == "__main__":
    main()
