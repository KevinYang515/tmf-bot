"""
Gap Burst Strategy - 試撮跳空慣性 scalp（取代 nq_strategy，獨立執行，不動 V38）

策略（tick 級回測 2026-01~07 定版）：
  0845 session: 08:44:50 試撮價 vs 夜盤收(05:00) |gap| >= 0.5%
                → 預掛 MKP 順 gap 方向 1 口
                → TP +80 LMT / 停損 -30 (tick 監控) / 開盤後 300 秒強制平倉
                backtest: n=19, EV +281/口, WR 57.9%, PF 2.87, worst -356

  1500 session: 14:59:50 試撮價 vs 日盤收(13:45) |gap| >= 0.3%
                → 預掛 MKP 順 gap 方向 1 口
                → TP +100 LMT / 停損 -80 / 開盤後 180 秒強制平倉
                backtest: n=24, EV +251/口, WR 70.8%, PF 2.57, worst -856

  額外: 每日記錄試撮快照(:30/:40/:45/:50) + 實際開盤價 → gap_calibration.csv
        (校準試撮 noise, 未觸發日也記)

不依賴 yfinance / KOSPI / NQ — 只用 Shioaji 試撮 tick + kbars。
執行方式：supervisor（與 V38 並存）
狀態：gap_state.json / 日誌：logs/gap_strategy.log
"""
import os
import csv
import time
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")

def now_tp():
    return datetime.now(TAIPEI)

import requests
import pandas as pd
import shioaji as sj
from shioaji.constant import Action, OrderType, FuturesOCType, FuturesPriceType
from dotenv import load_dotenv

# ==========================================
# 0. 設定
# ==========================================
load_dotenv(Path(__file__).parent / ".env")

STRATEGY_NAME  = "GapBurst"
STATE_FILE     = Path(__file__).parent / "gap_state.json"
LOG_DIR        = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
CALIB_CSV      = LOG_DIR / "gap_calibration.csv"
TRADES_CSV     = LOG_DIR / "gap_trades.csv"

USE_SIMULATION = True    # ★ paper trade：模擬帳號
DRY_RUN        = False   # True = 完全不送單只 log

POSITION_QTY   = 1
POINT_VALUE    = 10      # TMF NT$10/pt

# session 參數（tick 級回測定版 2026-07-04，overnight research 更新見 GAP_STRATEGY.md）
SESSIONS = {
    "0845": {
        "prep_time":    "08:42",      # 主迴圈觸發（分鐘級）
        "snap_times":   ["08:44:30", "08:44:40", "08:44:45", "08:44:50"],
        "decide_time":  "08:44:50",
        "open_time":    "08:45:00",
        "ref_bar_hm":   (5, 0),       # 夜盤收 = 今日 05:00 bar close
        "threshold":    0.5,          # |gap %|
        "tp":           80,           # 固定 TP：動態 TP 掃描過(D1~D5)全部更差，gap 越大 MFE 反而略降
        "tp_dynamic":   None,
        "stop":         30,
        "cap_seconds":  300,
    },
    "1500": {
        "prep_time":    "14:57",
        "snap_times":   ["14:59:30", "14:59:40", "14:59:45", "14:59:50"],
        "decide_time":  "14:59:50",
        "open_time":    "15:00:00",
        "ref_bar_hm":   (13, 45),     # 日盤收 = 今日 13:45 bar close
        "threshold":    0.3,
        "tp":           100,          # tp_dynamic 有值時當地板(lo)
        # 動態 TP = clip(alpha * |gap_pts|, lo, hi)；gap_pts 用 |fill_price - ref_close|
        # H1/H2 walk-forward 驗證: 固定TP100 H2 EV+239 -> 動態 H2 EV+299 (n=12 each)，全樣本+251->+281
        "tp_dynamic":   {"alpha": 0.4, "lo": 100, "hi": 300},
        "stop":         80,           # 停損維持固定：動態停損掃描(D3)全部更差 worst 大幅惡化
        "cap_seconds":  180,
    },
}

LINE_NOTIFY_TOKEN = os.environ.get("LINE_NOTIFY_TOKEN", "")
SJ_API_KEY        = os.environ.get("SJ_API_KEY")
SJ_SECRET_KEY     = os.environ.get("SJ_SECRET_KEY")

# ==========================================
# 1. Logger
# ==========================================
logger = logging.getLogger("Gap_Strategy")
logger.setLevel(logging.INFO)
fh = TimedRotatingFileHandler(
    LOG_DIR / "gap_strategy.log",
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
            data={"message": "[Gap策略] " + msg},
            timeout=5,
        )
    except Exception as e:
        logger.error(f"[Line] {e}")


