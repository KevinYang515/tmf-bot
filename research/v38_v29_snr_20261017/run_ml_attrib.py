"""Causal entry-time ML attribution for the frozen V38/v28 ledger.

This script deliberately uses the vendor engine only for its read-only bar
construction/indicator definitions.  All feature rows are stamped with the
closed five-minute decision bar that precedes their next-open fill.
"""
from __future__ import annotations

import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import shap
from scipy.stats import spearmanr


HERE = Path(__file__).resolve().parent
ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
DATA = HERE / "mxf_1min_2020_20261026.csv"
TRADES = HERE / "br_trades_v28.csv"
DAILY = Path(r"E:\stock\newstrat_rr_20261019\turtle_continuous_tx_20261022.csv")
OUT_YEARS = (2022, 2023, 2024, 2025, 2026)
ALL_YEARS = tuple(range(2020, 2027))
SEED = 20261026

if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
import engine_v26_bbw as engine  # noqa: E402


LIVE_V28 = {
    **engine.P,
    "opt_stale_hr": 10,
    "opt_cooldown_min": 30,
    "opt_short_pyramid_cap_mode": "hour4",
}


def safe_div(a: pd.Series | np.ndarray, b: pd.Series | np.ndarray) -> pd.Series:
    a_s = pd.Series(a)
    b_s = pd.Series(b, index=a_s.index).replace(0, np.nan)
    return a_s / b_s


def er(close: pd.Series, n: int) -> pd.Series:
    return safe_div((close - close.shift(n)).abs(), close.diff().abs().rolling(n).sum())


def make_sessions(bars: pd.DataFrame) -> pd.DataFrame:
    """Causal session identifiers; a 15:00--05:00 night session is one unit."""
    out = bars.copy()
    t = pd.to_datetime(out["open_ts"])
    is_day = (t.dt.hour >= 8) & (t.dt.hour <= 13)
    night_trade_date = (t.dt.normalize() + pd.to_timedelta((t.dt.hour >= 15).astype(int), unit="D"))
    out["session"] = np.where(is_day, "day", "night")
    out["session_date"] = pd.Series(np.where(is_day, t.dt.normalize(), night_trade_date), index=out.index)
    out["session_id"] = out["session"] + "_" + out["session_date"].dt.strftime("%Y%m%d")
    out["clock"] = t.dt.strftime("%H:%M")
    return out


def volume_features(df1: pd.DataFrame, b5: pd.DataFrame) -> pd.DataFrame:
    """Add volume only; OHLC/timestamps remain engine-built exactly."""
    minute = df1.copy()
    minute["bin"] = minute["open_ts"].dt.floor("5min")
    vol = minute.groupby("bin", sort=True)["volume"].sum().rename("vol5").reset_index()
    vol = vol.rename(columns={"bin": "open_ts"})
    out = b5.merge(vol, on="open_ts", how="left", validate="one_to_one")
    out = make_sessions(out)
    out["vol_rel_48"] = safe_div(out["vol5"], out["vol5"].shift(1).rolling(48, min_periods=12).mean())
    out["session_cum_vol"] = out.groupby("session_id", sort=False)["vol5"].cumsum()
    out["vol_same_clock_mean20"] = out.groupby(["session", "clock"], sort=False)["vol5"].transform(
        lambda x: x.shift(1).rolling(20, min_periods=5).mean()
    )
    out["vol_rel_same_clock20"] = safe_div(out["vol5"], out["vol_same_clock_mean20"])
    out["cum_same_clock_mean20"] = out.groupby(["session", "clock"], sort=False)["session_cum_vol"].transform(
        lambda x: x.shift(1).rolling(20, min_periods=5).mean()
    )
    out["session_cum_vol_rel20"] = safe_div(out["session_cum_vol"], out["cum_same_clock_mean20"])
    return out


