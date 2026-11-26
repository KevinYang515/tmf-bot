import pandas as pd, numpy as np
H="E:/stock/v38_v29_snr_20261017/"
m=pd.read_csv(H+"shadow_gates/mxf_1min_live.csv",parse_dates=["ts"]).set_index("ts").sort_index()
m=m[m.index>="2020-03-02"]
td=(m.index+pd.Timedelta(hours=9)).normalize()      # night belongs to next day
g=m.groupby(td); d=pd.DataFrame({"h":g.High.max(),"l":g.Low.min(),"c":g.Close.last()})
d["pc"]=d.c.shift(1); d=d.dropna()
d["dn"]=(d.l/d.pc-1)*100; d["up"]=(d.h/d.pc-1)*100; d["ret"]=(d.c/d.pc-1)*100
# V down: low <= -5%, close retraced >=40% of the drop ; V up symmetric
d["Vdn"]=(d.dn<=-5)&((d.c-d.l)>=0.4*(d.pc-d.l))
d["Vup"]=(d.up>=5)&((d.h-d.c)>=0.4*(d.h-d.pc))
d["trend_dn"]=(d.dn<=-5)&~d.Vdn; d["trend_up"]=(d.up>=5)&~d.Vup
E=pd.read_csv(H+"shadow_gates/v30eopt_off0_base_latest.csv",parse_dates=["entry_ts","exit_ts"])
E["d"]=(E.exit_ts+pd.Timedelta(hours=9)).dt.normalize()
E["typ"]=E.kind+"|"+E.exit_sig.str.replace(r"^[LS]_","",regex=True)
def lab(x):
    for k in ("Vdn","Vup","trend_dn","trend_up"):
        if d.at[x,k] if x in d.index else False: return k
    return "其他"
E["day"]=E.d.map(lab)
print("事件日數 2020+:",{k:int(d[k].sum()) for k in ("Vdn","Vup","trend_dn","trend_up")}, " 2024+:",{k:int(d[d.index>='2024'][k].sum()) for k in ("Vdn","Vup","trend_dn","trend_up")})
print(d[d.Vdn|d.Vup][["pc","l","h","c","dn","up","ret"]].round(1).tail(15).to_string())
for lab_,x in (("2020+",E),("2024+",E[E.d>="2024"])):
    print(f"\n== {lab_} 依日型態 V38 損益(萬) ==")
    print(x.groupby("day").agg(筆=("pnl","size"),合計=("pnl",lambda s:s.sum()/1e4),每日=("d",lambda s:s.nunique())).assign(每日平均=lambda r:r.合計/r.每日).round(1).to_string())
x=E[(E.d>="2024")&(E.day=="Vdn")]
print("\n== 2024+ V型下殺反彈日：依單別×出場 ==")
print(x.groupby(["side","typ"]).agg(筆=("pnl","size"),合計萬=("pnl",lambda s:s.sum()/1e4)).round(1).sort_values("合計萬").to_string())
print("\n逐日:"); print(x.groupby("d").pnl.sum().div(1e4).round(1).to_string())
