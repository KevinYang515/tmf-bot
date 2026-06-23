"""查 PUFG6 是哪檔股票 + margin 詳細"""
import shioaji as sj, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path.home() / "stock/.env")
api = sj.Shioaji(simulation=False)
api.login(os.environ["SJ_API_KEY"], os.environ["SJ_SECRET_KEY"], fetch_contract=True)

# 個股期 PUF 是哪檔
print("=" * 60)
print("【PUF 個股期合約】")
print("=" * 60)
puf_list = list(api.Contracts.Futures.PUF) if hasattr(api.Contracts.Futures, "PUF") else []
for c in puf_list[:5]:
    print(f"  PUF code={c.code} name={getattr(c, 'name', '?')} "
          f"underlying={getattr(c, 'underlying_code', '?')} delivery={c.delivery_month}")

# 帳戶 margin 資訊
print()
print("=" * 60)
print("【帳戶 margin】")
print("=" * 60)
try:
    margin = api.margin(api.futopt_account)
    for k, v in margin.__dict__.items():
        print(f"  {k}: {v}")
except Exception as e:
    print(f"  err: {e}")

# 部位詳細
print()
print("=" * 60)
print("【部位詳細】")
print("=" * 60)
for p in api.list_positions(api.futopt_account):
    print(f"  {p.code}: dir={p.direction} qty={p.quantity} price={p.price} pnl={p.pnl}")

api.logout()
print("\n[Done]")
