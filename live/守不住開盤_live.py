"""
守不住開盤 V8 Live Trading 框架 (永豐 Shioaji)

執行模式:
  DRY_RUN = True   ← 完全不下單，只 log signal (推薦先跑一週驗證邏輯)
  DRY_RUN = False + SIMULATION = True   ← Shioaji 模擬單帳號 (真實 quote + 假成交)
  DRY_RUN = False + SIMULATION = False  ← 真實下單 (謹慎!)

三層防禦 (見策略報告 §):
  Layer 1: 開倉同時掛觸價單 (停損)，永遠在訂單簿
  Layer 2: Trail stop (Python monitor 動態 cancel/replace)
  Layer 3: 11:30 強制平倉

執行架構:
  08:50  連線 Shioaji + 預篩候選股 (gap up 0.5%~10% 預估)
  09:00  訂閱候選股 tick + 1-min K
  09:00-09:35  累積 morning_high
  09:35-09:37  trigger detection + 開倉 + Layer 1 觸價單
  09:37+ 每秒檢查 trail stop, cancel/replace 觸價單
  11:30  強制平倉所有未平倉部位
"""
import os, sys, time, json, signal
from pathlib import Path
from datetime import datetime, time as dtime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
import logging

os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── 模式控制 ──────────────────────────────────────────────────
DRY_RUN     = True   # ⚠️ True = 不下單，只 log
SIMULATION  = True   # Shioaji 模擬單模式 (DRY_RUN=False 時才生效)

# ── 策略參數 (V8 production) ─────────────────────────────────
BUDGET          = 5_000_000   # 同時暴露上限
N_MAX           = 5
LOT_SHARES      = 1000

GAP_MIN         = 0.005       # gap up 0.5%~10%
GAP_MAX         = 0.10
VOL_MULT        = 1.0         # 不過濾日量 (live 來不及算)
STOCK_AOR_MAX   = 0.030       # V8: 漲不動 < 3.0%
MH_TO_LIMIT_MIN = 0.010       # V5: morning_high 距漲停 ≥ 1.0%
SIGNAL_WAIT_MIN = 35          # 09:35 開始監看
SIGNAL_END_MIN  = 37          # 09:37 截止
ENTRY_BUFFER    = 0.0005      # V7: 從 morning_high 回落 0.05%
STOP_TICKS      = 1           # 初始 stop = morning_high + 1 tick
EXIT_TIME_MIN   = 11 * 60 + 30   # 11:30 強平

# ── 路徑 / Log ────────────────────────────────────────────────
BASE_DIR = Path(r"D:\stock\tmf-bot\live")
BASE_DIR.mkdir(exist_ok=True)
LOG_DIR  = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
UNIVERSE_FILE = BASE_DIR / "universe.csv"   # 候選股名單 (ticker, prev_close)

today_str = datetime.now().strftime("%Y%m%d")
log_path = LOG_DIR / f"live_{today_str}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live")


# ── 台股 tick size ────────────────────────────────────────────
def tick_size(price: float) -> float:
    if price < 10:    return 0.01
    if price < 50:    return 0.05
    if price < 100:   return 0.1
    if price < 500:   return 0.5
    if price < 1000:  return 1.0
    return 5.0


# ── State per ticker ──────────────────────────────────────────
@dataclass
class TickerState:
    ticker: str
    prev_close: float
    day_open: Optional[float] = None
    morning_high: float = 0.0
    morning_high_time: Optional[datetime] = None
    last_price: Optional[float] = None
    last_bid: Optional[float] = None
    last_ask: Optional[float] = None
    # post-entry
    entry_filled: bool = False
    entry_price: Optional[float] = None
    entry_qty: int = 0
    entry_time: Optional[datetime] = None
    running_low: Optional[float] = None
    current_stop: Optional[float] = None
    stop_order_id: Optional[str] = None
    exit_filled: bool = False
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # "trail" / "time" / "manual"

    def gap_pct(self) -> float:
        if self.day_open is None:
            return 0
        return (self.day_open - self.prev_close) / self.prev_close

    def stock_aor(self) -> float:
        if self.day_open is None or self.morning_high == 0:
            return 0
        return self.morning_high / self.day_open - 1

    def limit_price(self) -> float:
        return self.prev_close * 1.10

    def mh_to_limit(self) -> float:
        if self.morning_high == 0:
            return 0
        return (self.limit_price() - self.morning_high) / self.morning_high

    def rank_score(self) -> float:
        return self.gap_pct() / (self.stock_aor() + 0.001)


