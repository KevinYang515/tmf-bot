import pandas as pd, numpy as np
K=pd.read_pickle("camp2.pkl"); K=K[K.side=="L"]
m=pd.read_csv("E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index()
td=(m.index+pd.Timedelta(hours=9)).normalize(); dc=m.Close.groupby(td).last(); ma60=dc.rolling(60).mean().shift(1)
rows=[]
for _,r in K.iterrows():
    s=r.start; w7=m.loc[s-pd.Timedelta(days=7):s]
    if len(w7)<100: continue
    d=(s+pd.Timedelta(hours=9)).normalize()
    if d not in ma60.index or not np.isfinite(ma60[d]): continue
    rows.append(dict(start=s,net=r.net,mv7=(r.entry/w7.Low.min()-1)*100,多頭=r.entry>ma60[d],yr=s.year))
R=pd.DataFrame(rows); R["晚"]=np.where(R.mv7>=5,"已漲≥5%","<5%")
pd.set_option("display.width",200)
print("=== 多單：逐年 ===")
print(R.groupby(["yr","晚"]).agg(n=("net","size"),勝率=("net",lambda s:round((s>0).mean()*100)),平均萬=("net",lambda s:round(s.mean()/1e4,2))).unstack("晚").to_string())
print("\n=== 多單：大盤在60日均線上(多頭)/下(空頭) ===")
print(R.groupby([R.start>="2024","多頭","晚"]).agg(n=("net","size"),勝率=("net",lambda s:round((s>0).mean()*100)),平均萬=("net",lambda s:round(s.mean()/1e4,2))).unstack("晚").to_string())
