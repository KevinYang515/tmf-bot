"""Round 8 scoring per PREREG (risk-adjusted)."""
import sys, glob; sys.path.insert(0, ".."); import pandas as pd, numpy as np
import fa_cost
fa_cost._src = fa_cost._src.replace("mxf_1min_2020_20261111.csv", "shadow_gates/mxf_1min_live.csv")
T = fa_cost.load(glob.glob(fa_cost.H + "gap/fable_audit/round8/eng/*_off*.csv")); assert T.net_R.notna().all()
mdd = fa_cost.mdd; BT = "NOBE"
wk = pd.to_datetime(T.exit_ts).dt.dayofweek.eq(0) & pd.to_datetime(T.entry_ts).lt(pd.to_datetime(T.exit_ts) - pd.Timedelta(hours=48))
T["wkgap"] = wk
rows = []
for (tag, o), t in T.groupby(["tag", "off"]):
    d = t.groupby("d").net_R.sum(); a = d[d.index >= "2024-01-01"]; b = d[d.index < "2024-01-01"]
    rows.append(dict(tag=tag, off=o, net24=a.sum()/1e4, mdd24=mdd(a)/1e4, RR24=a.sum()/abs(mdd(a)), net23=b.sum()/1e4, mdd23=mdd(b)/1e4, RR23=b.sum()/abs(mdd(b)),
                     worst24=a.min()/1e4, wkgap24=t[t.wkgap & (t.d >= "2024-01-01")].net_R.sum()/1e4, n=len(t)))
R = pd.DataFrame(rows); B = R[R.tag == BT].set_index("off")
R["bRR24"] = R.off.map(B.RR24); R["bRR23"] = R.off.map(B.RR23)
M = R.groupby("tag").agg(net24=("net24","mean"), mdd24=("mdd24","mean"), RR24=("RR24","mean"), net23=("net23","mean"), mdd23=("mdd23","mean"), RR23=("RR23","mean"),
                         worst24=("worst24","mean"), wkgap24=("wkgap24","mean"), n=("n","mean"),
                         w24=("RR24", lambda s: 0), )
M["w24"] = R.assign(w=R.RR24 > R.bRR24).groupby("tag").w.sum(); M["nw23"] = R.assign(w=R.RR23 >= R.bRR23).groupby("tag").w.sum()
bb = M.loc[BT]
def verdict(tag, r):
    if tag == BT: return "—"
    k = 1.10
    c = [r.RR24 >= k*bb.RR24, r.w24 >= 3, r.net24 >= 0.85*bb.net24, r.nw23 >= 3]
    return "PASS" if all(c) else "FAIL(" + "".join(str(i+1) for i, x in enumerate(c) if not x) + ")"
M["verdict"] = [verdict(t, r) for t, r in M.iterrows()]
pd.set_option("display.width", 250)
print("=== 4 切法平均（萬元；RR=淨利/最大回撤）基準 NOBE ===")
print(M.round(2).to_string())
print("\n逐切法 RR24:\n" + R.pivot(index="tag", columns="off", values="RR24").round(2).to_string())
print("\n逐切法 net24:\n" + R.pivot(index="tag", columns="off", values="net24").round(1).to_string())
# recent weekend check: Mon 2026-11-23 not in data (data ends Fri night) -> open lots at end
e = T[T.exit_ts >= "2026-11-21 04:59"].groupby(["tag","off","side"]).size().unstack(["side"]).fillna(0)
print("\n資料結尾(11/21 05:00)仍持有口數（=週末留倉）:\n" + e.groupby("tag").mean().round(1).to_string())
M.to_csv("summary6.csv")
print("\n=== 2026-07~ 與 Add_SL ===")
for (tag,o),t in T.groupby(["tag","off"]):
    if o!=0: continue
    d=t.groupby("d").net_R.sum(); r=d[d.index>="2026-07-01"]
    s=t[t.exit_sig.astype(str).str.endswith("Add_SL")&(pd.to_datetime(t.exit_ts)>="2026-07-01")]
    print(tag, "net萬",round(r.sum()/1e4,1),"MDD萬",round(mdd(r)/1e4,1),"Add_SL筆",len(s),"平均點",round((s.pnl/50).mean()) if len(s) else 0)
