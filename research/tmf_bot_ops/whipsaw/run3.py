import pandas as pd, numpy as np
H="E:/stock/v38_v29_snr_20261017/"
t=pd.read_csv(H+"gap/fable_audit/round12/eng/S24_2_off0.csv",parse_dates=["entry_ts","exit_ts"]).sort_values("entry_ts").reset_index(drop=True)
m=pd.read_csv(H+"shadow_gates/mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index()
C=m.Close
# campaigns
cid=0; op=[]; cids=[]
for i,r in t.iterrows():
    op=[(e,s) for e,s in op if e>r.entry_ts]
    if not op or op[0][1]!=r.side: cid+=1
    cids.append(cid); op.append((r.exit_ts,r.side))
t["cid"]=cids; t["dir"]=np.where(t.side=="L",1,-1)
rows=[]
for c,g in t.groupby("cid"):
    s,e=g.entry_ts.min(),g.exit_ts.max(); px=C[s:e]
    if len(px)==0: continue
    op=np.zeros(len(px))
    for _,r in g.iterrows():
        mk=(px.index>=r.entry_ts)&(px.index<r.exit_ts)
        op[mk]+= (px.values[mk]-r.entry_px)*r.dir*50
    rows.append(dict(cid=c,side=g.side.iloc[0],start=s,end=e,net=g.pnl.sum(),mfe=op.max(),lots=len(g),
                     entry=g.entry_px.iloc[0],exit_last=g.sort_values("exit_ts").exit_px.iloc[-1]))
K=pd.DataFrame(rows).sort_values("start").reset_index(drop=True)
K["prev_side"]=K.side.shift(); K["prev_end"]=K.end.shift(); K["prev_exit"]=K.exit_last.shift(); K["prev_net"]=K.net.shift()
K["gap_h"]=(K.start-K.prev_end).dt.total_seconds()/3600
K["dir"]=np.where(K.side=="L",1,-1)
K["晚進點"]=(K.entry-K.prev_exit)*K.dir   # >0 = 比上次出場價更順向(追)
K["再進場"]=(K.side==K.prev_side)&(K.gap_h<=24)
K["吐回"]=K.mfe-K.net
K["大賺變賠"]=(K.mfe>=5e4)&(K.net<0)
K["seg"]=np.where(K.start<"2024","20-23",np.where(K.start<"2026-07","24-26H1","26-07+"))
pd.set_option("display.width",220)
print("=== 波段總覽 (萬) ===")
print(K.groupby("seg").agg(波段=("net","size"),淨=("net",lambda x:x.sum()/1e4),平均MFE=("mfe",lambda x:x.mean()/1e4),平均吐回=("吐回",lambda x:x.mean()/1e4),大賺變賠次=("大賺變賠","sum")).round(2).to_string())
print("\n=== 再進場(同向、前波結束24h內) vs 其他 ===")
K["類"]=np.where(K.再進場, np.where(K.晚進點>0,"再進-追價","再進-較好價"),"首次/換向")
print(K.groupby(["seg","類"]).agg(n=("net","size"),平均萬=("net",lambda x:x.mean()/1e4),合計萬=("net",lambda x:x.sum()/1e4),勝率=("net",lambda x:(x>0).mean()*100),前波平均萬=("prev_net",lambda x:x.mean()/1e4)).round(2).to_string())
print("\n=== 前一波是停損/賠錢出場後的同向再進場 ===")
x=K[K.再進場]; x=x.assign(前波=np.where(x.prev_net>0,"前波賺","前波賠"))
print(x.groupby(["seg","前波"]).agg(n=("net","size"),平均萬=("net",lambda s:s.mean()/1e4),合計萬=("net",lambda s:s.sum()/1e4),勝率=("net",lambda s:(s>0).mean()*100)).round(2).to_string())
print("\n=== 2026-10-25 起逐波段 ===")
r=K[K.start>="2026-10-25"][["start","end","side","lots","entry","exit_last","mfe","net","類","gap_h","晚進點"]].copy()
r["mfe"]=(r.mfe/1e4).round(1); r["net"]=(r.net/1e4).round(1); print(r.round(1).to_string())
K.to_pickle("camp3.pkl")
