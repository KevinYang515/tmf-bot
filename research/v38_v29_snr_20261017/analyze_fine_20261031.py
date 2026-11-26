import glob, pandas as pd, numpy as np, subprocess, sys
H = "E:/stock/v38_v29_snr_20261017/"
b = pd.read_csv(H+"g2lb_20261031_trades.csv"); b = b[b.case == "G2_lb20"].assign(case="base")
parts = [b] + [pd.read_csv(f) for f in sorted(glob.glob(H+"fine/*.csv"))]
pd.concat(parts).to_csv(H+"fine_20261031_trades.csv", index=False, encoding="utf-8-sig")
s = open(H+"analyze_realcost_20261031.py", encoding="utf-8").read()
s = s.replace('realcost_20261031_trades.csv', 'fine_20261031_trades.csv').replace('realcost_20261031_summary.csv', 'fine_20261031_summary.csv')
i, j = s.index("# consistency vs earlier runs"), s.index('m = pd.read_csv(H+"mxf_1min')
s = s[:i] + s[j:]
s = s.replace('pd.set_option("display.width", 300); print(R.to_string(index=False))', '''R = R[R["成本"] == "實盤成本R"].set_index("版本"); B = R.loc["base"]
R["Δ2024起"] = (R["2024起"] - B["2024起"]).round(1); R["ΔMDD"] = (R["2024起MDD"] - B["2024起MDD"]).round(1); R["Δ2020-23"] = (R["2020-23(參考)"] - B["2020-23(參考)"]).round(1)
R["Δ%"] = (R["Δ2024起"] / B["2024起"] * 100).round(1)
R["判讀"] = np.where(R["Δ%"] <= -15, "⚠️懸崖", np.where((R["Δ2024起"] > 0) & (R["Δ2020-23"] > 0) & (R["ΔMDD"] >= 0), "候選↑", ""))
R.to_csv(H+"fine_20261031_summary.csv", encoding="utf-8-sig")
pd.set_option("display.width", 300); print(R[["2024起","Δ2024起","Δ%","2024起MDD","ΔMDD","近12月","2020-23(參考)","Δ2020-23","波段賺賠比","判讀"]].to_string())''')
s = s.replace('t = T[T.exit_ts >= "2024-01-01"]; print("avg slip', '#')
exec(compile(s, "sens_analysis", "exec"))
