"""
Strategy D 每日訊號產生器
-----------------------------------------
每天 17:30 後執行（等 finlab/disposal-signals 資料更新完）
output 「明日進場」候選清單

進場條件（全部成立）：
- 20 分鐘漲多處置 結束後 1-14 天
- 大型(>500億) OR 中型(100-500億) — on-date
- 股價 >= 300（用今天收盤檢查 + 預估明日開盤）
- 前一日漲跌幅 >= 9%
- 量比 >= 1
- 排除處置期間

輸出：
- console 表格
- D:/stock/tmf-bot/daily_signals/<YYYY-MM-DD>.csv
- 兩組：D-Cash 全部候選 / D-SSF 子集（有 SSF 的）

用法：
$ python daily_signal.py             # 今日訊號（用最新資料推測明日進場）
$ python daily_signal.py 2026-06-23  # 指定日期回看
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

FINLAB_DIR  = Path('D:/stock/finlab_db')
DISP_HIST   = Path('D:/stock/disposal-signals/data/history.csv')
SSF_LIST    = Path('D:/stock/tmf-bot/backtest/strategy_c_results/ssf_list.csv')
OUT_DIR     = Path('D:/stock/tmf-bot/daily_signals')
OUT_DIR.mkdir(parents=True, exist_ok=True)

RET_TH = 9.0
VOL_TH = 1.0
PRICE_MIN = 300

def main(target_date=None):
    # 載入資料
    close = pd.read_feather(FINLAB_DIR / 'price#收盤價.feather')
    close = close.set_index('date')
    close.index = pd.to_datetime(close.index)
    close.columns = close.columns.astype(str)
    close = close.sort_index()

    volume = pd.read_feather(FINLAB_DIR / 'price#成交股數.feather')
    volume = volume.set_index('date')
    volume.index = pd.to_datetime(volume.index)
    volume.columns = volume.columns.astype(str)
    volume = volume.sort_index()

    prev_ret = close.pct_change() * 100
    avg_vol = volume.rolling(20, min_periods=10).mean()
    vol_ratio = volume / avg_vol

    info = pd.read_feather(FINLAB_DIR / 'company_basic_info.feather')
    info = info.set_index('stock_id') if 'stock_id' in info.columns else info
    info.index = info.index.astype(str)
    name_map = dict(zip(info.index.astype(str), info['公司簡稱'].astype(str)))
    shares = pd.to_numeric(info['已發行普通股數或TDR原發行股數'], errors='coerce')

    # 載入處置紀錄
    hist = pd.read_csv(DISP_HIST)
    hist.columns = hist.columns.str.replace('﻿', '', regex=False)
    hist['起始日'] = pd.to_datetime(hist['起始日'], errors='coerce')
    hist['出關日'] = pd.to_datetime(hist['出關日'], errors='coerce')
    hist['代號'] = hist['代號'].astype(str)
    hist['近20日漲幅'] = pd.to_numeric(hist['近20日漲幅'], errors='coerce')
    hist['處置原因'] = np.where(hist['近20日漲幅'] >= 0, '漲多處置', '跌深處置')
    hist.loc[hist['近20日漲幅'].isna(), '處置原因'] = 'unknown'

    # 處置期間索引
    disp_active = {}
    for _, r in hist.dropna(subset=['起始日','出關日']).iterrows():
        for d in pd.date_range(r['起始日'], r['出關日'], freq='D'):
            disp_active.setdefault(str(d.date()), set()).add(r['代號'])

    # 每股的處置 records
    disp_recs = {}
    for sid, grp in hist.dropna(subset=['出關日']).groupby('代號'):
        recs = sorted(zip(grp['出關日'], grp['處置原因'], grp['處置類型'], grp['大戶(%)'], grp['名稱']))
        disp_recs[sid] = recs

    def last_disp(sid, date):
        recs = disp_recs.get(sid, [])
        past = [r for r in recs if r[0] < date]
        if not past: return (None, None, None, None, None)
        return (date - past[-1][0]).days, past[-1][1], past[-1][2], past[-1][3], past[-1][4]

    # SSF 清單
    ssf = pd.read_csv(SSF_LIST)
    ssf_codes = set(ssf['underlying_code'].astype(str))
    ssf_root_map = dict(zip(ssf['underlying_code'].astype(str), ssf['ssf_root']))

    # 確定 target_date
    if target_date:
        td = pd.Timestamp(target_date)
        # td 是「我們想看的明日進場日」，所以前一日 close 用 td - 1 (上一個交易日)
        prev_days = close.index[close.index < td]
        if not len(prev_days):
            print(f'錯誤：{td} 之前沒交易日資料')
            return
        prev_date = prev_days[-1]
        print(f'\n=== Strategy D 每日訊號 - 進場日 {td.strftime("%Y-%m-%d")} ===')
        print(f'    （資料截至 {prev_date.strftime("%Y-%m-%d")} 收盤）')
    else:
        prev_date = close.index[-1]
        td = prev_date + pd.Timedelta(days=1)
        # 找下一個交易日
        while td.weekday() >= 5:
            td += pd.Timedelta(days=1)
        print(f'\n=== Strategy D 每日訊號 - 明日進場 {td.strftime("%Y-%m-%d")} ===')
        print(f'    （資料截至 {prev_date.strftime("%Y-%m-%d")} 收盤）')

    # 篩選候選
    ret_row = prev_ret.loc[prev_date] if prev_date in prev_ret.index else None
    vol_row = vol_ratio.loc[prev_date] if prev_date in vol_ratio.index else None
    close_row = close.loc[prev_date] if prev_date in close.index else None
    if ret_row is None or vol_row is None or close_row is None:
        print('資料不足')
        return

    disposal_t = disp_active.get(str(td.date()), set())

    candidates = []
    for code in close.columns:
        ret_val = ret_row.get(code, np.nan)
        vol_val = vol_row.get(code, np.nan)
        prev_close = close_row.get(code, np.nan)
        if pd.isna(ret_val) or pd.isna(vol_val) or pd.isna(prev_close): continue
        if ret_val < RET_TH or vol_val < VOL_TH: continue
        if prev_close < PRICE_MIN: continue
        if code in disposal_t: continue   # 處置中
        # 市值
        s = shares.get(code, np.nan)
        if pd.isna(s) or s <= 0: continue
        cap_yi = prev_close * s / 1e8
        if cap_yi < 100: continue   # 不要小型/中小
        cap_label = 'A_大型' if cap_yi >= 500 else 'B_中型'
        # 處置條件
        days_post, rsn, typ, whale, dname = last_disp(code, td)
        if days_post is None or days_post > 14: continue
        if rsn != '漲多處置' or typ != '20分鐘': continue
        # 通過全部！
        candidates.append({
            'code': code,
            'name': dname or name_map.get(code, ''),
            'cap_yi': round(cap_yi, 0),
            'cap_label': cap_label,
            'prev_close': prev_close,
            'ret_prev_%': round(ret_val, 1),
            'vol_ratio': round(vol_val, 2),
            'days_post_disp': days_post,
            'whale_chg_%': whale,
            'has_ssf': code in ssf_codes,
            'ssf_root': ssf_root_map.get(code, ''),
            'limit_up': round(prev_close * 1.10, 2),  # 預估漲停價
        })

    if not candidates:
        print('\n  ✗ 沒有符合條件的候選')
        return

    df = pd.DataFrame(candidates).sort_values(['cap_label','ret_prev_%'], ascending=[True, False])
    print(f'\n  ✓ 找到 {len(df)} 筆候選')
    print(f'\n--- D-Cash 候選（全部）---')
    print(df.to_string(index=False))

    ssf_df = df[df['has_ssf']]
    print(f'\n--- D-SSF 候選子集（{len(ssf_df)} 筆有 SSF）---')
    if not ssf_df.empty:
        print(ssf_df[['code','name','ssf_root','prev_close','ret_prev_%','days_post_disp']].to_string(index=False))
    else:
        print('  （今日無 SSF 可做）')

    # 存檔
    out_path = OUT_DIR / f'{td.strftime("%Y-%m-%d")}.csv'
    df.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f'\n→ {out_path}')

    # 提醒
    print(f'\n=== 下單提醒 ===')
    print(f'1. 進場時間：{td.strftime("%Y-%m-%d")} 08:30 - 09:00 之間下集合競價委託')
    print(f'   D-Cash: 限價買 @ 漲停價（cross 出來會以開盤價成交）')
    print(f'   D-SSF:  期貨買 @ 8:45 開盤市價（paper trade 階段）')
    print(f'2. 出場：TP +10t / trail -2t / 13:00 強制平倉')
    print(f'3. 排除處置中：今日已有 {len(disposal_t)} 個股票在處置')


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else None
    main(target)
