"""
Shioaji 登入測試 — 在 VM 上執行
  python3 test_sj_login.py
"""
import os, sys
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import shioaji as sj

api_key    = os.environ.get("SJ_API_KEY")
secret_key = os.environ.get("SJ_SECRET_KEY")

if not api_key or not secret_key:
    print("[ERROR] .env 缺少 SJ_API_KEY 或 SJ_SECRET_KEY")
    sys.exit(1)

print(f"API key: {api_key[:6]}***")
print("登入中 (simulation=True)...")

api = sj.Shioaji(simulation=True)
api.login(api_key=api_key, secret_key=secret_key)

print("✓ 登入成功")
print(f"  股票帳號: {api.stock_account}")
print(f"  期貨帳號: {api.futopt_account}")

# 測試拉一個合約
ct = api.Contracts.Stocks.get("2330")
if ct:
    print(f"  台積電合約: {ct.code} {ct.name} tick={ct.unit}")
else:
    print("  [WARN] 抓不到 2330 合約，contracts 可能未初始化")

api.logout()
print("登出完成")
