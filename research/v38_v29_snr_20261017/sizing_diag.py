# 大賺後保守 / 大虧後積極：依前一日為止的 v28 狀態決定隔日口數（日損益線性縮放近似）
import pandas as pd, numpy as np
P=pd.read_csv('br_daily_pnl.csv',parse_dates=['day']); P=P[(P.variant=='v28')&(P.definition=='BD1')].set_index('day').net.sort_index()
eq=P.cumsum(); dd=eq-eq.cummax()
r20=P.rolling(20).sum()
def pct(s):  # expanding 分位（只用過去），前 120 天=NaN
    return s.expanding(120).apply(lambda x:(x[:-1]<x[-1]).mean() if len(x)>1 else np.nan,raw=True)
q20=pct(r20).shift(1)                      # 前一日為止
ddn=(dd/P.rolling(250,min_periods=120).std()).shift(1)   # 回撤深度（以日損益標準差衡量）
S={'S0 固定1口':pd.Series(1.0,P.index),
   'S1 大賺後保守(近20日前20%→0.5)':np.where(q20>0.8,0.5,1.0),
   'S2 大虧後積極(近20日後20%→1.5)':np.where(q20<0.2,1.5,1.0),
   'S3 兩者都做':np.where(q20>0.8,0.5,np.where(q20<0.2,1.5,1.0)),
   'S4 反向:賺加碼虧減碼':np.where(q20>0.8,1.5,np.where(q20<0.2,0.5,1.0)),
   'S5 深回撤加碼(回撤>5σ→1.5)':np.where(ddn<-5,1.5,1.0),
   'S6 深回撤減碼(回撤>5σ→0.5)':np.where(ddn<-5,0.5,1.0)}
def mdd(p): e=p.cumsum(); return (e-e.cummax()).min()
rows=[]
for k,w in S.items():
    w=pd.Series(w,P.index).fillna(1.0); p=P*w
    r={'規則':k,'平均口數':round(w.mean(),2)}
    for lab,lo,hi in [('全期','2020','2027'),('2020-23','2020','2024'),('2024-26','2024','2027')]:
        s=p[(p.index>=lo)&(p.index<hi)]; ww=w[(w.index>=lo)&(w.index<hi)]
        r[lab+'淨利']=round(s.sum()/1e4,1); r[lab+'MDD']=round(mdd(s)/1e4,1)
        r[lab+'每口淨利/MDD']=round((s.sum()/ww.mean())/-(mdd(s)/ww.mean()),2)
    rows.append(r)
R=pd.DataFrame(rows); R.to_csv('sizing_diag.csv',index=False,encoding='utf-8-sig'); print(R.to_string(index=False))
# 下一期條件平均
X=pd.DataFrame({'q':q20,'y20':P[::-1].rolling(20).sum()[::-1].shift(-1),'y1':P}).dropna()
for lab,lo,hi in [('2020-23','2020','2024'),('2024-26','2024','2027')]:
    s=X[(X.index>=lo)&(X.index<hi)]; print(lab,(s.groupby(pd.cut(s.q,[0,.2,.4,.6,.8,1.0],include_lowest=True)).y1.mean()/1e3).round(1).to_dict())
