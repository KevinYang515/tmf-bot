"""
NQ Strength Strategy - 獨立執行，不動 V38

策略：
  1500 session: |NQ 13:00→15:00 %| > 0.3% → 15:00:00 進場 2 口
                TP1 +100 ticks, TP2 +200 ticks, Stop -50 ticks
  0845 session: |NQ 05:00→08:00 %| > 0.5% → 08:45:00 進場 2 口
                TP1 +100, TP2 +200, Stop -150

Session 結束強制平倉：1500 → 23:00 / 0845 → 13:25

執行方式：透過 supervisor 在背景跑（與 V38 並存）
資料持久化：nq_state.json
日誌：logs/nq_strategy.log
"""
import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
from zoneinfo import ZoneInfo

# ★★ 強制 Taipei 時區 — 因為 VM 是 UTC ★★
TAIPEI = ZoneInfo("Asia/Taipei")

def now_tp():
    """回 Taipei 時間的 datetime"""
    return datetime.now(TAIPEI)

import requests
import pandas as pd
import shioaji as sj
from shioaji.constant import (
    Action, OrderType, FuturesOCType, FuturesPriceType, StockPriceType
)
from dotenv import load_dotenv

# ==========================================
# 0. 設定
# ==========================================
load_dotenv(Path(__file__).parent / ".env")

STRATEGY_NAME    = "NQ_strength"
STATE_FILE       = Path(__file__).parent / "nq_state.json"
LOG_DIR          = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ★★ 安全模式 — 跑 paper 用 ★★
# True  = Shioaji 模擬模式（不會真的下單，安全測試用）
# False = 實盤（會真的賠錢，確認 paper 跑 OK 後才改）
USE_SIMULATION   = True

# ★★ Dry-run 模式 — 只 log 不送任何單，最保險 ★★
# True  = 完全不碰 Shioaji 下單 API，只 print 預計動作
# False = 會送單到 Shioaji（依 USE_SIMULATION 決定真假）
DRY_RUN          = False

# 訊號參數（v2: 配置 B — 上升 edge + 5/5 期正 EV）
# 1500 改 0.05% — slope +60/期, 2026H1 EV +615
# 0845 維持 0.5% — 樣本少但 edge 集中在強訊號
THRESHOLD_1500   = 0.05  # |NQ%| > 0.05%
THRESHOLD_0845   = 0.5

# v4 (2026-06-26): 0845 用 KOSPI 當 V0 filter (非獨立訊號)
# Backtest 2024-01~2026-06 (V0_kc_strict):
#   n=24, total +28,002, EV +1,167, WR 70.8%, Sharpe +7.43, PF 2.52, maxDD -3,724
#   vs baseline V0 n=38 Sharpe +3.33 PF 1.57
#   by half-year 5/5 期正 EV
# 規則: NQ |%|>0.5% AND KOSPI 同向 AND |KOSPI gap|>0.3% (intraday 08:00 TW open vs 前日 close)
ENABLE_V4_FILTER     = True   # ★ V4 上線 ★
THRESHOLD_KOSPI_0845 = 0.3    # KOSPI gap 同向確認門檻 (>0.3%)

# session-specific TP / Stop
TP1_TICKS_1500   = 150   # 從 100 → 150
TP2_TICKS_1500   = 300   # 從 200 → 300
STOP_TICKS_1500  = 75    # 從 50 → 75（寬一點，2026 行情震盪適用）

TP1_TICKS_0845   = 100
TP2_TICKS_0845   = 200
STOP_TICKS_0845  = 150

POSITION_QTY     = 2     # 進場口數（會分配 1 + 1 給 TP1 / TP2）
POINT_VALUE      = 10    # TMF 每點 NT$10
MAX_LOSS_DAILY   = -10000   # 日內最大虧損（單筆超過自動停止當天）

# 排程時間（Taipei）
SIGNAL_CHECK_TIMES = {
    # (signal_calc 計算訊號, entry_submit 提早預掛, opening_time 真實開盤, force_close)
    # 訊號計算放在預掛前 1 分鐘（最新 NQ 資料）
    "0845": ("08:44", "08:44:30", "08:45:00", "13:44"),  # 從 13:25 → 13:44 (backtest +9% EV)
    "1500": ("14:59", "14:59:30", "15:00:00", "23:00"),
}

