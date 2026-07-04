"""
回填 26 個 gap_night_pct 缺失的交易日（絕大多數是週一），驗證修正後的
fetch_ref_close 邏輯（往前查4天視窗，取範圍內最後一根05:00 bar）能不能抓到，
並算出正確的 gap_night_pct，看有沒有本來該觸發卻被 bug 藏起來的交易日。
在 VM 上跑（需要 Shioaji 歷史 kbars）。
"""
import shioaji as sj, os, time
import pandas as pd
import numpy as np
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.home() / "stock/.env")
api = sj.Shioaji(simulation=False)
api.login(os.environ["SJ_API_KEY"], os.environ["SJ_SECRET_KEY"], fetch_contract=True)

contracts = [c for c in api.Contracts.Futures.TMF if len(c.code) <= 5]
contract = sorted(contracts, key=lambda c: c.delivery_date)[0]
print("contract:", contract.code, contract.delivery_date)

all8 = pd.read_csv(Path.home() / "stock/backtest/gap_days_all_2026.csv")
missing = all8[all8["gap_night_pct"].isna()].copy()
print(f"缺失天數: {len(missing)}")

MISSING_DATES = missing["date"].tolist()
OPENS = dict(zip(missing["date"], missing["open"]))

results = []
for d in MISSING_DATES:
    d_ts = pd.Timestamp(d)
    start = (d_ts - pd.Timedelta(days=4)).strftime("%Y-%m-%d")
    try:
        kb = api.kbars(contract, start=start, end=d)
        df = pd.DataFrame({**kb})
        if df.empty:
            results.append({"date": d, "night_close": None, "note": "kbars empty"})
            time.sleep(0.3)
            continue
        df["ts"] = pd.to_datetime(df["ts"])
        m = df[(df["ts"].dt.hour == 5) & (df["ts"].dt.minute == 0)]
        if m.empty:
            results.append({"date": d, "night_close": None, "note": "no 05:00 bar in window"})
        else:
            nc = float(m.iloc[-1]["Close"])
            bar_date = m.iloc[-1]["ts"].strftime("%Y-%m-%d")
            op = OPENS[d]
            gap_pct = (op - nc) / nc * 100
            results.append({"date": d, "night_close": nc, "bar_actual_date": bar_date,
                             "open": op, "gap_night_pct": gap_pct,
                             "cross_05": abs(gap_pct) >= 0.5, "note": "OK"})
    except Exception as e:
        results.append({"date": d, "night_close": None, "note": f"ERROR: {e}"})
    time.sleep(0.3)

res = pd.DataFrame(results)
pd.set_option("display.width", 160)
pd.set_option("display.max_rows", 40)
print(res.to_string(index=False))

n_ok = res["note"].eq("OK").sum()
n_cross = res.get("cross_05", pd.Series(dtype=bool)).sum() if "cross_05" in res.columns else 0
print(f"\n成功回填: {n_ok}/{len(res)}")
print(f"回填後 |gap_night_pct| >= 0.5% (會觸發): {n_cross} 天")
if n_cross:
    print(res[res.get("cross_05", False) == True][["date", "open", "night_close", "gap_night_pct"]].to_string(index=False))

res.to_csv(Path.home() / "stock/backtest/monday_backfill_result.csv", index=False)
print("\n存檔 -> ~/stock/backtest/monday_backfill_result.csv")

api.logout()
