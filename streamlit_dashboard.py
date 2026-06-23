"""
V38 + NQ-TMF 實盤交易 Dashboard
====================================
Data sources:
- KevinYang515/trading-dashboard/logs/trade_records.csv  (每筆成交)
- KevinYang515/trading-dashboard/logs/balance_log.csv    (每日帳戶快照)
- KevinYang515/trading-dashboard/logs/webhook_raw.csv    (每個 webhook，含漏單) [optional]
"""
import streamlit as st
import pandas as pd
import numpy as np
import requests
import base64
import io
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="TMF 交易 Dashboard", page_icon="📈", layout="wide")

TZ_TW = timezone(timedelta(hours=8))
REPO = "KevinYang515/trading-dashboard"
TRADE_URL   = f"https://raw.githubusercontent.com/{REPO}/main/logs/trade_records.csv"
BALANCE_URL = f"https://raw.githubusercontent.com/{REPO}/main/logs/balance_log.csv"
WEBHOOK_URL = f"https://raw.githubusercontent.com/{REPO}/main/logs/webhook_raw.csv"
TMF_POINT_VALUE = 10

# ==========================================
# Data loaders
# ==========================================
@st.cache_data(ttl=60)
def load_csv(url):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return pd.DataFrame()
        return pd.read_csv(io.StringIO(r.text), encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_trades():
    df = load_csv(TRADE_URL)
    if df.empty: return df
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["date"] = df["datetime"].dt.date
    for col in ["signal_price", "fill_price", "slippage_pts", "slippage_twd",
                "pos_before", "target_pos", "quantity"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("datetime").reset_index(drop=True)


@st.cache_data(ttl=60)
def load_balance():
    df = load_csv(BALANCE_URL)
    if df.empty: return df
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["date"] = df["datetime"].dt.date
    for col in ["yesterday_balance", "today_balance", "equity",
                "future_settle_profitloss", "future_open_position", "available_margin"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("datetime").reset_index(drop=True)


@st.cache_data(ttl=60)
def load_webhook():
    df = load_csv(WEBHOOK_URL)
    if df.empty: return df
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]
    df["received_at"] = pd.to_datetime(df["received_at"], errors="coerce", utc=True).dt.tz_convert(TZ_TW)
    df["date"] = df["received_at"].dt.date
    return df.sort_values("received_at").reset_index(drop=True)


# ==========================================
# FIFO PnL
# ==========================================
def fifo_pnl(trades):
    """每筆成交 FIFO 配對算 round-trip PnL，回傳每筆事件含 realized_pnl 欄"""
    from collections import deque
    longs = deque()   # (entry_price, qty, ts)
    shorts = deque()
    out = []
    for _, t in trades.iterrows():
        if pd.isna(t.get("fill_price")):
            out.append({"datetime": t["datetime"], "date": t["date"],
                        "action": t.get("action"), "qty": int(t.get("quantity", 0) or 0),
                        "price": None, "realized_pnl": 0.0, "open_pos_after": np.nan})
            continue
        p = float(t["fill_price"])
        q = int(t.get("quantity", 1) or 1)
        action = t.get("action")
        rpnl = 0.0
        if action == "BUY":
            rem = q
            while rem > 0 and shorts:
                sp, sq, _ts = shorts[0]
                use = min(rem, sq)
                rpnl += (sp - p) * use * TMF_POINT_VALUE
                if sq > use: shorts[0] = (sp, sq - use, _ts)
                else: shorts.popleft()
                rem -= use
            if rem > 0:
                longs.append((p, rem, t["datetime"]))
        elif action == "SELL":
            rem = q
            while rem > 0 and longs:
                lp, lq, _ts = longs[0]
                use = min(rem, lq)
                rpnl += (p - lp) * use * TMF_POINT_VALUE
                if lq > use: longs[0] = (lp, lq - use, _ts)
                else: longs.popleft()
                rem -= use
            if rem > 0:
                shorts.append((p, rem, t["datetime"]))
        open_pos = sum(q for _, q, _ in longs) - sum(q for _, q, _ in shorts)
        out.append({"datetime": t["datetime"], "date": t["date"],
                    "action": action, "qty": q, "price": p,
                    "realized_pnl": rpnl, "open_pos_after": open_pos})
    return pd.DataFrame(out)


def stats(realized_series):
    """回傳 dict：n, total, WR, PF, avg_win, avg_loss, max_win, max_loss"""
    r = realized_series[realized_series != 0]
    n = len(r)
    if n == 0:
        return {"n": 0, "total": 0, "WR": 0.0, "PF": 0.0,
                "avg_win": 0, "avg_loss": 0, "max_win": 0, "max_loss": 0}
    wins = r[r > 0]; losses = r[r < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {
        "n": int(n),
        "total": int(r.sum()),
        "WR": round((r > 0).mean() * 100, 1),
        "PF": round(pf, 2),
        "avg_win": int(wins.mean()) if len(wins) > 0 else 0,
        "avg_loss": int(losses.mean()) if len(losses) > 0 else 0,
        "max_win": int(r.max()),
        "max_loss": int(r.min()),
    }


# ==========================================
# UI
# ==========================================
st.title("📈 V38 + NQ-TMF 實盤 Dashboard")

trades = load_trades()
balance = load_balance()
webhook = load_webhook()

if trades.empty:
    st.info("尚無交易資料")
    st.stop()

# ─ FIFO PnL ──────────────────────────────────────────
filled = trades[trades["order_status"].astype(str).str.contains("Filled", na=False)].copy()
pnl_df = fifo_pnl(filled)
pnl_df["cumulative"] = pnl_df["realized_pnl"].cumsum()

today = datetime.now(TZ_TW).date()
this_week_start = today - timedelta(days=today.weekday())
this_month_start = today.replace(day=1)

# ==========================================
# Section 1: 全期累計獲利（最頂層數字）
# ==========================================
st.markdown("### 💰 累計實現獲利")
total_all = stats(pnl_df["realized_pnl"])
first_date = pnl_df["date"].min() if not pnl_df.empty else today
days_elapsed = (today - first_date).days + 1

c1, c2, c3, c4 = st.columns(4)
c1.metric("📊 全期累計 PnL", f"{total_all['total']:+,} 元",
          delta=f"自 {first_date} ({days_elapsed} 天)")
c2.metric("✅ 勝率", f"{total_all['WR']}%",
          delta=f"{int(total_all['n'] * total_all['WR']/100)} 勝 / {total_all['n']} 筆")
c3.metric("⚖️ Profit Factor", f"{total_all['PF']}",
          delta="> 1 = 有 edge")
c4.metric("💵 平均單筆", f"{int(total_all['total']/max(total_all['n'],1)):+,} 元",
          delta=f"勝 {total_all['avg_win']:+,} / 敗 {total_all['avg_loss']:+,}")

st.caption(f"從 {first_date} 起算，FIFO 配對所有完成的 round-trip，含手續費後實際入袋")

# ==========================================
# Section 2: 累計 PnL 趨勢圖
# ==========================================
st.divider()
st.markdown("### 📈 累計 PnL 走勢")

if not pnl_df.empty:
    chart_df = pnl_df.copy()
    chart_df["date_str"] = chart_df["datetime"].dt.strftime("%Y-%m-%d %H:%M")
    chart_df = chart_df[["date_str", "cumulative"]].set_index("date_str")
    chart_df.columns = ["累計 PnL (元)"]
    st.line_chart(chart_df, height=300)
    st.caption(f"每筆成交後的累計實現損益。{len(pnl_df)} 筆。")

# ==========================================
# Section 3: 期間統計（本日 / 本週 / 本月 / 全期）
# ==========================================
st.divider()
st.markdown("### 📅 期間統計對比")

def period_stats(start_date, end_date, label):
    sub = pnl_df[(pnl_df["date"] >= start_date) & (pnl_df["date"] <= end_date)]
    s = stats(sub["realized_pnl"])
    return {"period": label, **s}

periods = [
    period_stats(today, today, "🌟 今日"),
    period_stats(this_week_start, today, "📆 本週"),
    period_stats(this_month_start, today, "📅 本月"),
    period_stats(first_date, today, "🌍 全期"),
]
pdf = pd.DataFrame(periods)
pdf.rename(columns={
    "period": "期間", "n": "筆數", "total": "總 PnL", "WR": "勝率%",
    "PF": "PF", "avg_win": "均勝", "avg_loss": "均敗",
    "max_win": "最大單筆勝", "max_loss": "最大單筆敗",
}, inplace=True)

# Format numbers
for c in ["總 PnL", "均勝", "均敗", "最大單筆勝", "最大單筆敗"]:
    pdf[c] = pdf[c].apply(lambda x: f"{int(x):+,}")
pdf["勝率%"] = pdf["勝率%"].apply(lambda x: f"{x}%")

st.dataframe(pdf, use_container_width=True, hide_index=True)

# ==========================================
# Section 4: 漏單統計（如果 webhook log 有資料）
# ==========================================
st.divider()
st.markdown("### 🚨 漏單統計（V38 webhook）")

if webhook.empty:
    st.info("尚無 webhook 紀錄資料（需從 VM 同步 webhook_raw.csv 到 trading-dashboard 才能顯示）")
else:
    # 過濾今天 / 本週 / 本月 / 全期
    today_wh = webhook[webhook["date"] == today]
    week_wh = webhook[webhook["date"] >= this_week_start]
    month_wh = webhook[webhook["date"] >= this_month_start]
    all_wh = webhook

    def webhook_stats(df, label):
        if df.empty:
            return {"期間": label, "alerts": 0, "成交": 0, "broker 拒收": 0, "dedup 殺掉": 0, "其他": 0}
        d = df["decision"].astype(str)
        return {
            "期間": label,
            "alerts 總數": len(df),
            "成交 (success)": int((d == "EXECUTED:success").sum()),
            "broker 拒收 (warning)": int((d == "EXECUTED:warning").sum()),
            "dedup 殺掉": int((d == "DEDUP_DROPPED").sum()),
            "其他 reject": int(d.str.startswith("REJECT_").sum()),
        }

    wh_pdf = pd.DataFrame([
        webhook_stats(today_wh, "🌟 今日"),
        webhook_stats(week_wh, "📆 本週"),
        webhook_stats(month_wh, "📅 本月"),
        webhook_stats(all_wh, "🌍 全期"),
    ])
    st.dataframe(wh_pdf, use_container_width=True, hide_index=True)
    st.caption("**broker 拒收**通常是「可委託金額不足」(99Q9) — 帳戶保證金不夠。**dedup 殺掉**是 app.py 5 秒內收到相同 target_pos 自動去重。")

    # Decision breakdown 最近 20 筆
    st.markdown("**最近 20 個 webhook 詳細**")
    recent = webhook.tail(20)[[
        "received_at", "order_action", "order_comment",
        "target_pos", "signal_price", "decision"
    ]].copy()
    recent["received_at"] = recent["received_at"].dt.strftime("%m/%d %H:%M:%S")
    recent.columns = ["時間", "方向", "原因", "目標部位", "訊號價", "結果"]

    def color_decision(row):
        d = str(row["結果"])
        if "success" in d: bg = "background-color: #0d2b1a"
        elif "warning" in d or "DEDUP" in d: bg = "background-color: #2b2b0d"
        elif "REJECT" in d or "ERROR" in d: bg = "background-color: #2b0d0d"
        else: bg = ""
        return [bg] * len(row)

    st.dataframe(recent.style.apply(color_decision, axis=1),
                 use_container_width=True, hide_index=True)

# ==========================================
# Section 5: 每日成交明細（原有功能）
# ==========================================
st.divider()
st.markdown("### 📋 成交明細")
available_dates = sorted(filled["date"].unique(), reverse=True)
default_idx = list(available_dates).index(today) if today in available_dates else 0
selected_date = st.selectbox("選擇日期", options=available_dates, index=default_idx,
                              format_func=lambda d: str(d))

day_df = filled[filled["date"] == selected_date].copy()
if day_df.empty:
    st.info("當日無成交紀錄")
else:
    display = day_df[["datetime", "action", "contract", "quantity",
                       "signal_price", "fill_price", "slippage_pts", "slippage_twd",
                       "pos_before", "target_pos", "order_status"]].copy()
    display["datetime"] = display["datetime"].dt.strftime("%H:%M:%S")
    for c in ["signal_price", "fill_price", "slippage_twd"]:
        display[c] = display[c].apply(lambda x: int(x) if pd.notna(x) else "")
    display["slippage_pts"] = display["slippage_pts"].apply(
        lambda x: f"{int(x):+d}" if pd.notna(x) else ""
    )
    display["action"] = display["action"].map({"BUY": "買", "SELL": "賣"})
    display["order_status"] = display["order_status"].astype(str).str.replace("Status.", "", regex=False)
    display.columns = ["時間", "動作", "合約", "口數", "信號價", "成交價",
                       "滑價(點)", "滑價(元)", "前部位", "目標", "狀態"]

    def color_row(row):
        bg = "background-color: #0d2b1a" if row["動作"] == "買" else "background-color: #2b0d0d"
        return [bg] * len(row)

    st.dataframe(display.style.apply(color_row, axis=1),
                 use_container_width=True, hide_index=True)

# ==========================================
# Section 6: 帳戶權益歷史
# ==========================================
st.divider()
st.markdown("### 💼 帳戶權益歷史")

if not balance.empty:
    daily = balance.sort_values("datetime").groupby("date").last().reset_index()
    daily["date_str"] = daily["date"].astype(str)
    latest = daily.iloc[-1]

    c1, c2, c3 = st.columns(3)
    c1.metric("最新權益數", f"{int(latest['equity']):,}")
    c2.metric("可動用保證金", f"{int(latest['available_margin']):,}")
    c3.metric("浮動損益", f"{int(latest.get('future_open_position', 0)):+,}")

    daily_chart = daily.set_index("date_str")[["equity"]]
    daily_chart.columns = ["權益數 (元)"]
    st.line_chart(daily_chart, height=240)

    st.caption("⚠️ 權益變化 = 交易 PnL + 入金/出金，**不等於**累計交易獲利。"
               "看「累計實現獲利」才是純策略績效。")
else:
    st.info("尚無帳戶餘額資料")

# Footer
st.markdown("---")
st.caption(f"資料來源：[trading-dashboard]({f'https://github.com/{REPO}'}) | "
           f"Cache TTL 60 秒 | 更新於 {datetime.now(TZ_TW).strftime('%Y-%m-%d %H:%M:%S')}")
