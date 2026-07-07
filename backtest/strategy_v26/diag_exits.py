# -*- coding: utf-8 -*-
"""診斷: 配對交易的出場差異來源"""
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

# 嚴格配對: 同 side + 同進場時間 + 同進場價
key_tv = tvt.assign(k=tvt.side + "|" + tvt.entry_ts.astype(str) + "|" + tvt.entry_px.astype(str))
key_py = py.assign(k=py.side + "|" + py.entry_ts.astype(str) + "|" + py.entry_px.astype(int).astype(str))
m = key_tv.merge(key_py, on="k", suffixes=("_tv", "_py"))
print(f"嚴格配對 (side+進場時間+進場價): {len(m)}/{len(tvt)}")

m["same_exit_bar"] = (m.exit_ts_tv == m.exit_ts_py)
m["xdiff"] = m.exit_px_py - m.exit_px_tv
m["pnl_diff"] = m.pnl_py - m.pnl_tv
print(f"出場同一根 bar: {m.same_exit_bar.mean()*100:.0f}%")
print(f"pnl 差總和: {m.pnl_diff.sum():+,.0f}")

print("\n== 按 TV 出場訊號分組 ==")
g = m.groupby("exit_sig_tv").agg(
    n=("pnl_diff", "size"),
    same_bar=("same_exit_bar", "mean"),
    avg_xdiff=("xdiff", "mean"),
    pnl_diff_sum=("pnl_diff", "sum"),
).round(1)
print(g.to_string())

print("\n== 不同 bar 出場、pnl 差最大 12 筆 ==")
bad = m[~m.same_exit_bar].reindex(m[~m.same_exit_bar].pnl_diff.abs().sort_values(ascending=False).index)
cols = ["side_tv", "entry_ts_tv", "entry_px_tv", "exit_ts_tv", "exit_px_tv", "exit_sig_tv",
        "exit_ts_py", "exit_px_py", "exit_sig_py", "pnl_diff"]
print(bad[cols].head(12).to_string(index=False))

print("\n== 同 bar 但價差 !=0 的分佈 (成交價模型誤差) ==")
sb = m[m.same_exit_bar & (m.xdiff != 0)]
print(f"筆數 {len(sb)}, 平均 xdiff {sb.xdiff.mean():+.1f}, 中位 {sb.xdiff.median():+.1f}")
print(sb.groupby("exit_sig_tv")["xdiff"].agg(["count", "mean"]).round(1).to_string())