# ==========================================
# 2. State / CSV
# ==========================================
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"today_signals_done": {}}

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")

state = load_state()

CALIB_HEADERS = ["date", "session", "ref_close",
                 "trial_1", "trial_2", "trial_3", "trial_4",
                 "actual_open", "gap_at_decide_pct", "gap_actual_pct",
                 "triggered", "direction"]
TRADE_HEADERS = ["date", "session", "direction", "ref_close", "trial_price",
                 "gap_pct", "fill_price", "tp_used", "exit_reason", "exit_price_est",
                 "pnl_pt_est", "pnl_twd_est"]

def append_csv(path, headers, row):
    new = not path.exists()
    try:
        with open(path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            if new: w.writeheader()
            w.writerow(row)
    except Exception as e:
        logger.error(f"[CSV {path.name}] {e}")


# ==========================================
# 3. Shioaji
# ==========================================
api = sj.Shioaji(simulation=USE_SIMULATION)


def login_shioaji():
    mode_str = "SIMULATION（模擬）" if USE_SIMULATION else "LIVE（實盤）"
    if DRY_RUN: mode_str += " + DRY-RUN"
    logger.info(f"=== 登入 Shioaji [{mode_str}] ===")
    api.login(SJ_API_KEY, SJ_SECRET_KEY, fetch_contract=True)
    logger.info("登入完成")
    line_notify(f"Gap 策略啟動 [{mode_str}]")


def get_tmf_contract():
    contracts = [c for c in api.Contracts.Futures.TMF if len(c.code) <= 5]
    if not contracts:
        raise Exception("找不到 TMF 合約")
    return sorted(contracts, key=lambda x: x.delivery_month)[0]


def fetch_ref_close(contract, hm):
    """今日 kbars 指定 (hour, minute) bar 的 close — 夜盤收 05:00 / 日盤收 13:45"""
    today = now_tp().strftime("%Y-%m-%d")
    try:
        kb = api.kbars(contract, start=today, end=today)
        df = pd.DataFrame({**kb})
        if df.empty:
            return None
        df["ts"] = pd.to_datetime(df["ts"])
        m = df[(df["ts"].dt.hour == hm[0]) & (df["ts"].dt.minute == hm[1])]
        if m.empty:
            return None
        return float(m.iloc[-1]["Close"])
    except Exception as e:
        logger.error(f"[RefClose] {e}")
        return None


# ==========================================
# 4. Tick stream — 試撮捕捉 + 停損監控 共用一個 callback
# ==========================================
_tick_state = {
    "contract_code": None,
    "last_sim_price": None,     # 最新試撮價
    "last_real_price": None,    # 最新真實成交價
    "first_real_price": None,   # 開盤第一筆真實成交 (= 開盤價)
    # 停損監控
    "mon_active": False,
    "mon_direction": 0,
    "mon_stop_price": 0,
    "mon_exit_reason": None,
    "mon_event": threading.Event(),
}
_tick_lock = threading.Lock()


def _on_tick(exchange, tick):
    try:
        if tick.code != _tick_state["contract_code"]:
            return
        price = float(tick.close)
        if getattr(tick, "simtrade", 0):
            _tick_state["last_sim_price"] = price
            return
        # 真實成交
        if _tick_state["first_real_price"] is None:
            _tick_state["first_real_price"] = price
        _tick_state["last_real_price"] = price
        # 停損檢查
        if _tick_state["mon_active"]:
            d = _tick_state["mon_direction"]
            sp = _tick_state["mon_stop_price"]
            if (d == 1 and price <= sp) or (d == -1 and price >= sp):
                with _tick_lock:
                    if _tick_state["mon_active"]:
                        _tick_state["mon_active"] = False
                        _tick_state["mon_exit_reason"] = f"stop_hit@{price:.0f}"
                        logger.warning(f"[Tick Stop] cur={price:.0f} stop={sp:.0f}")
                        _tick_state["mon_event"].set()
    except Exception as e:
        logger.error(f"[on_tick] {e}")


def subscribe_ticks(contract):
    _tick_state.update({
        "contract_code": contract.code,
        "last_sim_price": None,
        "last_real_price": None,
        "first_real_price": None,
    })
    api.quote.set_on_tick_fop_v1_callback(_on_tick)
    api.quote.subscribe(contract, quote_type=sj.constant.QuoteType.Tick,
                        version=sj.constant.QuoteVersion.v1)
    logger.info(f"[Tick] 已訂閱 {contract.code}")


def unsubscribe_ticks(contract):
    try:
        api.quote.unsubscribe(contract, quote_type=sj.constant.QuoteType.Tick,
                              version=sj.constant.QuoteVersion.v1)
        logger.info(f"[Tick] 已取消訂閱 {contract.code}")
    except Exception as e:
        logger.error(f"[Tick unsub] {e}")


def get_trial_price(contract):
    """優先用 tick stream 的試撮價, fallback 用 snapshot"""
    p = _tick_state["last_sim_price"]
    if p is not None:
        return p
    try:
        snap = api.snapshots([contract])
        if snap and len(snap) > 0 and float(snap[0].close) > 0:
            return float(snap[0].close)
    except Exception as e:
        logger.error(f"[Snapshot] {e}")
    return None


# ==========================================
# 5. 下單
# ==========================================
def _safe_place_order(contract, order, label=""):
    if DRY_RUN:
        logger.info(f"[DRY-RUN] {label} {order.action} {order.quantity} 口 "
                    f"{order.price_type}@{order.price} (未送單)")
        class FakeTrade:
            class status:
                id = f"dry-{label}-{int(time.time()*1000)}"
                status = "Submitted"
                deals = []
        return FakeTrade()
    return api.place_order(contract, order)


def place_moo_entry(contract, direction, qty):
    """集合競價預掛 ROD/MKP"""
    action = Action.Buy if direction == 1 else Action.Sell
    order = api.Order(
        action=action, price=0, quantity=qty,
        order_type=OrderType.ROD, price_type=FuturesPriceType.MKP,
        octype=FuturesOCType.New, account=api.futopt_account,
    )
    trade = _safe_place_order(contract, order, label="Entry")
    logger.info(f"[Entry Pre-Auction] {action} {qty} 口 ROD/MKP  id={trade.status.id}")
    return trade


def place_tp_limit(contract, direction, qty, target_price):
    action = Action.Sell if direction == 1 else Action.Buy
    order = api.Order(
        action=action, price=round(target_price), quantity=qty,
        order_type=OrderType.ROD, price_type=FuturesPriceType.LMT,
        octype=FuturesOCType.Cover, account=api.futopt_account,
    )
    trade = _safe_place_order(contract, order, label=f"TP@{target_price:.0f}")
    logger.info(f"[TP] {action} {qty} 口 LMT@{target_price:.0f}  id={trade.status.id}")
    return trade


def _get_my_qty(contract, direction):
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


def market_close(contract, direction, label):
    qty = _get_my_qty(contract, direction)
    if qty == 0:
        logger.info(f"[{label}] 部位已歸零")
        return "already_closed"
    try:
        action = Action.Sell if direction == 1 else Action.Buy
        order = api.Order(
            action=action, price=0, quantity=qty,
            order_type=OrderType.IOC, price_type=FuturesPriceType.MKP,
            octype=FuturesOCType.Cover, account=api.futopt_account,
        )
        _safe_place_order(contract, order, label=label)
        logger.warning(f"[{label}] MKP {action} {qty} 口")
        return "closed_mkp"
    except Exception as e:
        logger.error(f"[{label}] {e}")
        return "error"


def cancel_pending_orders():
    try:
        api.update_status(api.futopt_account)
        for t in api.list_trades():
            if t.status.status not in ["Cancelled", "Filled"]:
                try:
                    api.cancel_order(t)
                    logger.info(f"[Cancel] order {t.status.id}")
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"[Cancel All] {e}")


