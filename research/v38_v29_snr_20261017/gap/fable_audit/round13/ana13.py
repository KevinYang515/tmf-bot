"""Round 13 sweep analysis per PREREG (walk-forward, neighborhood plateau)."""
import sys, glob, itertools; sys.path.insert(0, ".."); import pandas as pd, numpy as np
import fa_cost
fa_cost._src = fa_cost._src.replace("mxf_1min_2020_20261111.csv", "shadow_gates/mxf_1min_live.csv")
fs = glob.glob(fa_cost.H + "gap/fable_audit/round13/eng/SW_*_off*.csv")
T = fa_cost.load(fs); mdd = fa_cost.mdd
rows = []
for (tag, o), t in T.groupby(["tag", "off"]):
    d = t.groupby("d").net_R.sum()
    tr = d[(d.index >= "2020-03-01") & (d.index < "2025-01-01")]; te = d[d.index >= "2025-01-01"]; a24 = d[d.index >= "2024-01-01"]
    rows.append(dict(tag=tag, off=o, rr_tr=tr.sum() / abs(mdd(tr)), rr_te=te.sum() / abs(mdd(te)), net_te=te.sum() / 1e4, rr24=a24.sum() / abs(mdd(a24)), net24=a24.sum() / 1e4, mdd24=mdd(a24) / 1e4))
R = pd.DataFrame(rows)
M = R.groupby("tag")[["rr_tr", "rr_te", "net_te", "rr24", "net24", "mdd24"]].mean()
P = M.index.to_series().str.extract(r"SW_(\d+)_(\d+)_(\d+)_(\d+)").astype(int); P.index = M.index; M = M.join(P.rename(columns={0: "sl", 1: "tr", 2: "pd", 3: "al"}))
G = {"sl": [20, 25, 30], "tr": [25, 30, 35], "pd": [8, 10, 12], "al": [40, 45, 50]}
def nb(r):
    keys = [r.name]
    for k, vals in G.items():
        i = vals.index(r[k])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals):
                q = dict(sl=r.sl, tr=r.tr, pd=r.pd, al=r.al); q[k] = vals[j]
                keys.append(f"SW_{q['sl']}_{q['tr']}_{q['pd']}_{q['al']}")
    return M.loc[[k for k in keys if k in M.index], "rr_tr"].mean()
M["nb_tr"] = M.apply(nb, axis=1)
cur = "SW_25_30_10_45"
M["rank_tr"] = M.rr_tr.rank(ascending=False); M["rank_te"] = M.rr_te.rank(ascending=False)
pd.set_option("display.width", 220)
print("n combos", len(M), " current:", cur)
print("\n=== 依訓練期鄰域平均 nb_tr 排名前 10 ===")
print(M.sort_values("nb_tr", ascending=False).head(10).round(2).to_string())
print("\n=== 現值組 ===\n", M.loc[[cur]].round(2).to_string())
best = M.nb_tr.idxmax()
b = R[R.tag == best].set_index("off"); c = R[R.tag == cur].set_index("off")
w = int((b.rr_te > c.rr_te).sum())
print(f"\n候選 {best}: 驗證RR {M.at[best,'rr_te']:.2f} vs 現值 {M.at[cur,'rr_te']:.2f} (需≥{1.05*M.at[cur,'rr_te']:.2f})，offset 較佳 {w}/4")
print("結論:", "建議改參數" if (M.at[best, 'rr_te'] >= 1.05 * M.at[cur, 'rr_te'] and w >= 3) else "維持現值")
print("\n=== 各參數邊際（訓練RR / 驗證RR 平均）===")
for k in G:
    print(k, M.groupby(k)[["rr_tr", "rr_te"]].mean().round(2).to_dict("index"))
M.to_csv("sweep13.csv", encoding="utf-8-sig")
