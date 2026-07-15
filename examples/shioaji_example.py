"""
永豐 Shioaji API 範例
=====================
安裝：pip install "shioaji[speed]" pandas

機密資料一律走環境變數（跟本 repo 其他腳本同慣例），不要寫進程式碼：

    SJ_API_KEY     API 金鑰
    SJ_SECRET_KEY  API 密鑰
    SJ_CA_PATH     憑證 .pfx 路徑（實單才需要）
    SJ_CA_PASS     憑證密碼
    SJ_PERSON_ID   身分證字號

PowerShell 設定範例：
    $env:SJ_API_KEY = "..."; $env:SJ_SECRET_KEY = "..."
Linux / VM（放 ~/.bashrc 或 systemd EnvironmentFile）：
    export SJ_API_KEY=...

已知陷阱（血淚換來的）：
- 現股當沖「先賣後買」要用 daytrade_short=True，不是 first_sell
- 下單被拒不會丟 exception，place_order 後務必 update_status 檢查
- 股票 kbar 的 Volume 單位是「張」不是股
- API 流量每日 2GB，抓歷史 K 線很吃量，超額後不會馬上重置
- future_settle_profitloss 是結算價損益，跟 FIFO 成交價對不上
"""
import os
import shioaji as sj
from shioaji.constant import (
    Action, StockPriceType, OrderType, StockOrderLot, StockOrderCond,
    FuturesPriceType, FuturesOCType,
)

API_KEY    = os.environ["SJ_API_KEY"]
SECRET_KEY = os.environ["SJ_SECRET_KEY"]
CA_PATH    = os.environ.get("SJ_CA_PATH", "Sinopac-1.pfx")
CA_PASS    = os.environ.get("SJ_CA_PASS")
PERSON_ID  = os.environ.get("SJ_PERSON_ID")

SIMULATION = os.environ.get("SJ_SIMULATION", "1") == "1"  # 預設模擬環境


# ── 1. 登入 ────────────────────────────────────────────────
api = sj.Shioaji(simulation=SIMULATION)
api.login(api_key=API_KEY, secret_key=SECRET_KEY, contracts_timeout=10_000)

# 實單下股票/期貨前要啟用憑證（模擬環境不用）
if not SIMULATION:
    ok = api.activate_ca(ca_path=CA_PATH, ca_passwd=CA_PASS, person_id=PERSON_ID)
    assert ok, "憑證啟用失敗"

# ── 2. 商品檔 ──────────────────────────────────────────────
stk = api.Contracts.Stocks["2330"]          # 台積電
mxf = api.Contracts.Futures.MXF["MXFR1"]    # 小台近月（R1 = 自動換月連續合約）

# ── 3. 行情：快照 / 歷史 K 線 / tick 訂閱 ─────────────────
snap = api.snapshots([stk])[0]
print("snapshot:", snap.close, snap.volume, snap.buy_price, snap.sell_price)

import pandas as pd
kbars = api.kbars(stk, start="2026-07-14", end="2026-07-15")
df = pd.DataFrame({**kbars})
df["ts"] = pd.to_datetime(df["ts"])
print(df.tail(3))   # ⚠️ 股票 kbar 的 Volume 單位是「張」


def on_tick(exchange, tick):
    print("tick:", tick.code, tick.close, tick.volume)

api.quote.set_on_tick_stk_v1_callback(on_tick)
api.quote.subscribe(stk, quote_type="tick")

# ── 4. 股票下單 ────────────────────────────────────────────
order = api.Order(
    price=1050.0,
    quantity=1,                          # 單位：張
    action=Action.Buy,
    price_type=StockPriceType.LMT,       # LMT 限價 / MKT 市價
    order_type=OrderType.ROD,            # ROD / IOC / FOK
    order_lot=StockOrderLot.Common,      # Common 整股 / IntradayOdd 盤中零股
    order_cond=StockOrderCond.Cash,      # Cash 現股 / MarginTrading / ShortSelling
    account=api.stock_account,
)
trade = api.place_order(stk, order)

# ⚠️ 現股當沖「先賣後買」要用 daytrade_short=True（不是 first_sell）
sell_first = api.Order(
    price=1050.0, quantity=1,
    action=Action.Sell,
    price_type=StockPriceType.LMT, order_type=OrderType.ROD,
    order_cond=StockOrderCond.Cash,
    daytrade_short=True,
    account=api.stock_account,
)

# ⚠️ 下單後務必檢查狀態，被拒單不會丟 exception
api.update_status(api.stock_account)
print("order status:", trade.status.status)   # Submitted / Filled / Failed / Cancelled
if str(trade.status.status) == "Failed":
    print("拒單原因:", trade.status.msg)

# ── 5. 期貨下單（小台 MXF）────────────────────────────────
f_order = api.Order(
    price=0,
    quantity=1,
    action=Action.Buy,
    price_type=FuturesPriceType.MKP,     # MKP 範圍市價 / LMT / MKT
    order_type=OrderType.IOC,
    octype=FuturesOCType.Auto,           # Auto / New / Cover / DayTrade
    account=api.futopt_account,
)
f_trade = api.place_order(mxf, f_order)

# 改價 / 減量 / 刪單
# api.update_order(trade=trade, price=1045.0)
# api.update_order(trade=trade, qty=1)
# api.cancel_order(trade)

# ── 6. 成交回報 callback ───────────────────────────────────
def on_order(state, msg):
    print(f"[{state}] {msg}")   # OrderState.StockOrder / StockDeal / FuturesOrder ...

api.set_order_callback(on_order)

# ── 7. 帳務 ────────────────────────────────────────────────
print("現股庫存:", api.list_positions(api.stock_account))
print("期貨部位:", api.list_positions(api.futopt_account))
# ⚠️ future_settle_profitloss 是「結算價」損益；長期績效請自己記 equity

print("API 流量:", api.usage())   # 每日 2GB 上限

api.logout()
