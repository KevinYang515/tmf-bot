import sys; from pathlib import Path
import pandas as pd
sys.path.insert(0, r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
from engine_v26_bbw import load_1min, run, COMMISSION, POINT_VALUE
from multiprocessing import Pool
DATA = Path(__file__).with_name("mxf_1min_corrected_20261022.csv")
V = {"v27": {"opt_stale_hr": 10, "opt_cooldown_min": 30},
     "v28": {"opt_stale_hr": 10, "opt_cooldown_min": 30, "opt_short_pyramid_cap_mode": "hour4"},
     "v29": {"opt_stale_hr": 10, "opt_cooldown_min": 30, "opt_short_pyramid_cap_mode": "hour4", "l_trailBase": 3.5}}
def go(k):
    t = run(load_1min(DATA), p=V[k], intrabar_mode="1min")
    t["net"] = t.pnl.astype(float) - (2*(40-COMMISSION) + 2*4*POINT_VALUE)
    t["v"] = k; return t
if __name__ == "__main__":
    with Pool(3) as pool: T = pd.concat(pool.map(go, list(V)))
    T["exit_ts"] = pd.to_datetime(T.exit_ts); T.to_csv("recent_20261022_trades.csv", index=False, encoding="utf-8-sig")
    # trading-day date: night session (>=15:00) belongs to next day
    d = T.exit_ts.dt.normalize() + pd.to_timedelta((T.exit_ts.dt.hour >= 15).astype(int), "D")
    D = T.assign(d=d).pivot_table(index="d", columns="v", values="net", aggfunc="sum")
    m = load_1min(DATA); m["d"] = m.ts.dt.normalize() + pd.to_timedelta((m.ts.dt.hour >= 15).astype(int), "D")
    cl = m.groupby("d").close.last(); D["BH"] = cl.diff()*POINT_VALUE
    D = D.fillna(0).sort_index(); D.to_csv("recent_20261022_daily.csv", encoding="utf-8-sig")
    end = D.index.max(); print("last day", end.date())
    def mdd(p): e = p.cumsum(); return (e-e.cummax()).min()
    for lab, mo in [("近1月",1),("近3月",3),("近6月",6),("近12月",12)]:
        s = D[D.index > end - pd.DateOffset(months=mo)]
        print(lab, " | ".join(f"{c} {s[c].sum()/1e4:.1f}萬 (MDD {mdd(s[c])/1e4:.1f})" for c in ["v27","v28","v29","BH"]))
    print((D.groupby(D.index.to_period("M")).sum()/1e4).tail(13).round(1))
    print((D.groupby(D.index.year).sum()/1e4).round(1))
    s = D[D.index > end - pd.DateOffset(months=12)]
    for c in ["v27","v28","v29"]:
        tt = T[(T.v==c)&(T.exit_ts > end - pd.DateOffset(months=12))]
        print(c, "lots", len(tt), "win", round((tt.net>0).mean(),2), "avgW", round(tt.net[tt.net>0].mean()), "avgL", round(tt.net[tt.net<=0].mean()))
    print("corr12m", s.corr().round(2).to_string())
