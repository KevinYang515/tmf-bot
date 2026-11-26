import pandas as pd, numpy as np
H = "E:/stock/v38_v29_snr_20261017/"
T = pd.read_csv(H+"mlg4_trades_v29_H1_p20.csv", parse_dates=["entry_ts","exit_ts"]); T = T[T.exit_ts >= "2020-03-02"].sort_values("entry_ts").reset_index(drop=True)
T["pts"] = T.net/50; T["hold_h"] = (T.exit_ts-T.entry_ts).dt.total_seconds()/3600; T["yr"] = T.exit_ts.dt.year
# campaign: lot belongs to latest Cmd of same side entered at/before it
T["cid"] = ""
for s in ["L","S"]:
    m = T.side == s; c = (T.kind.eq("Cmd") & m).cumsum(); T.loc[m, "cid"] = s + c[m].astype(str)
def st(g, col="net"):
    w, l = g[col][g[col] > 0], g[col][g[col] <= 0]
    return pd.Series({"筆數": len(g), "勝率%": round(len(w)/len(g)*100,1) if len(g) else np.nan, "均賺萬": round(w.mean()/1e4,2), "均賠萬": round(l.mean()/1e4,2),
                      "賺賠比": round(w.mean()/-l.mean(),2) if len(l) else np.nan, "合計萬": round(g[col].sum()/1e4,1)})
C = T.groupby("cid").agg(side=("side","first"), start=("entry_ts","min"), end=("exit_ts","max"), net=("net","sum"), n=("net","size"),
                          cmd_net=("net", lambda s: s[T.loc[s.index,"kind"].eq("Cmd")].sum()))
C["yr"] = C.end.dt.year; C["hold_h"] = (C.end-C.start).dt.total_seconds()/3600
pd.set_option("display.width", 250)
print("== 單口 vs 波段(Cmd+加碼為一個波段) =="); print(pd.DataFrame({"單口": st(T), "波段": st(C)}).T)
print("== 波段 逐年 =="); print(C.groupby("yr").apply(st).to_string())
print("== 單口 依種類 =="); print(T.groupby(["kind"]).apply(st).to_string())
print("== 單口 依多空 =="); print(T.groupby("side").apply(st).to_string())
print("== 波段 依加碼口數 =="); C["nb"] = pd.cut(C.n, [0,1,2,4,8,100], labels=["只有1口","2口","3-4口","5-8口","9口以上"]); print(C.groupby("nb").apply(st).to_string())
print("== 單口 依出場訊號 =="); print(T.groupby("exit_sig").apply(st).sort_values("合計萬").to_string())
print("== 單口 依持有時間 =="); T["hb"] = pd.cut(T.hold_h, [0,0.5,1,3,10,1000], labels=["<30分","30-60分","1-3時","3-10時",">10時"]); print(T.groupby("hb").apply(st).to_string())
# concentration
w = C.net[C.net > 0].sort_values(ascending=False); tot = C.net.sum()
for k in [10, 20, 50]: print(f"前{k}大獲利波段 = {w.head(k).sum()/1e4:.0f}萬 (總淨利 {tot/1e4:.0f}萬, 波段數 {len(C)})")
l = C.net[C.net <= 0].sort_values(); print("最大10筆虧損波段合計", round(l.head(10).sum()/1e4,1), "萬; 最大單筆", round(l.iloc[0]/1e4,1))
print(C.sort_values("net").head(8)[["side","start","end","n","net"]].to_string())
print("== 2024+ 波段 依加碼口數 =="); print(C[C.yr >= 2024].groupby("nb").apply(st).to_string())
print("== 2024+ 出場訊號 =="); print(T[T.yr >= 2024].groupby("exit_sig").apply(st).sort_values("合計萬").to_string())
