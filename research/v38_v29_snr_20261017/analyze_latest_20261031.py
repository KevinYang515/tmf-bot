import pandas as pd, numpy as np
H = "E:/stock/v38_v29_snr_20261017/"
T = pd.read_csv(H+"latest_20261031_trades.csv", parse_dates=["entry_ts","exit_ts"]); T = T[T.exit_ts >= "2024-01-01"]
def tday(s): return s.dt.normalize() + pd.to_timedelta((s.dt.hour >= 15).astype(int), "D")
def mdd(p): e = p.cumsum(); return (e - e.cummax()).min()
def camp(t):
    t = t.sort_values("entry_ts").reset_index(drop=True); t["cid"] = ""
    for s in ["L","S"]:
        m = t.side == s; c = (t.kind.eq("Cmd") & m).cumsum(); t.loc[m, "cid"] = s + c[m].astype(str)
    return t.groupby("cid").net.sum()
order = list(dict.fromkeys(T.case))
pd.set_option("display.width", 300)
for slip in (4, 8, 12):
    T["net"] = T.pnl - 40 - 2*slip*50
    D = T.assign(d=tday(T.exit_ts)).pivot_table(index="d", columns="case", values="net", aggfunc="sum").fillna(0).sort_index()[order]
    end = D.index.max(); rows = []
    for k in order:
        s = D[k]; c = camp(T[T.case == k]); w, l = c[c > 0], c[c <= 0]; mo = s.groupby(s.index.to_period("M")).sum()
        r = {"版本": k, "2024": s[s.index.year == 2024].sum(), "2025": s[s.index.year == 2025].sum(), "2026": s[s.index.year == 2026].sum(), "2024起": s.sum()}
        for lab, m in [("近12月", 12), ("近6月", 6), ("近3月", 3), ("近1月", 1)]: r[lab] = s[s.index > end - pd.DateOffset(months=m)].sum()
        r = {a: (round(b/1e4, 1) if a != "版本" else b) for a, b in r.items()}
        r.update({"2024起MDD": round(mdd(s)/1e4, 1), "近12月MDD": round(mdd(s[s.index > end - pd.DateOffset(months=12)])/1e4, 1),
                  "賺錢月": f"{(mo > 0).sum()}/{len(mo)}", "波段賺賠比": round(w.mean()/-l.mean(), 2), "波段勝率%": round(len(w)/len(c)*100, 1), "口數": len(T[T.case == k])})
        rows.append(r)
    R = pd.DataFrame(rows).set_index("版本"); R.to_csv(H+f"latest_20261031_slip{slip}.csv", encoding="utf-8-sig")
    print(f"\n=== 滑價每邊 {slip} 點 (每口來回成本 {40+2*slip*50} 元) 資料到 {T.exit_ts.max()} ==="); print(R.to_string())
m1 = pd.read_csv(H+"mxf_1min_2020_20261031.csv", parse_dates=["ts"]); m1["r"] = m1.High - m1.Low
print("\n1分K平均振幅(點) by year:", m1.groupby(m1.ts.dt.year).r.mean().round(1).to_dict())
print("1分K平均振幅(點) 2026 by month:", m1[m1.ts.dt.year == 2026].groupby(m1.ts.dt.month).r.mean().round(1).to_dict())
