# -*- coding: utf-8 -*-
import pandas as pd, numpy as np, sys
sys.stdout.reconfigure(encoding='utf-8')

tv = pd.read_csv(r"D:\stock\tmf-bot\tv\result\V38.0623_v26_Session_TAIFEX_MXF1!_2026-07-07.csv")
tv["dt"] = pd.to_datetime(tv["日期和時間"])
ex = tv[tv["類型"].str.contains("出場")].copy()
ex = ex[(ex.dt >= "2026-04-16") & (ex.dt <= "2026-06-13")]
tv_d = ex.groupby(ex.dt.dt.date)["淨損益 TWD"].sum()

py = pd.read_csv(r"D:\stock\tmf-bot\backtest\strategy_v26\py_trades_validate.csv", parse_dates=["entry_ts","exit_ts"])
py = py[(py.entry_ts >= "2026-04-16") & (py.exit_ts <= "2026-06-13")]
py_d = py.groupby(py.exit_ts.dt.date)["pnl"].sum()

cmp = pd.DataFrame({"tv": tv_d, "py": py_d}).fillna(0)
print(f"日損益相關係數: {cmp.tv.corr(cmp.py):.3f}")
print(f"總計 TV {cmp.tv.sum():+,.0f} vs PY {cmp.py.sum():+,.0f} ({(cmp.py.sum()/cmp.tv.sum()-1)*100:+.1f}%)")
diff = (cmp.py - cmp.tv)
print(f"日差異: 平均 {diff.mean():+,.0f}, std {diff.std():,.0f}")
print("\n差異最大 5 日:")
print(diff.abs().sort_values(ascending=False).head(5).to_string())
