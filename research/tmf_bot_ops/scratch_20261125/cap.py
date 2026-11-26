import pandas as pd, numpy as np
t=pd.read_csv("E:/stock/v38_v29_snr_20261017/shadow_gates/v30eopt_off0_base_latest.csv",parse_dates=["entry_ts","exit_ts"]).sort_values("entry_ts").reset_index(drop=True)
def mdd(p): e=p.cumsum(); return (e-e.cummax()).min()
def run(cap):
    keep=[]; openx=[]
    for i,r in t.iterrows():
        openx=[x for x in openx if x>r.entry_ts]
        if len(openx)>=cap: continue
        keep.append(i); openx.append(r.exit_ts)
    return t.loc[keep]
mx=max(len([1 for j in range(max(0,i-10),i) if t.exit_ts[j]>t.entry_ts[i]]) for i in range(len(t)))
print("引擎最大同時口數≈",mx+1)
per={"2020-23":("2020","2023-12-31"),"2024-25":("2024","2025-12-31"),"2026H1":("2026","2026-06-30"),"2026-07~11":("2026-07","2026-12-31"),"2024+":("2024","2026-12-31")}
rows=[]
for cap in (1,2,3,4,99):
    k=run(cap).sort_values("exit_ts")
    for p,(a,b) in per.items():
        y=k[(k.exit_ts>=a)&(k.exit_ts<=b+" 23:59")].pnl
        rows.append(dict(上限=cap,期間=p,淨利萬=y.sum()/1e4,MDD萬=mdd(y)/1e4,RR=y.sum()/-mdd(y)))
R=pd.DataFrame(rows).round(2); print(R.pivot(index="上限",columns="期間",values=["淨利萬","MDD萬","RR"]).to_string())
