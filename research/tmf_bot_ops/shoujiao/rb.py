import pandas as pd, numpy as np
m=pd.read_csv("E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index()
m=m[m.index>="2020-03-02"]
b=m.resample("5min",label="right",closed="right").agg({"Low":"min","Close":"last"}).dropna()
b["td"]=(b.index+pd.Timedelta(hours=9)).normalize()
last=b.groupby("td").Close.last(); b["prev"]=b.td.map(last.shift(1)); b=b.dropna()
rows=[]
for d,g in b.groupby("td"):
    rl=g.Low.cummin(); pc=g.prev.iat[0]; C=g.Close.values
    nd=b[b.td>d].td.min(); nx=last.get(nd,np.nan)
    for R in (1,1.5,2):
        ok=(rl<=pc*0.95)&(g.Close>=rl*(1+R/100))
        if not ok.any(): continue
        i=int(np.argmax(ok.values)); px=C[i]; lo=rl.iat[i]
        rows.append(dict(day=d,R=R,ts=g.index[i],low_pct=(lo/pc-1)*100,px=px,到收盤=(C[-1]/px-1)*100,到隔日收=(nx/px-1)*100,
                         再破底=bool((g.Low.values[i+1:]<lo).any()), 收盤距低=(C[-1]/lo-1)*100))
R=pd.DataFrame(rows); pd.set_option("display.width",200)
print(R.groupby("R").agg(次數=("px","size"),到收盤平均=("到收盤","mean"),到收盤中位=("到收盤","median"),到收盤上漲比例=("到收盤",lambda s:(s>0).mean()),
    到隔日收平均=("到隔日收","mean"),到隔日收上漲比例=("到隔日收",lambda s:(s>0).mean()),當日再破底=("再破底","mean")).round(2).to_string())
print(R[R.R==1][["day","ts","low_pct","到收盤","到隔日收","再破底"]].round(2).to_string())
