import pandas as pd, numpy as np
m=pd.read_csv("E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index()
m=m[m.index>="2020-03-02"]
C=m.Close.values; L=m.Low.values; H=m.High.values; idx=m.index
td=(idx+pd.Timedelta(hours=9)).normalize()
days=pd.Index(td.unique()); di=days.get_indexer(td)
dh=pd.Series(H).groupby(di).max().values; dl=pd.Series(L).groupby(di).min().values
COST=6; HZ=[60,240,600,1200]
# baseline: long at every 60th bar
base={h:((C[np.arange(0,len(C)-h,60)+h]-C[np.arange(0,len(C)-h,60)]-COST)/C[np.arange(0,len(C)-h,60)]*1e4) for h in HZ}
rows=[]
for D in (6,10):
  for R in (2,3,4):
    ev=[]; last=-1; i=0
    # rolling: intraday running low within current day combined with prior 2 days lows
    for k in range(10,len(days)):
        s,e=np.searchsorted(di,k),np.searchsorted(di,k+1)
        hi10=max(dh[k-10:k].max(),0); low_prev=dl[k-2:k].min()
        runlow=np.minimum.accumulate(L[s:e]); low3=np.minimum(runlow,low_prev)
        cond=(low3<=hi10*(1-D/100))&(C[s:e]>=low3*(1+R/100))
        j=np.argmax(cond) if cond.any() else -1
        if j>=0: ev.append((s+j,low3[j]))
    for stop in (False,True):
      for h in HZ:
        r=[]; ts=[]
        for p,lo in ev:
            if p+h>=len(C): continue
            ex=C[p+h]
            if stop:
                hit=np.where(L[p+1:p+h+1]<lo)[0]
                if len(hit): ex=lo-2
            r.append((ex-C[p]-COST)/C[p]*1e4); ts.append(idx[p])
        r=pd.Series(r,index=ts)
        for lab,x in (("2020+",r),("2024+",r[r.index>="2024"])):
            if len(x)<3: continue
            x2=x.drop(x.idxmax())
            rows.append(dict(D=D,R=R,stop=stop,h=h,per=lab,n=len(x),bp=x.mean(),t=x.mean()/x.std()*np.sqrt(len(x)),win=(x>0).mean()*100,
              ex_max=x2.mean(),base=base[h].mean()))
    print(f"D={D} R={R} 事件 {len(ev)}:", [str(idx[p].date()) for p,_ in ev][-12:])
T=pd.DataFrame(rows).round(1); T.to_csv("result.csv",index=False)
pd.set_option("display.width",200); print(T.to_string())
