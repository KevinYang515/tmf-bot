import os, sys; sys.path.insert(0, ".")
import pandas as pd, numpy as np
import fa_run5 as F
G = F.G; G["_OFF"] = 0; gw = F.gw; p = F.v30e_ltp()
H = "E:/stock/v38_v29_snr_20261017/"
A = gw.load_1min(H + "mxf_1min_2020_20261111.csv"); B = gw.load_1min(H + "mxf_1min_2020_20261121.csv")
print("load", A.shape, B.shape, A.columns.tolist())
n = len(A) - 1
for c in A.columns:
    x, y = A[c].iloc[:n].values, B[c].iloc[:n].values
    if not (pd.Series(x).equals(pd.Series(y))): print("load col differs", c)
a = G["prepare"](A, p); b = G["prepare"](B, p)
cut = a.open_ts < "2026-11-01"; aa = a[cut].reset_index(drop=True); bb = b.iloc[:len(aa)].reset_index(drop=True)
print("prepare", a.shape, b.shape, (aa.open_ts.values == bb.open_ts.values).all())
for c in aa.columns:
    u, v = aa[c], bb[c]
    if u.dtype.kind in "fc":
        d = ~((u == v) | (u.isna() & v.isna()))
    else:
        d = u.astype(str) != v.astype(str)
    if d.any(): print("prepare col", c, int(d.sum()), "first", aa.open_ts[d].iloc[0], u[d].iloc[0], v[d].iloc[0])