# ── 候選股篩選 (盤前/開盤後) ──────────────────────────────────
def load_universe() -> Dict[str, TickerState]:
    """從 CSV 載入候選股名單 (盤前由另一支 script 產生)"""
    if not UNIVERSE_FILE.exists():
        log.error(f"找不到 universe file: {UNIVERSE_FILE}")
        return {}
    import csv
    states = {}
    with open(UNIVERSE_FILE, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = row["ticker"]
            states[t] = TickerState(ticker=t, prev_close=float(row["prev_close"]))
    log.info(f"載入候選股 {len(states)} 檔")
    return states


# ── Quote callbacks ───────────────────────────────────────────
states: Dict[str, TickerState] = {}
api = None  # Shioaji instance


def on_tick(topic, quote):
    """tick callback (Shioaji)"""
    try:
        ticker = quote["code"]
        price = float(quote["close"])  # 最新成交價
        if ticker not in states:
            return
        s = states[ticker]

        # 第一筆 = 開盤價
        if s.day_open is None:
            s.day_open = price
            log.info(f"  {ticker} 開盤 {price} gap={s.gap_pct()*100:+.2f}%")

        # 累積 morning_high (09:00-09:35)
        now = datetime.now().time()
        if dtime(9, 0) <= now < dtime(9, SIGNAL_WAIT_MIN):
            if price > s.morning_high:
                s.morning_high = price
                s.morning_high_time = datetime.now()

        s.last_price = price

        # 進場後: 更新 running_low + trail
        if s.entry_filled and not s.exit_filled:
            if s.running_low is None or price < s.running_low:
                s.running_low = price
                _maybe_update_trail(s)

    except Exception as e:
        log.error(f"on_tick error {topic}: {e}")


def _maybe_update_trail(s: TickerState):
    """重新計算 trail stop 並 cancel/replace 觸價單"""
    if s.running_low is None: return
    ts_h = tick_size(s.morning_high)
    new_stop = s.running_low + STOP_TICKS * ts_h
    new_stop = min(new_stop, s.limit_price() - tick_size(s.limit_price()))
    if s.current_stop is None or new_stop < s.current_stop:
        old = s.current_stop
        s.current_stop = new_stop
        log.info(f"  {s.ticker} trail update {old}->{new_stop:.2f} (low={s.running_low})")
        if not DRY_RUN:
            _replace_stop_order(s)


# ── 下單 (Shioaji) ────────────────────────────────────────────
def _place_short_entry(s: TickerState, trigger_price: float, qty: int):
    """開倉: short 觸價單 (限價賣出)"""
    if DRY_RUN:
        log.info(f"  [DRY] {s.ticker} SHORT @ {trigger_price} qty={qty}")
        # 模擬立即成交
        s.entry_filled = True
        s.entry_price = trigger_price
        s.entry_qty = qty
        s.entry_time = datetime.now()
        s.running_low = trigger_price
        ts_h = tick_size(s.morning_high)
        s.current_stop = min(s.morning_high + STOP_TICKS * ts_h,
                             s.limit_price() - tick_size(s.limit_price()))
        log.info(f"  [DRY] {s.ticker} 初始 stop = {s.current_stop:.2f}")
        return

    # 真實下單
    # TODO: 確認 Shioaji 借券 / 現股當沖空 API
    import shioaji as sj
    contract = api.Contracts.Stocks[s.ticker]
    order = api.Order(
        action=sj.constant.Action.Sell,
        price=trigger_price,
        quantity=qty,
        price_type=sj.constant.StockPriceType.LMT,
        order_type=sj.constant.OrderType.ROD,
        order_lot=sj.constant.StockOrderLot.Common,
        # 現股當沖: order_cond=ShortSelling? 需查文件
        first_sell=sj.constant.StockFirstSell.Yes,  # 沖銷標記
        account=api.stock_account,
    )
    trade = api.place_order(contract, order)
    log.info(f"  下單 {s.ticker} SHORT @ {trigger_price} qty={qty} status={trade.status.status}")
    return trade


def _place_stop_cover(s: TickerState):
    """同步掛 Layer 1 觸價單 (回補)"""
    if DRY_RUN: return
    import shioaji as sj
    contract = api.Contracts.Stocks[s.ticker]
    order = api.Order(
        action=sj.constant.Action.Buy,
        price=0,  # 市價
        quantity=s.entry_qty,
        price_type=sj.constant.StockPriceType.MKT,
        order_type=sj.constant.OrderType.ROD,
        trigger_price=s.current_stop,  # ⚠️ 需確認 Shioaji 觸價單 API
        account=api.stock_account,
    )
    trade = api.place_order(contract, order)
    s.stop_order_id = trade.order.id
    log.info(f"  {s.ticker} Layer 1 觸價單掛單 trigger={s.current_stop} id={s.stop_order_id}")


def _replace_stop_order(s: TickerState):
    """Cancel 舊 stop 並掛新的 (trail)"""
    if DRY_RUN: return
    if s.stop_order_id:
        # TODO: api.cancel_order(trade)
        log.info(f"  {s.ticker} cancel 舊 stop {s.stop_order_id}")
    _place_stop_cover(s)


def _force_close(s: TickerState, reason: str = "time"):
    """11:30 強制市價平倉"""
    if not s.entry_filled or s.exit_filled: return
    log.info(f"  {s.ticker} 強制平倉 ({reason})")
    if DRY_RUN:
        s.exit_filled = True
        s.exit_price = s.last_price or s.entry_price
        s.exit_reason = reason
        return
    # cancel 殘留觸價單
    if s.stop_order_id:
        # api.cancel_order(...)
        pass
    # 市價回補
    import shioaji as sj
    contract = api.Contracts.Stocks[s.ticker]
    order = api.Order(
        action=sj.constant.Action.Buy,
        price=0,
        quantity=s.entry_qty,
        price_type=sj.constant.StockPriceType.MKT,
        order_type=sj.constant.OrderType.IOC,
        account=api.stock_account,
    )
    api.place_order(contract, order)


# ── 主流程 ────────────────────────────────────────────────────
def trigger_detection_loop():
    """09:35-09:37: 持續檢查 trigger，達標就排序、開倉"""
    triggered: List[TickerState] = []
    end_time = dtime(9, SIGNAL_END_MIN)

    while datetime.now().time() < end_time:
        for s in states.values():
            if s.entry_filled or s.day_open is None: continue
            if s.morning_high == 0: continue
            if s.stock_aor() >= STOCK_AOR_MAX: continue
            if s.mh_to_limit() < MH_TO_LIMIT_MIN: continue
            trigger_price = s.morning_high * (1 - ENTRY_BUFFER)
            if s.last_price is not None and s.last_price <= trigger_price:
                if s not in triggered:
                    triggered.append(s)
                    log.info(f"  ✓ {s.ticker} TRIGGER @ {s.last_price} (target {trigger_price:.2f})")
        time.sleep(1)

    # 按 rank_score 排序, 取 top-N_MAX
    triggered.sort(key=lambda x: x.rank_score(), reverse=True)
    log.info(f"\n=== trigger 候選 {len(triggered)} 檔, 取 top-{N_MAX} ===")

    per_slot = BUDGET / N_MAX
    for s in triggered[:N_MAX]:
        trigger_price = s.morning_high * (1 - ENTRY_BUFFER)
        lots = int(per_slot // (trigger_price * LOT_SHARES))
        if lots == 0:
            log.warning(f"  {s.ticker} 買不起 1 張 (entry={trigger_price}), skip")
            continue
        qty = lots * LOT_SHARES
        log.info(f"  → 開倉 {s.ticker} qty={qty} ({lots}張)")
        _place_short_entry(s, trigger_price, qty)
        if s.entry_filled:
            _place_stop_cover(s)


def trail_monitor_loop():
    """09:37 - 11:30: 持續監聽 tick + 更新 trail"""
    end_time = dtime(11, 30)
    while datetime.now().time() < end_time:
        time.sleep(1)
        # tick callback 已處理 trail 更新


def force_close_all():
    """11:30 強平所有部位"""
    log.info("\n=== 11:30 強制平倉 ===")
    for s in states.values():
        if s.entry_filled and not s.exit_filled:
            _force_close(s, "time")


def save_daily_log():
    """存當日 trade log (給後續 fill vs backtest 比較)"""
    out = []
    for s in states.values():
        if not s.entry_filled: continue
        out.append({
            "ticker": s.ticker,
            "prev_close": s.prev_close,
            "day_open": s.day_open,
            "morning_high": s.morning_high,
            "stock_aor": s.stock_aor(),
            "gap_pct": s.gap_pct(),
            "mh_to_limit": s.mh_to_limit(),
            "entry_price": s.entry_price,
            "entry_time": s.entry_time.isoformat() if s.entry_time else None,
            "entry_qty": s.entry_qty,
            "exit_price": s.exit_price,
            "exit_reason": s.exit_reason,
            "running_low": s.running_low,
            "current_stop": s.current_stop,
            "return": ((s.entry_price - s.exit_price)/s.entry_price
                       if (s.entry_price and s.exit_price) else None),
        })
    out_path = LOG_DIR / f"trades_{today_str}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    log.info(f"\n=== 存 {len(out)} 筆 trade log → {out_path} ===")


# ── Shioaji 連線 ──────────────────────────────────────────────
def connect_shioaji():
    if DRY_RUN:
        log.info("DRY_RUN 模式，不連 Shioaji")
        return None
    import shioaji as sj
    global api
    api = sj.Shioaji(simulation=SIMULATION)
    # TODO: 從環境變數讀 credentials
    api.login(
        api_key=os.environ["SHIOAJI_API_KEY"],
        secret_key=os.environ["SHIOAJI_SECRET"],
    )
    log.info(f"Shioaji 連線成功 (simulation={SIMULATION})")
    api.set_default_account(api.stock_account)
    api.quote.set_quote_callback(on_tick)
    return api


def subscribe_universe():
    if DRY_RUN: return
    for ticker in states:
        contract = api.Contracts.Stocks[ticker]
        api.quote.subscribe(contract, quote_type="tick")
    log.info(f"訂閱 {len(states)} 檔 tick")


# ── Main ──────────────────────────────────────────────────────
def main():
    global states
    log.info("=" * 60)
    log.info(f"守不住開盤 V8 Live (DRY={DRY_RUN}, SIM={SIMULATION})")
    log.info("=" * 60)

    states = load_universe()
    if not states:
        log.error("候選股為空，結束")
        return

    connect_shioaji()
    subscribe_universe()

    # 等待 09:35
    log.info("等待 09:35...")
    while datetime.now().time() < dtime(9, SIGNAL_WAIT_MIN):
        time.sleep(1)

    log.info("\n=== 09:35 開始 trigger detection ===")
    trigger_detection_loop()

    log.info("\n=== 09:37 進入 trail monitor ===")
    trail_monitor_loop()

    force_close_all()
    time.sleep(5)  # 等市價單成交
    save_daily_log()

    if not DRY_RUN:
        api.logout()


if __name__ == "__main__":
    main()
