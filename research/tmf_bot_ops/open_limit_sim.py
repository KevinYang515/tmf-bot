import pandas as pd, numpy as np
m=pd.read_csv('E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv',parse_dates=['ts']).set_index('ts').sort_index()
gap=m.index.to_series().diff()>pd.Timedelta(minutes=30); first=m.index[gap.values]
d=pd.read_csv('E:/stock/tmf_bot_ops/data/trade_records.csv'); d['when']=pd.to_datetime(d.datetime)
x=d[(d.ticker=='MXF1!')&d.order_status.astype(str).str.contains('Filled')&d.fill_price.notna()].copy()
hm=x.when.dt.hour*60+x.when.dt.minute; x=x[((hm>=525)&(hm<527))|((hm>=900)&(hm<902))]
print('open-minute fills', len(x), 'lots', x.quantity.sum(), 'cost vs TV price (pts·lot):', round(((np.where(x.action=='BUY',1,-1))*(x.fill_price-x.signal_price)*x.quantity).sum()))
for band in [20,40,60,100]:
  for wait in [1,2]:
    tot_act=tot_sim=0; nfill=0
    for _,r in x.iterrows():
        s=1 if r.action=='BUY' else -1; f=first[first<=r.when+pd.Timedelta(minutes=1)][-1]
        seg=m.loc[f:].iloc[:wait+1]; lim=r.signal_price+s*band
        # limit live during first `wait` minutes (approx: touched if the bar traded at/better than limit)
        w=seg.iloc[:wait]; hit=(w.Low<=lim).any() if s>0 else (w.High>=lim).any()
        if hit:
            # fill at limit or better: assume at limit if the bar opened worse, else at bar open (conservative = limit)
            px=lim; nfill+=1
        else:
            px=seg.Close.iloc[wait-1]+s*10   # fallback: market after wait minutes, +10 pts impact
        tot_sim+=s*(px-r.signal_price)*r.quantity; tot_act+=s*(r.fill_price-r.signal_price)*r.quantity
    print(f'band {band:3d} wait {wait}m: limit filled {nfill}/{len(x)}  actual {tot_act:+.0f} pts  sim {tot_sim:+.0f} pts  diff {tot_sim-tot_act:+.0f} pts (= {50*(tot_sim-tot_act):+,.0f} NT)')
