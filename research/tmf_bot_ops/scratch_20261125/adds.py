import pandas as pd, numpy as np
t=pd.read_csv("E:/stock/v38_v29_snr_20261017/shadow_gates/v30eopt_off0_base_latest.csv",parse_dates=["entry_ts","exit_ts"]).sort_values("exit_ts")
print(t.kind.value_counts().to_dict())
def mdd(p): e=p.cumsum(); return (e-e.cummax()).min()
t["grp"]=np.where(t.kind=="Add","加碼","基本")
per={"2020-23":("2020","2023-12-31"),"2024":("2024","2024-12-31"),"2025":("2025","2025-12-31"),"2026H1":("2026","2026-06-30"),"2026-07~10":("2026-07","2026-10-31"),"2026-11":("2026-11","2026-12-31")}
rows=[]
for k,(a,b) in per.items():
    x=t[(t.exit_ts>=a)&(t.exit_ts<=b+" 23:59")]
    for g in ("基本","加碼","全部"):
        y=x if g=="全部" else x[x.grp==g]
        rows.append(dict(期間=k,類=g,筆=len(y),淨利萬=y.pnl.sum()/1e4,每口萬=y.pnl.mean()/1e4,勝率=(y.pnl>0).mean()*100,MDD萬=mdd(y.pnl)/1e4))
print(pd.DataFrame(rows).round(2).to_string())
# 每個波段: 加碼口數 vs 該波段加碼損益
c=t.assign(cid=(t.kind!="Add").cumsum())
