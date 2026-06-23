# Shioaji 集合競價委託筆記

> Strategy D-Cash 上線必備
> 09:00 集合競價是策略 alpha 的唯一來源（09:01 後 edge 歸零）

## 核心邏輯

```
8:30 - 9:00 之間下「限價買 @ 漲停價」
    ↓
9:00:00 集合競價 cross
    ↓
所有「願買 ≥ cross」的單以 cross price 成交
    ↓
你的單成交在 cross = 開盤價，不是漲停價
```

掛漲停 = **確保被 priority queue 接受** 但成交在實際開盤價。**無滑點**。

## Shioaji API 範例

```python
import shioaji as sj
from shioaji import TFTOrder, OrderType, StockPriceType, Action

# 1. 建立 contract
contract = api.Contracts.Stocks.TSE['7610']  # 或 OTC

# 2. 取漲停價
# 漲停價 = round_down(prev_close × 1.10, tick)
prev_close = 2315.0
limit_up = round_down_to_tick(prev_close * 1.10)  # 例：2546.5
# 注意 tick size：100-500 元 tick=0.5, 500-1000 tick=1, 1000+ tick=5

# 3. 集合競價限價買單
order = api.Order(
    price=limit_up,                # 掛漲停價
    quantity=1,                    # 1 張 = 1000 股
    action=Action.Buy,
    price_type=StockPriceType.LMT, # 限價
    order_type=OrderType.ROD,      # 當日有效
    # 關鍵：要在 8:30-9:00 之間下單，自動進集合競價
)

# 4. 下單
trade = api.place_order(contract, order)
print(trade)
# trade.status.status 會從 Submitted -> PendingSubmit -> Filled 變化

# 5. 9:00 集合競價成交後
# trade.deals[0].price = 實際成交價 = 開盤 cross price
# trade.deals[0].quantity = 成交數量（部分成交可能 < 1 張）

# 6. 9:00 後立即設停利停損
# TP: 限價賣 @ entry + 10*tick
# Stop: 動態 trail（自己維護，每分鐘更新）
```

## 注意事項

### 1. 「集合競價」與「盤中限價」的差別

下單時段決定是否進入集合競價：
- **8:30 - 9:00 下的 LMT 單** → 進入開盤集合競價（9:00 cross）
- **9:00 之後下的 LMT 單** → 進入連續競價（不會 cross 在開盤）

**Strategy D 必須在 8:30-9:00 下單**

### 2. 漲停價 round down 規則

```python
def get_tick(p):
    if p < 10: return 0.01
    if p < 50: return 0.05
    if p < 100: return 0.1
    if p < 500: return 0.5
    if p < 1000: return 1.0
    return 5.0

def limit_up_price(prev_close):
    target = prev_close * 1.10
    tick = get_tick(target)
    # 漲停價是「<= 110%」的最大 tick 倍數
    return (int(target / tick)) * tick
```

### 3. 部分成交處理

集合競價可能只 cross 一部分（你掛 1 張，可能只成交 0.5 張）：
- `trade.deals` 是 list，看每筆 deals 的 quantity
- 若全部 1000 股有成交→繼續 TP/trail
- 若沒成交 → 取消單 + 跳過該筆

### 4. 沒成交的處理

- 沒 cross（買到）→ trade.status.status_code 看
- 9:00 之後若還是 PendingSubmit/Submitted → 取消（這是「漲停鎖死」情境，3.7% 機率）

```python
if trade.status.status_code in ['PendingSubmit', 'Submitted']:
    api.cancel_order(trade)   # 9:00:30 後取消
```

### 5. Trail Stop 實作邏輯

```python
# entry 後啟動 trail
entry_price = trade.deals[0].price
tick = get_tick(entry_price)
tp_price = entry_price + 10 * tick
stop_price = entry_price - 2 * tick

# 立即掛 TP 限價賣
sell_order = api.Order(price=tp_price, quantity=1,
                       action=Action.Sell, price_type=StockPriceType.LMT,
                       order_type=OrderType.ROD)
tp_trade = api.place_order(contract, sell_order)

# 同時開 callback 監聽 tick，動態調整 stop
def on_tick(topic, tick):
    nonlocal stop_price
    new_stop = tick.close - 2 * get_tick(tick.close)
    if new_stop > stop_price:
        # 修改 stop（取消舊單，重掛新 stop limit）
        stop_price = new_stop
        # ... cancel/replace 邏輯

api.quote.subscribe(contract, quote_type=sj.constant.QuoteType.Tick)
api.quote.set_on_tick_stk_v1_callback(on_tick)
```

### 6. 13:00 強制平倉

13:00 前若還沒觸發 TP 或 stop，市價賣出。

```python
if datetime.now().time() >= datetime.time(13, 0):
    market_sell = api.Order(price=0, quantity=remaining_qty,
                            action=Action.Sell, price_type=StockPriceType.MKT,
                            order_type=OrderType.IOC)
    api.place_order(contract, market_sell)
```

## TODO 上線前需驗證

- [ ] 測試「掛漲停 8:50 下單，9:00 是否真能 cross」 — 用紙上記錄 1-2 次
- [ ] 漲停買不到時 cancel order 的時機（9:00:30 還是 9:01:00？）
- [ ] Trail stop callback 在 1-min tick 頻率夠不夠快
- [ ] 部分成交時的 TP 量是否能對應（only sell 已成交量）
- [ ] 13:00 close 強制平倉的具體時間（13:00:00 還是 13:24:59？）

## 待 Shioaji docs 確認

我寫的 API 是基於 Shioaji 1.5.3 文件記憶 + python-shioaji 常見模式。**實際上線前需查最新 docs**：
- https://sinotrade.github.io/zh_TW/tutor/order/Stock/
- 特別是 `OrderType.ROD` vs `OrderType.IOC` 在集合競價的差別

可以先寫個 paper test script，在 8:30-9:00 真的下「**極低價** 限價買」（保證不成交），看 trade 物件結構，再改成漲停價真實上線。
