"""
守不住開盤 V8 — 盤前候選股篩選 (08:30 cron job)

執行流程:
  1. 用 finlab 載入昨日 close + 20 日均量
  2. 載入 backtest 319 檔 universe
  3. 輸出 universe.csv (ticker, prev_close, avg_vol) 給 live script
"""
import os, sys
os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(r"D:\stock\tmf-bot\live")
BASE_DIR.mkdir(exist_ok=True)

# 從 backtest 用到的 319 檔股票 (kbar 目錄)
KBAR_DIR = Path(r"D:\stock\tmf-bot\backtest\strategy_c\kbars")
UNIVERSE_FILE = BASE_DIR / "universe.csv"


def get_universe_tickers():
    """從 backtest kbar 目錄取得 319 檔 ticker list"""
    return sorted([f.stem for f in KBAR_DIR.glob("*.csv")])


def load_prev_close():
    """從 finlab 載入昨日 close"""
    try:
        import finlab
        # token 從環境或 file
        token_file = Path(r"D:\stock\check_finlab.txt")
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()
            finlab.login(token)
        close = pd.read_feather(r"D:\stock\finlab_db\price#收盤價.feather")
        close = close.set_index("date")
        close.index = pd.to_datetime(close.index)
        return close
    except Exception as e:
        print(f"finlab load 失敗: {e}")
        return None


def main():
    tickers = get_universe_tickers()
    print(f"backtest universe: {len(tickers)} 檔")

    close_df = load_prev_close()
    if close_df is None:
        print("⚠️ 無法載入 prev_close，退出")
        return

    # 取最後一個交易日
    latest_date = close_df.index.max()
    latest_close = close_df.loc[latest_date]
    print(f"最新 close 日期: {latest_date.date()}")

    rows = []
    missing = []
    for t in tickers:
        if t in latest_close.index:
            pc = latest_close[t]
            if pd.notna(pc) and pc > 0:
                rows.append({"ticker": t, "prev_close": float(pc),
                             "date": latest_date.date()})
            else:
                missing.append(t)
        else:
            missing.append(t)

    out = pd.DataFrame(rows)
    out.to_csv(UNIVERSE_FILE, index=False, encoding="utf-8")
    print(f"\n寫入 {UNIVERSE_FILE}: {len(out)} 檔有 prev_close")
    print(f"缺資料: {len(missing)} 檔 (前 10: {missing[:10]})")


if __name__ == "__main__":
    main()
