import pandas as pd, numpy as np
K=pd.read_pickle("camp.pkl")
m=pd.read_csv("E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index()
t=pd.read_csv("E:/stock/v38_v29_snr_20261017/gap/fable_audit/round9/eng1125/NOBE_off0.csv",parse_dates=["entry_ts","exit_ts"])
td=(m.index+pd.Timedelta(hours=9)).normalize(); dc=m.Close.groupby(td).last()
rows=[]
for _,r in K.iterrows():
    s=r.start; w5=m.loc[s-pd.Timedelta(days=7):s]; w1=m.loc[s-pd.Timedelta(hours=24):s]
    if len(w5)<100: continue
    d=(s+pd.Timedelta(hours=9)).normalize(); prev=dc[dc.index<d]
    if not len(prev): continue
    pc=prev.iloc[-1]; sg=-1 if r.side=="S" else 1
    mv5=((r.entry/w5.Low.min()-1) if sg>0 else (1-r.entry/w5.High.max()))*100
    lots=t[(t.entry_ts>=s)&(t.entry_ts<=r.end)]
    rows.append(dict(start=s,side=r.side,net=r.net,mv5=mv5,
        mv1=((r.entry/w1.Low.min()-1) if sg>0 else (1-r.entry/w1.High.max()))*100,
        今日已走=(r.entry/pc-1)*100*sg, 時=s.hour, 夜=int(s.hour>=15 or s.hour<5),
        首單損益=lots[lots.kind=="Cmd"].pnl.sum(), 加碼損益=lots[lots.kind!="Cmd"].pnl.sum(), 口數=len(lots)))
R=pd.DataFrame(rows); R["seg"]=np.where(R.start<"2024","20-23","24+")
R["晚"]=R.groupby("seg").mv5.transform(lambda s:s>=s.quantile(0.8))
pd.set_option("display.width",220)
print("=== 晚進場(各期前20%) vs 其他：損益來自首單還是加碼（平均萬） ===")
print(R.groupby(["seg","晚"]).agg(n=("net","size"),勝率=("net",lambda s:(s>0).mean()*100),平均=("net",lambda s:s.mean()/1e4),
    首單平均=("首單損益",lambda s:s.mean()/1e4),加碼平均=("加碼損益",lambda s:s.mean()/1e4),
    虧損波段平均=("net",lambda s:s[s<0].mean()/1e4),獲利波段平均=("net",lambda s:s[s>0].mean()/1e4),平均口數=("口數","mean")).round(2).to_string())
L=R[R.晚]
for f,bins in (("今日已走",[-99,1,3,5,99]),("mv1",[-99,1,2,4,99]),("夜",None),("side",None)):
    q=pd.cut(L[f],bins).astype(str) if bins else L[f].astype(str)
    print(f"\n### 晚進場內，依 {f}")
    print(L.groupby([q,"seg"]).agg(n=("net","size"),勝率=("net",lambda s:(s>0).mean()*100),平均萬=("net",lambda s:s.mean()/1e4),加碼平均萬=("加碼損益",lambda s:s.mean()/1e4)).unstack("seg").round(2).to_string())
