import pandas as pd, numpy as np
t=pd.read_csv("E:/stock/v38_v29_snr_20261017/gap/fable_audit/round12/eng/S24_2_off0.csv",parse_dates=["entry_ts","exit_ts"]).sort_values("entry_ts").reset_index(drop=True)
m=pd.read_csv("E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts")
tdk=lambda ts:(ts+pd.Timedelta(hours=9)).normalize()
dc=m.Close.groupby(tdk(m.index)).last(); pcs=dc.shift(1)
ad=t[t.kind.isin(["Add","G"])].copy(); ad["td"]=(ad.entry_ts+pd.Timedelta(hours=9)).dt.normalize()
rows=[]; chain={}
for i,r in ad.iterrows():
    prev=ad[(ad.side==r.side)&(ad.exit_ts<=r.entry_ts)&(ad.exit_ts>=r.entry_ts-pd.Timedelta(minutes=60))]
    re_=len(prev)>0
    key=(r.td,r.side); 
    if re_: chain[key]=chain.get(key,0)+1
    nth_day=((ad.td==r.td)&(ad.side==r.side)&(ad.entry_ts<r.entry_ts)).sum()+1
    pc=pcs.get(r.td,np.nan); sg=1 if r.side=="L" else -1
    rows.append(dict(entry_ts=r.entry_ts,side="多" if sg>0 else "空",pnl=r.pnl,類=("出場後又加" if re_ else "一般加碼"),
        連續再加第幾次=min(chain.get(key,0),4) if re_ else 0, 當日第幾口加碼=min(nth_day,6),
        盤="日" if 8<=r.entry_ts.hour<14 else "夜", 已走=(r.entry_px/pc-1)*100*sg if pc==pc else np.nan))
R=pd.DataFrame(rows); R["期"]=np.where(R.entry_ts<"2024","20-23","24+")
R["已走%"]=pd.cut(R.已走,[-99,1,3,5,7,99]).astype(str)
def T(keys,data=R):
    return data.groupby(keys+["期"]).agg(n=("pnl","size"),勝率=("pnl",lambda s:round((s>0).mean()*100)),平均萬=("pnl",lambda s:round(s.mean()/1e4,2))).unstack("期")
pd.set_option("display.width",250); pd.set_option("display.max_rows",200)
X=R[R.類=="出場後又加"]
print("### 出場後又加：多空×日夜"); print(T(["side","盤"],X).to_string())
print("\n### 出場後又加：多空×已走%"); print(T(["side","已走%"],X).to_string())
print("\n### 出場後又加：多空×當天連續第幾次再加"); print(T(["side","連續再加第幾次"],X).to_string())
print("\n### 所有加碼：多空×當日第幾口加碼"); print(T(["side","當日第幾口加碼"]).to_string())
print("\n### 所有加碼：多空×日夜×已走%"); print(T(["side","盤","已走%"]).to_string())
R.to_pickle("readd2.pkl")
