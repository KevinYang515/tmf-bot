# 便宜診斷：前一交易日可得的盤勢特徵，能否區分 v28 隔天/未來5天損益（不改策略）
import pandas as pd, numpy as np
P=pd.read_csv('br_daily_pnl.csv',parse_dates=['day']); P=P[(P.variant=='v28')&(P.definition=='BD1')].set_index('day').net
m=pd.read_csv('mxf_1min_2020_20261026.csv',parse_dates=['ts'])
m['d']=m.ts.dt.normalize()+pd.to_timedelta((m.ts.dt.hour>=15).astype(int),'D')
# 5分K
m['b']=m.ts.dt.floor('5min')
b=m.groupby(['d','b']).agg(c=('Close','last'),v=('Volume','sum')).reset_index()
g=b.groupby('d')
day=pd.DataFrame({'c':g.c.last(),'path':g.c.apply(lambda s:s.diff().abs().sum()),'net':g.c.apply(lambda s:abs(s.iloc[-1]-s.iloc[0])),'vol':g.v.sum(),
                  'hi':m.groupby('d').High.max(),'lo':m.groupby('d').Low.min()})
day['er_intraday']=day.net/day.path                       # 當日5分K效率比(低=來回洗)
day['rng_pct']=(day.hi-day.lo)/day.c
F=pd.DataFrame(index=day.index)
F['ER當日5分K_5日均']=day.er_intraday.rolling(5).mean()
F['ER日線20']=(day.c-day.c.shift(20)).abs()/day.c.diff().abs().rolling(20).sum()
F['日振幅%_20日均']=day.rng_pct.rolling(20).mean()
F['振幅點數_20日均']=(day.hi-day.lo).rolling(20).mean()
F['量比5/60']=day.vol.rolling(5).mean()/day.vol.rolling(60).mean()
F['量比1/20']=day.vol/day.vol.rolling(20).mean()
F['振幅比5/60']=day.rng_pct.rolling(5).mean()/day.rng_pct.rolling(60).mean()
F['v28近20日損益']=P.reindex(day.index).fillna(0).rolling(20).sum()
F=F.shift(1)   # 只用前一交易日
y1=P.reindex(F.index); y5=P.reindex(F.index).fillna(0)[::-1].rolling(5).sum()[::-1]
X=F.join(pd.DataFrame({'y1':y1,'y5':y5})).dropna()
X=X[X.index>='2020-06-01']
rows=[]
for f in F.columns:
    for lab,lo,hi in [('全期','2020','2027'),('2020-23','2020','2024'),('2024-26','2024','2027')]:
        s=X[(X.index>=lo)&(X.index<hi)]
        q=pd.qcut(s[f].rank(method='first'),5,labels=False)
        mean=s.groupby(q).y1.mean()/1e3
        rows.append(dict(特徵=f,期間=lab,**{f'Q{i+1}':round(mean.get(i,np.nan),1) for i in range(5)},
                         Q1日虧比=round((s[q==0].y1<0).mean(),2),spearman=round(s[f].corr(s.y1,method='spearman'),3),sp5=round(s[f].corr(s.y5,method='spearman'),3)))
R=pd.DataFrame(rows); R.to_csv('chop_diag.csv',index=False,encoding='utf-8-sig'); print(R.to_string(index=False))
