"""Fable's own summary of any eng dir (argv[1], default eng). Base = tag 'base' in that dir. Applies the PREREG pass rule."""
import sys, glob; sys.path.insert(0, ".."); import pandas as pd; from fa_cost import *
pd.set_option("display.width", 280)
d = "eng"; BT = sys.argv[1] if len(sys.argv) > 1 else "base"
T = load(glob.glob(H + f"gap/fable_audit/round4/{d}/*_off*.csv")); R = summarize(T, BT)
B0 = R[R.tag == BT].set_index("off")
for c in ["net24", "ref2023", "exTop10"]: R["w_" + c] = R["d_" + c] > 0
cols = ["net24", "mdd24", "ref2023", "exTop10", "d_net24", "d_ref2023", "d_y24", "d_y25", "d_y26", "d_exTop10", "lots24"]
M = R.groupby("tag")[cols].mean().round(1).join(R.groupby("tag")[["w_net24", "w_ref2023", "w_exTop10"]].sum()).join(R.groupby("tag").off.count().rename("n_off"))
b = M.loc[BT]
def verdict(r):
    c1 = r.net24 >= 1.05 * b.net24; c2 = r.w_net24 >= 3; c3 = abs(r.mdd24) <= 1.05 * abs(b.mdd24); c4 = r.w_ref2023 >= 3; c5 = r.d_exTop10 >= 0
    if all([c1, c2, c3, c4, c5]): return "PASS*"
    if (not c1) and r.d_net24 > 0 and all([c2, c3, c4, c5]): return "OBSERVE"
    return "FAIL(" + "".join(str(k + 1) for k, c in enumerate([c1, c2, c3, c4, c5]) if not c) + ")"
M["verdict"] = [("—" if t == BT else verdict(r)) for t, r in M.iterrows()]
print(M.to_string()); P = R.pivot(index="tag", columns="off", values="d_net24").round(1); print(P.to_string())
print(R.pivot(index="tag", columns="off", values="d_ref2023").round(1).to_string())
M.join(P.add_prefix("d24_off")).to_csv(f"summary4_{BT}.csv")
