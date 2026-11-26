import pandas as pd, numpy as np
SD="E:/stock/v38_v29_snr_20261017/shadow_gates/"
m=pd.read_csv(SD+"mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index()
b=m.resample("5min",label="right",closed="right").agg({"High":"max","Low":"min","Close":"last"}).dropna()
pc=b.Close.shift(1); tr=pd.concat([b.High-b.Low,(b.High-pc).abs(),(b.Low-pc).abs()],axis=1).max(axis=1)
atr=tr.ewm(alpha=1/14,adjust=False).mean(); ap=atr/b.Close*100
print("5分ATR%價格 中位數 2020-23:",round(ap[:"2023"].median(),3)," 2024-25:",round(ap["2024":"2025"].median(),3)," 2026H1:",round(ap["2026-01":"2026-06"].median(),3))
for mo in ["2026-07","2026-08","2026-09","2026-10","2026-11"]: print(mo,"ATR%",round(ap[mo].median(),3),"ATR點",int(atr[mo].median()),"加碼停損距離≈4.5×ATR=",int(4.5*atr[mo].median()),"點")
a=pd.read_pickle("adds.pkl")
t=pd.read_csv(SD+"v30eopt_off0_base_latest.csv",parse_dates=["entry_ts","exit_ts"])
t["mo"]=t.exit_ts.dt.to_period("M"); t["grp"]=np.where(t.kind=="Add","加碼",np.where(t.kind=="G","G","基本"))
r=t[t.exit_ts>="2026-01-01"]
T=r.pivot_table(index="mo",columns="grp",values="pnl",aggfunc="sum")/1e4
T["合計"]=T.sum(axis=1)
sl=r[r.exit_sig.str.contains("Add_SL")].groupby("mo").agg(停損筆=("pnl","size"),停損合計萬=("pnl",lambda x:x.sum()/1e4),每筆停損點=("pnl",lambda x:(x/50).mean()))
ad=r[r.kind=="Add"].groupby("mo").agg(加碼筆=("pnl","size"),加碼勝率=("pnl",lambda x:(x>0).mean()*100))
print(T.join(ad).join(sl).round(1).to_string())
