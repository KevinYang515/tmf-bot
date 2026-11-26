"""Exploratory (not a formal test): extreme intraday moves vs prev day-session close; hold vs exit at threshold."""
import pandas as pd, numpy as np
pd.set_option('display.width',220)
SD='E:/stock/v38_v29_snr_20261017/shadow_gates/'
m=pd.read_csv(SD+'mxf_1min_live.csv',parse_dates=['ts'],usecols=['ts','Close']).set_index('ts').Close
h=m.index.hour*60+m.index.minute
td=(m.index+pd.to_timedelta(np.where(m.index.hour>=15,9,0),unit='h')).normalize()
day=m[(h>=8*60+46)&(h<=13*60+45)]
dclose=day.groupby(day.index.normalize()).last()           # day-session close ~ settlement
ref=pd.Series(dclose.shift(1).reindex(td).values,index=m.index)  # previous trading day's day-session close
# for night bars (td = next day), prev day-session close is the same calendar day's close -> handled because td is next day
mv=(m/ref-1)*100
D=pd.DataFrame({'mv':mv,'td':td}).dropna()
g=D.groupby('td').mv; daily=pd.DataFrame({'low':g.min(),'high':g.max(),'close':g.last()})
# --- crash-level context ---
c=dclose; peak=c.cummax(); ddn=(c/peak-1)*100
print('=== 日盤收盤距前高回檔 (各段最深) ===')
for a,b in [('2020-02','2020-04'),('2022-01','2022-12'),('2024-07','2024-09'),('2025-03','2025-05'),('2026-01','2026-12')]:
    z=ddn[a:b]; print(f'{a}~{b}: 最深 {z.min():6.1f}% 於 {z.idxmin().date()}  高點 {peak[z.idxmin()]:.0f}')
print('近 15 日 日盤收盤與日漲跌%:'); print(pd.DataFrame({'close':c,'ret%':c.pct_change()*100,'回檔%':ddn}).tail(15).round(1).to_string())
print('\n=== 盤中距昨日收盤最大跌幅 ≤ -X% 的天數（2020/3~2026/11/20 早上）===')
for X in [4,5,6,7,8,9]:
    z=daily[daily.low<=-X]; print(f'-{X}%: {len(z):3d} 天  其中 2024後 {len(z["2024":]):3d}')
print('\n跌超過 6% 的日子：當天最低 / 收盤 / 隔日收盤漲跌')
nx=(c.shift(-1)/c-1)*100
z=daily[daily.low<=-6].copy(); z['next']=nx.reindex(z.index).values; print(z.round(1).to_string())
# --- hold vs exit at threshold, engine lots ---
t=pd.read_pickle(SD+'trades_gated.pkl'); t['entry_ts']=pd.to_datetime(t.entry_ts); t['exit_ts']=pd.to_datetime(t.exit_ts)
mvs=mv.dropna()
print('\n=== 引擎部位：當日跌(漲)到 X% 時若立刻出場 vs 照原規則續抱 ===')
print('差額 = 續抱 - 立刻出場（點數×50，未扣成本）；正 = 續抱較好')
for side,sg in [('S',-1),('L',1)]:
    for X in [4,5,6,7]:
        hit=mvs[(mvs*sg)>=X]
        first=hit.groupby(td[mvs.index.get_indexer(hit.index)] if False else pd.Series(D.td.reindex(hit.index).values,index=hit.index)).apply(lambda s:s.index[0])
        rows=[]
        for d_,ts in first.items():
            px=m.loc[ts]
            op=t[(t.side==side)&(t.entry_ts<ts)&(t.exit_ts>ts)]
            if len(op)==0: continue
            diff=((op.exit_px-px)*(1 if side=='L' else -1)*50).sum()
            rows.append((d_.date(),ts,len(op),diff))
        r=pd.DataFrame(rows,columns=['td','hit','lots','diff'])
        if len(r)==0: print(side,X,'無'); continue
        print(f"{'空' if side=='S' else '多'}單 {X}%: 事件 {len(r):3d} 天, 部位 {r.lots.sum():3d} 口, 續抱-出場 合計 {r['diff'].sum()/1e4:+7.1f}萬, 續抱較好天數 {(r['diff']>0).sum()}/{len(r)}, 2024後 {r[r.td>=pd.Timestamp('2024-01-01').date()]['diff'].sum()/1e4:+.1f}萬")
        if X==6: print(r.assign(diff=(r['diff']/1e4).round(2)).to_string(index=False))
