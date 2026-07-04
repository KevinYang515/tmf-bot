"""
抓 6 個因 ref_close bug 被藏起來的週一 0845 大 gap 日的 tick 資料，
補進 gap_ticks/ 讓它們能加入回測。用跟原本 gap_ticks 一樣的格式(MXF, 08:44起)。
"""
import shioaji as sj, os, time
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.home() / "stock/.env")
api = sj.Shioaji(simulation=False)
api.login(os.environ["SJ_API_KEY"], os.environ["SJ_SECRET_KEY"], fetch_contract=True)

contract = api.Contracts.Futures.MXF.MXFR1
print("contract:", contract.code)

DATES = ["2026-05-04", "2026-05-11", "2026-05-18", "2026-05-25", "2026-06-01", "2026-06-15"]
OUT_DIR = Path.home() / "stock/backtest/gap_ticks_monday"
OUT_DIR.mkdir(parents=True, exist_ok=True)

for d in DATES:
    print(f"Fetching {d}...", end=" ", flush=True)
    try:
        ticks = api.ticks(contract, date=d)
        df = pd.DataFrame({**ticks})
        if df.empty:
            print("EMPTY")
            continue
        df["ts"] = pd.to_datetime(df["ts"])
        df["time"] = df["ts"].dt.strftime("%H:%M:%S")
        sub = df[(df["time"] >= "08:44:00") & (df["time"] <= "08:52:00")].copy()
        sub = sub.drop(columns=["time"])
        out = OUT_DIR / f"MXF_{d}.csv"
        sub.to_csv(out, index=False)
        print(f"{len(sub)} ticks -> {out.name}")
        time.sleep(0.5)
    except Exception as e:
        print(f"ERROR: {e}")
        time.sleep(1)

api.logout()
print(f"\nDone. Files in {OUT_DIR}")