def enrich_5m(df1: pd.DataFrame) -> pd.DataFrame:
    b5 = engine.prepare(df1, LIVE_V28).copy()
    b5 = volume_features(df1, b5)
    c = b5["close"]
    a = b5["atr"]
    b5["atr100"] = engine.atr(b5, 100)
    b5["dist_ema_long_atr"] = safe_div(c - b5["ema_long"], a)
    b5["dist_ema_short_atr"] = safe_div(c - b5["ema_short"], a)
    b5["dist_ema_fast_atr"] = safe_div(c - b5["ema_fast"], a)
    b5["atr5_points"] = a
    b5["atr5_pct"] = safe_div(a, c)
    b5["atr5_ratio_14_100"] = safe_div(a, b5["atr100"])
    b5["er5_12"] = er(c, 12)
    b5["er5_48"] = er(c, 48)
    for n in (1, 6, 12, 48):
        b5[f"ret5_{n}_atr"] = safe_div(c - c.shift(n), a)
    b5["range5_atr"] = safe_div(b5["high"] - b5["low"], a)
    b5["close_location5"] = safe_div(c - b5["low"], b5["high"] - b5["low"]).fillna(0.5)
    hi20 = b5["high"].rolling(20).max()
    lo20 = b5["low"].rolling(20).min()
    b5["donchian20_pos"] = safe_div(c - lo20, hi20 - lo20).fillna(0.5)
    return b5


def enrich_60m(df1: pd.DataFrame) -> pd.DataFrame:
    b60 = engine.build_bars(df1, 60).copy()
    b60["atr60"] = engine.atr(b60, 14)
    b60["ema50"] = engine.pine_ema(b60["close"], 50)
    b60["ema50_slope_12_atr"] = safe_div(b60["ema50"] - b60["ema50"].shift(12), b60["atr60"])
    b60["close_vs_ema50_atr60"] = safe_div(b60["close"] - b60["ema50"], b60["atr60"])
    b60["er60_12"] = er(b60["close"], 12)
    return b60


def enrich_daily() -> pd.DataFrame:
    d = pd.read_csv(DAILY, parse_dates=["date"]).sort_values("date").drop_duplicates("date", keep="last")
    d = d.rename(columns={"open_diff": "open", "high_diff": "high", "low_diff": "low", "close_diff": "close"}).copy()
    c = d["close"].astype(float)
    for n in (20, 60, 200):
        ma = c.rolling(n, min_periods=n).mean()
        d[f"daily_dist_ma{n}_pct"] = safe_div(c - ma, ma)
    ma60 = c.rolling(60, min_periods=60).mean()
    ma200 = c.rolling(200, min_periods=200).mean()
    d["daily_ma60_slope20"] = safe_div(ma60 - ma60.shift(20), ma60.shift(20))
    d["daily_ma200_slope20"] = safe_div(ma200 - ma200.shift(20), ma200.shift(20))
    d["daily_er20"] = er(c, 20)
    d["daily_er60"] = er(c, 60)
    d["daily_adx14"] = engine.adx(d[["high", "low", "close"]], 14)
    d["daily_drawdown120"] = safe_div(c, c.rolling(120, min_periods=120).max()) - 1.0
    range_pct = safe_div(d["high"] - d["low"], c)
    d["daily_range_rel20"] = safe_div(range_pct, range_pct.rolling(20, min_periods=20).mean())
    d["daily_gap_pct"] = safe_div(d["open"] - c.shift(1), c.shift(1))
    return d


def assign_campaigns(trades: pd.DataFrame) -> pd.DataFrame:
    """Associate each ledger lot to its engine campaign without using outcome data."""
    tr = trades.sort_values(["entry_ts", "exit_ts", "kind"]).copy()
    tr["campaign_id"] = -1
    tr["pyramid_level"] = -1
    cid = -1
    for ts, idx in tr.groupby("entry_ts", sort=True).groups.items():
        rows = tr.loc[idx]
        if (rows["kind"] == "Cmd").any():
            cid += 1
        if cid < 0:
            raise AssertionError(f"lot before first Cmd at {ts}")
        tr.loc[idx, "campaign_id"] = cid
    for cid, idx in tr.groupby("campaign_id", sort=True).groups.items():
        ordered = tr.loc[idx].sort_values(["entry_ts", "kind", "exit_ts"])
        levels = np.arange(len(ordered), dtype=int)
        cmd = ordered["kind"].eq("Cmd").to_numpy()
        if cmd.sum() != 1 or not cmd[0]:
            raise AssertionError(f"campaign {cid} does not start with exactly one Cmd")
        tr.loc[ordered.index, "pyramid_level"] = levels
    return tr.sort_index()


