import pandas as pd, numpy as np
H="E:/stock/v38_v29_snr_20261017/"
t=pd.read_csv(H+"gap/fable_audit/round12/eng/S24_2_off0.csv",parse_dates=["entry_ts","exit_ts"])
m=pd.read_csv(H+"shadow_gates/mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index(); m=m[m.index>="2020-03-02"]
b=m.resample("5min",label="right",closed="right").agg({"High":"max","Low":"min","Close":"last"}).dropna()
b["td"]=(b.index+pd.Timedelta(hours=9)).normalize(); last=b.groupby("td").Close.last(); b["prev"]=b.td.map(last.shift(1)); b=b.dropna()
rows=[]
for d,g in b.groupby("td"):
    pc=g.prev.iat[0]; rh=g.High.cummax(); rl=g.Low.cummin(); C=g.Close
    for side,cond,sg in (("多",(rh>=pc*1.05),1),("空",(rl<=pc*0.95),-1)):
        for R in (1,2,3):
            ok=cond&((C<=rh*(1-R/100)) if sg>0 else (C>=rl*(1+R/100)))
            if not ok.any(): continue
            ts=ok.idxmax(); px=C[ts]
            lots=t[(t.side==("L" if sg>0 else "S"))&(t.entry_ts<=ts)&(t.exit_ts>ts)]
            for _,l in lots.iterrows():
                hold=(l.exit_px-px)*sg*50          # 抱到實際出場 相對 事件點出場 的差（>0 = 抱著比較好）
                rows.append(dict(side=side,R=R,day=d,ts=ts,kind=l.kind,hold=hold,exit_sig=l.exit_sig,期=("20-23" if d<pd.Timestamp("2024-01-01") else "24+")))
X=pd.DataFrame(rows); pd.set_option("display.width",220)
print("事件發生時手上的單：『抱到原規則出場』比『事件點立刻出場』多賺(萬/口)；>0 = 應該續抱")
print(X.groupby(["side","R","期"]).agg(事件天數=("day","nunique"),口數=("hold","size"),平均差萬=("hold",lambda s:round(s.mean()/1e4,2)),合計差萬=("hold",lambda s:round(s.sum()/1e4,1)),續抱較好比例=("hold",lambda s:round((s>0).mean()*100))).unstack("期").to_string())
print("\n依單別（R=1）："); print(X[X.R==1].groupby(["side","kind","期"]).agg(口數=("hold","size"),平均差萬=("hold",lambda s:round(s.mean()/1e4,2)),合計差萬=("hold",lambda s:round(s.sum()/1e4,1))).unstack("期").to_string())
print("\n逐日（R=1，合計差 萬）："); print(X[X.R==1].groupby(["side","day"]).hold.sum().div(1e4).round(1).to_string())
