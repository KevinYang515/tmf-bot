import pandas as pd, glob
def load(f):
    df=pd.read_csv(f,encoding='utf-8-sig'); df['dt']=pd.to_datetime(df['日期和時間'],errors='coerce')
    for c in ['價格 TWD','淨損益 TWD']: df[c]=pd.to_numeric(df[c].astype(str).str.replace(',',''),errors='coerce')
    ex=df[df['類型'].str.contains('出場')&df.dt.notna()].copy(); en=df[df['類型'].str.contains('進場')].set_index('交易編號')
    ex['entry_ts']=ex['交易編號'].map(en['dt']); ex['side']=ex['類型'].str.contains('多').map({True:'L',False:'S'})
    ex['kind']=ex['交易編號'].map(en['訊號']).str.extract(r'_(Cmd|Add|G)')[0]
    return ex.rename(columns={'淨損益 TWD':'pnl'})
A=load(glob.glob('tv_exports/*onfills.csv')[0]); B=load(glob.glob('tv_exports/*barclose_only.csv')[0])
E=pd.read_csv('trades_v27.csv',parse_dates=['entry_ts'])
print('全期 by year (net, n):')
y=pd.DataFrame({'onfills':A.groupby(A.entry_ts.dt.year).pnl.sum(),'barclose':B.groupby(B.entry_ts.dt.year).pnl.sum(),
 'n_on':A.groupby(A.entry_ts.dt.year).size(),'n_bc':B.groupby(B.entry_ts.dt.year).size()}); print(y); print(y.sum())
for nm,d in [('onfills',A),('barclose',B)]:
    e=d.sort_values('dt'); eq=e.pnl.cumsum(); print(nm,'closed MDD',(eq-eq.cummax()).min())
lo,hi=E.entry_ts.min(),E.entry_ts.max()
def key(d,c): 
    d=d[(d[c]>=lo)&(d[c]<=hi)].copy(); d['k']=d[c].astype(str)+d.side; return d
a,b,e=key(A,'entry_ts'),key(B,'entry_ts'),key(E,'entry_ts')
for n1,x in [('onfills',a),('barclose',b)]:
    c=len(set(x.k)&set(e.k)); print(f'{n1} vs engine: TV {len(x)} ENG {len(e)} common {c} ({c/len(x):.1%} of TV, {c/len(e):.1%} of ENG)')
print('onfills vs barclose common',len(set(a.k)&set(b.k)))
Q=lambda s:s.dt.to_period('Q')
q=pd.DataFrame({'onfills':a.groupby(Q(a.entry_ts)).pnl.sum(),'barclose':b.groupby(Q(b.entry_ts)).pnl.sum(),'engine':e.groupby(Q(e.entry_ts)).pnl.sum()}); print(q)
print('kind counts overlap', a.kind.value_counts().to_dict(), b.kind.value_counts().to_dict(), e.kind.value_counts().to_dict())
