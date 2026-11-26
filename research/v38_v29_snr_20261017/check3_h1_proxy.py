import sys, pandas as pd, numpy as np
df = pd.read_csv(sys.argv[1], parse_dates=["entry_ts"])
L = df[df.side == "L"].copy()
cmd = L[L.kind == "Cmd"].groupby("campaign_id").entry_px.first()
a = L[L.kind.isin(["Add", "G"])].copy()
a["cmd_px"] = a.campaign_id.map(cmd)
a = a.dropna(subset=["cmd_px"])
a["fav_atr"] = (a.entry_px - a.cmd_px) / a.entry_atr5
a["ordinal"] = a.sort_values("entry_ts").groupby("campaign_id").cumcount() + 1
a["H"] = np.where(a.entry_ts < "2025-04-01", "H1", "H2")
for f in ["hvn_5d_pct_behind_atr", "hvn_5d_atr_behind_atr"]:
    v = a.dropna(subset=[f])
    print(f"\n== {f} n={len(v)}  rho(fav)={v[f].corr(v.fav_atr, method='spearman'):.2f}  rho(ord)={v[f].corr(v.ordinal, method='spearman'):.2f}  rho(mfe? no)")
    v["fav_t"] = pd.qcut(v.fav_atr, 3, labels=["favLo", "favMid", "favHi"])
    for (t, h), g in v.groupby(["fav_t", "H"], observed=True):
        g = g.copy(); g["q"] = pd.qcut(g[f], 5, labels=False, duplicates="drop") + 1
        m = g.groupby("q").pnl.mean().round(0)
        print(f"{t:6s} {h} n={len(g):4d} Q1..Q5 mean pnl: {list(m.values)}  Q1-rest={g[g.q==1].pnl.mean()-g[g.q>1].pnl.mean():.0f}")
    for k in ["Add", "G"]:
        g = v[v.kind == k].copy(); g["q"] = pd.qcut(g[f], 5, labels=False, duplicates="drop") + 1
        print(f"kind={k} n={len(g)} Q1..Q5: {list(g.groupby('q').pnl.mean().round(0).values)}")
