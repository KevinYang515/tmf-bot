import sys, glob; sys.path.insert(0, r"E:/stock/v38_v29_snr_20261017/gap/fable_audit"); import pandas as pd, numpy as np
import fa_cost
fa_cost._src = fa_cost._src.replace("mxf_1min_2020_20261111.csv", "shadow_gates/mxf_1min_live.csv")
F=[f for f in glob.glob(fa_cost.H+"gap/fable_audit/round9/eng1125/*_off*.csv") if any(k in f for k in ("NOBE_","LB7_"))]
T=fa_cost.load(F)
allD=[]
for o in range(4):
    a=T[(T.tag=="NOBE")&(T.off==o)].groupby("d").net_R.sum(); b=T[(T.tag=="LB7")&(T.off==o)].groupby("d").net_R.sum()
    df=pd.concat([a,b],axis=1,keys=["N","L"]).fillna(0); df["diff"]=df.L-df.N; df["off"]=o; allD.append(df[df["diff"].abs()>1])
D=pd.concat(allD); D["yr"]=D.index.year
print((D.groupby(["yr","off"])["diff"].sum().unstack()/1e4).round(1))
p=D.reset_index().pivot_table(index="d",columns="off",values="diff",aggfunc="sum").fillna(0)/1e4
p["mean"]=p.mean(axis=1); print(p.round(2).to_string())
# leave-one-episode-out: drop 2026-11-06
for ex in [["2026-11-06"],["2026-11-06","2026-08-01"],["2026-11-20","2026-11-21","2026-11-24","2026-11-25"]]:
    rr=[]
    for o in range(4):
        for tag in ("NOBE","LB7"):
            d=T[(T.tag==tag)&(T.off==o)].groupby("d").net_R.sum(); d=d[(d.index>="2024-01-01")&(~d.index.isin(pd.to_datetime(ex)))]
            rr.append((tag,o,d.sum()/abs(fa_cost.mdd(d))))
    r=pd.DataFrame(rr,columns=["tag","off","RR"]).groupby("tag").RR.mean(); print("excl",ex,r.round(2).to_dict())
