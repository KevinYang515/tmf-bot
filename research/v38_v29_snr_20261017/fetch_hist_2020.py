"""Fetch MXFR1 1-min kbars 2020-03-02 -> 2023-12-31 and 2026-10-22 -> today; merge with corrected 20261022 file."""
import ast, time, pandas as pd, shioaji as sj
from datetime import date
from pathlib import Path
HERE=Path(__file__).parent
CRED=Path(r"E:\D_backup\stock\minute_kbar_fetch\fetch_minute_kbars_parallel.py")
v={n.targets[0].id:ast.literal_eval(n.value) for n in ast.parse(CRED.read_text(encoding="utf-8")).body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in {"SJ_API_KEY","SJ_SECRET_KEY"}}
api=sj.Shioaji(simulation=False); parts=[]
try:
    api.login(v["SJ_API_KEY"],v["SJ_SECRET_KEY"])
    c=api.Contracts.Futures.MXF.MXFR1
    months=pd.date_range("2020-03-01","2023-12-01",freq="MS")
    for m in months:
        s=max(m,pd.Timestamp("2020-03-02")).date().isoformat(); e=(m+pd.offsets.MonthEnd(0)).date().isoformat()
        f=pd.DataFrame({**api.kbars(c,start=s,end=e)}); parts.append(f); print(s,len(f),flush=True); time.sleep(1)
    f=pd.DataFrame({**api.kbars(c,start="2026-10-22",end=date.today().isoformat())}); parts.append(f); print("recent",len(f))
    print(api.usage())
finally:
    api.logout()
new=pd.concat(parts); new["ts"]=pd.to_datetime(new.ts)
ex=pd.read_csv(HERE/"mxf_1min_corrected_20261022.csv",parse_dates=["ts"]); cols=list(ex.columns)
ov=ex.merge(new[cols],on="ts",suffixes=("_e","_f"))
print("overlap",len(ov),"OHLC mismatch",(ov.Close_e!=ov.Close_f).sum())
m=pd.concat([new[new.ts<ex.ts.min()][cols],ex,new[new.ts>ex.ts.max()][cols]]).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
m["ret"]=m.Close.pct_change().abs(); m["rng"]=(m.High-m.Low)/m.Close
print("spikes:",m[(m.ret>0.03)|(m.rng>0.03)][["ts","Open","High","Low","Close"]].to_string())
d=pd.Series(m.ts.dt.normalize().unique()); g=[(a.date(),b.date()) for a,b in zip(d[:-1],d[1:]) if (b-a).days>5]; print("gaps>5d",g)
m[cols].to_csv(HERE/"mxf_1min_2020_20261026.csv",index=False); print(m.ts.min(),m.ts.max(),len(m))
