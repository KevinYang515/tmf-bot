import pandas as pd, numpy as np
K=pd.read_pickle("camp3.pkl")
m=pd.read_csv("E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index()
td=(m.index+pd.Timedelta(hours=9)).normalize(); g=m.groupby(td)
D=pd.DataFrame({"h":g.High.max(),"l":g.Low.min(),"c":g.Close.last()}); D["rng"]=(D.h-D.l)/D.c*100; D["v20"]=D.rng.rolling(20).mean().shift(1); D["pc"]=D.c.shift(1)
rows=[]
for _,r in K.iterrows():
    s=r.start; w7=m.loc[s-pd.Timedelta(days=7):s]; w1=m.loc[s-pd.Timedelta(hours=24):s]
    d=(s+pd.Timedelta(hours=9)).normalize()
    if len(w7)<100 or d not in D.index or not np.isfinite(D.at[d,"v20"]): continue
    sg=1 if r.side=="L" else -1; pc=D.at[d,"pc"]
    rows.append(dict(start=s,side="多" if sg>0 else "空",net=r.net,
        mv7=((r.entry/w7.Low.min()-1) if sg>0 else (1-r.entry/w7.High.max()))*100,
        mv1=((r.entry/w1.Low.min()-1) if sg>0 else (1-r.entry/w1.High.max()))*100,
        today=(r.entry/pc-1)*100*sg, v20=D.at[d,"v20"], 盤="日" if 8<=s.hour<14 else "夜"))
R=pd.DataFrame(rows); R["期"]=np.where(R.start<"2024","20-23","24+")
pd.set_option("display.width",250)
print("=== 新版整體 依 多空×日夜 ===")
print(R.groupby(["side","盤","期"]).agg(n=("net","size"),勝率=("net",lambda s:round((s>0).mean()*100)),平均萬=("net",lambda s:round(s.mean()/1e4,2)),合計萬=("net",lambda s:round(s.sum()/1e4,1))).unstack("期").to_string())
B={"mv7":[-99,3,5,99],"mv1":[-99,1,2,3,99],"today":[-99,0,1,3,99],"v20":[0,1.3,2,99]}
for f,b in B.items():
    q=pd.cut(R[f],b).astype(str)
    t=R.assign(q=q).groupby(["side","盤","q","期"]).agg(n=("net","size"),勝率=("net",lambda s:round((s>0).mean()*100)),平均萬=("net",lambda s:round(s.mean()/1e4,2))).unstack("期")
    print(f"\n### {f}"); print(t.to_string())
R.to_pickle("attr3.pkl")