def state_at_decisions(panel: pd.DataFrame, lots: pd.DataFrame) -> pd.DataFrame:
    """All state values are based on exits at or before the decision close."""
    out = panel.sort_values("decision_close_ts").copy()
    events = lots.sort_values("exit_ts").copy()
    events["net"] = events["net"].astype(float)
    exit_ts = events["exit_ts"].to_numpy(dtype="datetime64[ns]")
    nets = events["net"].to_numpy(float)
    is_stop = events["exit_sig"].astype(str).str.contains("SL", case=False, na=False).to_numpy()
    ends = lots.groupby("campaign_id", sort=True).agg(end_ts=("exit_ts", "max"), campaign_net=("net", "sum")).sort_values("end_ts")
    end_ts = ends["end_ts"].to_numpy(dtype="datetime64[ns]")
    cnet = ends["campaign_net"].to_numpy(float)
    last5, last20, streak, mins_stop = [], [], [], []
    for t in out["decision_close_ts"].to_numpy(dtype="datetime64[ns]"):
        j = np.searchsorted(exit_ts, t, side="right")
        last5.append(float(nets[max(0, j - 5):j].sum()))
        last20.append(float(nets[max(0, j - 20):j].sum()))
        k = np.searchsorted(end_ts, t, side="right")
        s = 0
        for value in cnet[:k][::-1]:
            if value <= 0:
                s += 1
            else:
                break
        streak.append(s)
        stop_indices = np.flatnonzero(is_stop[:j])
        if len(stop_indices):
            mins_stop.append((pd.Timestamp(t) - pd.Timestamp(exit_ts[stop_indices[-1]])).total_seconds() / 60.0)
        else:
            mins_stop.append(1_000_000.0)
    out["net_last5_closed"] = last5
    out["net_last20_closed"] = last20
    out["consecutive_losing_campaigns"] = streak
    out["minutes_since_stopout"] = mins_stop
    return out.sort_index()


