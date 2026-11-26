import pandas as pd, numpy as np
SD='E:/stock/v38_v29_snr_20261017/shadow_gates/'
m=pd.read_csv(SD+'mxf_1min_live.csv',parse_dates=['ts'],usecols=['ts','Open','Close']).set_index('ts')
h=m.index.hour*60+m.index.minute
isday=(h>=8*60+46)&(h<=13*60+45); isnight=~isday
seg=(pd.Series(isday,index=m.index)!=pd.Series(isday,index=m.index).shift()).cumsum()
g=m.groupby(seg.values); S=pd.DataFrame({'start':g.apply(lambda x:x.index[0]),'end':g.apply(lambda x:x.index[-1]),
  'open':g.Open.first(),'close':g.Close.last(),'day':g.apply(lambda x:isday[m.index.get_loc(x.index[0])])}).reset_index(drop=True)
rows=[]
for i in range(1,len(S)-1):
    n=S.iloc[i]
    if n.day or not S.iloc[i-1].day or not S.iloc[i+1].day: continue
    if (n.end-n.start)<pd.Timedelta(hours=10): continue        # full night only
    ref=S.iloc[i-1].close; nxt=S.iloc[i+1]
    rows.append(dict(nend=n.end,mv=(n.close/ref-1)*100,pxN=n.close,pxO=nxt.open,
      wkend=(nxt.start-n.end)>pd.Timedelta(days=1),nday=(S.iloc[i+2].close/nxt.open-1)*100 if i+2<len(S) and S.iloc[i+2].day==False and i+3<len(S) else np.nan))
N=pd.DataFrame(rows); N=N[N.nend<'2026-11-21']
t=pd.read_pickle(SD+'trades_gated.pkl'); t['entry_ts']=pd.to_datetime(t.entry_ts); t['exit_ts']=pd.to_datetime(t.exit_ts)
print('夜盤數',len(N),'期間',N.nend.min().date(),'~',N.nend.max().date())
out=[]
for side,sg,nm in [('S',-1,'空單/夜盤跌'),('L',1,'多單/夜盤漲')]:
  print(f'\n######## {nm} ########')
  for X in [2,3,4,5]:
    E=[]
    for _,r in N[N.mv*sg>=X].iterrows():
        op=t[(t.side==side)&(t.entry_ts<=r.nend)&(t.exit_ts>r.nend)]
        if len(op)==0: continue
        k=-sg  # short: profit = entry-exit
        HA=((r.pxN-op.exit_px)*(-k)*50).sum() if False else ((op.exit_px-r.pxN)*sg*50).sum()
        HB=((op.exit_px-r.pxO)*sg*50).sum()
        E.append(dict(夜盤結束=r.nend.strftime('%Y-%m-%d'),夜盤漲跌=round(r.mv,1),口=len(op),跳空到開盤點=r.pxO-r.pxN,
          續抱減夜盤走萬=HA/1e4,續抱減開盤走萬=HB/1e4,週末長假=r.wkend))
    E=pd.DataFrame(E)
    if E.empty: print(X,'無'); continue
    y=pd.to_datetime(E.夜盤結束)>='2024-01-01'
    s=lambda c,msk=slice(None):E.loc[msk,c].sum()
    w=E.週末長假
    print(f"\n-- 夜盤{'跌' if sg<0 else '漲'} >= {X}%: {len(E)} 晚 ({y.sum()} 晚在2024後, 週末/長假 {w.sum()}) --")
    print(f"  續抱 vs 夜盤收盤走: 合計 {s('續抱減夜盤走萬'):+.1f}萬 | 2024後 {s('續抱減夜盤走萬',y):+.1f}萬 | 走較好 {(E.續抱減夜盤走萬<0).sum()}/{len(E)} | 週末/長假 {s('續抱減夜盤走萬',w):+.1f}萬 ({(E[w].續抱減夜盤走萬<0).sum()}/{w.sum()})")
    print(f"  續抱 vs 日盤開盤走: 合計 {s('續抱減開盤走萬'):+.1f}萬 | 2024後 {s('續抱減開盤走萬',y):+.1f}萬 | 走較好 {(E.續抱減開盤走萬<0).sum()}/{len(E)}")
    print(f"  夜盤走 vs 開盤走(=跳空): 合計 {(s('續抱減開盤走萬')-s('續抱減夜盤走萬')):+.1f}萬（正=等開盤較好）")
    out.append((nm,X,len(E),s('續抱減夜盤走萬'),s('續抱減夜盤走萬',y),(E.續抱減夜盤走萬<0).mean()))
    if X==3: print(E.round(2).to_string(index=False))
print('\n=== 預登記判定（空單、多單分開）：夜盤就走 需 H-A<0、2024後<0、走較好>=60%，4門檻中>=3 ===')
for nm in ['空單/夜盤跌','多單/夜盤漲']:
    ok=[o for o in out if o[0]==nm and o[3]<0 and o[4]<0 and o[5]>=0.6]
    print(nm,'成立門檻數',len(ok),'/4 ->','通過(該夜盤就走)' if len(ok)>=3 else '不通過(續抱)')
