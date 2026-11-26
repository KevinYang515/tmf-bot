"""Exploratory: near limit-down (>=6..9% vs prev day close). Hold vs exit at hit; risk after hit. Data via shadow live csv."""
import pandas as pd, numpy as np
SD='E:/stock/v38_v29_snr_20261017/shadow_gates/'
m=pd.read_csv(SD+'mxf_1min_live.csv',parse_dates=['ts'],usecols=['ts','High','Low','Close']).set_index('ts')
C=m.Close; h=C.index.hour*60+C.index.minute
td=pd.Series((C.index+pd.to_timedelta(np.where(C.index.hour>=15,9,0),unit='h')).normalize(),index=C.index)
day=C[(h>=8*60+46)&(h<=13*60+45)]; dclose=day.groupby(day.index.normalize()).last()
ref=pd.Series(dclose.shift(1).reindex(td.values).values,index=C.index)
mv=((C/ref-1)*100).dropna()
print('資料最後一根:',C.index[-1])
t=pd.read_pickle(SD+'trades_gated.pkl'); t['entry_ts']=pd.to_datetime(t.entry_ts); t['exit_ts']=pd.to_datetime(t.exit_ts)
nx=(dclose.shift(-1)/dclose-1)*100
for X in [6,7,8,9]:
    hit=mv[mv<=-X]; first=hit.groupby(td.reindex(hit.index).values).apply(lambda s:s.index[0])
    rows=[]
    for d_,ts in first.items():
        px=C.loc[ts]; r0=ref.loc[ts]; room=(px-r0*0.9)
        op=t[(t.side=='S')&(t.entry_ts<ts)&(t.exit_ts>ts)]
        dc=dclose.get(d_,np.nan)
        if len(op)==0: rows.append((d_.date(),ts.strftime('%m-%d %H:%M'),0,np.nan,np.nan,room,(dc/r0-1)*100,nx.get(d_,np.nan))); continue
        diff=((px-op.exit_px)*50).sum()
        mae=max(m.High[ts:e].max()-px for e in op.exit_ts)   # worst rebound vs hit price while any lot still held
        rows.append((d_.date(),ts.strftime('%m-%d %H:%M'),len(op),diff/1e4,mae,room,(dc/r0-1)*100,nx.get(d_,np.nan)))
    r=pd.DataFrame(rows,columns=['日','觸發','口','續抱-出場萬','觸發後最大反彈點','距跌停剩點','當日收%','隔日%'])
    w=r[r['口']>0]
    print(f'\n=== 跌 {X}% 觸發: {len(r)} 天，有空單 {len(w)} 天；續抱-出場 合計 {w["續抱-出場萬"].sum():+.1f}萬，續抱較好 {(w["續抱-出場萬"]>0).sum()}/{len(w)} ===')
    print(r.round(1).to_string(index=False))
