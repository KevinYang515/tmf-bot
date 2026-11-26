import pandas as pd, numpy as np
a=pd.read_pickle("adds.pkl").sort_values("entry_ts")
SD="E:/stock/v38_v29_snr_20261017/shadow_gates/"
t=pd.read_csv(SD+"v30eopt_off0_base_latest.csv",parse_dates=["entry_ts","exit_ts"]).sort_values("entry_ts").reset_index(drop=True)
# extra features
a["時"]=a.entry_ts.dt.hour; a["週"]=a.entry_ts.dt.dayofweek
a["振幅組"]=pd.cut(a["振幅20%"],[0,1.3,1.8,2.5,99],labels=["<1.3","1.3-1.8","1.8-2.5",">2.5"]).astype(str)
a["時段"]=pd.cut((a.entry_ts.dt.hour*60+a.entry_ts.dt.minute+15*60)%(24*60),[0,6*60,10*60,14*60,24*60],labels=["15-21夜前","21-01夜中","01-05夜尾","日盤"],include_lowest=True).astype(str)
# same-campaign: how many earlier lots in campaign already closed at a loss before this add
prev=[]
for i,r in a.iterrows():
    c=t[(t.index<i)&(t.exit_ts<=r.entry_ts)&(t.entry_ts>=r.entry_ts-pd.Timedelta(days=5))&(t.side==r.side)]
    prev.append(int((c.pnl<0).sum()>0))
a["近期同向停損過"]=prev
a["跨盤"]=np.where(a.entry_ts.dt.normalize()!=a.exit_ts.dt.normalize(),"跨日","同日")
def tab(rows,cols=None):
    g=a.groupby([rows]+([cols] if cols else [])+["seg"]).agg(n=("bp","size"),bp=("bp","mean")).unstack("seg")
    return g.round(1)
pd.set_option("display.width",220)
for f in ["時段","週","近期同向停損過"]:
    print(f"\n### {f}"); print(tab(f).to_string())
for r,c in [("第幾口","振幅組"),("第幾口","時段"),("第幾口","順向走幅Q"),("振幅組","時段"),("side","振幅組")]:
    if c=="順向走幅Q": a["順向走幅Q"]=pd.qcut(a["順向走幅%"],4,labels=["低","中低","中高","高"]).astype(str)
    print(f"\n### {r} × {c}"); print(tab(r,c).to_string())
# decision tree train 20-23, test 24+
from sklearn.tree import DecisionTreeRegressor, export_text
X=pd.get_dummies(a[["第幾口","振幅20%","順向走幅%","距首單h","距MA20%","前日漲跌%","今日距昨收%","時","週","近期同向停損過"]].assign(side=(a.side=="S").astype(int)),dtype=float)
tr=a.seg=="訓練20-23"
m=DecisionTreeRegressor(max_depth=3,min_samples_leaf=80,random_state=0).fit(X[tr],a.bp[tr])
print("\n### 決策樹(訓練20-23)"); print(export_text(m,feature_names=list(X.columns)))
a["leaf"]=m.apply(X)
L=a.groupby(["leaf","seg"]).agg(n=("bp","size"),bp=("bp","mean")).unstack("seg").round(1); print(L.to_string())
a.to_pickle("adds2.pkl")
