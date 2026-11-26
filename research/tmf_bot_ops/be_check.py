import pandas as pd, numpy as np
t=pd.read_csv('E:/stock/v38_v29_snr_20261017/tv_exports/tv_v30e_trades_parsed_20261106.csv'); sig=t.columns[3]
t['entry_ts']=pd.to_datetime(t.entry_ts); t['exit_ts']=pd.to_datetime(t.exit_ts)
m=pd.read_csv('E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv',parse_dates=['ts']).set_index('ts')
o=m.index-pd.Timedelta(minutes=1)
b=m.groupby(o.floor('5min')).agg(H=('High','max'),L=('Low','min'),C=('Close','last'))
tr=pd.concat([b.H-b.L,(b.H-b.C.shift()).abs(),(b.L-b.C.shift()).abs()],axis=1).max(axis=1); b['atr']=tr.ewm(alpha=1/14,adjust=False).mean()
def arm_bar(r):
    s=1 if r.side=='L' else -1; e=r.entry_ts
    prev=b.loc[:e-pd.Timedelta(minutes=1)]
    if prev.empty: return np.nan
    atr=prev.atr.iloc[-1]; seg=b.loc[e:r.exit_ts]
    hit=np.where(s*(seg.C.values-r.entry_px)>2*atr)[0]
    return hit[0] if len(hit) else -1
cmd=t[t.esig.isin(['L_Cmd','S_Cmd'])].copy()
cmd['arm']=cmd.apply(arm_bar,axis=1)
cmd['isBE']=cmd[sig].isin(['L_BE','S_BE'])
print('TV BE exits: arm bar index (0=entry bar):'); print(cmd[cmd.isBE][['entry_ts','side',sig,'arm']].to_string(index=False))
armed=cmd[cmd.arm>=0]
print('\nCmd trades where BE should have armed:',len(armed))
print(armed.groupby(armed.arm.clip(upper=3))['isBE'].agg(['size','sum']).rename(index={3:'>=3'}).to_string())
