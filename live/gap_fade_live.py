"""
守不住開盤 V8 — Shioaji 實盤腳本（模擬單版）
D:\stock\tmf-bot\live\gap_fade_live.py

VM 執行：
  screen -S gap_fade
  ~/stock/bin/python3 live/gap_fade_live.py
  Ctrl+A D  (detach)

模式（第 45 行）：
  SIMULATION = True  → 只記 log，不送委託（預設）
  SIMULATION = False → 真實下單（需 CA 憑證，確認無誤後才改）

時程：
  08:55 啟動
  09:01 取 snapshot → 篩 gap 0.5%-10% 候選
  09:02-09:35 每分鐘更新 MorningHigh
  09:36-09:38 判斷進場（score 排序取 top 5）
  09:39-11:29 每分鐘 trail stop
  11:30 強平 → 印出今日摘要 → 結束

資料來源：
  - 合約清單 + 昨收（reference）→ Shioaji 合約
  - 今日開盤                    → Shioaji snapshot（09:01）
  - 1 分 K（High/Low）          → Shioaji kbars
  ※ 不依賴 finlab，VM 上可直接跑
"""

import os, sys
os.environ["PYTHONUTF8"] = "1"

import shioaji as sj
from shioaji.constant import Action, StockPriceType, OrderType
import pandas as pd
from pathlib import Path
from datetime import datetime, date
import time
import logging
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ── 模式 ─────────────────────────────────────────────────────────
SIMULATION = True   # ← 確認訊號正確後才改 False

# ── 策略參數（與 backtest 完全一致）──────────────────────────────
GAP_MIN         = 0.005
GAP_MAX         = 0.10
STOCK_AOR_MAX   = 0.030
MH_TO_LIMIT_MIN = 0.010
ENTRY_BUFFER    = 0.0005
N_MAX           = 5
POSITION_DOLLAR = 1_000_000

# ── 時間（分鐘）─────────────────────────────────────────────────
MORNING_END = 9 * 60 + 35   # 09:35
ENTRY_END   = 9 * 60 + 37   # 09:37
EXIT_MIN    = 11 * 60 + 30  # 11:30


# ── 工具 ─────────────────────────────────────────────────────────
def tick_size(p: float) -> float:
    if p < 10:   return 0.01
    if p < 50:   return 0.05
    if p < 100:  return 0.10
    if p < 500:  return 0.50
    if p < 1000: return 1.00
    return 5.00

def setup_logger() -> logging.Logger:
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    lg  = logging.getLogger("GapFade")
    lg.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S")
    fh  = logging.FileHandler(log_dir / f"gap_fade_{date.today()}.log", encoding="utf-8")
    ch  = logging.StreamHandler(sys.stdout)
    fh.setFormatter(fmt); ch.setFormatter(fmt)
    lg.addHandler(fh); lg.addHandler(ch)
    return lg

log = setup_logger()


# ── Per-stock 狀態 ────────────────────────────────────────────────
class Stock:
    def __init__(self, code, day_open, prev_close):
        self.code        = code
        self.day_open    = day_open
        self.prev_close  = prev_close
        self.limit_price = round(prev_close * 1.10, 2)
        self.gap_pct     = (day_open - prev_close) / prev_close
        self.morning_high = day_open
        self.stock_aor   = 0.0
        # 進場後
        self.has_entry   = False
        self.entry_px    = 0.0
        self.entry_lots  = 0
        self.entry_ts    = None
        self.running_low = 0.0
        self.cur_stop    = 0.0
        self.last_bar_ts = None


