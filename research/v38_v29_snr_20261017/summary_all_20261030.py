import pandas as pd
H = r"E:\stock\v38_v29_snr_20261017\\"
C = pd.read_csv(H+"cmp_20261029_trades.csv", parse_dates=["entry_ts","exit_ts"])
S = {k: C[C.v == k] for k in ["v27","v28","v29","v28_G2","v29_G2"]}
for k, f in {"v28_G2_H1":"mlg4_trades_v28_H1_p20.csv","v29_G2_H1":"mlg4_trades_v29_H1_p20.csv","v29_G2_H1_H4(參考)":"mlg4_trades_v29_H14_p20_H4p33.csv"}.items():
    S[k] = pd.read_csv(H+f, parse_dates=["entry_ts","exit_ts"])
def tday(s): return s.dt.normalize() + pd.to_timedelta((s.dt.hour >= 15).astype(int), "D")
D = pd.DataFrame({k: t[t.exit_ts >= "2020-03-02"].assign(d=lambda x: tday(x.exit_ts)).groupby("d").net.sum() for k, t in S.items()}).fillna(0).sort_index()
end = D.index.max()
def mdd(p): e = p.cumsum(); return (e - e.cummax()).min()
P = {"2020/3起": D, "2024起": D[D.index >= "2024"], "近12月": D[D.index > end - pd.DateOffset(months=12)],
     "近6月": D[D.index > end - pd.DateOffset(months=6)], "近3月": D[D.index > end - pd.DateOffset(months=3)], "近1月": D[D.index > end - pd.DateOffset(months=1)]}
rows = []
for k, t in S.items():
    t = t[t.exit_ts >= "2020-03-02"]; r = {"版本": k}
    for y, v in D[k].groupby(D.index.year).sum().items(): r[str(y)] = round(v/1e4, 1)
    for lab, s in P.items(): r[lab] = round(s[k].sum()/1e4, 1); r[lab+"MDD"] = round(mdd(s[k])/1e4, 1)
    r["淨利/MDD"] = round(D[k].sum()/-mdd(D[k]), 2); r["口數"] = len(t); r["勝率"] = round((t.net > 0).mean()*100, 1)
    r["均賺/均賠"] = round(t.net[t.net > 0].mean()/-t.net[t.net <= 0].mean(), 2)
    m = D[k].groupby(D.index.year).sum(); r["最差年"] = round(m.min()/1e4, 1)
    rows.append(r)
R = pd.DataFrame(rows); R.to_csv(H+"summary_all_20261030.csv", index=False, encoding="utf-8-sig")
pd.set_option("display.width", 300); print(end.date()); print(R.T.to_string())
