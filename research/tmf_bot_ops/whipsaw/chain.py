import pandas as pd, numpy as np
K=pd.read_pickle("camp.pkl").sort_values("start").reset_index(drop=True)
K["td"]=(K.start+pd.Timedelta(hours=9)).dt.normalize()
# k = number of consecutive LOSING campaigns, same side, same trading day, immediately before this one
ks=[]; prev=None
for i,r in K.iterrows():
    if prev is not None and prev.side==r.side and prev.td==r.td and prev.net<0: k=ks[-1]+1 if ks else 1
    else: k=0
    ks.append(k); prev=r
K["連續停損後第幾次"]=np.minimum(ks,3)
K["seg"]=np.where(K.start<"2024","20-23","24+")
pd.set_option("display.width",200)
print(K.groupby(["side","連續停損後第幾次","seg"]).agg(n=("net","size"),勝率=("net",lambda s:(s>0).mean()*100),平均萬=("net",lambda s:s.mean()/1e4),合計萬=("net",lambda s:s.sum()/1e4)).unstack("seg").round(2).to_string())