def build_panel() -> tuple[pd.DataFrame, list[str]]:
    df1 = engine.load_1min(DATA)
    b5 = enrich_5m(df1)
    b60 = enrich_60m(df1)
    daily = enrich_daily()
    lots = pd.read_csv(TRADES, parse_dates=["entry_ts", "exit_ts"])
    lots = assign_campaigns(lots)
    lots["side_long"] = (lots["side"] == "L").astype(int)
    lots["kind_code"] = lots["kind"].map({"Cmd": 0, "Add": 1, "G": 2}).astype(int)
    # The engine's B[i] decision bar is the immediately preceding available
    # 5m bar; after a session/data gap its close need not share the fill label.
    decision = b5.copy()
    decision["entry_ts"] = pd.to_datetime(decision["open_ts"].shift(-1))
    panel = lots.merge(decision, on="entry_ts", how="left", validate="many_to_one", suffixes=("", "_bar"))
    if panel["close_ts"].isna().any():
        raise AssertionError(f"unmatched decision bars: {int(panel['close_ts'].isna().sum())}")
    panel = panel.rename(columns={"close_ts": "decision_close_ts", "open_ts": "decision_open_ts", "close": "decision_close"})
    timing_ok = (panel["decision_close_ts"] <= panel["entry_ts"]) & (panel["decision_open_ts"] < panel["entry_ts"])
    if not timing_ok.all():
        raise AssertionError("a feature row is not the closed bar immediately preceding its fill")
    # Causal 60-minute as-of join: only the last fully closed 60m bar is visible.
    b60_join = b60[["close_ts", "ema50_slope_12_atr", "close_vs_ema50_atr60", "er60_12"]].sort_values("close_ts")
    panel = pd.merge_asof(panel.sort_values("decision_close_ts"), b60_join, left_on="decision_close_ts", right_on="close_ts", direction="backward").drop(columns="close_ts")
    # A TX day session is usable only after 13:45; the rule is supplied verbatim by the task.
    panel["daily_cutoff_date"] = (panel["decision_close_ts"] - pd.Timedelta(hours=13, minutes=45)).dt.normalize()
    dcols = [c for c in daily.columns if c.startswith("daily_")] + ["date"]
    panel = pd.merge_asof(panel.sort_values("daily_cutoff_date"), daily[dcols].sort_values("date"), left_on="daily_cutoff_date", right_on="date", direction="backward").drop(columns="date")
    # Campaign state just before the current next-open fill.
    cmd = panel.loc[panel["kind"] == "Cmd", ["campaign_id", "entry_ts", "entry_px"]].rename(columns={"entry_ts": "cmd_entry_ts", "entry_px": "cmd_entry_px"})
    panel = panel.merge(cmd, on="campaign_id", how="left", validate="many_to_one")
    panel["minutes_since_cmd"] = np.where(panel["kind"].eq("Cmd"), 0.0, (panel["decision_close_ts"] - panel["cmd_entry_ts"]).dt.total_seconds() / 60.0)
    # Use only already-filled, still-open lots from the same campaign at the decision close.
    open_counts, upnls = [], []
    for r in panel.itertuples(index=False):
        if r.kind == "Cmd":
            open_counts.append(0)
            upnls.append(0.0)
            continue
        current = lots.loc[(lots.campaign_id == r.campaign_id) & (lots.entry_ts < r.entry_ts) & (lots.exit_ts > r.decision_close_ts)]
        n_open = len(current)
        open_counts.append(n_open)
        if n_open and np.isfinite(r.atr5_points) and r.atr5_points > 0:
            direction = 1.0 if r.side == "L" else -1.0
            upnls.append(float((r.decision_close - current.entry_px.mean()) * direction / r.atr5_points))
        else:
            upnls.append(np.nan)
    panel["lots_open"] = open_counts
    panel["campaign_unrealized_atr"] = upnls
    t = panel["decision_open_ts"]
    panel["decision_hour"] = t.dt.hour
    panel["session_day"] = panel["session"].eq("day").astype(int)
    day_end = panel["decision_close_ts"].dt.normalize() + pd.Timedelta(hours=13, minutes=45)
    night_end = panel["decision_close_ts"].dt.normalize() + pd.to_timedelta((panel["decision_close_ts"].dt.hour >= 15).astype(int), unit="D") + pd.Timedelta(hours=5)
    session_end = day_end.where(panel["session_day"].eq(1), night_end)
    panel["minutes_to_session_end"] = (session_end - panel["decision_close_ts"]).dt.total_seconds() / 60.0
    panel["weekday"] = t.dt.weekday
    panel = state_at_decisions(panel, lots)
    panel["y_atr_r"] = safe_div(panel["net"], panel["atr5_points"] * 50.0)
    panel["entry_year"] = panel["entry_ts"].dt.year
    panel["exit_year"] = panel["exit_ts"].dt.year
    feature_names = [
        "side_long", "kind_code", "pyramid_level", "minutes_since_cmd", "campaign_unrealized_atr", "lots_open",
        "decision_hour", "session_day", "minutes_to_session_end", "weekday",
        "dist_ema_long_atr", "dist_ema_short_atr", "dist_ema_fast_atr", "atr5_points", "atr5_pct", "atr5_ratio_14_100",
        "er5_12", "er5_48", "ret5_1_atr", "ret5_6_atr", "ret5_12_atr", "ret5_48_atr", "range5_atr", "close_location5", "donchian20_pos",
        "vol_rel_48", "vol_rel_same_clock20", "session_cum_vol_rel20",
        "ema50_slope_12_atr", "close_vs_ema50_atr60", "er60_12",
        "daily_dist_ma20_pct", "daily_dist_ma60_pct", "daily_dist_ma200_pct", "daily_ma60_slope20", "daily_ma200_slope20", "daily_er20", "daily_er60", "daily_adx14", "daily_drawdown120", "daily_range_rel20", "daily_gap_pct",
        "net_last5_closed", "net_last20_closed", "consecutive_losing_campaigns", "minutes_since_stopout",
    ]
    missing = [x for x in feature_names if x not in panel]
    if missing:
        raise AssertionError(f"missing model features: {missing}")
    # Explicit availability audit: every non-target feature has a decision-time definition.
    assert (panel["decision_close_ts"] <= panel["entry_ts"]).all()
    return panel.sort_values(["entry_ts", "exit_ts", "kind"]).reset_index(drop=True), feature_names


