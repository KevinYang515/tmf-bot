"""Re-run v27/v28/v29 and G2 variants on data to 2026-10-29; compare periods incl. BH."""
from pathlib import Path
from multiprocessing import Pool
import pandas as pd
import engine_ml_gate_wrapper as mlg
HERE = Path(__file__).resolve().parent
DATA = HERE / "mxf_1min_2020_20261029.csv"
CONT = Path(r"E:\stock\newstrat_rr_20261019\turtle_continuous_tx_20261029.csv")
TH = 0.72777104
COST = 2 * (40 - mlg.COMMISSION) + 2 * 4 * mlg.POINT_VALUE
V27 = {**mlg.P, "opt_stale_hr": 10, "opt_cooldown_min": 30}
V28 = {**V27, "opt_short_pyramid_cap_mode": "hour4"}
V29 = {**V28, "l_trailBase": 3.5, "l_trailBaseDay": 3.5, "l_trailBaseNight": 3.5}
G = {"opt_ml_gate": {"variant": "G2", "session_cum_vol_rel20_threshold": TH}}
CASES = {"v27": V27, "v28": V28, "v29": V29, "v28_G2": {**V28, **G}, "v29_G2": {**V29, **G}}
def go(k):
    t = mlg.run(mlg.load_1min(DATA), p=CASES[k], intrabar_mode="1min")
    t["net"] = t.pnl.astype(float) - COST; t["v"] = k; return t
def tday(s): s = pd.to_datetime(s); return s.dt.normalize() + pd.to_timedelta((s.dt.hour >= 15).astype(int), "D")
if __name__ == "__main__":
    with Pool(5) as pool: T = pd.concat(pool.map(go, list(CASES)))
    T["exit_ts"] = pd.to_datetime(T.exit_ts); T["entry_ts"] = pd.to_datetime(T.entry_ts)
    T.to_csv(HERE / "cmp_20261029_trades.csv", index=False, encoding="utf-8-sig")
    # consistency vs previous run (lots closed before 2026-10-22)
    prev = {"v28": "mlg2_trades_v28.csv", "v29": "mlg2_trades_v29.csv", "v28_G2": "mlg2_trades_G2_p20.csv", "v29_G2": "mlg2_trades_v29_G2_p20.csv"}
    for k, f in prev.items():
        p = pd.read_csv(HERE / f, parse_dates=["exit_ts"]); cut = pd.Timestamp("2026-10-22")
        a = T[(T.v == k) & (T.exit_ts < cut)].net.sum(); b = p[p.exit_ts < cut].net.sum()
        print(f"check {k}: new {a:,.0f} old {b:,.0f} lots {len(T[(T.v==k)&(T.exit_ts<cut)])}/{len(p[p.exit_ts<cut])}")
    T = T[T.exit_ts >= "2020-03-02"]
    D = T.assign(d=tday(T.exit_ts)).pivot_table(index="d", columns="v", values="net", aggfunc="sum")
    c = pd.read_csv(CONT, parse_dates=["date"]).set_index("date").close_diff
    m = mlg.load_1min(DATA); last = m[m.ts.dt.normalize() == "2026-10-29"]
    last = last[(last.ts.dt.hour >= 8) & (last.ts.dt.hour < 14)]
    if c.index.max() < pd.Timestamp("2026-10-29") and len(last): c.loc[pd.Timestamp("2026-10-29")] = last.close.iloc[-1]
    D["BH"] = c.diff().reindex(D.index.union(c.index)) * mlg.POINT_VALUE
    D = D[D.index >= "2020-03-02"].fillna(0).sort_index()
    D.to_csv(HERE / "cmp_20261029_daily.csv", encoding="utf-8-sig")
    end = D.index.max(); print("last day", end.date())
    cols = ["v27", "v28", "v29", "v28_G2", "v29_G2", "BH"]
    def mdd(p): e = p.cumsum(); return (e - e.cummax()).min()
    rows = []
    for lab, s in [("2020-03起", D), ("2024起", D[D.index >= "2024-01-01"]), ("2026YTD", D[D.index >= "2026-01-01"]),
                   ("近12月", D[D.index > end - pd.DateOffset(months=12)]), ("近6月", D[D.index > end - pd.DateOffset(months=6)]),
                   ("近3月", D[D.index > end - pd.DateOffset(months=3)]), ("近1月", D[D.index > end - pd.DateOffset(months=1)]),
                   ("10/23後", D[D.index > "2026-10-22"])]:
        rows.append({"期間": lab, **{f"{k}": round(s[k].sum() / 1e4, 1) for k in cols}, **{f"{k}_MDD": round(mdd(s[k]) / 1e4, 1) for k in cols}})
    R = pd.DataFrame(rows); R.to_csv(HERE / "cmp_20261029_periods.csv", index=False, encoding="utf-8-sig"); print(R.to_string())
    print((D[cols].groupby(D.index.year).sum() / 1e4).round(1).to_string())
    print((D[cols].groupby(D.index.to_period("M")).sum() / 1e4).round(1).tail(6).to_string())
    print(D[cols][D.index > "2026-10-19"].div(1e4).round(1).to_string())
    print("open/last trades:\n", T[T.exit_ts > "2026-10-22"][["v","side","kind","entry_ts","entry_px","exit_ts","exit_px","exit_sig","net"]].to_string())
