"""
手動補空 1 口 TMFG6 — 對齊 TV S_Cmd 訊號 @ 46277
=================================================
策略：
1. 先試 LMT @ market mid（夜盤 MKP 可能被 broker 拒絕）
2. 失敗的話降級試 MKP
3. 全程 dump trade.status 找出 broker 拒收的真實 reason
"""
import shioaji as sj
from shioaji.constant import Action, OrderType, FuturesOCType, FuturesPriceType
import os, time, pprint, json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.home() / "stock/.env")

api = sj.Shioaji(simulation=False)
api.login(os.environ["SJ_API_KEY"], os.environ["SJ_SECRET_KEY"], fetch_contract=True)
print("[Login] OK")

# 啟用憑證 (real 必要)
ca_path = Path.home() / "stock" / os.environ.get("SJ_CA_PATH", "Sinopac-1.pfx")
try:
    api.activate_ca(
        ca_path=str(ca_path),
        ca_passwd=os.environ["SJ_CA_PASS"],
        person_id=os.environ["SJ_PERSON_ID"],
    )
    print("[CA] activated")
except Exception as e:
    print(f"[CA] activation fail: {e}")

# 找 TMFG6
contracts = [c for c in api.Contracts.Futures.TMF if len(c.code) <= 5]
target_month = "202607"
contract = None
for c in contracts:
    if c.delivery_month == target_month:
        contract = c; break
if contract is None:
    contract = sorted(contracts, key=lambda x: x.delivery_month)[0]
print(f"[Contract] {contract.code} delivery_month={contract.delivery_month}")

# 抓即時 snapshot 看 bid/ask
snap = api.snapshots([contract])
if snap:
    s = snap[0]
    print(f"[Snap] close={s.close} bid={s.buy_price} ask={s.sell_price} vol={s.volume} amount={s.amount}")
    market_close = float(s.close)
else:
    print("[Snap] no data, using signal_price 46277")
    market_close = 46277

# 現有部位
positions = api.list_positions(api.futopt_account)
print("[Positions] before:")
for p in positions:
    print(f"  {p.code} {p.direction} {p.quantity} 口 @ {p.price}")
if not positions:
    print("  (空手)")


def dump(trade, label):
    print(f"\n=== {label} ===")
    try:
        print("trade.status:")
        pprint.pprint(trade.status.__dict__)
    except Exception as e:
        print(f"  status dump fail: {e}")
    try:
        print("trade.order:")
        pprint.pprint(trade.order.__dict__)
    except Exception as e:
        print(f"  order dump fail: {e}")
    try:
        print("trade.contract.code:", trade.contract.code)
    except:
        pass


# ---- 嘗試 1: LMT @ market_close (最常見成功) ROD ----
print("\n========== ATTEMPT 1: LMT @ market_close ROD ==========")
try:
    order1 = api.Order(
        action=Action.Sell,
        price=int(market_close),
        quantity=1,
        order_type=OrderType.ROD,
        price_type=FuturesPriceType.LMT,
        octype=FuturesOCType.Auto,
        account=api.futopt_account,
    )
    trade1 = api.place_order(contract, order1)
    print(f"[Order1] submitted, waiting 4s for fill...")
    time.sleep(4)
    api.update_status(api.futopt_account)
    dump(trade1, "Attempt 1 result (LMT/ROD)")

    if str(trade1.status.status) in ("Filled", "PartFilled"):
        print(f"\n✅ SUCCESS Attempt 1: status={trade1.status.status}")
        positions = api.list_positions(api.futopt_account)
        print("[Positions] after:")
        for p in positions:
            print(f"  {p.code} {p.direction} {p.quantity} 口 @ {p.price}")
        api.logout()
        exit()
    elif str(trade1.status.status) == "Submitted":
        # 還掛單沒成 — 取消，試下個方法
        print(f"\n⏳ Submitted but not filled, cancelling and trying next method")
        try:
            api.cancel_order(trade1)
            time.sleep(2)
        except Exception as e:
            print(f"  cancel fail: {e}")
except Exception as e:
    print(f"\n❌ Attempt 1 exception: {e}")


# ---- 嘗試 2: LMT @ bid price - 1 (更積極) ROD ----
snap = api.snapshots([contract])
if snap:
    s = snap[0]
    bid_minus = max(int(s.buy_price) - 1, int(s.buy_price))
    print(f"\n========== ATTEMPT 2: LMT @ bid_price ({bid_minus}) ROD ==========")
    try:
        order2 = api.Order(
            action=Action.Sell,
            price=bid_minus,
            quantity=1,
            order_type=OrderType.ROD,
            price_type=FuturesPriceType.LMT,
            octype=FuturesOCType.Auto,
            account=api.futopt_account,
        )
        trade2 = api.place_order(contract, order2)
        time.sleep(4)
        api.update_status(api.futopt_account)
        dump(trade2, "Attempt 2 result (LMT/ROD @ bid)")
        if str(trade2.status.status) in ("Filled", "PartFilled"):
            print(f"\n✅ SUCCESS Attempt 2")
            api.logout(); exit()
        elif str(trade2.status.status) == "Submitted":
            api.cancel_order(trade2)
            time.sleep(2)
    except Exception as e:
        print(f"\n❌ Attempt 2 exception: {e}")


# ---- 嘗試 3: MKP IOC（複製 app.py 邏輯）看 dump 真實 reason ----
print(f"\n========== ATTEMPT 3: MKP IOC（複製 app.py 失敗的方式）==========")
try:
    order3 = api.Order(
        action=Action.Sell,
        price=0,
        quantity=1,
        order_type=OrderType.IOC,
        price_type=FuturesPriceType.MKP,
        octype=FuturesOCType.Auto,
        account=api.futopt_account,
    )
    trade3 = api.place_order(contract, order3)
    time.sleep(3)
    api.update_status(api.futopt_account)
    dump(trade3, "Attempt 3 result (MKP/IOC — app.py 用的方式)")
except Exception as e:
    print(f"\n❌ Attempt 3 exception: {e}")


# 最終部位
positions = api.list_positions(api.futopt_account)
print("\n[Positions] FINAL:")
for p in positions:
    print(f"  {p.code} {p.direction} {p.quantity} 口 @ {p.price}")
if not positions:
    print("  (仍空手 — 全部嘗試失敗)")

api.logout()
print("\n[Done]")
