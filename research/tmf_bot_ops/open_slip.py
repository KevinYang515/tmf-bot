import pandas as pd, numpy as np
m=pd.read_csv('E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv',parse_dates=['ts']).set_index('ts').sort_index()
gap=m.index.to_series().diff()>pd.Timedelta(minutes=30); first=m.index[gap.values]   # first 1-min bar of each session (ts = bar end)
# live
d=pd.read_csv('E:/stock/tmf_bot_ops/data/trade_records.csv'); d['when']=pd.to_datetime(d.datetime)
x=d[(d.ticker=='MXF1!')&d.order_status.astype(str).str.contains('Filled')&d.fill_price.notna()].copy()
hm=x.when.dt.hour*60+x.when.dt.minute
x=x[((hm>=525)&(hm<527))|((hm>=900)&(hm<902))].copy()
x['s']=np.where(x.action=='BUY',1,-1)
def sess_open(t):
    f=first[first<=t+pd.Timedelta(minutes=1)]
    return m.loc[f[-1]] if len(f) else None
rows=[]
for _,r in x.iterrows():
    f=first[first<=r.when+pd.Timedelta(minutes=1)][-1]; b=m.loc[f]; nxt=m.loc[f:].iloc[:6]
    rows.append(dict(dt=r.when,act=r.action,q=r.quantity,sig=r.signal_price,fill=r.fill_price,open=b.Open,hi=b.High,lo=b.Low,
        vs_sig=r.s*(r.fill_price-r.signal_price),vs_open=r.s*(r.fill_price-b.Open),
        m1close=r.s*(b.Close-r.fill_price)*-1, m2=r.s*(nxt.Close.iloc[1]-r.fill_price)*-1, m5=r.s*(nxt.Close.iloc[4]-r.fill_price)*-1))
L=pd.DataFrame(rows)
print('live open-minute fills:',len(L)); print(L[['vs_sig','vs_open','m1close','m2','m5']].describe().round(1).to_string())
print('(m1close/m2/m5 = 如果改在第1/2/5分鐘收盤成交，比實際成交 貴(+)/便宜(-) 幾點)')
print(L.sort_values('vs_open').tail(6)[['dt','act','sig','fill','open','hi','lo','vs_sig','vs_open']].to_string(index=False))
# historical: engine entries/exits at session open (all years, base off0)
t=pd.read_csv('E:/stock/v38_v29_snr_20261017/shadow_gates/v30eopt_off0_base_latest.csv',parse_dates=['entry_ts','exit_ts'])
fs=set(first-pd.Timedelta(minutes=1))
ev=[]
for col,sgn in [('entry_ts',1),('exit_ts',-1)]:
    z=t[t[col].isin(fs)]
    for _,r in z.iterrows():
        s=(1 if r.side=='L' else -1)*sgn; f=r[col]; seg=m.loc[f+pd.Timedelta(minutes=1):].iloc[:6]; o=seg.Open.iloc[0]
        ev.append(dict(ts=f,yr=f.year,kind=('entry' if sgn==1 else 'exit'),rng1=seg.High.iloc[0]-seg.Low.iloc[0],
          d1=s*(seg.Close.iloc[0]-o),d2=s*(seg.Close.iloc[1]-o),d3=s*(seg.Close.iloc[2]-o),d5=s*(seg.Close.iloc[4]-o),
          adv1=s*(seg.High.iloc[0]-o) if s>0 else s*(seg.Low.iloc[0]-o)))
E=pd.DataFrame(ev)
print('\nengine orders at session-open minute:',len(E))
print('d_k = 從開盤價到第k分鐘收盤，朝不利方向(+)=晚k分鐘下單要多付的點數')
for lab,z in [('all',E),('2024+',E[E.yr>=2024]),('2026',E[E.yr>=2026])]:
    print(lab,len(z),'d1 %.1f d2 %.1f d3 %.1f d5 %.1f | 第一分鐘振幅中位 %.0f p90 %.0f'%(z.d1.mean(),z.d2.mean(),z.d3.mean(),z.d5.mean(),z.rng1.median(),z.rng1.quantile(.9)))
print(E[E.yr>=2024].groupby('kind')[['d1','d2','d5']].mean().round(1).to_string())
print('\n--- live open fills detail ---')
pc=[]
for _,r in L.iterrows():
    f=first[first<=r.dt+pd.Timedelta(minutes=1)][-1]; prev=m.loc[:f-pd.Timedelta(minutes=1)].Close.iloc[-1]; pc.append(prev)
L['prevC']=pc
w=pd.read_csv('E:/stock/tmf_bot_ops/data/webhook_raw_open.csv') if False else None
print(L[['dt','act','sig','prevC','open','fill','vs_open','m5']].to_string(index=False))
