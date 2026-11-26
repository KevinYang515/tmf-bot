import pandas as pd, numpy as np
SD="E:/stock/v38_v29_snr_20261017/shadow_gates/"
t=pd.read_csv(SD+"v30eopt_off0_base_latest.csv",parse_dates=["entry_ts","exit_ts"]).sort_values("entry_ts").reset_index(drop=True)
m=pd.read_csv(SD+"mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index()
td=(m.index+pd.Timedelta(hours=9)).normalize()
d=m.groupby(td).agg(h=("High","max"),l=("Low","min"),c=("Close","last"))
d["rngp"]=(d.h-d.l)/d.c*100; d["v20"]=d.rngp.rolling(20).mean().shift(1); d["ma20"]=d.c.rolling(20).mean().shift(1)
d["pc"]=d.c.shift(1); d["ret1"]=(d.c.shift(1)/d.c.shift(2)-1)*100
# campaign: chain of same-side overlapping lots
camp=[]; cid=0; open_=[]; first={}
for i,r in t.iterrows():
    open_=[(e,s) for e,s in open_ if e>r.entry_ts]
    if not open_ or open_[0][1]!=r.side: cid+=1; first[cid]=(r.entry_ts,r.entry_px,i)
    camp.append((cid,len(open_)+1)); open_.append((r.exit_ts,r.side))
t["cid"]=[c for c,_ in camp]; t["lotno"]=[n for _,n in camp]
t["dir"]=np.where(t.side=="L",1,-1)
t["bp"]=t.pnl/50/t.entry_px*1e4
a=t[t.kind=="Add"].copy()
a["td"]=(a.entry_ts+pd.Timedelta(hours=9)).dt.normalize()
a=a.join(d[["v20","ma20","pc","ret1","h","l"]],on="td")
f0=a.cid.map(lambda c:first[c][1]); f0t=a.cid.map(lambda c:first[c][0])
a["順向走幅%"]=(a.entry_px/f0-1)*100*a.dir
a["距首單h"]=(a.entry_ts-f0t).dt.total_seconds()/3600
a["距MA20%"]=(a.entry_px/a.ma20-1)*100*a.dir
a["前日漲跌%"]=a.ret1*a.dir
a["今日距昨收%"]=(a.entry_px/a.pc-1)*100*a.dir
a["夜盤"]=np.where((a.entry_ts.dt.hour>=15)|(a.entry_ts.dt.hour<5),"夜","日")
a["振幅20%"]=a.v20; a["第幾口"]=a.lotno.clip(upper=4)
a=a.dropna(subset=["v20","ma20"])
a["seg"]=np.where(a.entry_ts<"2024-01-01","訓練20-23","驗證24+")
def mdd(p): e=p.cumsum(); return (e-e.cummax()).min()
out=[]
for f in ["第幾口","夜盤","side","振幅20%","順向走幅%","距首單h","距MA20%","前日漲跌%","今日距昨收%"]:
    if (not pd.api.types.is_numeric_dtype(a[f])) or f=="第幾口": a["q"]=a[f].astype(str)
    else: a["q"]=pd.qcut(a[f],5,labels=["Q1","Q2","Q3","Q4","Q5"]).astype(str)
    g=a.groupby(["q","seg"]).agg(n=("bp","size"),bp=("bp","mean"),萬=("pnl",lambda x:x.sum()/1e4),rng=(f,lambda x:f"{x.min():.1f}~{x.max():.1f}" if pd.api.types.is_numeric_dtype(x) else "")).unstack("seg")
    print(f"\n### {f}"); print(g.round(1).to_string())
    for q in a.q.unique():
        tr=a[(a.seg=="訓練20-23")]; te=a[a.seg=="驗證24+"]
        if tr[tr.q==q].bp.mean()<0 and te[te.q==q].bp.mean()<0:
            keep=t[~t.index.isin(a[(a.q==q)].index)]; k24=keep[keep.exit_ts>="2024"].sort_values("exit_ts").pnl; b24=t[t.exit_ts>="2024"].sort_values("exit_ts").pnl
            out.append((f,q,round(tr[tr.q==q].bp.mean(),1),round(te[te.q==q].bp.mean(),1),len(te[te.q==q]),round(k24.sum()/1e4,1),round(mdd(k24)/1e4,1),round(k24.sum()/-mdd(k24),2),round(b24.sum()/1e4,1),round(mdd(b24)/1e4,1),round(b24.sum()/-mdd(b24),2)))
print("\n候選(兩段皆<0)：特徵,組,訓練bp,驗證bp,驗證n,刪後2024+淨利,MDD,RR | 原 淨利,MDD,RR")
for o in out: print(o)
a.to_pickle("adds.pkl")
