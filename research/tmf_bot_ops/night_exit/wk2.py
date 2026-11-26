exec(open('wk.py',encoding='utf-8').read().split("def rep")[0])
D=R[R.wk&(R.side=='S')]; print(D[D.lots>=3][['d','fav','lots','gap','HA']].to_string(index=False))
x=D.sort_values('HA',ascending=False); print('前2大',x.HA.head(2).sum().round(1),'扣掉前2大後',x.HA.iloc[2:].sum().round(1),'走較好',(x.HA.iloc[2:]<0).mean().round(2))