# ── Bot ──────────────────────────────────────────────────────────
class GapFadeBot:
    def __init__(self, api: sj.Shioaji):
        self.api        = api
        self._contracts = {}   # code -> Shioaji contract
        self.candidates = {}   # code -> Stock
        self.positions  = {}   # code -> Stock
        self._trade_log = []   # 今日成交紀錄（供收盤摘要）

    # ① 載入合約（開盤前）：Shioaji 合約內含 reference = 昨收
    def load_universe(self):
        log.info("載入 Shioaji 合約清單...")
        result = {}
        for exchange in ["TSE", "OTC"]:
            try:
                ex_stocks = getattr(self.api.Contracts.Stocks, exchange, [])
                for c in ex_stocks:
                    code = getattr(c, "code", "")
                    ref  = getattr(c, "reference", 0)
                    if code and not code.startswith("0") and 30 <= ref <= 1000:
                        result[code] = c
            except Exception as e:
                log.warning(f"取 {exchange} 合約失敗: {e}")
        self._contracts = result
        log.info(f"universe: {len(result)} 支（昨收 30-1000，排除 ETF）")

    # ② 09:01：snapshot 取今日開盤，篩 gap candidates
    def find_candidates(self):
        contracts = list(self._contracts.values())
        log.info(f"取 snapshot {len(contracts)} 支...")
        day_opens = {}
        BATCH = 200
        for i in range(0, len(contracts), BATCH):
            try:
                for s in self.api.snapshots(contracts[i:i+BATCH]):
                    if getattr(s, "open", 0) > 0:
                        day_opens[s.code] = s.open
            except Exception as e:
                log.warning(f"snapshot batch {i}: {e}")
            time.sleep(0.3)

        cands = {}
        for code, ct in self._contracts.items():
            if code not in day_opens:
                continue
            op  = day_opens[code]
            pc  = ct.reference
            gap = (op - pc) / pc
            if GAP_MIN <= gap <= GAP_MAX:
                cands[code] = Stock(code, op, pc)

        self.candidates = cands
        log.info(f"gap candidates: {len(cands)} 支  "
                 f"({[f'{c}({s.gap_pct*100:.1f}%)' for c,s in list(cands.items())[:10]]}...)")

    # ③ 拉當日 1 分 K
    def _kbars(self, code: str) -> pd.DataFrame:
        today = date.today().isoformat()
        try:
            kb = self.api.kbars(self._contracts[code], start=today, end=today)
            if not kb or len(kb.ts) == 0:
                return pd.DataFrame()
            df = pd.DataFrame({
                "ts":   pd.to_datetime(kb.ts),
                "High": kb.High, "Low": kb.Low,
                "Open": kb.Open, "Close": kb.Close,
            }).sort_values("ts")
            df["min"] = df["ts"].dt.hour * 60 + df["ts"].dt.minute
            return df
        except Exception as e:
            log.warning(f"kbars {code}: {e}")
            return pd.DataFrame()

    # ④ 更新 MorningHigh（09:01-09:35）
    def update_morning_highs(self):
        for code, st in self.candidates.items():
            if st.has_entry:
                continue
            df = self._kbars(code)
            if df.empty:
                continue
            early = df[df["min"] < MORNING_END]
            if not early.empty:
                st.morning_high = early["High"].max()
                st.stock_aor    = st.morning_high / st.day_open - 1

    # ⑤ 檢查進場（09:36-09:38，check 09:35-09:37 bars）
    def check_entries(self):
        slots = N_MAX - len(self.positions)
        if slots <= 0:
            return
        triggered = []
        for code, st in self.candidates.items():
            if st.has_entry or st.morning_high <= 0:
                continue
            if st.stock_aor >= STOCK_AOR_MAX:
                continue
            if (st.limit_price - st.morning_high) / st.morning_high < MH_TO_LIMIT_MIN:
                continue
            trigger_px = st.morning_high * (1 - ENTRY_BUFFER)
            df = self._kbars(code)
            if df.empty:
                continue
            win = df[(df["min"] >= MORNING_END) & (df["min"] <= ENTRY_END)]
            if win.empty or win["Low"].min() > trigger_px:
                continue
            score = st.gap_pct / (st.stock_aor + 0.001)
            triggered.append((score, code, st, trigger_px))

        triggered.sort(reverse=True)
        for _, code, st, trigger_px in triggered[:slots]:
            self._enter(st, trigger_px)

    # ⑥ Trail stop（進場後每根 bar）
    def check_trail_stops(self):
        done = []
        for code, st in self.positions.items():
            df = self._kbars(code)
            if df.empty:
                continue
            cutoff = st.last_bar_ts if st.last_bar_ts else st.entry_ts
            new_bars = df[df["ts"] > cutoff]
            for _, bar in new_bars.iterrows():
                st.last_bar_ts = bar["ts"]
                if bar["Low"] < st.running_low:
                    st.running_low = bar["Low"]
                    tk = tick_size(st.running_low)
                    st.cur_stop = min(
                        st.running_low + tk,
                        st.limit_price - tick_size(st.limit_price)
                    )
                if bar["High"] >= st.cur_stop:
                    self._exit(st, st.cur_stop, market=False)
                    done.append(code)
                    break
        for code in done:
            del self.positions[code]

    # ⑦ 11:30 強平
    def force_close_all(self):
        log.info(f"[11:30] 強平 {len(self.positions)} 個部位")
        for st in self.positions.values():
            self._exit(st, price=0, market=True)
        self.positions.clear()

    # ── 每日摘要 ──────────────────────────────────────────────────
    def print_summary(self):
        log.info("=" * 50)
        log.info(f"今日摘要  {date.today()}  共 {len(self._trade_log)} 筆")
        total_pnl = 0
        for t in self._trade_log:
            pnl  = (t["entry"] - t["exit"]) * t["lots"] * 1000
            pct  = (t["entry"] - t["exit"]) / t["entry"] * 100
            total_pnl += pnl
            log.info(f"  {t['code']:6s}  進{t['entry']:.2f}→出{t['exit']:.2f}  "
                     f"{pct:+.2f}%  {pnl:+,.0f}元  ({t['reason']})")
        log.info(f"合計損益: {total_pnl:+,.0f} 元")
        log.info("=" * 50)

    # ── 下單 ──────────────────────────────────────────────────────
    def _enter(self, st: Stock, trigger_px: float):
        tk   = tick_size(trigger_px)
        px   = round(round(trigger_px / tk) * tk, 4)
        lots = int(POSITION_DOLLAR / (px * 1000))
        if lots < 1:
            return
        st.cur_stop    = min(st.morning_high + tick_size(st.morning_high),
                             st.limit_price  - tick_size(st.limit_price))
        st.entry_px    = px
        st.entry_lots  = lots
        st.running_low = px
        st.has_entry   = True
        st.entry_ts    = pd.Timestamp(datetime.now())

        log.info(f"[ENTRY] {st.code}  {lots}張 @{px:.2f}  "
                 f"stop={st.cur_stop:.2f}  gap={st.gap_pct*100:.1f}%  aor={st.stock_aor*100:.1f}%")
        if not SIMULATION:
            try:
                order = self.api.Order(
                    price=px, quantity=lots,
                    action=Action.Sell,
                    price_type=StockPriceType.LMT,
                    order_type=OrderType.ROD,
                    first_sell=True,
                    account=self.api.stock_account,
                )
                t = self.api.place_order(self._contracts[st.code], order)
                log.info(f"        委託 id={t.order.id}")
            except Exception as e:
                log.error(f"        委託失敗: {e}")
                return
        self.positions[st.code] = st

    def _exit(self, st: Stock, price: float, market: bool):
        exit_px = price if not market else 0
        reason  = "MARKET" if market else "TRAIL"
        display = "MARKET" if market else f"{price:.2f}"
        log.info(f"[EXIT]  {st.code}  {st.entry_lots}張 @{display}  ({reason})")
        self._trade_log.append({
            "code": st.code, "entry": st.entry_px,
            "exit": price if not market else st.cur_stop,
            "lots": st.entry_lots, "reason": reason,
        })
        if not SIMULATION:
            try:
                order = self.api.Order(
                    price=exit_px, quantity=st.entry_lots,
                    action=Action.Buy,
                    price_type=StockPriceType.MKT if market else StockPriceType.LMT,
                    order_type=OrderType.ROD,
                    account=self.api.stock_account,
                )
                t = self.api.place_order(self._contracts[st.code], order)
                log.info(f"        回補 id={t.order.id}")
            except Exception as e:
                log.error(f"        回補失敗: {e}")


