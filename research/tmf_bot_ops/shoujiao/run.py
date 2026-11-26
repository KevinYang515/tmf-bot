import pandas as pd, numpy as np
m=pd.read_csv("E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index()
m=m[m.index>="2020-03-02"]
b=m.resample("5min",label="right",closed="right").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
pc=b.Close.shift(1); tr=pd.concat([b.High-b.Low,(b.High-pc).abs(),(b.Low-pc).abs()],axis=1).max(axis=1)
b["atr"]=tr.ewm(alpha=1/14,adjust=False).mean().shift(1)
b["td"]=(b.index+pd.Timedelta(hours=9)).normalize()
last=b.groupby("td").Close.last(); b["prev"]=b.td.map(last.shift(1))
b["mv"]=(b.Close/b.prev-1)*100
b["daylow_prev"]=b.groupby("td").Low.transform(lambda s:s.cummin().shift(1))
b["dayhigh_prev"]=b.groupby("td").High.transform(lambda s:s.cummax().shift(1))
rng=b.High-b.Low
b["sj"]=(b.Low<b.daylow_prev)&((b[["Open","Close"]].min(axis=1)-b.Low)>=0.6*rng)&(rng>=1.5*b.atr)
b["st"]=(b.High>b.dayhigh_prev)&((b.High-b[["Open","Close"]].max(axis=1))>=0.6*rng)&(rng>=1.5*b.atr)
C=b.Close.values; L=b.Low.values; H=b.High.values; td=b.td.values; n=len(b)
endidx=pd.Series(np.arange(n)).groupby(td).transform("max").values
nxt=pd.Series(endidx).groupby(td).transform("max").values
# next trading day end
ud=np.unique(td); pos=np.searchsorted(ud,td); nd_end={d:i for d,i in zip(td,endidx)}
def fw(i,k): j=min(i+k,n-1); return (C[j]/C[i]-1)*100
rows=[]
for i in range(n):
    if not np.isfinite(b.mv.iat[i]): continue
    for ctx,flag,sg in (("跌≥5%",b.sj.iat[i],-1),("漲≥5%",b.st.iat[i],1)):
        if (sg<0 and b.mv.iat[i]<=-5) or (sg>0 and b.mv.iat[i]>=5):
            e=endidx[i]; k=pos[i]+1; e2=nd_end.get(ud[k],e) if k<len(ud) else e
            rows.append(dict(ts=b.index[i],ctx=ctx,flag=bool(flag),r30=fw(i,6),r60=fw(i,12),rclose=(C[e]/C[i]-1)*100,rnext=(C[e2]/C[i]-1)*100,
                             newext=(bool(e>i) and ((L[i+1:e+1].min()<L[i]) if sg<0 else (H[i+1:e+1].max()>H[i]))), day=td[i]))
R=pd.DataFrame(rows); R.to_csv("events.csv",index=False)
pd.set_option("display.width",220)
for ctx in ("跌≥5%","漲≥5%"):
    x=R[R.ctx==ctx]
    g=x.groupby("flag").agg(K棒數=("r60","size"),天數=("day","nunique"),r30平均=("r30","mean"),r60平均=("r60","mean"),r60中位=("r60","median"),
        到收盤平均=("rclose","mean"),到隔日收平均=("rnext","mean"),r60上漲比例=("r60",lambda s:(s>0).mean()),當日再破極值=("newext","mean"))
    print(f"\n=== 情境 {ctx}：{'收腳' if ctx.startswith('跌') else '收頭'}=True vs 其他 ===  (報酬>0=上漲)"); print(g.round(2).to_string())
print("\n收腳事件清單:"); print(R[(R.ctx=="跌≥5%")&R.flag][["ts","r30","r60","rclose","rnext","newext"]].round(2).to_string())
