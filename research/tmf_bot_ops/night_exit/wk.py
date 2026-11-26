exec(open('run.py',encoding='utf-8').read().split("print('夜盤數'")[0])
R=[]
for _,r in N.iterrows():
    op=t[(t.entry_ts<=r.nend)&(t.exit_ts>r.nend)]
    for side,sg in [('S',-1),('L',1)]:
        o=op[op.side==side]
        if len(o)==0: continue
        R.append(dict(d=r.nend,side=side,wk=r.wkend,fav=r.mv*sg,lots=len(o),gap=(r.pxO-r.pxN)*sg,
          HA=((o.exit_px-r.pxN)*sg*50).sum()/1e4))
R=pd.DataFrame(R); R['y24']=R.d>='2024-01-01'
def rep(df,lab):
    if len(df)==0: print(f'{lab:28s}  無'); return
    print(f"{lab:28s} {len(df):4d}晚 續抱-走 {df.HA.sum():+7.1f}萬 (2024後 {df[df.y24].HA.sum():+6.1f}) 走較好 {(df.HA<0).mean()*100:3.0f}% 平均跳空(順向+) {df.gap.mean()*1:+5.0f}點 最差一晚 {df.HA.min():+5.1f}萬")
for side,nm in [('S','空單'),('L','多單')]:
  print(f'\n##### {nm}：夜盤收盤就走 vs 續抱 #####')
  for wk,wn in [(True,'週末/長假'),(False,'平日')]:
    D=R[(R.side==side)&(R.wk==wk)]
    rep(D,f'{wn} 全部')
    rep(D[D.fav>=1],f'{wn} 夜盤順向>=1%(對部位有利)')
    rep(D[D.fav>=2],f'{wn} 夜盤順向>=2%')
    rep(D[D.fav<=-1],f'{wn} 夜盤逆向>=1%(對部位不利)')
    rep(D[D.lots>=3],f'{wn} 持有>=3口')
W=R[R.wk&(R.side=='S')&(R.fav>=1)].sort_values('d'); print('\n週末 空單 夜盤跌>=1% 明細'); print(W[['d','fav','lots','gap','HA']].round(2).to_string(index=False))
