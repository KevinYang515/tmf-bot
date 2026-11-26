import pandas as pd, glob
exec(open('live_vs_tv.py',encoding='utf-8').read().split("lo,hi=")[0])
a,b=w.t.min(),pd.Timestamp('2026-08-22 23:59')
ww=w[(w.t>=a)&(w.t<=b)]
def evs(p):
    d=tv(p); d=d[(d.t>=a-pd.Timedelta('5min'))&(d.t<=b)].drop_duplicates(['t','sig']); return set(zip(d.t,d.sig))
O,B=evs('*onfills.csv'),evs('*barclose_only.csv')
def has(S,t,s): return any(abs((t-x).total_seconds())<=300 and s==y for x,y in S)
c={'both':0,'onfills_only':0,'barclose_only':0,'neither':0}
ex={'onfills_only':[],'barclose_only':[]}
for t,s in zip(ww.t,ww.sig):
    o,bb=has(O,t,s),has(B,t,s)
    k='both' if o and bb else 'onfills_only' if o else 'barclose_only' if bb else 'neither'; c[k]+=1
    if k in ex: ex[k].append((t,s))
print('live events 06-23..08-22:',len(ww),c)
print('onfills-only examples',ex['onfills_only'][:8]); print('barclose-only examples',ex['barclose_only'][:8])
