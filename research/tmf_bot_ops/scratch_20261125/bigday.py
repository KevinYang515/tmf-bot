import pandas as pd, numpy as np, sys
SD="E:/stock/v38_v29_snr_20261017/shadow_gates/"
m=pd.read_csv(SD+"mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index()
m=m[m.index>="2020-03-02"]
t=pd.read_csv(SD+"v30eopt_off0_base_latest.csv",parse_dates=["entry_ts","exit_ts"])
idx=m.index; pos=np.zeros(len(idx))
sgn=np.where(t.side=="L",1,-1)
a=idx.searchsorted(t.entry_ts.values); b=idx.searchsorted(t.exit_ts.values)
d=np.zeros(len(idx)+1)
np.add.at(d,a,sgn); np.add.at(d,b,-sgn)
pos=np.cumsum(d)[:-1]            # position held during bar after entry bar close
c=m.Close.values; pnl=np.zeros(len(c)); pnl[1:]=pos[:-1]*np.diff(c)*50
td=(idx+pd.Timedelta(hours=9)).normalize()
D=pd.DataFrame({"pnl":pnl,"c":c,"pos":pos},index=idx).groupby(td).agg(pnl=("pnl","sum"),c=("c","last"),maxpos=("pos",lambda x:x.abs().max()),
   start=("pos","first"),end=("pos","last"))
D["ret"]=D.c.pct_change()*100
D=D.dropna()
print("模型逐分鐘部位損益 vs 引擎實際損益(萬):",round(D.pnl.sum()/1e4,1),round(t.pnl.sum()/1e4,1),"(差=手續費滑價)")
for lab,s in [("2020+",D),("2024+",D[D.index>="2024-01-01"])]:
    print(f"\n== {lab} 依當日(夜+日)漲跌幅分組：V38 當天損益 ==")
    bins=[-99,-6,-4,-2.5,2.5,4,6,99]
    s=s.assign(b=pd.cut(s.ret,bins))
    r=s.groupby("b",observed=True).agg(天數=("pnl","size"),總損益萬=("pnl",lambda x:x.sum()/1e4),平均萬=("pnl",lambda x:x.mean()/1e4),
        有賺天比例=("pnl",lambda x:(x>0).mean()*100),有部位天比例=("maxpos",lambda x:(x>0).mean()*100))
    print(r.round(2).to_string())
print("\n== 2024+ 大漲日(>=+4%)逐日 ==")
u=D[(D.index>="2024-01-01")&(D.ret>=4)]
print(u.assign(pnl=(u.pnl/1e4).round(1)).round(2).to_string())
print("\n== 最近 ==")
print(D.tail(8).assign(pnl=lambda x:(x.pnl/1e4).round(1)).round(2).to_string())
