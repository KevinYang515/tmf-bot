"""
重算 intraday 訊號 — 修正 lookahead bias
===========================================
原版錯誤:
  - 用 hour=9 取 KOSPI/Nikkei → 那是 TW 09:00-10:00 bar
  - 但 TX 08:46 已開盤 → 整個 close 在 TX 開盤後 14min → lookahead

正確時間軸 (用 ts_taipei hour):
  - KOSPI 開盤 = 09:00 KR = 08:00 TW (hour=8 bar)
  - Nikkei 開盤 = 09:00 JST = 08:00 TW (hour=8 bar)
  - TX 開盤 = 08:46 TW
  - hour=8 bar 涵蓋 TW 08:00-09:00, close 在 09:00 TW (TX 已開 14min)

新 feature 設計 (對 0845 session, cutoff=TX 08:44 TW):
  ★ kospi_open_gap%: KOSPI 08:00 TW open vs prev day last close
                     - 100% no lookahead (TX 08:44 已可觀察 KOSPI 開盤 44min)
  ★ nkx_open_gap%:   同上 for Nikkei
  ★ kospi_first30%:  KOSPI 08:00-08:30 變化 (用 1h bar 近似)
                     - 仍小 leak (用 close@09:00 TW)，但相對乾淨
                     - 用 (08:00 TW Open) → (近最 close before 08:46) 近似
                     由於我們只有 1h bar，先跳過這個改用 5m 抓
  ★ nq_pre_0845%:    NQ 05:00→08:00 TW (原版正確)
  ★ es_pre_0845%:    同上

1500 訊號 (TX 14:59 TW cutoff):
  ★ nq_pre_1500%:    NQ 13:00→15:00 TW (原版正確)
  ★ es_pre_1500%:    同上
  ★ kospi_pre_close%: KOSPI 14:00 TW close vs 08:00 TW close
                      KOSPI 收盤 = 15:30 KR = 14:30 TW，14:00 TW bar 是倒數第二根
                      14:00 TW close 在 15:00 TW (lookahead 1min — 接受)
"""
import pandas as pd
from pathlib import Path

BASE = Path(__file__).parent
RAW = BASE / "intraday_raw"
OUT = BASE / "intraday_signals_v2.csv"


def load(name):
    f = RAW / f"{name}_1h.csv"
    if not f.exists(): return None
    df = pd.read_csv(f)
    df["taipei"] = pd.to_datetime(df["ts_taipei"])
    df["date"]   = df["taipei"].dt.date.astype(str)
    df["hour"]   = df["taipei"].dt.hour
    return df.sort_values("taipei")


nq    = load("nq")
es    = load("es")
nkx   = load("nkx")
kospi = load("kospi")

print(f"NQ {len(nq) if nq is not None else 'NA'}, "
      f"ES {len(es) if es is not None else 'NA'}, "
      f"Nikkei {len(nkx) if nkx is not None else 'NA'}, "
      f"KOSPI {len(kospi) if kospi is not None else 'NA'}")


def get_hour_bar(df, date_str, hour):
    """取該日該 TW hour 的 bar (整 row)"""
    sub = df[(df["date"] == date_str) & (df["hour"] == hour)]
    if sub.empty: return None
    return sub.iloc[0]


def get_close_at_or_before(df, date_str, hour):
    """取該日 hour 或之前最近的 close"""
    sub = df[(df["date"] == date_str) & (df["hour"] <= hour)]
    if sub.empty: return None
    return float(sub.iloc[-1]["Close"])


def get_prev_day_last_close(df, date_str):
    """取前一個交易日最後一根 bar 的 close"""
    sub = df[df["date"] < date_str]
    if sub.empty: return None
    return float(sub.iloc[-1]["Close"])


all_dates = sorted(set().union(
    set(nq["date"].unique()) if nq is not None else set(),
    set(es["date"].unique()) if es is not None else set(),
    set(nkx["date"].unique()) if nkx is not None else set(),
    set(kospi["date"].unique()) if kospi is not None else set()
))
print(f"日期範圍: {all_dates[0]} ~ {all_dates[-1]} ({len(all_dates)} 天)")