# ==========================================
# 6. 監控（tick 停損 + TP 歸零 + 時間上限）
# ==========================================
def monitor_position(contract, direction, stop_price, cap_seconds, open_dt):
    """回傳 (exit_reason, exit_price_est)"""
    logger.info(f"[Monitor] stop={stop_price:.0f}  cap={cap_seconds}s")
    _tick_state.update({
        "mon_active": True,
        "mon_direction": direction,
        "mon_stop_price": stop_price,
        "mon_exit_reason": None,
    })
    _tick_state["mon_event"].clear()

    deadline = open_dt.timestamp() + cap_seconds
    reason, exit_px = None, None
    try:
        while True:
            if _tick_state["mon_event"].wait(timeout=3):
                reason = _tick_state["mon_exit_reason"]
                cancel_pending_orders()
                market_close(contract, direction, "Stop-MKP")
                exit_px = _tick_state["last_real_price"] or stop_price
                line_notify(f"停損出場 {reason}")
                break

            # 時間上限
            if time.time() >= deadline:
                with _tick_lock:
                    _tick_state["mon_active"] = False
                reason = "time_cap"
                logger.info(f"[Monitor] {cap_seconds}s 時間上限 → 強制平倉")
                cancel_pending_orders()
                r = market_close(contract, direction, "TimeCap")
                exit_px = _tick_state["last_real_price"]
                if r == "already_closed":
                    reason = "tp_filled_at_cap"
                line_notify(f"時間上限出場 ({r})")
                break

            # 部位歸零 (TP 全成)
            try:
                api.update_status(api.futopt_account)
                if _get_my_qty(contract, direction) == 0:
                    with _tick_lock:
                        _tick_state["mon_active"] = False
                    reason = "tp_filled"
                    exit_px = None  # TP 價由呼叫端補
                    logger.info("[Monitor] 部位歸零（TP 已成）")
                    break
            except Exception as e:
                logger.error(f"[Monitor poll] {e}")
    finally:
        with _tick_lock:
            _tick_state["mon_active"] = False
    return reason, exit_px