def rank_ic(y: pd.Series | np.ndarray, score: pd.Series | np.ndarray) -> float:
    mask = np.isfinite(np.asarray(y, float)) & np.isfinite(np.asarray(score, float))
    if mask.sum() < 3:
        return np.nan
    result = spearmanr(np.asarray(y, float)[mask], np.asarray(score, float)[mask])
    return float(result.statistic) if np.isfinite(result.statistic) else np.nan


def make_model(seed: int) -> lgb.LGBMRegressor:
    return lgb.LGBMRegressor(
        objective="regression", n_estimators=300, learning_rate=0.03, num_leaves=15,
        min_child_samples=200, colsample_bytree=0.70, subsample=0.80, subsample_freq=1,
        reg_lambda=1.0, random_state=seed, n_jobs=-1, verbosity=-1,
    )


def deciles(pred: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, x in pred.groupby("test_year", sort=True):
        z = x.copy()
        z["decile"] = pd.qcut(z["pred_y_atr_r"].rank(method="first"), 10, labels=False) + 1
        for decile, q in z.groupby("decile", sort=True):
            rows.append({"test_year": year, "decile": int(decile), "lots": len(q), "score_min": q.pred_y_atr_r.min(), "score_max": q.pred_y_atr_r.max(), "mean_net": q.net.mean(), "sum_net": q.net.sum(), "mean_y_atr_r": q.y_atr_r.mean()})
    return pd.DataFrame(rows)


def trading_day(ts: pd.Series) -> pd.Series:
    t = pd.to_datetime(ts)
    return t.dt.normalize() + pd.to_timedelta((t.dt.hour >= 15).astype(int), unit="D")


def daily_mdd(lots: pd.DataFrame) -> float:
    if lots.empty:
        return 0.0
    day = lots.assign(day=trading_day(lots["exit_ts"])).groupby("day")["net"].sum().sort_index()
    eq = day.cumsum()
    return float((eq - eq.cummax()).min())


def bottom_drop(pred: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, base in pred.groupby("test_year", sort=True):
        for scope, eligible in (("all", base), ("Add_G", base.loc[base.kind.isin(["Add", "G"])])):
            n_drop = int(np.ceil(len(eligible) * 0.20))
            ids = eligible.nsmallest(n_drop, "pred_y_atr_r").index
            kept = base.drop(index=ids)
            base_net, kept_net = float(base.net.sum()), float(kept.net.sum())
            base_mdd, kept_mdd = daily_mdd(base), daily_mdd(kept)
            rows.append({"test_year": year, "scope": scope, "eligible_lots": len(eligible), "dropped_lots": n_drop,
                         "removed_net": float(base.loc[ids, "net"].sum()), "v28_net": base_net, "net_after_drop": kept_net,
                         "delta_net_vs_v28": kept_net - base_net, "v28_daily_mdd": base_mdd, "daily_mdd_after_drop": kept_mdd,
                         "delta_daily_mdd_vs_v28": kept_mdd - base_mdd})
    return pd.DataFrame(rows)


def quintiles(panel: pd.DataFrame, top5: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, signs = [], []
    periods = {"2020_2023": panel.entry_year.between(2020, 2023), "2024_2026": panel.entry_year.between(2024, 2026)}
    for feature in top5:
        sign_row = {"feature": feature}
        for label, mask in periods.items():
            x = panel.loc[mask, [feature, "net"]].dropna().copy()
            corr = rank_ic(x[feature], x["net"])
            sign_row[f"spearman_feature_net_{label}"] = corr
            if len(x) >= 5:
                x["quintile"] = pd.qcut(x[feature].rank(method="first"), 5, labels=False) + 1
                for q, a in x.groupby("quintile"):
                    rows.append({"feature": feature, "period": label, "quintile": int(q), "lots": len(a), "feature_min": a[feature].min(), "feature_max": a[feature].max(), "feature_mean": a[feature].mean(), "mean_net": a.net.mean(), "sum_net": a.net.sum()})
        a, b = sign_row.get("spearman_feature_net_2020_2023", np.nan), sign_row.get("spearman_feature_net_2024_2026", np.nan)
        sign_row["same_sign"] = bool(np.isfinite(a) and np.isfinite(b) and a * b > 0)
        signs.append(sign_row)
    return pd.DataFrame(rows), pd.DataFrame(signs)


def fmt(v: float, digits: int = 3) -> str:
    return "NA" if not np.isfinite(v) else f"{v:.{digits}f}"


def make_report(panel: pd.DataFrame, ic: pd.DataFrame, drops: pd.DataFrame, placebo: pd.DataFrame,
                shap_imp: pd.DataFrame, quint_signs: pd.DataFrame, real_mean: float, placebo_p95: float,
                pvalue: float, useful: bool) -> str:
    positive = int((ic.ic_spearman > 0).sum())
    ag = drops.loc[drops.scope.eq("Add_G")].copy()
    add_improved = int((ag.delta_net_vs_v28 > 0).sum())
    outcome = "沒有找到可用的進場時點預測；不應據此加上 ML 濾網。" if not useful else "通過事先設定的統計門檻；仍需以實盤路徑回測確認後才可採用。"
    lines = [
        "# V38 v28：ML 歸因（LightGBM + SHAP）",
        "",
        f"**結論：{outcome}**",
        "",
        f"本研究以每筆 lot 的下一根開盤成交前、剛收完的 5 分鐘訊號 bar 建特徵。五項固定門檻中，IC 為正的年份是 {positive}/5（要求至少 4/5），Add/G 剔除預測最低 20% 後淨利改善的年份是 {add_improved}/5（要求至少 4/5）；平均年 IC {fmt(real_mean)}，placebo 年 IC 均值的第 95 百分位為 {fmt(placebo_p95)}，單尾 p 值 {fmt(pvalue)}。",
        "",
        "## 方法與因果性",
        "",
        f"- 面板共有 {len(panel):,} lots；目標為 `net / (ATR14_5m × 50)`，原始 `net` 仍用於所有盈虧與 MDD 報表。",
        "- 對每筆成交，決策列是 engine 的前一個可用 5 分鐘 bar，並逐列 assert `decision_close_ts <= entry_ts` 及 `decision_open_ts < entry_ts`。少數休市/資料間隔會令收盤時間早於下一個成交標籤；仍不會取入場後資料。",
        "- 60 分鐘資料以最後一根 `close_ts <= decision_close_ts` 的 bar as-of 對齊；日線只取 `date <= (decision_close_ts - 13:45).normalize()` 的最後完成日盤。量能的同時段均值與累積量基準都先 shift 一個 session。",
        "- 驗證為擴張式 walk-forward：測試年 2022--2026；訓練只保留 `exit_ts <` 該年 1 月 1 日的 lots。固定 LightGBM（15 leaves、min leaf 200、300 trees、learning rate 0.03、feature fraction 0.70），沒有對測試年調參。",
        "",
        "## 年度 OOS IC",
        "",
        "| 測試年 | 訓練 lots | 測試 lots | Spearman IC | 測試平均 net | 測試總 net |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for r in ic.itertuples(index=False):
        lines.append(f"| {r.test_year} | {r.train_lots:,} | {r.test_lots:,} | {fmt(r.ic_spearman)} | {r.mean_net:.0f} | {r.sum_net:.0f} |")
    lines += [
        "",
        f"平均年度 IC：**{fmt(real_mean)}**；placebo 95th：**{fmt(placebo_p95)}**；實際值在 20 次置換中的單尾 p 值：**{fmt(pvalue)}**。",
        "",
        "## 剔除最低 20% 分數的事後診斷",
        "",
        "以下是把既有 lot 按預測分數剔除後重新加總，**不會重跑策略路徑，忽略持倉/後續訊號的連鎖影響，僅為診斷，不能當作可實作績效。** `ΔMDD > 0` 代表最大回撤較不深。",
        "",
        "| 年 | 範圍 | 剔除 lots | 剔除 lot 的 net | Δnet vs v28 | Δ daily MDD |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for r in drops.itertuples(index=False):
        lines.append(f"| {r.test_year} | {r.scope} | {r.dropped_lots} | {r.removed_net:.0f} | {r.delta_net_vs_v28:.0f} | {r.delta_daily_mdd_vs_v28:.0f} |")
    lines += ["", "## SHAP：OOS 預測的平均絕對貢獻前 15 名", "", "| 排名 | 特徵 | mean |SHAP| |", "|---:|---|---:|"]
    for r in shap_imp.head(15).itertuples(index=False):
        lines.append(f"| {r.rank} | {r.feature} | {r.mean_abs_shap:.6f} |")
    lines += ["", "## 前五項特徵的年代穩定性", "", "| 特徵 | 2020--2023 與 net 的 Spearman | 2024--2026 與 net 的 Spearman | 方向一致？ | 判讀 |", "|---|---:|---:|---|---|"]
    for r in quint_signs.itertuples(index=False):
        if r.same_sign:
            story = "方向一致，但僅是單變量描述，不能單獨證明可交易規則。"
        else:
            story = "no story：兩段樣本方向不一致，不能視為可信經濟訊號。"
        lines.append(f"| {r.feature} | {fmt(r.spearman_feature_net_2020_2023)} | {fmt(r.spearman_feature_net_2024_2026)} | {'是' if r.same_sign else '否'} | {story} |")
    lines += [
        "",
        "## 固定決策門檻",
        "",
        f"- IC > 0：{positive}/5，門檻 ≥4/5。",
        f"- 實際平均 IC > placebo 95th：{fmt(real_mean)} {'>' if real_mean > placebo_p95 else '≤'} {fmt(placebo_p95)}。",
        f"- Add/G 剔除最低 20% 後 Δnet > 0：{add_improved}/5，門檻 ≥4/5。",
        f"- **總判定：{'USEFUL（需進一步完整路徑回測）' if useful else 'NOT USEFUL；依任務規定停止，不把任何 ML 條件寫入 engine。'}**",
        "",
        "對應明細 CSV：`ml_features_panel.csv`、`ml_oos_predictions.csv`、`ml_ic_year.csv`、`ml_deciles.csv`、`ml_bottom20_diagnostic.csv`、`ml_placebo.csv`、`ml_shap_importance.csv`、`ml_feature_quintiles.csv`、`ml_feature_quintile_signs.csv`。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    panel, features = build_panel()
    # Keep identity/timing/target columns plus every raw feature for reproducibility.
    panel.to_csv(HERE / "ml_features_panel.csv", index=False, encoding="utf-8")
    all_preds, ic_rows, models = [], [], {}
    for year in OUT_YEARS:
        cut = pd.Timestamp(year=year, month=1, day=1)
        train = panel.loc[panel.exit_ts < cut].copy()
        test = panel.loc[panel.entry_year.eq(year)].copy()
        model = make_model(SEED + year)
        model.fit(train[features], train["y_atr_r"], categorical_feature=["kind_code"])
        test["pred_y_atr_r"] = model.predict(test[features])
        test["test_year"] = year
        all_preds.append(test)
        models[year] = model
        ic_rows.append({"test_year": year, "train_lots": len(train), "test_lots": len(test), "ic_spearman": rank_ic(test.y_atr_r, test.pred_y_atr_r), "mean_net": test.net.mean(), "sum_net": test.net.sum(), "mean_y_atr_r": test.y_atr_r.mean()})
    pred = pd.concat(all_preds, ignore_index=True)
    ic = pd.DataFrame(ic_rows)
    pred.to_csv(HERE / "ml_oos_predictions.csv", index=False, encoding="utf-8")
    ic.to_csv(HERE / "ml_ic_year.csv", index=False, encoding="utf-8")
    dtable = deciles(pred)
    dtable.to_csv(HERE / "ml_deciles.csv", index=False, encoding="utf-8")
    drops = bottom_drop(pred)
    drops.to_csv(HERE / "ml_bottom20_diagnostic.csv", index=False, encoding="utf-8")
    # 20 whole walk-forward placebo runs, shuffling labels independently inside each training set.
    placebo_rows, placebo_means, placebo_pool = [], [], []
    for run in range(1, 21):
        per_year, pieces = [], []
        for year in OUT_YEARS:
            cut = pd.Timestamp(year=year, month=1, day=1)
            train = panel.loc[panel.exit_ts < cut].copy()
            test = panel.loc[panel.entry_year.eq(year)].copy()
            rng = np.random.default_rng(SEED + run * 100 + year)
            shuffled_y = rng.permutation(train["y_atr_r"].to_numpy())
            model = make_model(SEED + run * 1000 + year)
            model.fit(train[features], shuffled_y, categorical_feature=["kind_code"])
            score = model.predict(test[features])
            value = rank_ic(test.y_atr_r, score)
            per_year.append(value)
            pieces.append(pd.DataFrame({"y": test.y_atr_r.to_numpy(), "score": score}))
            placebo_rows.append({"run": run, "test_year": year, "aggregate": "year", "ic_spearman": value})
        mean_ic = float(np.nanmean(per_year))
        pooled_ic = rank_ic(pd.concat(pieces).y, pd.concat(pieces).score)
        placebo_means.append(mean_ic)
        placebo_pool.append(pooled_ic)
        placebo_rows.extend([
            {"run": run, "test_year": "all", "aggregate": "mean_annual", "ic_spearman": mean_ic},
            {"run": run, "test_year": "all", "aggregate": "pooled", "ic_spearman": pooled_ic},
        ])
    placebo = pd.DataFrame(placebo_rows)
    placebo.to_csv(HERE / "ml_placebo.csv", index=False, encoding="utf-8")
    # SHAP values come from the model that genuinely made each OOS prediction.
    shap_parts = []
    for year, x in pred.groupby("test_year", sort=True):
        vals = shap.TreeExplainer(models[int(year)]).shap_values(x[features])
        shap_parts.append(pd.DataFrame(np.asarray(vals), columns=features, index=x.index))
    shap_values = pd.concat(shap_parts).reindex(pred.index)
    imp = pd.DataFrame({"feature": features, "mean_abs_shap": shap_values.abs().mean().to_numpy()}).sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)
    imp.insert(0, "rank", np.arange(1, len(imp) + 1))
    imp.to_csv(HERE / "ml_shap_importance.csv", index=False, encoding="utf-8")
    quint, qsigns = quintiles(panel, imp.head(5).feature.tolist())
    quint.to_csv(HERE / "ml_feature_quintiles.csv", index=False, encoding="utf-8")
    qsigns.to_csv(HERE / "ml_feature_quintile_signs.csv", index=False, encoding="utf-8")
    real_mean = float(ic.ic_spearman.mean())
    placebo_p95 = float(np.quantile(placebo_means, 0.95))
    real_pooled = rank_ic(pred.y_atr_r, pred.pred_y_atr_r)
    pvalue = float((1 + np.sum(np.asarray(placebo_means) >= real_mean)) / (len(placebo_means) + 1))
    useful = bool((ic.ic_spearman > 0).sum() >= 4 and real_mean > placebo_p95 and (drops.loc[drops.scope.eq("Add_G"), "delta_net_vs_v28"] > 0).sum() >= 4)
    summary = pd.DataFrame([{
        "real_mean_annual_ic": real_mean, "real_pooled_ic": real_pooled, "placebo_mean_annual_ic_p95": placebo_p95,
        "placebo_mean_annual_ic_mean": float(np.mean(placebo_means)), "placebo_pooled_ic_p95": float(np.quantile(placebo_pool, 0.95)),
        "one_sided_pvalue_mean_ic": pvalue, "positive_ic_years": int((ic.ic_spearman > 0).sum()),
        "improved_addg_years": int((drops.loc[drops.scope.eq("Add_G"), "delta_net_vs_v28"] > 0).sum()), "useful": useful,
    }])
    summary.to_csv(HERE / "ml_summary.csv", index=False, encoding="utf-8")
    if useful:
        # This branch has not been pre-authorised to invent a post-hoc engine rule.
        # The report makes the condition explicit instead of silently claiming a path run.
        raise RuntimeError("Useful gate unexpectedly met; stop before selecting a post-hoc threshold. A dedicated causal wrapper is required.")
    report = make_report(panel, ic, drops, placebo, imp, qsigns, real_mean, placebo_p95, pvalue, useful)
    (HERE / "results_ml_attrib.md").write_text(report, encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        (HERE / "ml_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
