"""
拉取 MXF 1分鐘 K 棒資料，存成 CSV
在 VM 上執行，不影響交易 bot（只是查詢，不下單）
用法：python backtest/fetch_kbars.py
"""
import shioaji as sj
import os
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime, timedelta
from pathlib import Path

DAYS_BACK = 90
OUT_PATH  = Path(__file__).parent / "mxf_1min.csv"

load_dotenv(Path(__file__).parent.parent / ".env")

print("=== 連線 Shioaji ===")
api = sj.Shioaji(simulation=False)
api.login(os.environ["SJ_API_KEY"], os.environ["SJ_SECRET_KEY"], fetch_contract=True)

print(f"=== 拉取 MXF 近 {DAYS_BACK} 天 1分K ===")
contract = api.Contracts.Futures.MXF.MXFR1
start = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
end   = datetime.now().strftime("%Y-%m-%d")

kbars = api.kbars(contract, start=start, end=end)
df = pd.DataFrame({**kbars})
df["ts"] = pd.to_datetime(df["ts"])
df = df.sort_values("ts").reset_index(drop=True)

api.logout()

df.to_csv(OUT_PATH, index=False)
print(f"已儲存 {len(df)} 筆 → {OUT_PATH}")
print(f"範圍: {df['ts'].min()} ~ {df['ts'].max()}")
