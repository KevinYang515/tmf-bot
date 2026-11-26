"""Round 5 summary: XT variants vs NOBE. argv: eng_dir data_file. Pass rule per PREREG (cond4 ties ok, cond5 reported only) + event table."""
import sys, glob, json, os; sys.path.insert(0, ".."); import pandas as pd, numpy as np
import fa_cost
d = sys.argv[1] if len(sys.argv) > 1 else "eng"; DF = sys.argv[2] if len(sys.argv) > 2 else "mxf_1min_2020_20261111.csv"
fa_cost._src = fa_cost._src.replace("mxf_1min_2020_20261111.csv", DF)
from fa_cost import summarize
pd.set_option("display.width", 280); BT = "NOBE"
T = fa_cost.load(glob.glob(fa_cost.H + f"gap/fable_audit/round5/{d}/*_off*.csv"))
assert T.net_R.notna().all(), "net_R NaN (cost model data file?)"
R = summarize(T, BT); b = R[R.tag == BT].groupby("off").first()
for c in ["net24", "ref2023", "exTop10"]: R["w_" + c] = R["d_" + c] > 0
R["tie23"] = R.d_ref2023.abs() < 1e-9
cols = ["net24", "mdd24", "ref2023", "d_net24", "d_ref2023", "d_y24", "d_y25", "d_y26", "d_exTop10"]
M = R.groupby("tag")[cols].mean().round(1).join(R.groupby("tag")[["w_net24", "w_ref2023", "tie23", "w_exTop10"]].sum())
bb = M.loc[BT]
def verdict(r):
    c1 = r.net24 >= 1.05 * bb.net24; c2 = r.w_net24 >= 3; c3 = abs(r.mdd24) <= 1.05 * abs(bb.mdd24); c4 = (r.w_ref2023 + r.tie23) >= 3
    if all([c1, c2, c3, c4]): return "PASS*"
    if (not c1) and r.d_net24 > 0 and all([c2, c3, c4]): return "OBSERVE"
    return "FAIL(" + "".join(str(k + 1) for k, c in enumerate([c1, c2, c3, c4]) if not c) + ")"
M["verdict"] = [("—" if t == BT else verdict(r)) for t, r in M.iterrows()]
print("=== 全期（萬元，4 切法平均）基準 = NOBE ===\n" + M.to_string())
print("\n逐切法 2024+ 差額:\n" + R.pivot(index="tag", columns="off", values="d_net24").round(1).to_string())
# event table: per trading day & side, mean over offsets of daily net_R diff (variant - NOBE), only armed days
D = T.groupby(["tag", "off", "d", "side"]).net_R.sum().unstack(["tag"]).fillna(0)
for tag in sorted(t for t in T.tag.unique() if t != BT):
    arm = set()
    for f in glob.glob(f"{d}/{tag}_off*_xtdays.json"):
        for day, s in json.load(open(f)): arm.add((pd.Timestamp(day), "L" if s > 0 else "S"))
    x = (D[tag] - D[BT]).groupby(["d", "side"]).mean() / 1e4      # mean over offsets
    x = x[x.abs() > 1e-6]
    print(f"\n--- {tag}: 有差異的 (交易日, 方向) 數 {len(x)}（觸發日 {len(arm)}）")
    for s in ("S", "L"):
        z = x.xs(s, level="side") if s in x.index.get_level_values("side") else pd.Series(dtype=float)
        n_arm = sum(1 for a in arm if a[1] == s)
        print(f"  {'空' if s=='S' else '多'}: 觸發日 {n_arm:3d} | 有差異日 {len(z):3d} | 幫到 {int((z>0).sum()):3d} 傷到 {int((z<0).sum()):3d} | 合計 {z.sum():+7.1f}萬 (2024+ {z[z.index>='2024-01-01'].sum():+7.1f}) | 最好 {z.max() if len(z) else 0:+.1f} 最差 {z.min() if len(z) else 0:+.1f}"
              + ("  ← 樣本<10，無法驗證" if n_arm < 10 else ""))
    w = x.sort_values(); print("  最傷 5 天:", [(str(i[0].date()), i[1], round(v, 1)) for i, v in w.head(5).items()])
    print("  最幫 5 天:", [(str(i[0].date()), i[1], round(v, 1)) for i, v in w.tail(5).items()])
M.to_csv(f"summary5_{d}.csv")
