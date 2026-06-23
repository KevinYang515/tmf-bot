"""補空 1 口 TMFG6 — 用 LMT @ ask 確保秒成，不 cancel"""
import shioaji as sj, os, time, pprint
from shioaji.constant import Action, OrderType, FuturesOCType, FuturesPriceType
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path.home() / "stock/.env")

api = sj.Shioaji(simulation=False)
api.login(os.environ["SJ_API_KEY"], os.environ["SJ_SECRET_KEY"], fetch_contract=True)
api.activate_ca(
    ca_path=str(Path.home() / "stock" / os.environ.get("SJ_CA_PATH", "Sinopac-1.pfx")),
    ca_passwd=os.environ["SJ_CA_PASS"],
    person_id=os.environ["SJ_PERSON_ID"],
)

# 找 TMFG6
contracts = [c for c in api.Contracts.Futures.TMF if len(c.code) <= 5]
contract = next((c for c in contracts if c.delivery_month == "202607"),
                sorted(contracts, key=lambda x: x.delivery_month)[0])

# Snapshot
snap = api.snapshots([contract])[0]
print(f"[Snap] close={snap.close} bid={snap.buy_price} ask={snap.sell_price}")

# SELL 用 LMT @ bid-1 (低於 bid 1 點 = 馬上成交 buyer 那邊)
# 但夜盤可能 vol 很低，所以挂 bid 等 buyer 主動接更安全
sell_price = int(snap.buy_price)  # = bid，馬上會被 buy side 接掉
print(f"[Plan] SELL 1 口 LMT @ {sell_price} ROD (= 現 bid，秒成)")

# Current pos
print(f"[Position before]")
for p in api.list_positions(api.futopt_account):
    print(f"  {p.code} {p.direction} {p.quantity}口 price={p.price}")

# Place order
order = api.Order(
    action=Action.Sell,
    price=sell_price,
    quantity=1,
    order_type=OrderType.ROD,
    price_type=FuturesPriceType.LMT,
    octype=FuturesOCType.Auto,
    account=api.futopt_account,
)
trade = api.place_order(contract, order)
print(f"[Submit] id={trade.status.id} status={trade.status.status}")

# 等成交（最多 30 秒）
for i in range(30):
    time.sleep(1)
    api.update_status(api.futopt_account)
    st = str(trade.status.status)
    if st == "Filled":
        print(f"[Fill] 第 {i+1}s 成交！deals:")
        for d in trade.status.deals:
            print(f"  qty={d.quantity} price={d.price}")
        break
    elif st == "Failed":
        print(f"[Failed] {trade.status.msg}")
        break
    elif st == "Cancelled":
        print(f"[Cancelled]")
        break

# Final
print()
print(f"[Position after]")
for p in api.list_positions(api.futopt_account):
    print(f"  {p.code} {p.direction} {p.quantity}口 price={p.price}")

# Margin after
m = api.margin(api.futopt_account)
print(f"\n[Margin after] equity={m.equity}  available={m.available_margin}  risk={m.risk_indicator}%")

api.logout()