# ── Main ─────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info(f"守不住開盤 V8  |  {'[模擬] 不送委託' if SIMULATION else '⚠️  真實下單'}")
    log.info("=" * 60)

    api = sj.Shioaji(simulation=SIMULATION)
    api.login(api_key=os.environ["SJ_API_KEY"], secret_key=os.environ["SJ_SECRET_KEY"])
    if not SIMULATION:
        api.activate_ca(
            ca_path=os.environ.get("SJ_CA_PATH", "Sinopac.pfx"),
            ca_passwd=os.environ["SJ_CA_PASS"],
            person_id=os.environ["SJ_PERSON_ID"],
        )
    log.info("Shioaji 登入成功")

    bot = GapFadeBot(api)
    bot.load_universe()
    log.info("等待 09:01...")

    last_min = -1
    while True:
        now     = datetime.now()
        h, m, s = now.hour, now.minute, now.second
        cur_min = h * 60 + m

        if s >= 5 and cur_min != last_min:
            last_min = cur_min

            if h == 9 and m == 1 and not bot.candidates:
                bot.find_candidates()

            elif h == 9 and 2 <= m <= 35:
                bot.update_morning_highs()

            elif h == 9 and 36 <= m <= 38:
                bot.check_entries()
                if bot.positions:
                    bot.check_trail_stops()

            elif 9 * 60 + 38 < cur_min < EXIT_MIN:
                if bot.positions:
                    bot.check_trail_stops()

            elif cur_min >= EXIT_MIN and h == 11:
                bot.force_close_all()
                bot.print_summary()
                break

        if h >= 12:
            bot.print_summary()
            break
        time.sleep(1)

    api.logout()
    log.info("程式結束")


if __name__ == "__main__":
    main()
