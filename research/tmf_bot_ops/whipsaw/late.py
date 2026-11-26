import pandas as pd, numpy as np
K=pd.read_pickle("camp.pkl")
m=pd.read_csv("E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index()
H=m.High; L=m.Low
res=[]
for _,r in K.iterrows():
    s=r.start
    w5=m.loc[s-pd.Timedelta(days=7):s]           # ~5 trading days lookback
    w1=m.loc[s-pd.Timedelta(hours=24):s]
    if len(w5)<100: continue
    if r.side=="S":
        mv5=(1-r.entry/w5.High.max())*100; mv1=(1-r.entry/w1.High.max())*100
    else:
        mv5=(r.entry/w5.Low.min()-1)*100; mv1=(r.entry/w1.Low.min()-1)*100
    res.append(dict(start=s,side=r.side,net=r.net,mfe=r.mfe,mv5=mv5,mv1=mv1))
R=pd.DataFrame(res); R["seg"]=np.where(R.start<"2024","20-23","24+")
pd.set_option("display.width",200)
for seg in ("20-23","24+"):
    x=R[R.seg==seg]
    print(f"\n=== {seg}  進場前已順向走多少（距近7天極值%）→ 波段結果 ===")
    print("中位數 已走%:", round(x.mv5.median(),2), " 24小時內已走%:", round(x.mv1.median(),2))
    x=x.assign(q=pd.qcut(x.mv5,5,labels=["Q1最早","Q2","Q3","Q4","Q5最晚"]))
    print(x.groupby("q",observed=True).agg(波段=("net","size"),已走範圍=("mv5",lambda s:f"{s.min():.1f}~{s.max():.1f}"),平均萬=("net",lambda s:s.mean()/1e4),
         合計萬=("net",lambda s:s.sum()/1e4),勝率=("net",lambda s:(s>0).mean()*100),平均最大浮盈萬=("mfe",lambda s:s.mean()/1e4)).round(2).to_string())
