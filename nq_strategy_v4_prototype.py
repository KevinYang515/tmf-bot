"""
v4 prototype — KOSPI 當 V0 filter (非獨立訊號源)
=======================================================
這是 DRAFT，未部署。給 user 早上 review 用。

設計理念 (依 backtest gap_research_v2 + v0_with_kospi_filter):
- KOSPI 開盤 gap 對 TX gap 預測 corr +0.79, hit 92% (>0.5% 時)
- BUT KOSPI/NKX 獨立作為訊號 → PF<1.0 (gap 已被 TX 08:46 開盤吸收, 沒 follow-through edge)
- KOSPI 真正的用途是當 V0 (NQ-only) 的 filter, 過濾掉 NQ 訊號但亞洲反向的偽訊號

Backtest 2024-01 ~ 2026-06 (cutoff=13:44, exit=A TP+100/+200 stop=-150):
              n   total    EV  win%  Sharpe   PF  maxDD
  V0 baseline 38 +20,284 +534 57.9% +3.33   1.57 -7,832
  V0_kc_strict 24 +28,002 +1,167 70.8% +7.43 2.52 -3,724  ★

V0_kc_strict 規則:
  ① NQ 5:00→8:00 TW > 0.5% (跟現行 V0 一樣)
  ② KOSPI 08:00 TW 開盤 vs 前一天 KOSPI 最後收盤 > 0.3%, 方向跟 ① 一致
  ③ 滿足 ①②才進場

By year/H — 5/5 期正 EV (2024H1 ~ 2026H1)

可選: V0_lowth (NQ>0.3% AND KOSPI>0.3% 同向) — n=46, PF 1.80, 樣本更大但 Sharpe 較低
"""
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo
import math

TAIPEI = ZoneInfo("Asia/Taipei")


def now_tp():
    return datetime.now(TAIPEI)


def fetch_kospi_open_gap():
    """
    回傳 KOSPI 「今日 08:00 TW 開盤」vs 「前一天 KOSPI 最後收盤」的 % 變化
    用 5m bar (yfinance) — 在 TW 08:44 訊號時呼叫, KOSPI 已開盤 44 分鐘

    回傳: (gap_pct, today_open_price) 或 (None, None)
    """
    try:
        df = yf.Ticker("^KS11").history(period="5d", interval="5m", auto_adjust=False)
        if df.empty:
            return None, None
        df.index = df.index.tz_convert(TAIPEI)
        # 去 NaN
        df = df[df["Close"].notna() & (df["Close"] > 0)]
        if df.empty:
            return None, None

        today = now_tp().date()
        today_bars = df[df.index.date == today]
        if today_bars.empty:
            # 還沒到 08:00 TW or KOSPI 沒開盤
            return None, None
        # 取今天最早的 bar (應該是 08:00 TW)
        today_open_bar = today_bars.iloc[0]
        today_open = float(today_open_bar["Open"])

        # 找昨日最後一根 bar 的 close
        prev_bars = df[df.index.date < today]
        if prev_bars.empty:
            return None, None
        prev_close = float(prev_bars.iloc[-1]["Close"])

        if prev_close <= 0 or not math.isfinite(today_open):
            return None, None

        gap_pct = (today_open - prev_close) / prev_close * 100
        return gap_pct, today_open
    except Exception as e:
        print(f"[KOSPI fetch err] {e}")
        return None, None


def decide_v4_signal(nq_pct, kospi_gap_pct,
                     nq_threshold=0.5, kospi_threshold=0.3,
                     mode="strict"):
    """
    v4 訊號決策
    mode:
      "strict"  V0_kc_strict — NQ>nq_th + KOSPI 同向且 |kos|>kospi_th
      "loose"   V0_lowth — NQ>0.3% + KOSPI 同向且 |kos|>kospi_th
      "filter_only" V0 + KOSPI 反向時跳過 (其他放行)
      "off"     pure V0 (現行 v2(B))

    回傳: direction (1=多, -1=空, 0=不進)
    """
    if mode == "off":
        if nq_pct is None: return 0
        if abs(nq_pct) < nq_threshold: return 0
        return 1 if nq_pct > 0 else -1

    if mode == "filter_only":
        if nq_pct is None or abs(nq_pct) < nq_threshold: return 0
        s = 1 if nq_pct > 0 else -1
        if kospi_gap_pct is None: return s  # KOSPI 缺資料: trust V0
        if abs(kospi_gap_pct) < kospi_threshold: return s  # KOSPI 太弱不算 filter
        if (kospi_gap_pct > 0) == (s == 1): return s  # 同向
        return 0  # 反向 → 跳過

    if mode == "strict":
        if nq_pct is None or abs(nq_pct) < nq_threshold: return 0
        s = 1 if nq_pct > 0 else -1
        if kospi_gap_pct is None: return 0  # KOSPI 缺 = 不進
        if abs(kospi_gap_pct) < kospi_threshold: return 0
        if (kospi_gap_pct > 0) == (s == 1): return s
        return 0

    if mode == "loose":
        if nq_pct is None or abs(nq_pct) < 0.3: return 0
        s = 1 if nq_pct > 0 else -1
        if kospi_gap_pct is None: return 0
        if abs(kospi_gap_pct) < kospi_threshold: return 0
        if (kospi_gap_pct > 0) == (s == 1): return s
        return 0

    raise ValueError(f"unknown mode {mode}")


# === 自我測試 ===
if __name__ == "__main__":
    print(f"[{now_tp().strftime('%Y-%m-%d %H:%M:%S TW')}] v4 prototype test")
    print()

    pct, op = fetch_kospi_open_gap()
    if pct is None:
        print("KOSPI gap: 取不到 (可能未到 08:00 TW or 假日)")
    else:
        print(f"KOSPI 今日開盤: {op:,.2f}")
        print(f"KOSPI open gap vs prev close: {pct:+.3f}%")

    print()
    print("=== 決策測試 (假設 NQ +0.6%) ===")
    for mode in ["off", "filter_only", "strict", "loose"]:
        d = decide_v4_signal(nq_pct=0.6, kospi_gap_pct=pct, mode=mode)
        d_str = {1: "LONG", -1: "SHORT", 0: "SKIP"}[d]
        print(f"  mode={mode:<12s} → {d_str}")

    print()
    print("=== 決策測試 (假設 NQ +0.38%, 06/24 NQ 真實值) ===")
    for mode in ["off", "filter_only", "strict", "loose"]:
        d = decide_v4_signal(nq_pct=0.38, kospi_gap_pct=pct, mode=mode)
        d_str = {1: "LONG", -1: "SHORT", 0: "SKIP"}[d]
        print(f"  mode={mode:<12s} → {d_str}")
