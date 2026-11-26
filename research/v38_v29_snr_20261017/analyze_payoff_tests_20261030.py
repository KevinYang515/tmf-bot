import glob, pandas as pd, numpy as np
H = "E:/stock/v38_v29_snr_20261017/"
ref = pd.read_csv(H+"mlg4_trades_v29_H1_p20.csv", parse_dates=["exit_ts"])
def tday(s): return s.dt.normalize() + pd.to_timedelta((s.dt.hour >= 15).astype(int), "D")
def mdd(p): e = p.cumsum(); return (e - e.cummax()).min()
def camp(T):
    T = T.sort_values("entry_ts").reset_index(drop=True); T["cid"] = ""
    for s in ["L","S"]:
        m = T.side == s; c = (T.kind.eq("Cmd") & m).cumsum(); T.loc[m, "cid"] = s + c[m].astype(str)
    return T.groupby("cid").net.sum()
order = ["base","A_cmdSL_x0.8","A_cmdSL_x0.9","A_cmdSL_x1.2","B_addSL_x0.8","B_addSL_x0.9","B_addSL_x1.2","C_longADX25","C_longADX30","C_shortOnly_diag","D_noG","C_longADX27","C_longADX35","B_addSL_x0.7","E_ADX30_addSL0.9","E_ADX30_addSL0.8","C_longADX40","C_longADX45"] + [f"v28_ADX{x}" for x in (20,25,27,30,35,40,45)]
S = {k: pd.read_csv(H+f"pay_trades_{k}.csv", parse_dates=["entry_ts","exit_ts"]) for k in order}
b = S["base"]; r28 = pd.read_csv(H+"mlg4_trades_v28_H1_p20.csv"); print("v28 base reproduces:", len(S["v28_ADX20"]) == len(r28), round(S["v28_ADX20"].net.sum()) == round(r28.net.sum()))
print("base reproduces mlg4 v29_H1_p20:", len(b) == len(ref), round(b.net.sum()) == round(ref.net.sum()))
rows = []; Y = {}
for k, T in S.items():
    T = T[T.exit_ts >= "2020-03-02"]; d = T.assign(d=tday(T.exit_ts)).groupby("d").net.sum()
    y = d.groupby(d.index.year).sum(); Y[k] = y; c = camp(T); w, l = c[c > 0], c[c <= 0]
    end = d.index.max(); d12 = d[d.index > end - pd.DateOffset(months=12)]; d3 = d[d.index > end - pd.DateOffset(months=3)]
    rows.append({"case": k, **{str(i): round(v/1e4,1) for i, v in y.items()}, "合計": round(d.sum()/1e4,1), "MDD": round(mdd(d)/1e4,1),
                 "2024-26": round(y.loc[2024:].sum()/1e4,1), "近12月": round(d12.sum()/1e4,1), "近12MDD": round(mdd(d12)/1e4,1), "近3月": round(d3.sum()/1e4,1),
                 "波段勝率%": round(len(w)/len(c)*100,1), "均賺": round(w.mean()/1e4,2), "均賠": round(l.mean()/1e4,2), "波段賺賠比": round(w.mean()/-l.mean(),2), "口數": len(T)})
R = pd.DataFrame(rows).set_index("case"); B = R.loc["base"]
bk = lambda k: "v28_ADX20" if k.startswith("v28") else "base"
R["贏base年數"] = [int((Y[k] > Y[bk(k)]).sum()) for k in R.index]
R["裁決"] = ["—" if k in ("base", "v28_ADX20") else ("PASS" if (r.合計 > B.合計 and r.贏base年數 >= 5 and r.MDD >= B.MDD*1.10 and r["2024-26"] >= B["2024-26"]) else "FAIL") for k, r in R.iterrows() for B in [R.loc[bk(k)]]]
R.to_csv(H+"pay_summary_20261030.csv", encoding="utf-8-sig"); pd.set_option("display.width", 300); print(R.to_string())
