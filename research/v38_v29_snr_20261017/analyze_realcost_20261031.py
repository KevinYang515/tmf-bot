"""Pre-declared realistic cost model R (fixed before seeing results):
 per side = 20 TWD fee + 0.00002*price*50 tax + slippage*50
 slippage: fill at session open (08:45/15:00 bar) = 50 pts; otherwise 3 pts x clip(ATR5_pts / ATR_ref, 0.67, 3),
 Add/G fills x1.3; ATR_ref = median 5m ATR14 (points) over the live window 2026-05-19..2026-09-23.
Also reported: old flat model (440 TWD/lot RT)."""
import pandas as pd, numpy as np
H = "E:/stock/v38_v29_snr_20261017/"
T = pd.read_csv(H+"realcost_20261031_trades.csv", parse_dates=["entry_ts","exit_ts"])
# consistency vs earlier runs (rule off)
old = {"v29": ("latest_20261031_trades.csv", "v29"), "v29+G2": ("latest_20261031_trades.csv", "v29+G2"), "v29+G2+ADX30": ("h1a_trades_noH1.csv", None)}
for k, (f, c) in old.items():
    o = pd.read_csv(H+f); o = o[o["case"] == c] if c else o; n = T[T.case == k]
    print("repro", k, len(n) == len(o), round(n.pnl.sum()) == round(o.pnl.sum()))
m = pd.read_csv(H+"mxf_1min_2020_20261031.csv", parse_dates=["ts"]).set_index("ts")
b = m.resample("5min", label="left", closed="right").agg({"High":"max","Low":"min","Close":"last"}).dropna()
tr = pd.concat([b.High-b.Low, (b.High-b.Close.shift()).abs(), (b.Low-b.Close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean()
ref = atr["2026-05-19":"2026-09-23"].median(); print("ATR_ref pts", round(ref, 1))
def slip(ts, kind):
    a = atr.reindex(ts, method="ffill").to_numpy()
    s = 3 * np.clip(a / ref, 0.67, 3) * np.where(kind.isin(["Add","G"]), 1.3, 1.0)
    hm = ts.dt.strftime("%H:%M"); return np.where(hm.isin(["08:45","15:00"]), 50, s)
T["slip_in"] = slip(T.entry_ts, T.kind); T["slip_out"] = slip(T.exit_ts, T.kind)
fee = lambda px: 20 + 0.00002*px*50
T["net_R"] = T.pnl - fee(T.entry_px) - fee(T.exit_px) - (T.slip_in + T.slip_out)*50
T["net_flat"] = T.pnl - 440
def tday(s): return s.dt.normalize() + pd.to_timedelta((s.dt.hour >= 15).astype(int), "D")
def mdd(p): e = p.cumsum(); return (e - e.cummax()).min()
def camp(t, col):
    t = t.sort_values("entry_ts").reset_index(drop=True); t["cid"] = ""
    for s in ["L","S"]:
        mm = t.side == s; c = (t.kind.eq("Cmd") & mm).cumsum(); t.loc[mm, "cid"] = s + c[mm].astype(str)
    return t.groupby("cid")[col].sum()
rows = []
for k in dict.fromkeys(T.case):
    for col, lab in [("net_R", "實盤成本R"), ("net_flat", "舊4點")]:
        t = T[(T.case == k) & (T.exit_ts >= "2020-03-02")]; d = t.assign(d=tday(t.exit_ts)).groupby("d")[col].sum()
        r = d[d.index >= "2024-01-01"]; y = r.groupby(r.index.year).sum(); mo = r.groupby(r.index.to_period("M")).sum()
        c = camp(t[t.exit_ts >= "2024-01-01"], col); w, l = c[c > 0], c[c <= 0]; end = d.index.max()
        rows.append({"版本": k, "成本": lab, "2024": round(y.get(2024,0)/1e4,1), "2025": round(y.get(2025,0)/1e4,1), "2026": round(y.get(2026,0)/1e4,1),
                     "2024起": round(r.sum()/1e4,1), "2024起MDD": round(mdd(r)/1e4,1), "近12月": round(d[d.index > end-pd.DateOffset(months=12)].sum()/1e4,1),
                     "近3月": round(d[d.index > end-pd.DateOffset(months=3)].sum()/1e4,1), "賺錢月": f"{(mo>0).sum()}/{len(mo)}",
                     "波段賺賠比": round(w.mean()/-l.mean(),2), "波段勝率%": round(len(w)/len(c)*100,1),
                     "2020-23(參考)": round(d[d.index < "2024-01-01"].sum()/1e4,1), "2024起口數": len(t[t.exit_ts >= "2024-01-01"]),
                     "開盤成交口": int(((t.entry_ts.dt.strftime("%H:%M").isin(["08:45","15:00"])) | (t.exit_ts.dt.strftime("%H:%M").isin(["08:45","15:00"])))[t.exit_ts >= "2024-01-01"].sum())})
R = pd.DataFrame(rows); R.to_csv(H+"realcost_20261031_summary.csv", index=False, encoding="utf-8-sig")
pd.set_option("display.width", 300); print(R.to_string(index=False))
t = T[T.exit_ts >= "2024-01-01"]; print("avg slip per side (R) 2024+ by year:", t.groupby(t.exit_ts.dt.year)[["slip_in","slip_out"]].mean().mean(axis=1).round(2).to_dict())
