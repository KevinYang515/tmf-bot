import re, pandas as pd, numpy as np
D="E:/stock/tmf_bot_ops/recon_1125/"
L=open(D+"live_lines.txt",encoding="utf-8").read().splitlines()
sig=None; fills=[]
for ln in L:
    ts=pd.Timestamp(ln[:19])+pd.Timedelta(hours=8)   # UTC -> TPE
    if "[Signal]" in ln:
        m=re.search(r"target=(-?\d+) \| sig_price=([\d.]+) \| action=(\w+) \| comment=(\S+)",ln); sig=(ts,int(m[1]),float(m[2]),m[3],m[4])
    elif "[Result]" in ln and "Filled" in ln:
        q=int(re.search(r"數量: (\d+)",ln)[1]); px=float(re.search(r"成交:([\d.]+)",ln)[1])
        fills.append(dict(ts=ts,qty=q*(1 if sig[3]=="buy" else -1),px=px,sig_ts=sig[0],target=sig[1],sig_px=sig[2],comment=sig[4]))
F=pd.DataFrame(fills).sort_values("ts").reset_index(drop=True)
F["pos_bot"]=F.qty.cumsum()
B=pd.read_csv(D+"balance.csv",encoding="utf-8-sig",parse_dates=["datetime"])
print("fills",len(F),"first",F.ts.min(),"last",F.ts.max())
# choose start: 2026-11-12 05:01 snapshot ; check bot pos
for t0 in ["2026-11-11 13:46","2026-11-12 05:01","2026-11-12 13:46"]:
    p=F[F.ts<=t0].qty.sum(); print(t0,"bot cum qty since log start",p)
F["pos"]=F.pos_bot+2
t0=pd.Timestamp("2026-11-12 05:01"); t1=pd.Timestamp("2026-11-25 13:46")
W=F[(F.ts>t0)&(F.ts<=t1)].copy()
b0=B[B.datetime.dt.strftime("%Y-%m-%d %H:%M")=="2026-11-12 05:01"].today_balance.iloc[0]
b1=B[B.datetime.dt.strftime("%Y-%m-%d %H:%M")=="2026-11-25 13:46"].today_balance.iloc[0]
print("\n帳戶 today_balance", b0, "->", b1, "變化", b1-b0)
cash=-(W.qty*W.px).sum()*50; cash_sig=-(W.qty*W.sig_px).sum()*50
netq=W.qty.sum(); n_sides=W.qty.abs().sum()
print("機器人成交: 口數(單邊)",n_sides,"淨口數",netq,"(≠0 代表有手動平倉)")
print("機器人成交現金流(萬)",round(cash/1e4,2),"| 若以TV訊號價成交(萬)",round(cash_sig/1e4,2),"| 滑價成本(萬)",round((cash_sig-cash)/1e4,2))
fee=n_sides*60; print("估手續費+稅(每口單邊約60元)(萬)",round(fee/1e4,2))
manual=(b1-b0)-cash+fee
print("殘差=帳戶變化-機器人現金流+費用 → 手動交易等(萬)",round(manual/1e4,2), " 手動淨口數",-netq)
E=pd.read_csv("E:/stock/v38_v29_snr_20261017/shadow_gates/v30eopt_off0_base_latest.csv",parse_dates=["entry_ts","exit_ts"])
Ew=E[(E.entry_ts>t0)&(E.exit_ts<=t1)]
print("\n引擎 off0 同期間 交易",len(Ew),"損益(萬)",round(Ew.pnl.sum()/1e4,2),"  跨起點的單:",len(E[(E.entry_ts<=t0)&(E.exit_ts>t0)]))
F.to_csv(D+"fills.csv",index=False); W.to_pickle(D+"W.pkl")
