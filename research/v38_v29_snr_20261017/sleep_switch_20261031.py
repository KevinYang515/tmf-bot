"""Pre-declared sleep-switch test on v29+G2+ADX30 (realistic cost R). A switch pauses NEW campaigns (Cmd) while ON;
campaigns are dropped whole (post-hoc; one position at a time so path effects are small). Cost ~10 pts/lot RT.
S1_k: 20-trading-day mean of 5m ATR14 (points), known as of previous trading day, < k*10 pts  (k=1.5,2,2.5)
S2_N_m: mean GROSS points/lot of the last N closed lots of the unfiltered strategy (shadow) < m*10 pts (N=100,200; m=1,1.5)"""
import pandas as pd, numpy as np
H = "E:/stock/v38_v29_snr_20261017/"
T = pd.read_csv(H+"g2lb_20261031_trades.csv", parse_dates=["entry_ts","exit_ts"]); T = T[T.case == "G2_lb20"].sort_values("entry_ts").reset_index(drop=True)
m = pd.read_csv(H+"mxf_1min_2020_20261031.csv", parse_dates=["ts"]).set_index("ts")
b = m.resample("5min", label="left", closed="right").agg({"High":"max","Low":"min","Close":"last"}).dropna()
tr = pd.concat([b.High-b.Low, (b.High-b.Close.shift()).abs(), (b.Low-b.Close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean()
def tday(s): return s.dt.normalize() + pd.to_timedelta((s.dt.hour >= 15).astype(int), "D")
ad = atr.groupby(tday(atr.index.to_series())).mean(); ad20 = ad.rolling(20).mean().shift(1)   # as of previous trading day
ref = atr["2026-05-19":"2026-09-23"].median()
def slip(ts, kind):
    a = atr.reindex(ts, method="ffill").to_numpy(); s = 3*np.clip(a/ref, .67, 3)*np.where(kind.isin(["Add","G"]), 1.3, 1)
    return np.where(ts.dt.strftime("%H:%M").isin(["08:45","15:00"]), 50, s)
fee = lambda px: 20 + 0.00002*px*50
T["net"] = T.pnl - fee(T.entry_px) - fee(T.exit_px) - (slip(T.entry_ts, T.kind) + slip(T.exit_ts, T.kind))*50
T["cid"] = ""
for s in ["L","S"]:
    mm = T.side == s; c = (T.kind.eq("Cmd") & mm).cumsum(); T.loc[mm, "cid"] = s + c[mm].astype(str)
C = T[T.kind == "Cmd"][["cid","entry_ts"]].copy(); C["d"] = tday(C.entry_ts)
C["atr20"] = ad20.reindex(C.d).to_numpy()
ex = T.sort_values("exit_ts"); gp = (ex.pnl/50).to_numpy(); et = ex.exit_ts.to_numpy()
def shadow(N):
    cs = np.concatenate([[0], np.cumsum(gp)]); out = []
    for t0 in C.entry_ts.to_numpy():
        k = np.searchsorted(et, t0, side="left")   # lots closed strictly before entry
        out.append((cs[k]-cs[k-N])/N if k >= N else np.nan)
    return np.array(out)
for N in (100, 200): C[f"sh{N}"] = shadow(N)
rules = {"none": np.zeros(len(C), bool)}
for k in (1.5, 2, 2.5): rules[f"S1_ATR20<{int(k*10)}pt"] = (C.atr20 < k*10).to_numpy()
for N in (100, 200):
    for mlt in (1, 1.5): rules[f"S2_last{N}<{mlt*10:g}pt"] = (C[f"sh{N}"] < mlt*10).to_numpy()
def mdd(p): e = p.cumsum(); return (e - e.cummax()).min()
rows = []
for name, off in rules.items():
    drop = set(C.cid[off]); t = T[~T.cid.isin(drop) & (T.exit_ts >= "2020-03-02")]
    d = t.assign(d=tday(t.exit_ts)).groupby("d").net.sum()
    y = d.groupby(d.index.year).sum()/1e4; pr = pd.Series(off, index=C.d.dt.year).groupby(level=0).mean()*100
    rows.append({"規則": name, **{str(k): round(v,1) for k, v in y.items()}, "2020-23": round(y.loc[:2023].sum(),1), "2024起": round(y.loc[2024:].sum(),1),
                 "2024起MDD": round(mdd(d[d.index >= "2024"])/1e4,1), "全期MDD": round(mdd(d)/1e4,1),
                 **{f"停%{k}": round(v) for k, v in pr.items()}})
R = pd.DataFrame(rows); R.to_csv(H+"sleep_switch_20261031.csv", index=False, encoding="utf-8-sig")
pd.set_option("display.width", 300); print(R.to_string(index=False))
print("ATR20 (pts) yearly median:", ad20.groupby(ad20.index.year).median().round(1).to_dict())
