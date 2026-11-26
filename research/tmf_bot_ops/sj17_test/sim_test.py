"""Shioaji 1.7.11 compatibility test in SIMULATION mode only (never production). Prints no credentials/account ids.
Usage: ~/sj17/bin/python sim_test.py [--orders]"""
import os, sys, time, traceback
from dotenv import dotenv_values
import shioaji as sj
from shioaji.constant import Action, OrderType, FuturesOCType, FuturesPriceType

E = dotenv_values(os.path.expanduser("~/stock/.env"))
ORD = "--orders" in sys.argv
res = []
def step(name, fn):
    t = time.time()
    try:
        out = fn(); res.append((name, "OK", round(time.time() - t, 2), out)); return out
    except Exception as e:
        res.append((name, "FAIL", round(time.time() - t, 2), f"{type(e).__name__}: {str(e)[:150]}")); return None

api = sj.Shioaji(simulation=True)
assert getattr(api, "simulation", True) is not False
step("login(sim)", lambda: (api.login(api_key=E["SJ_API_KEY"], secret_key=E["SJ_SECRET_KEY"]), "accounts ok")[1])
step("login old kwarg contracts_timeout (expect FAIL)", lambda: sj.Shioaji(simulation=True).login(api_key="x", secret_key="y", contracts_timeout=10000))
step("futopt_account exists", lambda: api.futopt_account is not None)
step("fetch_contracts", lambda: (api.fetch_contracts(contracts_timeout=30000), "ok")[1])
mxf = step("MXF contracts", lambda: [c.code + "/" + c.delivery_month for c in api.Contracts.Futures.MXF])
c = None
try:
    cs = [x for x in api.Contracts.Futures.MXF if x.code[-2:] not in ("R1", "R2")]
    c = sorted(cs, key=lambda x: x.delivery_month)[0]
except Exception:
    pass
step("snapshots", lambda: {k: getattr(api.snapshots([c])[0], k, None) for k in ("close", "buy_price", "sell_price", "ts")})
step("list_positions(timeout=5000)", lambda: [(p.code, str(p.direction), p.quantity) for p in api.list_positions(api.futopt_account, timeout=5000)])
step("margin", lambda: {k: getattr(api.margin(api.futopt_account), k, None) for k in ("equity", "available_margin")})
step("list_profit_loss", lambda: len(api.list_profit_loss(api.futopt_account, begin_date="2026-11-01", end_date="2026-11-18")))
step("usage", lambda: str(api.usage())[:120])
if ORD and c is not None:
    snap = api.snapshots([c])[0]; px = float(snap.close)
    def lmt_cancel():
        o = api.Order(action=Action.Buy, price=round(px * 0.9), quantity=1, order_type=OrderType.ROD, price_type=FuturesPriceType.LMT,
                      octype=FuturesOCType.Auto, account=api.futopt_account)
        tr = api.place_order(c, o); time.sleep(2); api.update_status(api.futopt_account); s1 = str(tr.status.status)
        api.cancel_order(tr); time.sleep(2); api.update_status(api.futopt_account); return f"placed:{s1} after cancel:{tr.status.status}"
    step("LMT ROD far + cancel", lmt_cancel)
    def mkp(action, oc):
        o = api.Order(action=action, price=0, quantity=1, order_type=OrderType.IOC, price_type=FuturesPriceType.MKP, octype=oc, account=api.futopt_account)
        tr = api.place_order(c, o); time.sleep(2); api.update_status(api.futopt_account)
        st = str(tr.status.status); deals = getattr(tr.status, "deals", []) or []
        return f"status_str={st!r} 'Filled' in st={'Filled' in st and 'Part' not in st} deals={[(d.price, d.quantity) for d in deals]}"
    step("MKP IOC buy (Auto)", lambda: mkp(Action.Buy, FuturesOCType.Auto))
    step("positions after buy", lambda: [(p.code, str(p.direction), p.quantity) for p in api.list_positions(api.futopt_account, timeout=5000)])
    step("MKP IOC sell (Cover)", lambda: mkp(Action.Sell, FuturesOCType.Cover))
    step("Cover with NO position (behaviour check)", lambda: mkp(Action.Sell, FuturesOCType.Cover))
    step("positions end", lambda: [(p.code, str(p.direction), p.quantity) for p in api.list_positions(api.futopt_account, timeout=5000)])
try: api.logout()
except Exception: pass
print("shioaji", sj.__version__, "| contract used:", getattr(c, "code", None))
for r in res: print(f"{r[1]:4s} {r[2]:6.2f}s  {r[0]:45s} {r[3]}")
