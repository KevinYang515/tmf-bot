import pandas as pd, numpy as np
H = "E:/stock/v38_v29_snr_20261017/"
T = pd.read_csv(H+"mlg4_trades_v29_H1_p20.csv", parse_dates=["entry_ts","exit_ts"]); T = T[T.exit_ts >= "2020-03-02"]
T["gpts"] = T.pnl/50  # gross points per lot (pnl before 440 cost? check)
c = pd.read_csv("E:/stock/newstrat_rr_20261019/turtle_continuous_tx_20261029.csv", parse_dates=["date"]).set_index("date")
c = c[c.index >= "2019-12-01"]
tr = pd.concat([c.high_diff-c.low_diff, (c.high_diff-c.close_diff.shift()).abs(), (c.low_diff-c.close_diff.shift()).abs()], axis=1).max(axis=1)
c["atr_pts"] = tr; c["atr_pct"] = tr/c.close_diff*100; c["ret"] = c.close_diff.pct_change()
c = c[c.index >= "2020-03-02"]
m1 = pd.read_csv(H+"mxf_1min_2020_20261029.csv", parse_dates=["ts"], usecols=["ts","Close","High","Low"])
b5 = m1.set_index("ts").resample("5min", label="right", closed="right").agg({"High":"max","Low":"min","Close":"last"}).dropna()
b5["r"] = b5.High-b5.Low
T["side_net"] = T.net
rows = []
for y, g in c.groupby(c.index.year):
    t = T[T.exit_ts.dt.year == y]; r5 = b5[b5.index.year == y]
    eff = abs(g.close_diff.iloc[-1]/g.close_diff.iloc[0]-1) / g.ret.abs().sum()
    rows.append({"年": y, "指數漲跌%": round((g.close_diff.iloc[-1]/c.close_diff[c.index < g.index[0]].iloc[-1] if y>2020 else g.close_diff.iloc[-1]/g.close_diff.iloc[0]-0)*100-100 if y>2020 else (g.close_diff.iloc[-1]/g.close_diff.iloc[0]-1)*100,1),
                 "平均指數": round(g.close_diff.mean()), "日ATR點": round(g.atr_pts.mean()), "日ATR%": round(g.atr_pct.mean(),2),
                 "5分K均幅點": round(r5.r.mean(),1), "5分K均幅%": round((r5.r/r5.Close).mean()*100,3), "年趨勢效率": round(eff,3),
                 "淨利萬": round(t.net.sum()/1e4,1), "多單萬": round(t[t.side=="L"].net.sum()/1e4,1), "空單萬": round(t[t.side=="S"].net.sum()/1e4,1),
                 "口數": len(t), "每口毛點": round(t.pnl.mean()/50,1), "每口毛點/5分K均幅": round(t.pnl.mean()/50/r5.r.mean(),2)})
R = pd.DataFrame(rows); print(R.to_string())
# monthly regressions
D = T.assign(m=T.exit_ts.dt.to_period("M")).groupby("m").net.sum()
M = pd.DataFrame({"net": D})
cm = c.assign(m=c.index.to_period("M")).groupby("m").agg(ret=("close_diff", lambda s: s.iloc[-1]/s.iloc[0]-1), atrp=("atr_pts","mean"), atrpct=("atr_pct","mean"))
M = M.join(cm).dropna(); M["absret"] = M.ret.abs()
print("monthly Spearman with net:", M.corr("spearman")["net"].round(2).to_dict())
for lab, g in [("2020-23", M[M.index.year < 2024]), ("2024-26", M[M.index.year >= 2024])]:
    print(lab, g.corr("spearman")["net"].round(2).to_dict(), "n", len(g))
# bucket by monthly ATR% tercile (vol in %) and absret
M["vol3"] = pd.qcut(M.atrpct, 3, labels=["低波","中波","高波"]); M["trend3"] = pd.qcut(M.absret, 3, labels=["小","中","大"])
print((M.pivot_table(index="vol3", columns="trend3", values="net", aggfunc="mean")/1e4).round(1))
print(M.pivot_table(index="vol3", columns="trend3", values="net", aggfunc="size"))
print("up/down months:", (M.groupby(M.ret > 0).net.agg(["mean","size"])/[1e4,1]).round(1))
