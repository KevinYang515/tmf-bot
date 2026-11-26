# PTT-style equity-based sizing test on V38 v28 engine trades (realistic cost 40/side + 4 ticks/side)
import pandas as pd, numpy as np, glob
def daily_from_engine(f):
    t=pd.read_csv(f,parse_dates=['entry_ts','exit_ts']); t['net']=t.pnl-40-400  # engine pnl already -40 RT; to 40/side+4tick: extra 40+400
    return t.groupby(t.exit_ts.dt.normalize()).net.sum()
def daily_from_tv(f):
    df=pd.read_csv(f,encoding='utf-8-sig'); df['dt']=pd.to_datetime(df['日期和時間'],errors='coerce')
    df['p']=pd.to_numeric(df['淨損益 TWD'].astype(str).str.replace(',',''),errors='coerce')
    x=df[df['類型'].str.contains('出場')&df.dt.notna()]; return x.groupby(x.dt.dt.normalize()).p.sum()
series={'engine_v28':daily_from_engine('v26cmp_trades_v28.csv'),'tv_v27_barclose':daily_from_tv(glob.glob('tv_exports/*barclose_only.csv')[0])}
def sim(d,rule,X):
    eq=0;peak=0;trough=0;mult=[];out=[]
    for v in d.values:
        dd=peak-eq; up=eq-trough
        if rule=='const': m=1
        elif rule=='add_in_dd':   m=1+min(2,int(dd//X))            # PTT: lose to X -> 2x, 2X -> 3x
        elif rule=='cut_in_dd':   m=0.5 if dd>=X else 1           # classic equity-curve risk reduction
        elif rule=='ptt_both':    m=(1+min(2,int(dd//X))) if dd>0 else (0.5 if up>=2*X else 1)
        mult.append(m); out.append(m*v)
        eq+=v; peak=max(peak,eq)
        if eq==peak: trough=eq
        trough=min(trough,eq) if eq<peak else trough
    o=pd.Series(out,index=d.index); c=o.cumsum(); mdd=(c-c.cummax()).min()
    return o.sum(),mdd,np.mean(mult),o
rows=[]
for nm,d in series.items():
    d=d.sort_index()
    ac=[d.resample('W').sum().autocorr(1), d.resample('ME').sum().autocorr(1)]
    print(nm,'weekly/monthly PnL autocorr',np.round(ac,3))
    for X in [100000,150000,200000]:
        for rule in ['const','add_in_dd','cut_in_dd','ptt_both']:
            if rule=='const' and X!=100000: continue
            net,mdd,avgm,o=sim(d,rule,X)
            # exposure-matched constant benchmark: same average multiplier
            c=(d*avgm).cumsum(); bmdd=(c-c.cummax()).min()
            h1=o[o.index<'2025-04-01'].sum()-(d[d.index<'2025-04-01']*avgm).sum()
            h2=o[o.index>='2025-04-01'].sum()-(d[d.index>='2025-04-01']*avgm).sum()
            rows.append(dict(series=nm,rule=rule,X=X,net=round(net),mdd=round(mdd),ret_mdd=round(net/-mdd,2),avg_mult=round(avgm,2),
                 matched_const_ret_mdd=round(d.sum()*avgm/-bmdd,2),delta_vs_matched_H1=round(h1),delta_vs_matched_H2=round(h2)))
r=pd.DataFrame(rows); print(r.to_string()); r.to_csv('sizing_ptt_results.csv',index=False,encoding='utf-8-sig')
