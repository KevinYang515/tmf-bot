import pandas as pd, numpy as np
m=pd.read_csv('E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv',parse_dates=['ts'],usecols=['ts','Open','High','Low','Close']).set_index('ts')
m=m[m.index<'2026-11-21']
h=m.index.hour*60+m.index.minute
day=m[(h>=8*60+46)&(h<=13*60+45)]; n05=m[(m.index.hour==5)&(m.index.minute==0)]
rows=[]
for d,g in day.groupby(day.index.normalize()):
    if len(g)<20 or g.index[0].strftime('%H:%M')!='08:46': continue
    r=n05[n05.index<g.index[0]]
    if r.empty: continue
    rt=r.index[-1]; ref=r.Close.iloc[-1]; stale=(d-rt.normalize()).days
    if stale>6: continue
    op=g.Open.iloc[0]; gap=(op/ref-1)*100
    if abs(gap)<0.5: continue
    s=np.sign(gap); cost=11/op*100
    tp=op*(1+s*0.002); sl=op*(1-s*0.00075); res=None
    for i in range(min(5,len(g))):
        hi,lo=g.High.iloc[i],g.Low.iloc[i]
        if (s>0 and lo<=sl) or (s<0 and hi>=sl): res=-0.075; break
        if (s>0 and hi>=tp) or (s<0 and lo<=tp): res=0.20; break
    if res is None: res=(g.Close.iloc[4]/op-1)*100*s
    rows.append(dict(d=d,wk=stale>=2,gap=gap,A=res-cost,B=(g.Close.iloc[4]/op-1)*100*s-cost,C=(g.Close.iloc[14]/op-1)*100*s-cost,
                     cost=cost))
D=pd.DataFrame(rows); D['era']=np.where(D.d>='2024-01-01','2024+','2020-23')
print('事件',len(D),'| 週一/連假',D.wk.sum(),'| 期間',D.d.min().date(),'~',D.d.max().date())
def rep(x,lab):
    if len(x)==0: print(lab,'n=0'); return
    t=lambda c: x[c].mean()/(x[c].std(ddof=1)/np.sqrt(len(x))) if len(x)>2 else np.nan
    print(f"{lab:26s} n={len(x):3d} | A(TP/停損) {x.A.mean()*100:+6.1f}bp 勝{(x.A>0).mean()*100:3.0f}% t={t('A'):+.1f} | B(5分) {x.B.mean()*100:+6.1f}bp t={t('B'):+.1f} | C(15分) {x.C.mean()*100:+6.1f}bp t={t('C'):+.1f}")
print('（bp=萬分之一，已扣成本；4萬點時 1bp≈4點）')
for era in ['2020-23','2024+']:
    for wk,nm in [(False,'平日'),(True,'週一/連假後')]:
        rep(D[(D.era==era)&(D.wk==wk)],f'{era} {nm}')
for wk,nm in [(False,'平日'),(True,'週一/連假後')]:
    rep(D[D.wk==wk],f'全期 {nm}')
    for lo,hi in [(0.5,1),(1,2),(2,99)]:
        rep(D[(D.wk==wk)&(D.gap.abs()>=lo)&(D.gap.abs()<hi)],f'   {nm} gap {lo}-{hi}%')
W=D[D.wk&(D.era=='2024+')].sort_values('d'); print('\n2024+ 週一/連假後明細'); print(W.assign(d=W.d.dt.date)[['d','gap','A','B','C']].round(2).to_string(index=False))
# 判定
ok=[]
for era in ['2020-23','2024+']:
    x=D[(D.era==era)&D.wk]; ok.append(len(x)>=15 and x.A.mean()>0)
x24w=D[(D.era=='2024+')&D.wk].A.mean(); x24d=D[(D.era=='2024+')&~D.wk].A.mean()
ok.append(x24w>=0.5*x24d if x24d>0 else x24w>0)
print('\n預登記判定:', '通過→可開放週一' if all(ok) else f'不通過（條件 {ok}）→ 維持週一不做')