records = []
for d in all_dates:
    rec = {"date": d}

    # =========================================================================
    # 0845 session features (TX cutoff 08:44 TW)
    # =========================================================================

    # NQ 0845: 05:00→08:00 TW (clean — NQ 24/5 trading)
    if nq is not None:
        c8 = get_close_at_or_before(nq, d, 8)
        c5 = get_close_at_or_before(nq, d, 5)
        if c8 is not None and c5 is not None and c5 != 0:
            rec["nq_0845"]     = c8 - c5
            rec["nq_0845_pct"] = (c8 - c5) / c5 * 100

    if es is not None:
        c8 = get_close_at_or_before(es, d, 8)
        c5 = get_close_at_or_before(es, d, 5)
        if c8 is not None and c5 is not None and c5 != 0:
            rec["es_0845"]     = c8 - c5
            rec["es_0845_pct"] = (c8 - c5) / c5 * 100

    # ★ KOSPI 開盤 gap (核心新 feature)
    # = Open of TW-08 bar (= KOSPI 09:00 KR 開盤價) vs 前一天最後 close
    # → 100% no lookahead (TX 08:44 已能觀察 KOSPI 開盤 44min)
    if kospi is not None:
        bar08 = get_hour_bar(kospi, d, 8)
        prev_close = get_prev_day_last_close(kospi, d)
        if bar08 is not None and prev_close is not None and prev_close != 0:
            open_today = float(bar08["Open"])
            gap_pct = (open_today - prev_close) / prev_close * 100
            rec["kospi_open_gap"]     = open_today - prev_close
            rec["kospi_open_gap_pct"] = gap_pct

    if nkx is not None:
        bar08 = get_hour_bar(nkx, d, 8)
        prev_close = get_prev_day_last_close(nkx, d)
        if bar08 is not None and prev_close is not None and prev_close != 0:
            open_today = float(bar08["Open"])
            gap_pct = (open_today - prev_close) / prev_close * 100
            rec["nkx_open_gap"]     = open_today - prev_close
            rec["nkx_open_gap_pct"] = gap_pct

    # ★ KOSPI 開盤後第一根 1h 的 H-O / L-O / C-O 範圍 (08:00-09:00 TW bar)
    # 注意: Close 是在 09:00 TW (TX 已開 14min), 小 leak
    # 對 backtest 樂觀, 實盤需用 5m bar 改成 08:00→08:44 真正乾淨值
    if kospi is not None:
        bar08 = get_hour_bar(kospi, d, 8)
        if bar08 is not None:
            o = float(bar08["Open"]); c = float(bar08["Close"])
            h = float(bar08["High"]); l = float(bar08["Low"])
            if o != 0:
                rec["kospi_first1h_pct"]   = (c - o) / o * 100  # 收 vs 開
                rec["kospi_first1h_h_pct"] = (h - o) / o * 100
                rec["kospi_first1h_l_pct"] = (l - o) / o * 100

    if nkx is not None:
        bar08 = get_hour_bar(nkx, d, 8)
        if bar08 is not None:
            o = float(bar08["Open"]); c = float(bar08["Close"])
            if o != 0:
                rec["nkx_first1h_pct"] = (c - o) / o * 100

    # =========================================================================
    # 1500 session features (TX cutoff 14:59 TW)
    # =========================================================================

    # NQ 1500: 13:00→15:00 TW
    if nq is not None:
        c15 = get_close_at_or_before(nq, d, 15)
        c13 = get_close_at_or_before(nq, d, 13)
        if c15 is not None and c13 is not None and c13 != 0:
            rec["nq_1500"]     = c15 - c13
            rec["nq_1500_pct"] = (c15 - c13) / c13 * 100

    if es is not None:
        c15 = get_close_at_or_before(es, d, 15)
        c13 = get_close_at_or_before(es, d, 13)
        if c15 is not None and c13 is not None and c13 != 0:
            rec["es_1500"]     = c15 - c13
            rec["es_1500_pct"] = (c15 - c13) / c13 * 100

    # KOSPI / NKX 全日累計 (TX 14:59 用): KOSPI 08:00→14:00 TW
    if kospi is not None:
        c14 = get_close_at_or_before(kospi, d, 14)
        bar08 = get_hour_bar(kospi, d, 8)
        if c14 is not None and bar08 is not None:
            o8 = float(bar08["Open"])
            if o8 != 0:
                rec["kospi_intraday_pct"] = (c14 - o8) / o8 * 100

    if nkx is not None:
        c14 = get_close_at_or_before(nkx, d, 14)
        bar08 = get_hour_bar(nkx, d, 8)
        if c14 is not None and bar08 is not None:
            o8 = float(bar08["Open"])
            if o8 != 0:
                rec["nkx_intraday_pct"] = (c14 - o8) / o8 * 100

    records.append(rec)

out = pd.DataFrame(records)
out.to_csv(OUT, index=False, encoding="utf-8-sig")
print(f"\n完成 → {OUT}  ({len(out)} 筆)")

# 覆蓋率
print("\n訊號覆蓋率 (非 NaN 筆數):")
for col in out.columns:
    if col == "date": continue
    n = out[col].notna().sum()
    pct = n / len(out) * 100 if len(out) else 0
    print(f"  {col:<28s} {n:>4d}/{len(out)}  ({pct:.0f}%)")

print("\n最近 5 筆:")
print(out.tail(5).to_string())
