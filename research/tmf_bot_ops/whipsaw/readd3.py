import pandas as pd, numpy as np
t=pd.read_csv("E:/stock/v38_v29_snr_20261017/gap/fable_audit/round12/eng/S24_2_off0.csv",parse_dates=["entry_ts","exit_ts"]).sort_values("entry_ts").reset_index(drop=True)
# 波段：從空手開第一口(母單)起，到全部平倉為止
cid=0; op=[]; cids=[]
for i,r in t.iterrows():
    op=[(e,s) for e,s in op if e>r.entry_ts]
    if not op or op[0][1]!=r.side: cid+=1
    cids.append(cid); op.append((r.exit_ts,r.side))
t["cid"]=cids
R=pd.read_pickle("readd2.pkl")
ad=t[t.kind.isin(["Add","G"])].copy()
ad["第幾次加碼"]=ad.groupby("cid").cumcount()+1
R=R.merge(ad[["entry_ts","第幾次加碼"]],on="entry_ts",how="left")
R["第幾次加碼"]=R["第幾次加碼"].clip(upper=8)
pd.set_option("display.width",250); pd.set_option("display.max_rows",200)
def T(keys,data):
    return data.groupby(keys+["期"]).agg(n=("pnl","size"),勝率=("pnl",lambda s:round((s>0).mean()*100)),平均萬=("pnl",lambda s:round(s.mean()/1e4,2)),合計萬=("pnl",lambda s:round(s.sum()/1e4,1))).unstack("期")
print("### 所有加碼/G：從母單起算第幾次加碼（8=8次以上）"); print(T(["side","第幾次加碼"],R).to_string())
print("\n### 只看『出場後又加』：第幾次加碼"); print(T(["side","第幾次加碼"],R[R.類=="出場後又加"]).to_string())
print("\n### 第幾次加碼 × 日夜（空單）"); print(T(["盤","第幾次加碼"],R[R.side=="空"]).to_string())

bad=((R.side=="多")&(R.第幾次加碼>=8))|((R.side=="空")&(R.盤=="夜")&(R.已走>=5))
print("\n\n===== 排除已知負期望規律後 =====")
for lab,x in (("排除前",R),("排除後",R[~bad]),("被排除",R[bad])):
    g=x.groupby(["side","期"]).agg(n=("pnl","size"),勝率=("pnl",lambda s:round((s>0).mean()*100)),平均萬=("pnl",lambda s:round(s.mean()/1e4,3)),合計萬=("pnl",lambda s:round(s.sum()/1e4,1))).unstack("期")
    print(f"\n[{lab}]"); print(g.to_string())
X=R[~bad]
print("\n### 排除後：多空×日夜×第幾次加碼（看是否還有兩段皆負的格子）")
t=T(["side","盤","第幾次加碼"],X)
print(t.to_string())
neg=t[(t[("平均萬","20-23")]<0)&(t[("平均萬","24+")]<0)]
print("\n>>> 兩段皆為負的格子："); print(neg.to_string() if len(neg) else "無")
X2=X.assign(走=pd.cut(X.已走,[-99,0,1,3,5,7,99]).astype(str))
t2=T(["side","盤","走"],X2); neg2=t2[(t2[("平均萬","20-23")]<0)&(t2[("平均萬","24+")]<0)]
print("\n### 排除後：多空×日夜×已走% 中兩段皆負的格子："); print(neg2.to_string() if len(neg2) else "無")