LINE_NOTIFY_TOKEN = os.environ.get("LINE_NOTIFY_TOKEN", "")
SJ_API_KEY        = os.environ.get("SJ_API_KEY")
SJ_SECRET_KEY     = os.environ.get("SJ_SECRET_KEY")
SJ_CA_PATH        = os.environ.get("SJ_CA_PATH", "Sinopac-1.pfx")
SJ_CA_PASS        = os.environ.get("SJ_CA_PASS")
SJ_PERSON_ID      = os.environ.get("SJ_PERSON_ID")

# ==========================================
# 1. Logger
# ==========================================
logger = logging.getLogger("NQ_Strategy")
logger.setLevel(logging.INFO)
fh = TimedRotatingFileHandler(
    LOG_DIR / "nq_strategy.log",
    when="midnight", interval=1, backupCount=30, encoding="utf-8"
)
fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
if not logger.handlers:
    logger.addHandler(fh)
    logger.addHandler(ch)


def line_notify(msg):
    if not LINE_NOTIFY_TOKEN: return
    try:
        requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": "Bearer " + LINE_NOTIFY_TOKEN},
            data={"message": "[NQ策略] " + msg},
            timeout=5,
        )
    except Exception as e:
        logger.error(f"[Line] {e}")


# ==========================================
# 2. State (重啟可續)
# ==========================================
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {
        "current_position": 0,
        "current_direction": 0,
        "entry_price": None,
        "entry_session": None,    # "0845" or "1500"
        "entry_date": None,
        "tp1_trade_id": None,
        "tp2_trade_id": None,
        "stop_trade_id": None,
        "today_signals_done": {},  # {date: ["0845", "1500"]}
        "daily_pnl": {},   # {date: pnl}
    }

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")

state = load_state()

# ==========================================
# 3. Shioaji 登入
# ==========================================
api = sj.Shioaji(simulation=USE_SIMULATION)
api_lock = None  # 跟 V38 完全獨立 session，不需要鎖


def login_shioaji():
    """登入 Shioaji，若失敗直接 raise（不影響其他程序）"""
    mode_str = "SIMULATION（模擬）" if USE_SIMULATION else "LIVE（實盤）"
    if DRY_RUN:
        mode_str += " + DRY-RUN（不送單）"
    logger.info(f"=== 登入 Shioaji [{mode_str}] ===")

    try:
        api.login(SJ_API_KEY, SJ_SECRET_KEY, fetch_contract=True)
    except Exception as e:
        logger.critical(f"登入失敗：{e}")
        raise

    # 啟用憑證（實盤才需要）
    if not USE_SIMULATION:
        ca_full = Path(__file__).parent / SJ_CA_PATH
        if ca_full.exists() and SJ_CA_PASS and SJ_PERSON_ID:
            try:
                api.activate_ca(
                    ca_path=str(ca_full),
                    ca_passwd=SJ_CA_PASS,
                    person_id=SJ_PERSON_ID,
                )
                logger.info("憑證啟用成功")
            except Exception as e:
                logger.error(f"憑證啟用失敗：{e}")
        else:
            logger.warning("沒找到憑證設定，實盤下單會失敗")

    logger.info("登入完成")
    line_notify(f"策略服務啟動 [{mode_str}]")


def get_tmf_contract():
    """取近月 TMF 合約"""
    contracts = [c for c in api.Contracts.Futures.TMF if len(c.code) <= 5]
    if not contracts:
        raise Exception("找不到 TMF 合約")
    return sorted(contracts, key=lambda x: x.delivery_month)[0]


