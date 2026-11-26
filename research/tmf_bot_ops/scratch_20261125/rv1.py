import sys, glob; sys.path.insert(0, r"E:/stock/v38_v29_snr_20261017/gap/fable_audit"); import pandas as pd, numpy as np
import fa_cost
fa_cost._src = fa_cost._src.replace("mxf_1min_2020_20261111.csv", "shadow_gates/mxf_1min_live.csv")
F=[f for f in glob.glob(fa_cost.H+"gap/fable_audit/round9/eng1125/*_off*.csv") if any(k in f for k in ("NOBE_","LB7_","LB8_","LB6_"))]
T=fa_cost.load(F); mdd=fa_cost.mdd
print(T.exit_ts.max(), T[T.exit_sig.astype(str).str.contains("END")].groupby("case").net_R.sum()/1e4)
for o in range(4):
    a=T[(T.tag=="NOBE")&(T.off==o)].groupby("d").net_R.sum(); b=T[(T.tag=="LB7")&(T.off==o)].groupby("d").net_R.sum()
    df=pd.concat([a,b],axis=1,keys=["N","L"]).fillna(0); df["diff"]=df.L-df.N
    x=df[df.index>="2024-01-01"]; nz=x[x["diff"].abs()>1]
    print(f"--- off{o} 2024+ diff total {x['diff'].sum()/1e4:.1f}萬, nonzero days {len(nz)}")
    print((nz.sort_values("diff",key=abs,ascending=False).head(12)/1e4).round(2).to_string())
    # mdd window
    for nm in "NL":
        e=x[nm].cumsum(); dd=e-e.cummax(); t1=dd.idxmin(); t0=e[:t1].idxmax(); print(nm,"mdd",round(dd.min()/1e4,2),t0.date(),t1.date())
    # excluding final days >= 2026-11-24
    y=x[x.index<"2026-11-24"]; print("ex 11/24+: N RR",round(y.N.sum()/abs(mdd(y.N)),2),"L RR",round(y.L.sum()/abs(mdd(y.L)),2))
