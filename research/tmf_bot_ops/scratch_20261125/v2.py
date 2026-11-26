import pandas as pd, numpy as np
H="E:/stock/v38_v29_snr_20261017/"
m=pd.read_csv(H+"mxf_1min_2020_20261121b.csv")
tc=[c for c in m.columns if 'time' in c.lower() or 'date' in c.lower() or c.lower()=='ts'][0]
m[tc]=pd.to_datetime(m[tc]); m=m.set_index(tc)
cols={c.lower():c for c in m.columns}
# trading day: bars after 15:00 belong to next day
td=(m.index+pd.Timedelta(hours=9)).normalize()
d=m.groupby(td).agg(h=(cols['high'],'max'),l=(cols['low'],'min'),c=(cols['close'],'last'))
d['rng']=d.h-d.l; d['rngp']=d.rng/d.c*100
d['v20']=d.rngp.rolling(20).mean().shift(1)          # 過去20天平均日振幅%(不含當日)
d['pts20']=d.rng.rolling(20).mean().shift(1)
t=pd.read_pickle(H+"shadow_gates/trades_gated.pkl")
c=t.groupby('cid').agg(ts=('entry_ts','min'),pnl=('pnl','sum'),side=('side','first'),n=('pnl','size'))
c['td']=(c.ts+pd.Timedelta(hours=9)).dt.normalize()
c=c.join(d[['v20','pts20']],on='td').dropna()
c['yr']=c.ts.dt.year
print("各年：平均日振幅% / 點 , 波段數, 淨利(萬), 每波段(萬), 勝率")
for y,g in c.groupby('yr'):
    print(y, round(g.v20.mean(),2), int(g.pts20.mean()), len(g), round(g.pnl.sum()/1e4,1), round(g.pnl.mean()/1e4,2), round((g.pnl>0).mean()*100))
for lab,sub in [("2020+",c),("2024+",c[c.yr>=2024])]:
for th in (3,3.5,4,4.5):
    g=c[c.v20>=th]
    if len(g): print(th, len(g), round(g.pnl.sum()/1e4,1), round(g.pnl.mean()/1e4,2), round((g.pnl>0).mean()*100), round(g.pnl.min()/1e4,1), round(g.pnl.max()/1e4,1), g.ts.min().date(), g.ts.max().date())
g=c[c.v20>=4]; print(g[['ts','side','n','pnl','v20']].assign(pnl=lambda x:(x.pnl/1e4).round(1)).to_string())