# ==========================================
# 4. NQ 訊號計算
# ==========================================
def fetch_nq_change(session):
    """
    抓 yfinance NQ 1h 計算指定 session 前的 % 變化
    1500: NQ 13:00→15:00 (Taipei)
    0845: NQ 05:00→08:00 (Taipei)
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker("NQ=F")
        df = ticker.history(period="3d", interval="1h", auto_adjust=False)
        if df.empty:
            logger.warning("yfinance NQ 抓取為空")
            return None, None

        # 轉 Taipei 時區
        df.index = df.index.tz_convert("Asia/Taipei")
        today = now_tp().date()
        today_str = today.strftime("%Y-%m-%d")

        if session == "1500":
            hour_from, hour_to = 13, 15
        else:  # 0845
            hour_from, hour_to = 5, 8

        # 找今天該時段附近的 close
        sub = df[df.index.date == today]
        if sub.empty:
            logger.warning(f"今天 ({today_str}) NQ 資料缺")
            return None, None

        before = sub[sub.index.hour <= hour_from]
        after  = sub[sub.index.hour <= hour_to]
        if before.empty or after.empty:
            logger.warning(f"NQ {hour_from}:00 / {hour_to}:00 資料缺")
            return None, None

        c_from = float(before.iloc[-1]["Close"])
        c_to   = float(after.iloc[-1]["Close"])
        pct = (c_to - c_from) / c_from * 100
        logger.info(f"[NQ Signal {session}] {hour_from}:00={c_from:.2f} -> {hour_to}:00={c_to:.2f}  ({pct:+.2f}%)")
        return pct, c_to
    except Exception as e:
        logger.error(f"[NQ Fetch] {e}")
        return None, None


def fetch_kospi_open_gap():
    """
    v4: 用 5m intraday bar 抓 KOSPI 今日 08:00 TW 開盤 vs 前日最後 close
    (KOSPI 開盤 = 09:00 KR = 08:00 TW, 在 TX 08:44 cutoff 前 44min)

    回傳 (gap_pct, today_open) 或 (None, None)
    """
    try:
        import yfinance as yf
        import math
        df = yf.Ticker("^KS11").history(period="5d", interval="5m", auto_adjust=False)
        if df.empty:
            logger.warning("yfinance KOSPI 5m 抓取為空")
            return None, None
        df.index = df.index.tz_convert(TAIPEI)
        df = df[df["Close"].notna() & (df["Close"] > 0)]
        if df.empty:
            logger.warning("yfinance KOSPI 過濾 NaN 後為空")
            return None, None

        today = now_tp().date()
        today_bars = df[df.index.date == today]
        if today_bars.empty:
            logger.warning(f"KOSPI 今日({today}) 還沒有 5m bar — 可能未到 08:00 TW or 假日")
            return None, None
        today_open = float(today_bars.iloc[0]["Open"])

        prev_bars = df[df.index.date < today]
        if prev_bars.empty:
            logger.warning("KOSPI 前日 bar 缺")
            return None, None
        prev_close = float(prev_bars.iloc[-1]["Close"])

        if not math.isfinite(today_open) or not math.isfinite(prev_close) or prev_close <= 0:
            logger.warning(f"KOSPI 價格不合理: today_open={today_open} prev_close={prev_close}")
            return None, None

        gap_pct = (today_open - prev_close) / prev_close * 100
        logger.info(f"[KOSPI 5m] prev_close@{prev_bars.index[-1].strftime('%m-%d %H:%M')}={prev_close:.2f} "
                    f"-> today_open@{today_bars.index[0].strftime('%H:%M')}={today_open:.2f}  ({gap_pct:+.3f}%)")
        return gap_pct, today_open
    except Exception as e:
        logger.error(f"[KOSPI Fetch] {e}")
        return None, None


# ==========================================
# 5. 下單
# ==========================================
def _safe_place_order(contract, order, label=""):
    """所有下單最終都經過這裡 — DRY_RUN 時只 log 不送單"""
    if DRY_RUN:
        logger.info(f"[DRY-RUN] {label} {order.action} {order.quantity} 口 "
                    f"{order.price_type}@{order.price} (未送單)")
        # 回傳假 trade 物件
        class FakeTrade:
            class status:
                id = f"dry-{label}-{int(time.time()*1000)}"
                status = "Submitted"
                deals = []
        return FakeTrade()
    return api.place_order(contract, order)


def place_moo_entry(contract, direction, qty):
    """
    集合競價預掛進場 — 用 ROD + MKP
    在 14:59:30 / 08:44:30 預掛，排隊到 15:00:00 / 08:45:00 集合競價
    保證吃到統一成交價
    """
    action = Action.Buy if direction == 1 else Action.Sell
    order = api.Order(
        action=action,
        price=0,
        quantity=qty,
        order_type=OrderType.ROD,    # 改 IOC → ROD（讓單留在簿子裡）
        price_type=FuturesPriceType.MKP,
        octype=FuturesOCType.New,
        account=api.futopt_account,
    )
    trade = _safe_place_order(contract, order, label="Entry")
    logger.info(f"[Entry Pre-Auction] {action} {qty} 口 ROD/MKP  id={trade.status.id}")
    return trade


def place_tp_limit(contract, direction, qty, target_price):
    """限價 TP（出場方向反向）"""
    action = Action.Sell if direction == 1 else Action.Buy
    order = api.Order(
        action=action,
        price=round(target_price),
        quantity=qty,
        order_type=OrderType.ROD,
        price_type=FuturesPriceType.LMT,
        octype=FuturesOCType.Cover,
        account=api.futopt_account,
    )
    trade = _safe_place_order(contract, order, label=f"TP@{target_price:.0f}")
    logger.info(f"[TP] {action} {qty} 口 LMT@{target_price:.0f}  id={trade.status.id}")
    return trade


def _get_my_qty(contract, direction):
    """取我目前該方向的剩餘部位口數"""
    try:
        positions = api.list_positions(api.futopt_account)
        my_qty = 0
        for p in positions:
            if p.code != contract.code: continue
            if (direction == 1 and p.direction == "Buy") or \
               (direction == -1 and p.direction == "Sell"):
                my_qty += abs(p.quantity)
        return my_qty
    except Exception as e:
        logger.error(f"[Get Qty] {e}")
        return 0


def _place_close(contract, direction, qty, price_type, price=0):
    """送平倉單（內部用）"""
    action = Action.Sell if direction == 1 else Action.Buy
    order = api.Order(
        action=action,
        price=round(price),
        quantity=qty,
        order_type=OrderType.ROD,
        price_type=price_type,
        octype=FuturesOCType.Cover,
        account=api.futopt_account,
    )
    return _safe_place_order(contract, order, label=f"Close-{price_type}")


def execute_stop_close(contract, direction, stop_price):
    """
    Stop 平倉 — 直接 MKP（簡單、快速、低期望滑點）
    理由：stop 觸發本身就代表市場在動，LMT 階梯反而會被快速行情遠拋
    """
    qty = _get_my_qty(contract, direction)
    if qty == 0:
        logger.info("[Stop Close] 部位已歸零")
        return "already_closed"

    try:
        action = Action.Sell if direction == 1 else Action.Buy
        order = api.Order(
            action=action,
            price=0,
            quantity=qty,
            order_type=OrderType.IOC,
            price_type=FuturesPriceType.MKP,    # 直接 MKP，5-10 ticks 保護
            octype=FuturesOCType.Cover,
            account=api.futopt_account,
        )
        trade = _safe_place_order(contract, order, label="Stop-MKP")
        logger.warning(f"[Stop MKP] {action} {qty} 口 id={trade.status.id}")
        return "stopped_mkp"
    except Exception as e:
        logger.error(f"[Stop Close] {e}")
        return "error"


def market_close_remaining_qty(contract, direction):
    """Session 末強制平倉 — 直接用 MKP"""
    qty = _get_my_qty(contract, direction)
    if qty == 0:
        return
    try:
        action = Action.Sell if direction == 1 else Action.Buy
        order = api.Order(
            action=action,
            price=0,
            quantity=qty,
            order_type=OrderType.IOC,
            price_type=FuturesPriceType.MKP,
            octype=FuturesOCType.Cover,
            account=api.futopt_account,
        )
        _safe_place_order(contract, order, label="SessionEnd")
        logger.info(f"[Session End] MKP 平倉 {action} {qty} 口")
    except Exception as e:
        logger.error(f"[Session End] {e}")


# ─ tick-based 監控 ────────────────────────────────────────────────────────────
import threading

_monitor_lock = threading.Lock()
_monitor_state = {
    "active": False,
    "direction": 0,
    "stop_price": 0,
    "contract_code": None,
    "exit_reason": None,
    "exit_event": threading.Event(),
}


def _on_tick(exchange, tick):
    """每筆 tick 進來檢查 stop（毫秒級觸發）"""
    if not _monitor_state["active"]:
        return
    if tick.code != _monitor_state["contract_code"]:
        return
    try:
        cur = float(tick.close)
        d = _monitor_state["direction"]
        sp = _monitor_state["stop_price"]
        if (d == 1 and cur <= sp) or (d == -1 and cur >= sp):
            with _monitor_lock:
                if _monitor_state["active"]:
                    _monitor_state["active"] = False
                    _monitor_state["exit_reason"] = f"stop_hit@{cur:.0f}"
                    logger.warning(f"[Tick Stop] cur={cur:.0f}  stop={sp:.0f}")
                    _monitor_state["exit_event"].set()
    except Exception as e:
        logger.error(f"[on_tick] {e}")


def monitor_position(contract, direction, stop_price, session_end_time):
    """
    Tick-based 監控 — 毫秒級觸發
    - tick 推播觸發 stop → 取消 TP + 市價平倉
    - 每 10 秒輪詢 1 次（檢查部位歸零 + session 末）
    """
    logger.info(f"[Monitor] 啟動 tick 推播  stop={stop_price:.0f}  end={session_end_time}")

    # 設定 monitor 狀態
    _monitor_state.update({
        "active": True,
        "direction": direction,
        "stop_price": stop_price,
        "contract_code": contract.code,
        "exit_reason": None,
    })
    _monitor_state["exit_event"].clear()

    # 訂閱 tick + 註冊 callback
    try:
        api.quote.set_on_tick_fop_v1_callback(_on_tick)
        api.quote.subscribe(
            contract,
            quote_type=sj.constant.QuoteType.Tick,
            version=sj.constant.QuoteVersion.v1,
        )
        logger.info(f"[Monitor] 已訂閱 {contract.code} tick")
    except Exception as e:
        logger.error(f"[Monitor] 訂閱失敗: {e}")

    reason = None
    try:
        while True:
            # 1. tick 已觸發 stop？
            if _monitor_state["exit_event"].wait(timeout=10):
                reason = _monitor_state["exit_reason"]
                line_notify(f"停損觸發 {reason}")
                cancel_pending_orders()
                # 階梯式 stop 平倉（LMT → LMT+buffer → MKP）
                tier_reason = execute_stop_close(contract, direction, stop_price)
                logger.info(f"[Stop Close] {tier_reason}")
                line_notify(f"出場：{tier_reason}")
                break

            # 2. session 末時間到？
            if now_tp().strftime("%H:%M") >= session_end_time:
                reason = "session_end"
                logger.info("[Monitor] session 末到，平倉")
                cancel_pending_orders()
                market_close_remaining_qty(contract, direction)
                break

            # 3. 部位歸零？（TP 全成）
            try:
                api.update_status(api.futopt_account)
                positions = api.list_positions(api.futopt_account)
                my_qty = 0
                for p in positions:
                    if p.code != contract.code: continue
                    if (direction == 1 and p.direction == "Buy") or \
                       (direction == -1 and p.direction == "Sell"):
                        my_qty += abs(p.quantity)
                if my_qty == 0:
                    reason = "tp_filled"
                    logger.info("[Monitor] 部位歸零（TP 已全成）")
                    break
            except Exception as e:
                logger.error(f"[Monitor poll] {e}")
    finally:
        with _monitor_lock:
            _monitor_state["active"] = False
        try:
            api.quote.unsubscribe(
                contract,
                quote_type=sj.constant.QuoteType.Tick,
                version=sj.constant.QuoteVersion.v1,
            )
            logger.info(f"[Monitor] 已取消訂閱 {contract.code}")
        except Exception as e:
            logger.error(f"[Monitor unsubscribe] {e}")

    return reason


def close_remaining(contract):
    """強制平倉剩餘倉位（session 結束）"""
    try:
        positions = api.list_positions(api.futopt_account)
        for p in positions:
            if p.code != contract.code:
                continue
            if p.quantity == 0:
                continue
            action = Action.Sell if p.direction == "Buy" else Action.Buy
            order = api.Order(
                action=action,
                price=0,
                quantity=abs(p.quantity),
                order_type=OrderType.IOC,
                price_type=FuturesPriceType.MKP,
                octype=FuturesOCType.Cover,
                account=api.futopt_account,
            )
            api.place_order(contract, order)
            logger.info(f"[Force Close] {action} {abs(p.quantity)} 口")
    except Exception as e:
        logger.error(f"[Close Remaining] {e}")


def cancel_pending_orders():
    """取消所有掛單"""
    try:
        api.update_status(api.futopt_account)
        trades = api.list_trades()
        for t in trades:
            if t.status.status not in ["Cancelled", "Filled"]:
                try:
                    api.cancel_order(t)
                    logger.info(f"[Cancel] order {t.status.id}")
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"[Cancel All] {e}")


# ==========================================
# 6. 主邏輯
# ==========================================
def handle_signal(session_key):
    """到了 signal 計算時間，抓 NQ (+ 0845 抓 KOSPI) 看是否進場"""
    today_str = now_tp().strftime("%Y-%m-%d")
    done = state["today_signals_done"].setdefault(today_str, [])
    if session_key in done:
        return  # 今天這個 session 已處理過

    threshold = THRESHOLD_1500 if session_key == "1500" else THRESHOLD_0845
    pct, nq_price = fetch_nq_change(session_key)
    if pct is None:
        return

    # === NQ 第一道門檻 ===
    nq_sig = 0
    if abs(pct) >= threshold:
        nq_sig = 1 if pct > 0 else -1

    # === v4: 0845 加 KOSPI filter (V0_kc_strict) ===
    direction = nq_sig
    kospi_pct = None
    trigger_label = ""
    if session_key == "0845" and ENABLE_V4_FILTER:
        if nq_sig == 0:
            # NQ 不過門檻直接退 — 不浪費 yfinance call
            logger.info(f"[Signal {session_key}] NQ={pct:+.2f}% < {threshold}% → SKIP (NQ 門檻)")
            done.append(session_key)
            save_state(state)
            return

        kospi_pct, kospi_open = fetch_kospi_open_gap()
        if kospi_pct is None:
            logger.warning(f"[Signal {session_key}] NQ 過門檻但 KOSPI 取不到 → SKIP (V4 規定)")
            line_notify(f"{session_key} V4 訊號:NQ={pct:+.2f}% 過但 KOSPI 缺資料, SKIP")
            done.append(session_key)
            save_state(state)
            return

        if abs(kospi_pct) < THRESHOLD_KOSPI_0845:
            logger.info(f"[Signal {session_key}] NQ={pct:+.2f}% / KOSPI={kospi_pct:+.3f}% "
                        f"< {THRESHOLD_KOSPI_0845}% → SKIP (KOSPI 確認太弱)")
            done.append(session_key)
            save_state(state)
            return

        kospi_sig = 1 if kospi_pct > 0 else -1
        if kospi_sig != nq_sig:
            logger.info(f"[Signal {session_key}] NQ={pct:+.2f}% / KOSPI={kospi_pct:+.3f}% "
                        f"反向 → SKIP (V4 filter)")
            line_notify(f"{session_key} V4: NQ/KOSPI 反向, SKIP\n"
                        f"NQ={pct:+.2f}% KOSPI={kospi_pct:+.3f}%")
            done.append(session_key)
            save_state(state)
            return

        trigger_label = " (V4 NQ+KOSPI 同向 ✓)"
        logger.info(f"[Signal {session_key}] NQ={pct:+.2f}% + KOSPI={kospi_pct:+.3f}% "
                    f"同向 → {'多' if direction==1 else '空'}{trigger_label}")

    # 非 0845 或 V4 關閉: 純 NQ 邏輯
    if direction == 0:
        logger.info(f"[Signal {session_key}] |NQ%|={abs(pct):.2f}% < {threshold}% → SKIP")
        done.append(session_key)
        save_state(state)
        return

    if not trigger_label:
        logger.info(f"[Signal {session_key}] |NQ%|={abs(pct):.2f}% >= {threshold}% → "
                    f"{'多' if direction==1 else '空'}")

    line_notify(f"{session_key} 訊號觸發\nNQ%={pct:+.2f}%" +
                (f"\nKOSPI={kospi_pct:+.3f}%" if kospi_pct is not None else "") +
                f"\n方向: {'多' if direction==1 else '空'}{trigger_label}")

    # 等到 entry_submit 時間（提早 30 秒預掛）
    _, entry_submit_t, opening_t, _ = SIGNAL_CHECK_TIMES[session_key]
    wait_until(entry_submit_t)
    logger.info(f"[Pre-Auction] 開始預掛  {now_tp().strftime('%H:%M:%S')}")

    # 預掛 MOO ROD/MKP 進場單
    contract = get_tmf_contract()
    entry_trade = place_moo_entry(contract, direction, POSITION_QTY)

    # 等真實開盤集合競價成交
    wait_until(opening_t)
    logger.info(f"[Opening] 開盤瞬間  {now_tp().strftime('%H:%M:%S')}")
    time.sleep(2)  # 給集合競價結算時間
    # 重試取成交回報（最多 10 秒）
    fill_price = None
    for attempt in range(10):
        try:
            api.update_status(api.futopt_account)
            for t in api.list_trades():
                if t.status.id == entry_trade.status.id and t.status.deals:
                    qty_w = sum(d.quantity * d.price for d in t.status.deals)
                    qty_s = sum(d.quantity for d in t.status.deals)
                    if qty_s > 0:
                        fill_price = qty_w / qty_s
                        logger.info(f"[Fill] 第 {attempt+1} 次取到 {fill_price:.0f}")
                        break
        except Exception as e:
            logger.warning(f"[Fill attempt {attempt+1}] {e}")
        if fill_price is not None:
            break
        time.sleep(1)

    # 取不到成交回報 → 用 snapshot 當估算（保險網）
    if fill_price is None:
        try:
            snap = api.snapshots([contract])
            if snap and len(snap) > 0:
                fill_price = float(snap[0].close)
                logger.warning(f"[Entry] 取不到成交回報，用 snapshot 估算 fill_price={fill_price:.0f}")
                line_notify(f"{session_key} 進場警示：用 snapshot 估算（模擬模式常見）")
            else:
                logger.error("[Entry] 連 snapshot 都沒，放棄掛 TP/Stop")
                line_notify(f"{session_key} 進場 ❌ 取不到任何價格")
                done.append(session_key)
                save_state(state)
                return
        except Exception as e:
            logger.error(f"[Snapshot fallback] {e}")
            done.append(session_key)
            save_state(state)
            return

    logger.info(f"[Entry Fill] {fill_price:.0f}")
    line_notify(f"{session_key} 進場成功\n方向: {'多' if direction==1 else '空'}\n成交價: {fill_price:.0f}")

    # 掛 TP1 / TP2 限價單（真的預掛到交易所）
    if session_key == "1500":
        stop_ticks = STOP_TICKS_1500
        tp1_ticks  = TP1_TICKS_1500
        tp2_ticks  = TP2_TICKS_1500
    else:
        stop_ticks = STOP_TICKS_0845
        tp1_ticks  = TP1_TICKS_0845
        tp2_ticks  = TP2_TICKS_0845
    tp1_p = fill_price + direction * tp1_ticks
    tp2_p = fill_price + direction * tp2_ticks
    stop_p = fill_price - direction * stop_ticks

    tp1_t = place_tp_limit(contract, direction, 1, tp1_p)
    tp2_t = place_tp_limit(contract, direction, 1, tp2_p)

    state.update({
        "current_position": POSITION_QTY * direction,
        "current_direction": direction,
        "entry_price": fill_price,
        "entry_session": session_key,
        "entry_date": today_str,
        "tp1_trade_id": tp1_t.status.id,
        "tp2_trade_id": tp2_t.status.id,
        "stop_price": stop_p,
    })
    done.append(session_key)
    save_state(state)

    # 啟動 Python 監控（取代假的 stop order）
    _, _, _, end_t = SIGNAL_CHECK_TIMES[session_key]
    reason = monitor_position(contract, direction, stop_p, end_t)
    logger.info(f"[Monitor] 結束: {reason}")
    line_notify(f"{session_key} 出場：{reason}")

    # 清空狀態
    state.update({
        "current_position": 0,
        "current_direction": 0,
        "entry_price": None,
        "entry_session": None,
        "tp1_trade_id": None,
        "tp2_trade_id": None,
        "stop_price": None,
    })
    save_state(state)


def handle_session_end(session_key):
    """session 結束強制平倉"""
    if state.get("entry_session") != session_key:
        return
    if state.get("current_position", 0) == 0:
        return

    logger.info(f"[End {session_key}] 強制平倉剩餘")
    contract = get_tmf_contract()
    cancel_pending_orders()
    close_remaining(contract)
    line_notify(f"{session_key} session 結束平倉")

    state.update({
        "current_position": 0,
        "current_direction": 0,
        "entry_price": None,
        "entry_session": None,
        "tp1_trade_id": None,
        "tp2_trade_id": None,
        "stop_trade_id": None,
    })
    save_state(state)


# ==========================================
# 7. 時間工具
# ==========================================
def now_str():
    return now_tp().strftime("%H:%M")


def wait_until(target_t):
    """等到指定 HH:MM 或 HH:MM:SS"""
    fmt = "%H:%M:%S" if target_t.count(":") == 2 else "%H:%M"
    while True:
        cur = now_tp().strftime(fmt)
        if cur >= target_t:
            return
        time.sleep(0.2 if fmt == "%H:%M:%S" else 1)


def reset_daily_state_if_new_day():
    today_str = now_tp().strftime("%Y-%m-%d")
    # 清理舊日期記錄（只留今天）
    old_signals = state.get("today_signals_done", {})
    state["today_signals_done"] = {today_str: old_signals.get(today_str, [])}
    save_state(state)


# ==========================================
# 8. 主迴圈
# ==========================================
def main():
    logger.info(f"=== NQ Strategy 啟動 ===")
    v4_str = f"  V4 filter: 0845 KOSPI 同向 |%|>{THRESHOLD_KOSPI_0845}% ★" if ENABLE_V4_FILTER else ""
    logger.info(f"配置 v2(B)：1500 TP +{TP1_TICKS_1500}/+{TP2_TICKS_1500} stop=-{STOP_TICKS_1500}  | "
                f"0845 TP +{TP1_TICKS_0845}/+{TP2_TICKS_0845} stop=-{STOP_TICKS_0845}{v4_str}")
    logger.info(f"門檻：1500 |NQ%|>{THRESHOLD_1500}% / 0845 |NQ%|>{THRESHOLD_0845}%")

    login_shioaji()

    last_minute = None
    while True:
        try:
            now = now_tp()
            now_hm = now.strftime("%H:%M")
            if now_hm == last_minute:
                time.sleep(10)
                continue
            last_minute = now_hm

            reset_daily_state_if_new_day()

            # 檢查各 session 的時間點
            # 只觸發 signal_t（後面 entry_submit / opening 由 handle_signal 內部處理）
            for session_key, (signal_t, _, _, end_t) in SIGNAL_CHECK_TIMES.items():
                if now_hm == signal_t:
                    logger.info(f"[Trigger] {now_hm} → handle_signal({session_key})")
                    handle_signal(session_key)
                elif now_hm == end_t:
                    logger.info(f"[Trigger] {now_hm} → handle_session_end({session_key})")
                    handle_session_end(session_key)

            time.sleep(20)
        except KeyboardInterrupt:
            logger.info("收到中斷訊號，退出")
            break
        except Exception as e:
            logger.exception(f"主迴圈例外: {e}")
            line_notify(f"⚠️ 主迴圈例外: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