# ==========================================
# 7. 主邏輯 — 一個 session 的完整流程
# ==========================================
def wait_until(target_t):
    fmt = "%H:%M:%S" if target_t.count(":") == 2 else "%H:%M"
    while True:
        if now_tp().strftime(fmt) >= target_t:
            return
        time.sleep(0.1 if fmt == "%H:%M:%S" else 1)


def handle_session(session_key):
    cfg = SESSIONS[session_key]
    today_str = now_tp().strftime("%Y-%m-%d")
    done = state["today_signals_done"].setdefault(today_str, [])
    if session_key in done:
        return
    done.append(session_key)
    save_state(state)

    contract = get_tmf_contract()

    # 1. 參考收盤價
    ref_close = fetch_ref_close(contract, cfg["ref_bar_hm"])
    if ref_close is None:
        logger.warning(f"[{session_key}] 參考收盤價取不到 → SKIP (假日/資料缺)")
        return
    logger.info(f"[{session_key}] ref_close ({cfg['ref_bar_hm'][0]:02d}:{cfg['ref_bar_hm'][1]:02d}) = {ref_close:.0f}")

    # 2. 訂閱 tick, 收集試撮快照
    subscribe_ticks(contract)
    trials = []
    try:
        for st in cfg["snap_times"]:
            wait_until(st)
            p = get_trial_price(contract)
            trials.append(p)
            logger.info(f"[{session_key}] 試撮@{st} = {p if p else 'N/A'}")

        # 3. 決策
        # 優先用最後一筆(:50)試撮；若當下剛好收不到，退而用最近一筆有值的快照
        # (避免單一 tick 瞬斷就整場 SKIP，即使 :30/:40/:45 早有明確讀值)
        trial = trials[-1]
        if trial is None:
            for p in reversed(trials[:-1]):
                if p is not None:
                    trial = p
                    logger.warning(f"[{session_key}] 最後一筆試撮缺值，改用較早的快照 {trial:.0f}")
                    break
        gap_pct = None
        direction = 0
        if trial is not None and ref_close > 0:
            gap_pct = (trial - ref_close) / ref_close * 100
            if abs(gap_pct) >= cfg["threshold"]:
                direction = 1 if gap_pct > 0 else -1

        if gap_pct is None:
            logger.warning(f"[{session_key}] 試撮價取不到 → SKIP")
        else:
            logger.info(f"[{session_key}] gap = {gap_pct:+.3f}%  門檻 {cfg['threshold']}% → "
                        f"{'多' if direction == 1 else '空' if direction == -1 else 'SKIP'}")

        entry_trade = None
        if direction != 0:
            line_notify(f"{session_key} 觸發 gap={gap_pct:+.3f}% "
                        f"{'多' if direction == 1 else '空'} (試撮 {trial:.0f} vs 收 {ref_close:.0f})")
            entry_trade = place_moo_entry(contract, direction, POSITION_QTY)

        # 4. 等開盤, 捕捉實際開盤價 (校準用, 不論有沒有進場)
        wait_until(cfg["open_time"])
        open_dt = now_tp()
        actual_open = None
        for _ in range(50):  # 最多等 5 秒
            actual_open = _tick_state["first_real_price"]
            if actual_open is not None:
                break
            time.sleep(0.1)
        gap_actual = (actual_open - ref_close) / ref_close * 100 if actual_open else None
        logger.info(f"[{session_key}] 實際開盤 = {actual_open if actual_open else 'N/A'} "
                    f"(gap_actual = {f'{gap_actual:+.3f}%' if gap_actual is not None else 'N/A'})")

        # 校準記錄
        append_csv(CALIB_CSV, CALIB_HEADERS, {
            "date": today_str, "session": session_key, "ref_close": ref_close,
            "trial_1": trials[0], "trial_2": trials[1],
            "trial_3": trials[2], "trial_4": trials[3],
            "actual_open": actual_open,
            "gap_at_decide_pct": round(gap_pct, 4) if gap_pct is not None else None,
            "gap_actual_pct": round(gap_actual, 4) if gap_actual is not None else None,
            "triggered": int(direction != 0), "direction": direction,
        })

        if direction == 0 or entry_trade is None:
            return

        # 5. 取 fill 價
        time.sleep(2)
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
                            break
            except Exception as e:
                logger.warning(f"[Fill attempt {attempt+1}] {e}")
            if fill_price is not None:
                break
            time.sleep(1)

        if fill_price is None:
            fill_price = actual_open or _tick_state["last_real_price"]
            if fill_price is None:
                logger.error(f"[{session_key}] 取不到 fill/開盤價 → 強制平倉退出")
                cancel_pending_orders()
                market_close(contract, direction, "NoFill-Abort")
                return
            logger.warning(f"[{session_key}] 用開盤價估 fill = {fill_price:.0f}")

        logger.info(f"[{session_key}] Entry Fill = {fill_price:.0f}")

        # 6. TP + 停損監控 + 時間上限
        tp_pts = cfg["tp"]
        dyn = cfg.get("tp_dynamic")
        if dyn:
            gap_pts_now = abs(fill_price - ref_close)
            tp_pts = min(max(dyn["alpha"] * gap_pts_now, dyn["lo"]), dyn["hi"])
            logger.info(f"[{session_key}] 動態 TP: gap_pts={gap_pts_now:.0f} -> TP={tp_pts:.0f}")
        tp_p = fill_price + direction * tp_pts
        stop_p = fill_price - direction * cfg["stop"]
        place_tp_limit(contract, direction, POSITION_QTY, tp_p)

        reason, exit_px = monitor_position(contract, direction, stop_p,
                                           cfg["cap_seconds"], open_dt)
        if reason and reason.startswith("tp_filled") and exit_px is None:
            exit_px = tp_p
        logger.info(f"[{session_key}] 出場: {reason} @ {exit_px if exit_px else 'N/A'}")

        pnl_pt = None
        if exit_px is not None:
            pnl_pt = direction * (exit_px - fill_price)
        append_csv(TRADES_CSV, TRADE_HEADERS, {
            "date": today_str, "session": session_key, "direction": direction,
            "ref_close": ref_close, "trial_price": trial,
            "gap_pct": round(gap_pct, 4),
            "fill_price": fill_price, "tp_used": round(tp_pts, 1), "exit_reason": reason,
            "exit_price_est": exit_px,
            "pnl_pt_est": round(pnl_pt, 1) if pnl_pt is not None else None,
            "pnl_twd_est": round(pnl_pt * POINT_VALUE * POSITION_QTY, 0) if pnl_pt is not None else None,
        })
        line_notify(f"{session_key} 出場 {reason}\n"
                    f"est PnL: {f'{pnl_pt*POINT_VALUE:+,.0f}' if pnl_pt is not None else 'N/A'} NT$")
    finally:
        unsubscribe_ticks(contract)


