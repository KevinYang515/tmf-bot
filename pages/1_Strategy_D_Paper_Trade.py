"""
Strategy D Paper Trade 紀錄頁
- 顯示 D-Cash / D-SSF 模擬單紀錄
- 顯示今日訊號（最新 daily_signals/*.csv）
- 統計：WR、總 PnL、by track
"""
import streamlit as st
import pandas as pd
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Strategy D - Paper Trade", page_icon="📋", layout="wide")

TZ_TW = timezone(timedelta(hours=8))
REPO_ROOT = Path(__file__).resolve().parent.parent

PAPER_LOG    = REPO_ROOT / 'paper_trade_log.csv'
SIGNALS_DIR  = REPO_ROOT / 'daily_signals'

st.title("📋 Strategy D - 出處置動能跟進（模擬單）")

st.markdown("""
**策略**：漲多 20 分鐘處置結束後 1-14 天 + 大中型市值 + 股價 ≥ 300 + 前一日漲幅 ≥ 9% + 量比 ≥ 1
**兩個 track**：
- **D-Cash**：現股 09:00 集合競價買入，TP +10t / trail -2t
- **D-SSF**：個股期貨 08:45 開盤買入（paper trade 階段）

📖 完整策略：[STRATEGY_D_PLAYBOOK.md](https://github.com/KevinYang515/tmf-bot/blob/main/STRATEGY_D_PLAYBOOK.md)
""")

# ── 今日訊號 ───────────────────────────────────────────────────────
st.divider()
st.subheader("🔔 最新訊號")

if SIGNALS_DIR.exists():
    files = sorted(SIGNALS_DIR.glob('*.csv'), reverse=True)
    if files:
        latest = files[0]
        td = latest.stem
        try:
            sig = pd.read_csv(latest)
        except Exception:
            sig = pd.DataFrame()
        if not sig.empty:
            st.caption(f"進場日：**{td}**　|　檔案：`daily_signals/{latest.name}`")
            cols_show = ['code','name','cap_label','prev_close','ret_prev_%','vol_ratio',
                         'days_post_disp','whale_chg_%','has_ssf','ssf_root','limit_up']
            existing_cols = [c for c in cols_show if c in sig.columns]
            st.dataframe(sig[existing_cols], use_container_width=True, hide_index=True)

            ssf_n = sig['has_ssf'].sum() if 'has_ssf' in sig.columns else 0
            c1, c2, c3 = st.columns(3)
            c1.metric("D-Cash 候選", f"{len(sig)} 筆")
            c2.metric("D-SSF 候選（子集）", f"{ssf_n} 筆")
            c3.metric("無 SSF（只能 cash）", f"{len(sig) - ssf_n} 筆")
        else:
            st.info(f"{td} 無候選訊號（資料截至前一交易日）")
    else:
        st.info("還沒有任何 daily_signals/*.csv 產生")
else:
    st.info("daily_signals/ 目錄不存在")

# ── Paper trade 紀錄 ──────────────────────────────────────────────
st.divider()
st.subheader("📊 Paper Trade 紀錄")

@st.cache_data(ttl=60)
def load_paper_log():
    if not PAPER_LOG.exists():
        return pd.DataFrame()
    # 跳過 # 開頭的註解行
    try:
        df = pd.read_csv(PAPER_LOG, comment='#')
        return df
    except Exception:
        return pd.DataFrame()

log = load_paper_log()

if log.empty or log['date'].isna().all():
    st.info("尚無 paper trade 紀錄。請手動填寫 `paper_trade_log.csv` 後 git push 更新。")
    st.code("""# CSV 格式（去掉 # 註解行後新增資料列）
date,track,code,name,signal_ret_prev,signal_days_post_disp,planned_entry,planned_tp,planned_stop,actual_entry,actual_exit,exit_reason,actual_pnl_per_share,actual_pnl_pct,fill_rate_ok,slippage_ticks,notes
2026-06-23,D-Cash,7610,聯友金屬-創,10.0,5,2546.5,2596.5,2536.5,2320,2370,TP,49.5,2.14,yes,0,test
""", language='csv')
else:
    # 清資料
    log = log.dropna(subset=['date'])
    log['date'] = pd.to_datetime(log['date'], errors='coerce')
    log = log.dropna(subset=['date'])
    for c in ['actual_pnl_per_share','actual_pnl_pct','slippage_ticks',
              'signal_ret_prev','signal_days_post_disp']:
        if c in log.columns:
            log[c] = pd.to_numeric(log[c], errors='coerce')

    # 篩選 track
    tracks = log['track'].dropna().unique().tolist()
    sel = st.multiselect("Track 篩選", options=tracks, default=tracks)
    view = log[log['track'].isin(sel)]

    # 統計 KPI
    if not view.empty:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("總筆數", f"{len(view)}")
        if 'actual_pnl_per_share' in view.columns:
            pnl = view['actual_pnl_per_share'].dropna()
            if not pnl.empty:
                c2.metric("總 PnL/股", f"{pnl.sum():+.2f}")
                c3.metric("平均 PnL/股", f"{pnl.mean():+.3f}")
                wr = (pnl > 0).mean() * 100
                c4.metric("WR", f"{wr:.1f}%")

        # By track
        if 'track' in view.columns:
            st.markdown("**By Track:**")
            agg = view.groupby('track').agg(
                n=('actual_pnl_per_share','count'),
                wr=('actual_pnl_per_share', lambda x: (x>0).mean()*100),
                total=('actual_pnl_per_share','sum'),
                avg=('actual_pnl_per_share','mean'),
            ).round(2)
            st.dataframe(agg, use_container_width=True)

        # 明細
        st.markdown("**明細：**")
        st.dataframe(view.sort_values('date', ascending=False),
                     use_container_width=True, hide_index=True)

# ── 說明 ──────────────────────────────────────────────────────────
st.divider()
with st.expander("📖 如何記錄 paper trade"):
    st.markdown("""
    1. 每天 17:30 後跑 `python backtest/daily_signal.py`，產生明日候選清單
    2. 隔天 08:30 - 09:00 之間：
       - **D-Cash**: 紙上模擬「掛漲停價限價買」
       - **D-SSF**: 紙上模擬「8:45 期貨開盤市價買」
    3. 09:00 後紀錄實際開盤成交價（cash 看現股、SSF 看期貨）
    4. 13:00 前觀察 TP/trail/CLOSE 出場結果
    5. 填寫 `paper_trade_log.csv` → git commit + push → 此頁自動更新
    """)
