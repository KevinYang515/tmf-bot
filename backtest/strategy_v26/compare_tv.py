# -*- coding: utf-8 -*-
"""逐筆比對: Python 引擎 vs TV 匯出 (重疊 4/16 ~ 6/13)"""
import pandas as pd
import numpy as np
import sys
sys.stdout.reconfigure(encoding='utf-8')

TV_CSV = r"D:\stock\tmf-bot\tv\result\V38.0623_v26_Session_TAIFEX_MXF1!_2026-07-07.csv"
PY_CSV = r"D:\stock\tmf-bot\backtest\strategy_v26\py_trades_validate.csv"
END = "2026-06-13"

tv = pd.read_csv(TV_CSV)
tv["dt"] = pd.to_datetime(tv["日期和時間"])
ex = tv[tv["類型"].str.contains("出場")]
en = tv[tv["類型"].str.contains("進場")]
tvt = ex.merge(en[["交易編號", "dt", "價格 TWD", "訊號"]], on="交易編號", suffixes=("_x", "_e"))
tvt = tvt.rename(columns={"dt_x": "exit_ts", "dt_e": "entry_ts", "價格 TWD_x": "exit_px",
                          "價格 TWD_e": "entry_px", "淨損益 TWD": "pnl", "訊號_x": "exit_sig",
                          "訊號_e": "entry_sig"})
tvt["side"] = np.where(tvt["類型"].str.contains("多頭"), "L", "S")
tvt = tvt[(tvt.entry_ts >= "2026-04-16") & (tvt.exit_ts <= END)].sort_values("entry_ts").reset_index(drop=True)

py = pd.read_csv(PY_CSV, parse_dates=["entry_ts", "exit_ts"])
py = py[(py.entry_ts >= "2026-04-16") & (py.exit_ts <= END)].sort_values("entry_ts").reset_index(drop=True)

print(f"TV: {len(tvt)} 筆, 淨損益 {tvt.pnl.sum():+,.0f}")
print(f"PY: {len(py)} 筆, 淨損益 {py.pnl.sum():+,.0f}")

# 進場配對: side 相同, 進場時間差 <= 10 分鐘
used = set()
matches = []
for _, r in tvt.iterrows():
    cand = py[(py.side == r.side) & (~py.index.isin(used))
              & (abs(py.entry_ts - r.entry_ts) <= pd.Timedelta(minutes=10))]
    if len(cand):
        j = (abs(cand.entry_ts - r.entry_ts)).idxmin()
        used.add(j)
        q = py.loc[j]
        matches.append(dict(
            tv_entry=r.entry_ts, py_entry=q.entry_ts, side=r.side,
            tv_epx=r.entry_px, py_epx=q.entry_px,
            tv_exit=r.exit_ts, py_exit=q.exit_ts,
            tv_xpx=r.exit_px, py_xpx=q.exit_px,
            tv_pnl=r.pnl, py_pnl=q.pnl,
            exit_dt_min=abs((q.exit_ts - r.exit_ts).total_seconds()) / 60,
            tv_sig=r.exit_sig, py_sig=q.exit_sig,
        ))

m = pd.DataFrame(matches)
print(f"\n進場配對成功: {len(m)}/{len(tvt)} ({len(m)/len(tvt)*100:.0f}%)")
if len(m):
    exact_e = (m.tv_epx == m.py_epx).mean()
    print(f"進場價完全相同: {exact_e*100:.0f}%")
    print(f"出場時間差 <=10 分: {(m.exit_dt_min <= 10).mean()*100:.0f}%")
    print(f"出場價差中位數: {abs(m.tv_xpx - m.py_xpx).median():.0f} 點")
    print(f"配對後 pnl: TV {m.tv_pnl.sum():+,.0f} vs PY {m.py_pnl.sum():+,.0f}")

unmatched_tv = tvt[~tvt.index.isin([i for i, _ in enumerate(tvt.iterrows()) if i < len(m)])]
# TV 沒配到的
tv_matched_ts = set(m.tv_entry) if len(m) else set()
un_tv = tvt[~tvt.entry_ts.isin(tv_matched_ts)]
un_py = py[~py.index.isin(used)]
print(f"\nTV 有 PY 沒有: {len(un_tv)} 筆 (pnl {un_tv.pnl.sum():+,.0f})")
if len(un_tv):
    print(un_tv[["entry_ts", "side", "entry_sig", "entry_px", "exit_ts", "exit_sig", "pnl"]].head(20).to_string(index=False))
print(f"\nPY 有 TV 沒有: {len(un_py)} 筆 (pnl {un_py.pnl.sum():+,.0f})")
if len(un_py):
    print(un_py[["entry_ts", "side", "kind", "entry_px", "exit_ts", "exit_sig", "pnl"]].head(20).to_string(index=False))

# 出場價差最大的配對
if len(m):
    m["xdiff"] = abs(m.tv_xpx - m.py_xpx)
    bad = m.sort_values("xdiff", ascending=False).head(10)
    print("\n出場價差最大 10 筆:")
    print(bad[["side", "tv_entry", "tv_xpx", "py_xpx", "tv_sig", "py_sig", "tv_pnl", "py_pnl"]].to_string(index=False))
