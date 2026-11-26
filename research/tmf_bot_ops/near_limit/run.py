import pandas as pd, numpy as np
m=pd.read_csv("E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index()
m=m[m.index>="2020-03-02"]
C=m.Close.values; H=m.High.values; L=m.Low.values; idx=m.index
td=(idx+pd.Timedelta(hours=9)).normalize(); days=pd.Index(td.unique()); di=days.get_indexer(td)
dayc=pd.Series(C).groupby(di).last().values   # trading-day last close (13:45)
rows=[]
for k in range(1,len(days)):
    s,e=np.searchsorted(di,k),np.searchsorted(di,k+1); pc=dayc[k-1]
    for sign,lab in ((-1,"跌"),(1,"漲")):
        mv=(C[s:e]/pc-1)*100*(-sign)*-1  # signed move in direction sign
        mv=(C[s:e]/pc-1)*100*sign
        for th in (5,6,7,8):
            hit=np.where(mv>=th)[0]
            if not len(hit): continue
            p=s+hit[0]; px=C[p]
            # forward: to day end, next day end, +3 days end ; max adverse/favorable for continuation
            def fwd(kk):
                ee=np.searchsorted(di,min(kk+1,len(days)))
                if ee<=p: return np.nan,np.nan,np.nan
                seg=slice(p+1,ee)
                cont=(C[ee-1]/px-1)*100*sign          # >0 = continued in move direction
                mfe=(H[seg].max()/px-1)*100 if sign>0 else (1-L[seg].min()/px)*100
                mae=(1-L[seg].min()/px)*100 if sign>0 else (H[seg].max()/px-1)*100
                return cont,mfe,mae
            r=dict(day=days[k],dir=lab,th=th,ts=idx[p],px=px)
            for nm,kk in (("當日收",k),("隔日收",k+1),("3日收",k+3)):
                c_,f_,a_=fwd(kk); r[nm+"_延續%"]=c_; r[nm+"_順向最大%"]=f_; r[nm+"_反向最大%"]=a_
            r["當日再創極值"]= (L[p+1:e].min()<L[s:p+1].min()) if sign<0 else (H[p+1:e].max()>H[s:p+1].max())
            rows.append(r)
R=pd.DataFrame(rows); R.to_csv("events.csv",index=False)
pd.set_option("display.width",230)
for lab in ("跌","漲"):
    x=R[R.dir==lab]
    print(f"\n=== 盤中比昨收{lab}到 X% 的那一刻 → 之後（延續>0=繼續往{lab}方向；空間為中位數） ===")
    g=x.groupby("th").agg(次數=("px","size"),當日再創新極值=("當日再創極值","mean"),
        到收盤延續=("當日收_延續%","median"),到隔日收延續=("隔日收_延續%","median"),到3日延續=("3日收_延續%","median"),
        隔日內順向空間=("隔日收_順向最大%","median"),隔日內反向空間=("隔日收_反向最大%","median"),
        到3日延續為正比例=("3日收_延續%",lambda s:(s>0).mean()))
    print(g.round(2).to_string())
print("\n跌到7%的事件：")
print(R[(R.dir=="跌")&(R.th==7)][["day","ts","px","當日收_延續%","隔日收_延續%","3日收_延續%","當日再創極值"]].round(2).to_string())
