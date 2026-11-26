import pandas as pd, glob
w=pd.read_csv('vm_logs/webhook_raw.csv',encoding='utf-8-sig')
w=w[w.decision.astype(str).str.startswith('EXECUTED')].copy()
w['t']=pd.to_datetime(w.tv_timestamp,utc=True,errors='coerce').dt.tz_convert('Asia/Taipei').dt.tz_localize(None)
w['sig']=w.order_comment.astype(str)
def tv(p):
    df=pd.read_csv(glob.glob('tv_exports/'+p)[0],encoding='utf-8-sig'); df['t']=pd.to_datetime(df['日期和時間'],errors='coerce')
    df['sig']=df['訊號'].astype(str); return df[df.t.notna()][['t','sig','類型']]
lo,hi=w.t.min(),w.t.max()
print('live window',lo,hi,'live executed alerts',len(w))
out={}
for name,p in [('onfills','*onfills.csv'),('barclose','*barclose_only.csv'),('v26','V38.0623_v26*.csv')]:
    d=tv(p); d=d[(d.t>=lo-pd.Timedelta('5min'))&(d.t<=hi)]
    # TV rows are per lot; alerts are per order event. collapse TV to unique (t,sig)
    ev=d.drop_duplicates(['t','sig'])
    L=set(zip(w.t,w.sig)); T=set(zip(ev.t,ev.sig))
    # tolerant match: same sig within 5 min
    def tol(A,B):
        Bd={}
        for t,s in B: Bd.setdefault(s,[]).append(t)
        n=0
        for t,s in A:
            if any(abs((t-x).total_seconds())<=300 for x in Bd.get(s,[])): n+=1
        return n
    out[name]=dict(tv_events=len(T),live_events=len(L),exact=len(L&T),live_matched_tol=tol(L,T),tv_matched_tol=tol(T,L))
    if name=='onfills':
        miss=[x for x in T if not any(abs((x[0]-t).total_seconds())<=300 and s==x[1] for t,s in L)]
        m=pd.DataFrame(miss,columns=['t','sig']); print('onfills TV-only events by sig:',m.sig.value_counts().head(12).to_dict())
r=pd.DataFrame(out).T; r['live_match_pct']=(r.live_matched_tol/r.live_events*100).round(1); r['tv_match_pct']=(r.tv_matched_tol/r.tv_events*100).round(1); print(r)
print('live signal names:',w.sig.value_counts().head(25).to_dict())
print('---- by period ----')
per=[('06-23~08-22',lo,pd.Timestamp('2026-08-22 23:59')),('08-23~09-09',pd.Timestamp('2026-08-23'),pd.Timestamp('2026-09-09 23:59')),('09-10~09-23',pd.Timestamp('2026-09-10'),hi)]
for pn,a,b in per:
    ww=w[(w.t>=a)&(w.t<=b)]; L=set(zip(ww.t,ww.sig)); row=[pn,'live',len(L),'G_entries',ww.sig.str.contains('_G_').sum() - ww.sig.str.contains('Cut').sum()]
    for name,p in [('onfills','*onfills.csv'),('barclose','*barclose_only.csv')]:
        d=tv(p); d=d[(d.t>=a)&(d.t<=b)&d['類型'].str.contains('進場')].drop_duplicates(['t','sig'])
        dd=tv(p); dd=dd[(dd.t>=a)&(dd.t<=b)].drop_duplicates(['t','sig'])
        T=set(zip(dd.t,dd.sig))
        m=sum(1 for t,s in L if any(abs((t-x).total_seconds())<=300 and s==y for x,y in T))
        row+= [name,len(T),f'live匹配{m/len(L)*100:.0f}%' if len(L) else '', 'G進場',d.sig.str.contains('_G_').sum()]
    print(row)
