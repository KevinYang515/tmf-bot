import pandas as pd, numpy as np
pd.set_option('display.width',220)
SD='E:/stock/v38_v29_snr_20261017/shadow_gates/'
t=pd.read_pickle(SD+'trades_gated.pkl'); t['entry_ts']=pd.to_datetime(t.entry_ts); t['exit_ts']=pd.to_datetime(t.exit_ts)
m=pd.read_csv(SD+'mxf_1min_live.csv',parse_dates=['ts']).set_index('ts')
# trading day: night session belongs to next day; use shift of 15h? simple: date of (ts - 15h + 24h if hour>=15)
td=(m.index+pd.to_timedelta(np.where(m.index.hour>=15,9,0),unit='h')).normalize()
d=m.groupby(td).agg(O=('Open','first'),H=('High','max'),L=('Low','min'),C=('Close','last'))
d['rng']=d.H-d.L; d['rngp']=d.rng/d.C*100; d['ret']=d.C.pct_change()*100
d['oc']=(d.C-d.O)/d.O*100; d['eff']=(d.C-d.O).abs()/d.rng   # trend efficiency
print('=== 市況：每日（交易日含前夜盤）近 20 日 ===')
print(d.tail(20)[['O','H','L','C','rng','rngp','ret','eff']].round(2).to_string())
base=d['2024':'2026-09-30']
print('\n2024~9月 基準: 日振幅%% 中位 %.2f, 75分位 %.2f | 效率中位 %.2f'%(base.rngp.median(),base.rngp.quantile(.75),base.eff.median()))
for a,b in [('2026-10-01','2026-10-31'),('2026-11-01','2026-11-10'),('2026-11-11','2026-11-17')]:
    z=d[a:b]; print(f'{a}~{b}: 日振幅% 中位 {z.rngp.median():.2f}, 累計漲跌 {(z.C.iloc[-1]/z.O.iloc[0]-1)*100:+.1f}%, 效率中位 {z.eff.median():.2f}')
# campaigns
t['td']=(t.entry_ts+pd.to_timedelta(np.where(t.entry_ts.dt.hour>=15,9,0),unit='h')).dt.normalize()
c=t.groupby('cid').agg(t0=('entry_ts','min'),t1=('exit_ts','max'),td=('td','first'),side=('side','first'),lots=('side','size'),
   nadd=('kind',lambda k:(k=='Add').sum()),ng=('kind',lambda k:(k=='G').sum()),pnl=('pnl','sum'),R=('net_R','sum'),
   ex=('exit_sig',lambda s:'/'.join(sorted(set(s)))))
c['cost']=c.pnl-c.R
def summ(z,lab):
    w=z[z.R>0]; l=z[z.R<=0]
    print(f'{lab:28s} n{len(z):4d} 勝率{100*len(w)/max(len(z),1):3.0f}% 淨{z.R.sum()/1e4:+7.1f}萬 均贏{w.R.mean()/1e4 if len(w) else 0:+5.2f} 均輸{l.R.mean()/1e4 if len(l) else 0:+5.2f} 賺賠比{(w.R.mean()/-l.R.mean()) if len(w) and len(l) else np.nan:4.1f} 成本{z.cost.sum()/1e4:5.1f}萬 平均口數{z.lots.mean():.1f}')
print('\n=== campaign 統計 ===')
B=c['2024':'2026-09-30'] if False else c[(c.t0>='2024-01-01')&(c.t0<'2026-10-01')]
summ(B,'基準 2024~2026/9')
for a,b in [('2026-10-01','2026-11-01'),('2026-11-01','2026-11-11'),('2026-11-11 17:00','2026-11-18')]:
    z=c[(c.t0>=a)&(c.t0<b)]; summ(z,f'{a[:10]}~{b[:10]}')
    for s,g in z.groupby('side'): summ(g,'   side '+s)
R=c[c.t0>='2026-11-11 17:00'].copy()
R=R.join(d[['rngp','ret','eff']],on='td')
print('\n=== 11/11 重啟後逐波段 ===')
print(R.assign(R=(R.R/1e4).round(2),pnl=(R.pnl/1e4).round(2),cost=(R.cost/1e4).round(2))[['t0','t1','side','lots','nadd','ng','pnl','cost','R','ex','ret','rngp','eff']].round(2).to_string())
# by leg kind & session since 10/1 vs base
t['sess']=np.where((t.entry_ts.dt.hour>=15)|(t.entry_ts.dt.hour<5),'夜','日')
for lab,z in [('基準',t[(t.entry_ts>='2024-01-01')&(t.entry_ts<'2026-10-01')]),('10/1後',t[t.entry_ts>='2026-10-01']),('11/11後',t[t.entry_ts>='2026-11-11 17:00'])]:
    yrs=1
    print(f'\n--- {lab}: 依腳色/時段 (淨萬, 筆數, 勝率) ---')
    print(z.groupby(['side','kind']).net_R.agg(n='size',net=lambda x:round(x.sum()/1e4,1),win=lambda x:round(100*(x>0).mean()),avg=lambda x:round(x.mean()/1e4,2)).to_string())
    print(z.groupby('sess').net_R.agg(n='size',net=lambda x:round(x.sum()/1e4,1),win=lambda x:round(100*(x>0).mean())).to_string())
    print(z.groupby('exit_sig').net_R.agg(n='size',net=lambda x:round(x.sum()/1e4,1)).sort_values('net').to_string())

print('\n=== 歷史對照（2024~）：依當日振幅、趨勢效率、多空市況 ===')
H=c[c.t0>='2024-01-01'].join(d[['rngp','eff']],on='td')
dd=d.copy(); dd['ma20']=dd.C.rolling(20).mean(); dd['bear']=(dd.C.shift(1)<dd.ma20.shift(1))  # 前一日收盤在月線下
H=H.join(dd['bear'],on='td')
H['rb']=pd.cut(H.rngp,[0,1.5,2.5,4,100],labels=['<1.5%','1.5-2.5%','2.5-4%','>4%'])
H['eb']=pd.cut(H.eff,[0,.3,.6,1.01],labels=['盤整<.3','中.3-.6','趨勢>.6'])
f=lambda x: pd.Series({'n':len(x),'net萬':round(x.sum()/1e4,1),'均萬':round(x.mean()/1e4,2),'std萬':round(x.std()/1e4,2),'勝率':round(100*(x>0).mean())})
print(H.groupby('rb',observed=True).R.apply(f).unstack().to_string())
print(H.groupby('eb',observed=True).R.apply(f).unstack().to_string())
print(H.groupby(['bear','side'],observed=True).R.apply(f).unstack().to_string())
print(H.groupby(['rb','side'],observed=True).R.apply(f).unstack().to_string())
