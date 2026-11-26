"""Exploratory: 夜盤大漲跌後 日盤反向跳空 → 開盤後 5/15/30 分鐘 順跳空方向的走勢（停損連鎖假說）。1分K Close 近似，未模擬分鐘內順序。"""
import pandas as pd, numpy as np
m=pd.read_csv('E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv',parse_dates=['ts'],usecols=['ts','Open','High','Low','Close']).set_index('ts')
h=m.index.hour*60+m.index.minute; isday=(h>=8*60+46)&(h<=13*60+45)
seg=pd.Series(isday,index=m.index); sid=(seg!=seg.shift()).cumsum()
rows=[]; G=list(m.groupby(sid.values))
for i in range(2,len(G)):
    _,d=G[i]; _,n=G[i-1]; _,p=G[i-2]
    if not isday[m.index.get_loc(d.index[0])] or len(d)<60 or len(n)<300: continue
    pc=p.Close.iloc[-1]; nc=n.Close.iloc[-1]; op=d.Open.iloc[0]
    o=d.index[0]; f=lambda k: d.Close.iloc[k-1] if len(d)>=k else np.nan
    rows.append(dict(d=o.normalize(),night=(nc/pc-1)*100,gap=(op/nc-1)*100,op=op,c5=f(5),c15=f(15),c30=f(30),cday=d.Close.iloc[-1],
                     hi15=d.High.iloc[:15].max(),lo15=d.Low.iloc[:15].min()))
D=pd.DataFrame(rows); D['sg']=np.sign(D.gap)
for k in ['c5','c15','c30','cday']: D['r'+k[1:]]=(D[k]-D.op)*D.sg      # 點，順跳空方向為正
D['rev']=np.sign(D.night)!=D.sg; D['y24']=D.d>='2024-01-01'
COST=11  # 手續費稅+滑價 約11點/來回
print('日數',len(D),D.d.min().date(),'~',D.d.max().date(),'| 成本假設',COST,'點')
def rep(x,lab):
    if len(x)<3: print(f'{lab:34s} n={len(x)}'); return
    s=lambda c: f"{x[c].mean():+6.0f}"
    t5=x.r5.mean()/(x.r5.std()/np.sqrt(len(x)))
    print(f"{lab:34s} n={len(x):4d} (24後{x.y24.sum():3d}) 5分{s('r5')} 15分{s('r15')} 30分{s('r30')} 收盤{s('rday')} | 5分順向比例 {(x.r5>0).mean()*100:3.0f}% t5={t5:+.1f} | 24後15分{x[x.y24].r15.mean():+5.0f}")
for N in [1,2,3]:
  for g in [0.3,0.5,1.0]:
    big=D[(D.night.abs()>=N)&(D.gap.abs()>=g)]
    rep(big[big.rev],f'夜盤±{N}% 反向跳空>={g}%')
    rep(big[~big.rev],f'夜盤±{N}% 同向跳空>={g}%')
  print()
rep(D[D.gap.abs()>=0.5],'所有跳空>=0.5%（不分夜盤）')
x=D[(D.night.abs()>=2)&(D.gap.abs()>=0.3)&D.rev].sort_values('d')
print('\n夜盤±2% 反向跳空>=0.3% 明細（點）'); print(x[['d','night','gap','r5','r15','r30','rday']].round(1).to_string(index=False))
