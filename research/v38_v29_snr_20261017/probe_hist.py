import ast, pandas as pd, shioaji as sj
from pathlib import Path
CRED=Path(r"E:\D_backup\stock\minute_kbar_fetch\fetch_minute_kbars_parallel.py")
v={n.targets[0].id:ast.literal_eval(n.value) for n in ast.parse(CRED.read_text(encoding="utf-8")).body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in {"SJ_API_KEY","SJ_SECRET_KEY"}}
api=sj.Shioaji(simulation=False)
try:
    api.login(v["SJ_API_KEY"],v["SJ_SECRET_KEY"])
    for s,e in [("2020-03-02","2020-03-03"),("2022-03-01","2022-03-02"),("2019-06-03","2019-06-04")]:
        kb=api.kbars(api.Contracts.Futures.MXF.MXFR1,start=s,end=e); f=pd.DataFrame({**kb})
        print(s,len(f), pd.to_datetime(f.ts).min() if len(f) else None, f.Close.iloc[-1] if len(f) else None)
    print('usage', api.usage())
finally:
    api.logout()
