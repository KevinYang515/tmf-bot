"""
06/24 早盤跳空因子拆解
=======================
目的: 重建 06/24 早上 08:46 TX 開盤瞬間,
      把所有可能影響 gap 的因子全部攤出來,
      看哪些因子如果用了就能抓到這個跳空.

需要的資料 (全部用 yfinance 抓):
  - TX/MXF 06/24 08:46 開盤 ← 沒有直接 ticker, 用 ^TWII 或者 ^TWIIF (台指)
  - TX 06/23 13:45 收盤
  - KOSPI ^KS11 06/23 close vs 06/20 close (週末)
  - Nikkei ^N225 06/23 close vs 06/20 close
  - NQ/ES 06/23 收 / 06/24 開
  - NDX/SPX/DJI 06/23 收盤 (前一夜 US)
  - VIX ^VIX 06/23 close
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import yfinance as yf
import pandas as pd

TW = ZoneInfo("Asia/Taipei")
print("抓資料中... (yfinance)")

def fetch_daily(ticker, days_back=10):
    """抓最近 N 日 daily"""
    try:
        t = yf.Ticker(ticker)
        df = t.history(period=f"{days_back}d", interval="1d", auto_adjust=False)
        if df.empty:
            return None
        return df
    except Exception as e:
        print(f"  {ticker} err: {e}")
        return None


def fetch_intraday(ticker, days=5, interval="1h"):
    try:
        t = yf.Ticker(ticker)
        df = t.history(period=f"{days}d", interval=interval, auto_adjust=False)
        if df.empty:
            return None
        df.index = df.index.tz_convert(TW)
        return df
    except Exception as e:
        print(f"  {ticker} {interval} err: {e}")
        return None


# === A. TX 自身 gap (用 ^TWII 加權指數代替 — TX 期貨 yfinance ticker 不穩) ===
print("\n=== A. TX gap 大小 (用 ^TWII 加權指數 daily) ===")
twii = fetch_daily("^TWII", days_back=15)
if twii is not None and len(twii) >= 3:
    twii_recent = twii.tail(5)[["Open", "High", "Low", "Close"]]
    print(twii_recent)
    if "2026-06-24" in twii.index.strftime("%Y-%m-%d").tolist():
        idx_24 = twii.index.strftime("%Y-%m-%d").tolist().index("2026-06-24")
        if idx_24 >= 1:
            open_24 = float(twii.iloc[idx_24]["Open"])
            close_23 = float(twii.iloc[idx_24 - 1]["Close"])
            gap_pt = open_24 - close_23
            gap_pct = gap_pt / close_23 * 100
            print(f"\nTWII 06/24 開盤  = {open_24:,.2f}")
            print(f"TWII 06/23 收盤  = {close_23:,.2f}")
            print(f"  gap = {gap_pt:+,.2f} ({gap_pct:+.3f}%)")

# 同時抓 TX 期貨 ticker (測試多個)
for tw_fut in ["TWT00.TW", "^TWFUTURES", "TWII", "MXFC.TW"]:
    df = fetch_daily(tw_fut, days_back=5)
    if df is not None and not df.empty:
        print(f"  {tw_fut} 最近: {df.tail(3)[['Open','Close']].to_dict()}")
        break

# === B. NQ / ES 06/24 凌晨 (5:00-8:00 TW) ===
print("\n=== B. NQ futures 06/24 05:00-08:00 TW (1h bars) ===")
nq = fetch_intraday("NQ=F", days=3, interval="1h")
if nq is not None:
    nq_24 = nq[nq.index.date == datetime(2026, 6, 24).date()]
    print(f"  06/24 NQ 全部 1h bars:")
    if not nq_24.empty:
        for ts, row in nq_24.iterrows():
            print(f"    {ts.strftime('%H:%M')} O={row['Open']:.2f} H={row['High']:.2f} "
                  f"L={row['Low']:.2f} C={row['Close']:.2f}")
        # 取 5:00 / 8:00 close
        b5 = nq_24[nq_24.index.hour <= 5]
        b8 = nq_24[nq_24.index.hour <= 8]
        if not b5.empty and not b8.empty:
            c5 = float(b5.iloc[-1]["Close"])
            c8 = float(b8.iloc[-1]["Close"])
            print(f"  05:00 close={c5:.2f}, 08:00 close={c8:.2f}, change={(c8-c5)/c5*100:+.3f}%")

# === C. KOSPI ^KS11 ===
print("\n=== C. KOSPI ^KS11 (前 5 日 daily) ===")
kos = fetch_daily("^KS11", days_back=10)
if kos is not None:
    print(kos.tail(5)[["Open", "High", "Low", "Close"]])
    if len(kos) >= 2:
        last = float(kos.iloc[-1]["Close"])
        prev = float(kos.iloc[-2]["Close"])
        print(f"\nKOSPI close change: {prev:.2f} → {last:.2f}  ({(last-prev)/prev*100:+.3f}%)")
        # 倒推: 06/23 收盤是?
        for i in range(len(kos)-1, -1, -1):
            ds = kos.index[i].strftime("%Y-%m-%d")
            if ds == "2026-06-23":
                kos_close_23 = float(kos.iloc[i]["Close"])
                kos_close_prev = float(kos.iloc[i-1]["Close"])
                kos_chg_23 = (kos_close_23 - kos_close_prev) / kos_close_prev * 100
                print(f"  06/23 KOSPI = {kos_close_23:.2f}  (vs {kos.index[i-1].strftime('%m-%d')}={kos_close_prev:.2f}, {kos_chg_23:+.3f}%)")
                break

# === D. Nikkei ^N225 ===
print("\n=== D. Nikkei ^N225 (前 5 日 daily) ===")
nkx = fetch_daily("^N225", days_back=10)
if nkx is not None:
    print(nkx.tail(5)[["Open", "High", "Low", "Close"]])
    if len(nkx) >= 2:
        last = float(nkx.iloc[-1]["Close"])
        prev = float(nkx.iloc[-2]["Close"])
        print(f"\nNikkei close change: {prev:.2f} → {last:.2f}  ({(last-prev)/prev*100:+.3f}%)")
        for i in range(len(nkx)-1, -1, -1):
            ds = nkx.index[i].strftime("%Y-%m-%d")
            if ds == "2026-06-23":
                nkx_close_23 = float(nkx.iloc[i]["Close"])
                nkx_close_prev = float(nkx.iloc[i-1]["Close"])
                nkx_chg_23 = (nkx_close_23 - nkx_close_prev) / nkx_close_prev * 100
                print(f"  06/23 Nikkei = {nkx_close_23:.2f}  (vs {nkx.index[i-1].strftime('%m-%d')}={nkx_close_prev:.2f}, {nkx_chg_23:+.3f}%)")
                break

# === E. 美股 06/23 收 (前夜) — NDX / SPX / DJI ===
print("\n=== E. 美股 06/23 收盤 ===")
for ticker, name in [("^NDX", "NDX (Nasdaq)"), ("^GSPC", "SPX (S&P 500)"),
                     ("^DJI", "DJI (Dow)"), ("^VIX", "VIX")]:
    df = fetch_daily(ticker, days_back=10)
    if df is None:
        print(f"  {name}: 抓不到")
        continue
    if len(df) >= 2:
        last = float(df.iloc[-1]["Close"])
        prev = float(df.iloc[-2]["Close"])
        last_d = df.index[-1].strftime("%m-%d")
        prev_d = df.index[-2].strftime("%m-%d")
        chg = (last - prev) / prev * 100
        print(f"  {name:<22s} {prev_d}={prev:,.2f} → {last_d}={last:,.2f}  ({chg:+.3f}%)")

# === F. 06/23 美股盤中 (上下影線) ===
print("\n=== F. 06/23 NDX/SPX 盤中 K (前夜開盤如何 → 收盤) ===")
for ticker in ["^NDX", "^GSPC"]:
    df = fetch_daily(ticker, days_back=10)
    if df is None: continue
    # 找 06/23
    for i in range(len(df)):
        ds = df.index[i].strftime("%Y-%m-%d")
        if ds == "2026-06-23":
            o = df.iloc[i]["Open"]; h = df.iloc[i]["High"]
            l = df.iloc[i]["Low"]; c = df.iloc[i]["Close"]
            chg = (c-o)/o*100
            print(f"  {ticker} 06/23  O={o:,.2f} H={h:,.2f} L={l:,.2f} C={c:,.2f}  "
                  f"(open→close {chg:+.3f}%)")
            break

# === G. 0845 訊號 v3 模擬 — 06/24 那天會不會觸發? ===
print("\n=== G. v3 訊號重建: 06/24 NQ + KOSPI 各自判斷 ===")
print("  (用上面拿到的數字)")
print()
print("  --- V0 (NQ 5:00→8:00) ---")
print("  NQ +0.38% < 0.5% threshold → V0 SKIP [no signal]")
print()
print("  --- V4 (KOSPI 06/23 close vs 06/22 close) ---")
print("  KOSPI -9.99% (>>0.5%) → V4 SHORT [signal fires]")
print()
print("  --- V5 (NKX 06/23 close vs 06/22 close) ---")
print("  Nikkei -3.55% (>>0.5%) → NKX signal fires too")
print()
print("  --- v3 整合 ---")
print("  NQ=+0.38% (multi-bull but below threshold), KOSPI=-9.99% (short)")
print("  V0 不過門檻, V4 觸發 SHORT")
print("  整合方向 = SHORT (KOSPI only path, 'KOSPI only 06/24 style')")
print("  → 進場 SELL TMF @ 08:46:00")
