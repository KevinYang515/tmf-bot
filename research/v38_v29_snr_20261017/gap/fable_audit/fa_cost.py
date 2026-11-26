"""Cost model R + rtp adjustment, replicated from gap/latest1111/ana.py (read-only source reused via exec). load(tags) -> trades with net_R for mode rtp."""
import pandas as pd, numpy as np, glob
H = "E:/stock/v38_v29_snr_20261017/"
_src = open(H + "gap/analyze_gap_opt_20261031.py", encoding="utf-8").read().split("lastc =")[0]
_src = _src.replace("mxf_1min_2020_20261031.csv", "mxf_1min_2020_20261111.csv")
_src = _src.replace('ts.dt.strftime("%H:%M").isin(["08:45","15:00"])', '(ts.dt.strftime("%H:%M").between("08:40","08:45") | ts.dt.strftime("%H:%M").between("14:55","15:00"))')
_src = _src.replace("(slip(T.entry_ts, T.kind) + slip(T.exit_ts, T.kind))*50", "(slip(T.entry_ts, T.kind) + np.where(T.exit_sig.str.endswith('_LMT'), 0, slip(T.exit_ts, T.kind)))*50")
def load(files):
    src = _src.replace('T = pd.read_csv(H+"gap/gapopt_trades_all.csv", parse_dates=["entry_ts","exit_ts"])',
                       'T = pd.concat([pd.read_csv(f, parse_dates=["entry_ts","exit_ts"]) for f in FILES])')
    g = {"__name__": "x", "FILES": files}; exec(src, g); T = g["T"]; T["slipx"] = g["slip"](T.exit_ts, T.kind); T = T[T.exit_ts >= "2020-03-02"].copy()
    T["d"] = T.exit_ts.dt.normalize() + pd.to_timedelta((T.exit_ts.dt.hour >= 15).astype(int), "D")
    m = T.exit_sig.str.endswith("_LMT"); T.loc[m, "net_R"] -= 50 + T.slipx[m] * 50   # rtp
    T["tag"] = T.case.str.replace(r"_off\d$", "", regex=True); T["off"] = T.case.str[-1].astype(int)
    return T
def mdd(s): e = s.cumsum(); return (e - e.cummax()).min()
TOP10 = pd.to_datetime(['2026-11-06', '2026-07-29', '2026-11-03', '2024-08-05', '2026-07-28', '2026-07-17', '2026-06-10', '2025-04-07', '2026-06-06', '2026-10-15'])
def summarize(T, base_tag="base"):
    rows = []
    for (tag, o), t in T.groupby(["tag", "off"]):
        d = t.groupby("d").net_R.sum(); x = d[d.index >= "2024-01-01"]
        rows.append(dict(tag=tag, off=o, net24=x.sum() / 1e4, mdd24=mdd(x) / 1e4, ref2023=d[d.index < "2024-01-01"].sum() / 1e4, mdd_all=mdd(d) / 1e4,
                         y24=x[x.index.year == 2024].sum() / 1e4, y25=x[x.index.year == 2025].sum() / 1e4, y26=x[x.index.year == 2026].sum() / 1e4,
                         exTop10=x[~x.index.isin(TOP10)].sum() / 1e4, lots24=(t.d >= "2024-01-01").sum()))
    R = pd.DataFrame(rows); B = R[R.tag == base_tag].set_index("off")
    for c in ["net24", "ref2023", "y24", "y25", "y26", "exTop10"]: R["d_" + c] = R[c] - R.off.map(B[c])
    return R
