# one table, same data (to 10/31) & same cost model R: v27, v28 from latest run + realcost cases
import pandas as pd, re
H = "E:/stock/v38_v29_snr_20261017/"
src = open(H+"analyze_realcost_20261031.py", encoding="utf-8").read()
src = src.replace('T = pd.read_csv(H+"realcost_20261031_trades.csv", parse_dates=["entry_ts","exit_ts"])',
 'T = pd.concat([pd.read_csv(H+"latest_20261031_trades.csv", parse_dates=["entry_ts","exit_ts"]).query("case in [\'v27\',\'v28\']"), pd.read_csv(H+"realcost_20261031_trades.csv", parse_dates=["entry_ts","exit_ts"])])')
src = re.sub(r'for k, \(f, c\) in old.items\(\):\n(.*\n){2}', '', src)
src = src.replace("realcost_20261031_summary.csv", "unified_cmp_20261031.csv")
exec(src)
