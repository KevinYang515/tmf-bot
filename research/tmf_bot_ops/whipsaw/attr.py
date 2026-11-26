import pandas as pd, numpy as np
K=pd.read_pickle("camp2.pkl")
m=pd.read_csv("E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index()
td=(m.index+pd.Timedelta(hours=9)).normalize(); g=m.groupby(td)
D=pd.DataFrame({"h":g.High.max(),"l":g.Low.min(),"c":g.Close.last()}); D["rng"]=(D.h-D.l)/D.c*100; D["v20"]=D.rng.rolling(20).mean().shift(1); D["pc"]=D.c.shift(1)
rows=[]
for _,r in K.iterrows():
    s=r.start; w7=m.loc[s-pd.Timedelta(days=7):s]; w1=m.loc[s-pd.Timedelta(hours=24):s]
    d=(s+pd.Timedelta(hours=9)).normalize()
    if len(w7)<100 or d not in D.index or not np.isfinite(D.at[d,"v20"]): continue
    sg=1 if r.side=="L" else -1; pc=D.at[d,"pc"]
    mv7=((r.entry/w7.Low.min()-1) if sg>0 else (1-r.entry/w7.High.max()))*100
    mv1=((r.entry/w1.Low.min()-1) if sg>0 else (1-r.entry/w1.High.max()))*100
    hh=s.hour; ses="日盤" if 8<=hh<14 else ("夜15-21" if 15<=hh<21 else ("夜21-01" if hh>=21 or hh<1 else "夜01-05"))
    rows.append(dict(start=s,side="多" if sg>0 else "空",net=r.net,mv7=mv7,mv1=mv1,today=(r.entry/pc-1)*100*sg,ses=ses,v20=D.at[d,"v20"],wd=s.dayofweek))
R=pd.DataFrame(rows); R["期"]=np.where(R.start<"2024","20-23","24+")
B={"mv7":([-99,2,3,4,5,99],"進場時距7日極值已順向走%"),"mv1":([-99,1,2,3,99],"24小時內已順向走%"),"today":([-99,-1,1,3,5,99],"進場時距昨收已順向走%"),
   "v20":([0,1.2,1.6,2.2,99],"近20日平均日振幅%"),"ses":(None,"進場時段"),"wd":(None,"星期(0=一)")}
out=[]
pd.set_option("display.width",240)
for f,(bins,name) in B.items():
    q=pd.cut(R[f],bins).astype(str) if bins else R[f].astype(str)
    t=R.assign(q=q).groupby(["side","q","期"]).agg(n=("net","size"),勝率=("net",lambda s:round((s>0).mean()*100)),平均萬=("net",lambda s:round(s.mean()/1e4,2)),
        虧損時平均萬=("net",lambda s:round(s[s<0].mean()/1e4,2)),合計萬=("net",lambda s:round(s.sum()/1e4,1))).unstack("期")
    print(f"\n### {name}"); print(t.to_string())
    t.columns=[f"{a}_{b}" for a,b in t.columns]; t.insert(0,"特徵",name); out.append(t.reset_index())
pd.concat(out).to_csv("attr_side.csv",index=False,encoding="utf-8-sig")