# ==========================================
# 8. 主迴圈
# ==========================================
def reset_daily_state_if_new_day():
    today_str = now_tp().strftime("%Y-%m-%d")
    old = state.get("today_signals_done", {})
    state["today_signals_done"] = {today_str: old.get(today_str, [])}
    save_state(state)


def main():
    logger.info("=== Gap Burst Strategy 啟動 ===")
    logger.info(f"0845: 試撮 vs 夜盤收 |gap|>={SESSIONS['0845']['threshold']}% "
                f"TP+{SESSIONS['0845']['tp']} stop-{SESSIONS['0845']['stop']} cap {SESSIONS['0845']['cap_seconds']}s")
    logger.info(f"1500: 試撮 vs 日盤收 |gap|>={SESSIONS['1500']['threshold']}% "
                f"TP+{SESSIONS['1500']['tp']} stop-{SESSIONS['1500']['stop']} cap {SESSIONS['1500']['cap_seconds']}s")

    login_shioaji()

    last_minute = None
    while True:
        try:
            now_hm = now_tp().strftime("%H:%M")
            if now_hm == last_minute:
                time.sleep(5)
                continue
            last_minute = now_hm

            reset_daily_state_if_new_day()

            for session_key, cfg in SESSIONS.items():
                if now_hm == cfg["prep_time"]:
                    logger.info(f"[Trigger] {now_hm} → handle_session({session_key})")
                    handle_session(session_key)

            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("收到中斷訊號，退出")
            break
        except Exception as e:
            logger.exception(f"主迴圈例外: {e}")
            line_notify(f"⚠️ 主迴圈例外: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
