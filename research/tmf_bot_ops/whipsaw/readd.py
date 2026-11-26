import pandas as pd, numpy as np
H="E:/stock/v38_v29_snr_20261017/gap/fable_audit/round12/eng/"
pd.set_option("display.width",220)
for nm in ("NOBE","S24_2"):
    t=pd.read_csv(H+f"{nm}_off0.csv",parse_dates=["entry_ts","exit_ts"]).sort_values("entry_ts").reset_index(drop=True)
    ad=t[t.kind.isin(["Add","G"])].copy()
    rows=[]
    for i,r in ad.iterrows():
        prev=ad[(ad.side==r.side)&(ad.exit_ts<=r.entry_ts)&(ad.exit_ts>=r.entry_ts-pd.Timedelta(minutes=60))]
        if len(prev):
            p=prev.sort_values("exit_ts").iloc[-1]; gap=(r.entry_ts-p.exit_ts).total_seconds()/60
            dist=(r.entry_px-p.exit_px)*(1 if r.side=="L" else -1)   # >0 = 比上次出場更順向(追)
            typ="前單停損出場" if p.exit_sig.endswith("_SL") else ("前單停利出場" if "Exit" in p.exit_sig else p.exit_sig)
        else: gap=np.nan; dist=np.nan; typ="無(正常加碼)"
        rows.append(dict(entry_ts=r.entry_ts,side=r.side,pnl=r.pnl,exit_sig=r.exit_sig,gap=gap,dist=dist,typ=typ))
    R=pd.DataFrame(rows); R["期"]=np.where(R.entry_ts<"2024","20-23","24+")
    R["距離"]=pd.cut(R.dist,[-9999,-100,0,100,300,9999]).astype(str).where(R.dist.notna(),"—")
    print(f"\n===== {nm}：加碼/G 單，依『60分內同向剛有加碼單出場』分類 =====")
    print(R.groupby(["typ","期"]).agg(n=("pnl","size"),勝率=("pnl",lambda s:round((s>0).mean()*100)),平均萬=("pnl",lambda s:round(s.mean()/1e4,2)),合計萬=("pnl",lambda s:round(s.sum()/1e4,1)),
        之後被停損比例=("exit_sig",lambda s:round(s.str.endswith("_SL").mean()*100))).unstack("期").to_string())
    x=R[R.typ!="無(正常加碼)"]
    print("  依 重新加碼價 − 上次出場價（點，>0=更追）:")
    print(x.groupby(["距離","期"]).agg(n=("pnl","size"),平均萬=("pnl",lambda s:round(s.mean()/1e4,2)),勝率=("pnl",lambda s:round((s>0).mean()*100))).unstack("期").to_string())
