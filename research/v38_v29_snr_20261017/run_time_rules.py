"""Reproducible V38 time-of-day and holding-boundary study.

Uses the untouched upstream engine through ``engine_time_wrapper``.  This
script writes machine-readable CSVs plus the requested Traditional-Chinese
report.  Python is intentionally run via the project virtual environment.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

import engine_time_wrapper as eng


HERE = Path(__file__).resolve().parent
DATA = HERE / "mxf_1min_corrected_20261017b.csv"
OUT = HERE / "results_time.md"
TRADE_COLS = ["side", "kind", "entry_ts", "entry_px", "exit_ts", "exit_px", "exit_sig", "pnl"]
LIVE = {"opt_stale_hr": 10, "opt_cooldown_min": 30}
BASES = {
    "v28": {**LIVE, "opt_short_pyramid_cap_mode": "hour4"},
    "v29": {**LIVE, "opt_short_pyramid_cap_mode": "hour4", "l_trailBase": 3.5},
}
VARIANTS = {
    "base": {"name": "base", "block": "none", "force": "none"},
    "h4_noCmd": {"name": "h4_noCmd", "block": "h4_cmd", "force": "none"},
    "h4_noAll": {"name": "h4_noAll", "block": "h4_all", "force": "none"},
    "h4_noAll_shortOnly": {"name": "h4_noAll_shortOnly", "block": "h4_all_short", "force": "none"},
    "sat_h4_noCmd": {"name": "sat_h4_noCmd", "block": "sat_h4_cmd", "force": "none"},
    "sat_h4_noAll": {"name": "sat_h4_noAll", "block": "sat_h4_all", "force": "none"},
    "sat_h3h4_noAll": {"name": "sat_h3h4_noAll", "block": "sat_h3h4_all", "force": "none"},
    "flat_weekend": {"name": "flat_weekend", "block": "sat_h4_all", "force": "sat_05"},
    "flat_any_gap48": {"name": "flat_any_gap48", "block": "pre_gap48_hour", "force": "gap48"},
    "flat_fri_day": {"name": "flat_fri_day", "block": "fri_to_mon", "force": "fri_1345"},
    "flat_daily_night_end": {"name": "flat_daily_night_end", "block": "night_end", "force": "night_05"},
    "flat_daily_day_end": {"name": "flat_daily_day_end", "block": "day_end", "force": "day_1345"},
}
FORCED = {k for k, v in VARIANTS.items() if v["force"] != "none"}
SPLITS = ("full", "H1", "H2", "TRAIN", "TEST", "HOLDOUT", "2024", "2025", "2026")
H2 = pd.Timestamp("2025-04-01")
TRAIN = pd.Timestamp("2026-03-01")
TEST = pd.Timestamp("2026-06-01")
HOLDOUT = pd.Timestamp("2026-08-22")
WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]


def split_mask(d: pd.DataFrame, split: str) -> pd.Series:
    t = d.entry_ts
    if split == "full":
        return pd.Series(True, index=d.index)
    if split == "H1":
        return t < H2
    if split == "H2":
        return t >= H2
    if split == "TRAIN":
        return (t >= TRAIN) & (t < TEST)
    if split == "TEST":
        return (t >= TEST) & (t < HOLDOUT)
    if split == "HOLDOUT":
        return t >= HOLDOUT
    return t.dt.year == int(split)


def metrics(d: pd.DataFrame) -> dict[str, float | int]:
    if d.empty:
        return {"n": 0, "wr": np.nan, "net": 0.0, "pf": np.nan, "mdd": 0.0, "net_mdd": np.nan}
    wins = d[d.pnl > 0]
    losses = d[d.pnl <= 0]
    gp = float(wins.pnl.sum())
    gl = float(-losses.pnl.sum())
    equity = d.groupby("exit_ts", sort=True).pnl.sum().cumsum()
    mdd = float((equity - equity.cummax()).min())
    net = float(d.pnl.sum())
    return {
        "n": int(len(d)), "wr": 100 * len(wins) / len(d), "net": net,
        "pf": gp / gl if gl else np.inf, "mdd": mdd,
        "net_mdd": net / abs(mdd) if mdd else np.inf,
    }


def all_metrics(d: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    return {split: metrics(d.loc[split_mask(d, split)].copy()) for split in SPLITS}


def fmt_num(v: object, dec: int = 0) -> str:
    if pd.isna(v):
        return "—"
    if isinstance(v, (float, np.floating)) and np.isinf(v):
        return "∞"
    return f"{float(v):,.{dec}f}" if isinstance(v, (float, np.floating, int, np.integer)) else str(v)


def md_table(d: pd.DataFrame, columns: list[str]) -> list[str]:
    if d.empty:
        return ["（無資料）"]
    out = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in d.loc[:, columns].itertuples(index=False, name=None):
        vals = []
        for x in row:
            if isinstance(x, (float, np.floating)):
                vals.append(fmt_num(x, 2))
            else:
                vals.append(str(x))
        out.append("| " + " | ".join(vals) + " |")
    return out


def enrich_times(d: pd.DataFrame) -> pd.DataFrame:
    x = d.copy()
    x["entry_ts"] = pd.to_datetime(x.entry_ts)
    x["exit_ts"] = pd.to_datetime(x.exit_ts)
    x["entry_hour"] = x.entry_ts.dt.hour
    x["calendar_wd"] = x.entry_ts.dt.weekday
    # 00:00--04:59 belongs to the night session started on the previous date.
    x["session_date"] = x.entry_ts.dt.normalize() - pd.to_timedelta((x.entry_ts.dt.hour < 5).astype(int), unit="D")
    x["session_wd"] = x.session_date.dt.weekday
    return x


def loss_severity(d: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    losers = d[d.pnl <= 0]
    if losers.empty:
        return pd.DataFrame(columns=groups + ["net", "n", "wr", "loss_share", "count_share", "severity"])
    total_loss = -losers.pnl.sum()
    total_count = len(losers)
    full = d.groupby(groups, dropna=False).agg(net=("pnl", "sum"), n=("pnl", "size"), wr=("pnl", lambda z: 100 * (z > 0).mean())).reset_index()
    bad = losers.groupby(groups, dropna=False).agg(loss_dollars=("pnl", lambda z: -z.sum()), loss_n=("pnl", "size")).reset_index()
    ans = full.merge(bad, on=groups, how="left").fillna({"loss_dollars": 0, "loss_n": 0})
    ans["loss_share"] = ans.loss_dollars / total_loss if total_loss else np.nan
    ans["count_share"] = ans.loss_n / total_count if total_count else np.nan
    ans["severity"] = ans.loss_share / ans.count_share.replace(0, np.nan)
    return ans


def diagnostics(runs: dict[tuple[str, str], pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    full, h4 = [], []
    for base in BASES:
        d = enrich_times(runs[(base, "base")])
        tab = loss_severity(d, ["entry_hour", "calendar_wd", "session_wd"])
        tab.insert(0, "base", base)
        full.append(tab)
        z = d[d.entry_hour == 4]
        tab2 = loss_severity(z, ["side", "kind"])
        tab2.insert(0, "base", base)
        h4.append(tab2)
    all_hours = pd.concat(full, ignore_index=True)
    h4_detail = pd.concat(h4, ignore_index=True)
    focus = all_hours[all_hours.entry_hour.isin([3, 4])].copy()
    for col in ("calendar_wd", "session_wd"):
        focus[col] = focus[col].map(lambda n: WEEKDAY_ZH[int(n)])
    return all_hours, focus, h4_detail


def saturday_h3h4_compare(hour_table: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the detailed table into the requested Saturday-AM comparison."""
    z = hour_table[hour_table.entry_hour.isin([3, 4])].copy()
    z["calendar_group"] = np.where(z.calendar_wd.eq(5), "週六凌晨（週五夜盤）", "其他日")
    z["win_count"] = z.n * z.wr / 100
    out = z.groupby(["base", "entry_hour", "calendar_group"], as_index=False).agg(
        n=("n", "sum"), net=("net", "sum"), win_count=("win_count", "sum"),
        loss_dollars=("loss_dollars", "sum"), loss_n=("loss_n", "sum"),
    )
    out["wr"] = 100 * out.win_count / out.n
    denom = hour_table.groupby("base", as_index=False).agg(
        all_loss_dollars=("loss_dollars", "sum"), all_loss_n=("loss_n", "sum"))
    out = out.merge(denom, on="base", how="left")
    out["loss_share"] = out.loss_dollars / out.all_loss_dollars
    out["count_share"] = out.loss_n / out.all_loss_n
    out["severity"] = out.loss_share / out.count_share.replace(0, np.nan)
    return out.drop(columns=["win_count", "loss_dollars", "loss_n", "all_loss_dollars", "all_loss_n"])


def classify_boundaries(df1m: pd.DataFrame) -> list[dict[str, object]]:
    d = df1m.sort_values("open_ts").reset_index(drop=True)
    next_open = d.open_ts.shift(-1)
    last_close = d.ts
    is_last = next_open.notna() & (next_open > last_close)
    events: list[dict[str, object]] = []
    for i in np.flatnonzero(is_last.to_numpy()):
        close_t, open_t = last_close.iat[i], next_open.iat[i]
        close_q, open_q = pd.Timestamp(close_t), pd.Timestamp(open_t)
        labels = []
        if close_q.weekday() == 5 and close_q.hour == 5 and close_q.minute == 0 and open_q.weekday() == 0:
            labels.append("週末 Sat05→Mon")
        if open_t - close_t >= pd.Timedelta(hours=48):
            labels.append("所有>=48h缺口")
            if not (close_q.weekday() == 5 and open_q.weekday() == 0):
                labels.append("假日>=48h（非週末）")
        if close_q.hour == 5 and close_q.minute == 0 and open_q.hour == 8 and open_q.minute == 45:
            labels.append("夜→日 05→08:45")
        if close_q.hour == 13 and close_q.minute == 45 and open_q.hour == 15 and open_q.minute == 0:
            labels.append("日→夜 13:45→15")
        for label in labels:
            events.append({"boundary": label, "last_close_ts": close_t, "next_open_ts": open_t,
                           "last_close_px": float(d.close.iat[i]), "next_open_px": float(d.open.iat[i + 1]),
                           "gap_hours": (open_t - close_t) / pd.Timedelta(hours=1)})
    return events


def boundary_attribution(trades: pd.DataFrame, events: list[dict[str, object]], base: str) -> pd.DataFrame:
    rows = []
    for e in events:
        # entry before the next session and exit at/after its first open means
        # that the lot was genuinely exposed to that intervening price gap.
        z = trades[(trades.entry_ts < e["next_open_ts"]) & (trades.exit_ts >= e["next_open_ts"])].copy()
        if z.empty:
            rows.append({"base": base, **e, "lots_open": 0, "gap_pnl": 0.0, "total_lot_pnl": 0.0})
            continue
        direction = np.where(z.side.eq("L"), 1.0, -1.0)
        gap_pnl = (float(e["next_open_px"]) - float(e["last_close_px"])) * direction * eng.POINT_VALUE
        rows.append({"base": base, **e, "lots_open": len(z), "gap_pnl": float(gap_pnl.sum()),
                     "total_lot_pnl": float(z.pnl.sum())})
    detail = pd.DataFrame(rows)
    return detail.groupby(["base", "boundary"], as_index=False).agg(
        boundary_events=("last_close_ts", "size"), lots_open=("lots_open", "sum"),
        gap_pnl=("gap_pnl", "sum"), total_lot_pnl=("total_lot_pnl", "sum"),
    )


def block_predicate(variant: str) -> Callable[[pd.DataFrame], pd.Series]:
    def f(d: pd.DataFrame) -> pd.Series:
        t, hour, wd = d.entry_ts, d.entry_ts.dt.hour, d.entry_ts.dt.weekday
        if variant == "h4_noCmd": return (hour == 4) & d.kind.eq("Cmd")
        if variant == "h4_noAll": return hour == 4
        if variant == "h4_noAll_shortOnly": return (hour == 4) & d.side.eq("S")
        if variant == "sat_h4_noCmd": return (wd == 5) & (hour == 4) & d.kind.eq("Cmd")
        if variant == "sat_h4_noAll": return (wd == 5) & (hour == 4)
        if variant == "sat_h3h4_noAll": return (wd == 5) & hour.isin([3, 4])
        raise ValueError(variant)
    return f


def precision_checks(runs: dict[tuple[str, str], pd.DataFrame]) -> pd.DataFrame:
    rows = []
    entry_variants = [x for x in VARIANTS if x.startswith("h4_") or x.startswith("sat_")]
    for base in BASES:
        d = enrich_times(runs[(base, "base")])
        total_loss = -d.loc[d.pnl <= 0, "pnl"].sum()
        total_profit = d.loc[d.pnl > 0, "pnl"].sum()
        for variant in entry_variants:
            z = d.loc[block_predicate(variant)(d)]
            removed_loss = -z.loc[z.pnl <= 0, "pnl"].sum()
            removed_profit = z.loc[z.pnl > 0, "pnl"].sum()
            ls = removed_loss / total_loss if total_loss else np.nan
            ps = removed_profit / total_profit if total_profit else np.nan
            rows.append({"base": base, "variant": variant, "direct_blocked_lots": len(z),
                         "direct_blocked_net": z.pnl.sum(), "loss_removed": removed_loss,
                         "loss_share": ls, "profit_removed": removed_profit, "profit_share": ps,
                         "precision_loss_profit": ls / ps if ps else np.inf})
    return pd.DataFrame(rows)


def forced_report(trades: pd.DataFrame, audit: list[dict[str, object]], df1m: pd.DataFrame,
                  base: str, variant: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not audit:
        empty = pd.DataFrame(columns=["base", "variant", "forced_lots", "forced_pnl", "gap_move_avoided"])
        return empty, trades.copy()
    mins = df1m.sort_values("open_ts").set_index("open_ts")
    forced_keys = set()
    rows = []
    for a in audit:
        key = (pd.Timestamp(a["entry_ts"]), pd.Timestamp(a["exit_ts"]), a["side"], a["kind"], a["reason"])
        forced_keys.add(key)
        later = mins[mins.index > pd.Timestamp(a["exit_ts"])]
        if later.empty:
            next_open, next_px = pd.NaT, np.nan
        else:
            next_open, next_px = later.index[0], float(later.open.iat[0])
        direct = (next_px - float(a["fill_px"])) * (1 if a["side"] == "L" else -1) * eng.POINT_VALUE if pd.notna(next_px) else np.nan
        rows.append({"base": base, "variant": variant, "entry_ts": a["entry_ts"], "exit_ts": a["exit_ts"],
                     "side": a["side"], "kind": a["kind"], "reason": a["reason"], "fill_px": a["fill_px"],
                     "next_open_ts": next_open, "next_open_px": next_px, "gap_move_avoided": direct})
    detail = pd.DataFrame(rows)
    # The price/entry/kind tuple identifies each lot uniquely for these engine
    # outputs; use the report's actual forced exit signal as a final guard.
    is_forced = trades.apply(lambda r: (r.entry_ts, r.exit_ts, r.side, r.kind, r.exit_sig) in forced_keys, axis=1)
    slip = trades.copy()
    slip.loc[is_forced, "pnl"] -= 2 * eng.POINT_VALUE
    summary = pd.DataFrame([{"base": base, "variant": variant, "forced_lots": int(is_forced.sum()),
                             "forced_pnl": float(trades.loc[is_forced, "pnl"].sum()),
                             "gap_move_avoided": float(detail.gap_move_avoided.sum()),
                             "next_gap_hours_median": float((detail.next_open_ts - detail.exit_ts).dt.total_seconds().median() / 3600)}])
    return summary, slip


def make_metric_rows(runs: dict[tuple[str, str], pd.DataFrame], slips: dict[tuple[str, str], pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, slip_rows = [], []
    for base in BASES:
        base_m = all_metrics(runs[(base, "base")])
        for variant in VARIANTS:
            mset = all_metrics(runs[(base, variant)])
            strict = variant != "base" and all(mset[x]["net"] > base_m[x]["net"] for x in ("H1", "H2", "TRAIN", "TEST"))
            full_risk = variant != "base" and abs(mset["full"]["mdd"]) <= .9 * abs(base_m["full"]["mdd"]) and mset["full"]["net"] - base_m["full"]["net"] >= -.05 * abs(base_m["full"]["net"])
            verdict = "BASE" if variant == "base" else "PASS" if strict else "RISK-ONLY" if full_risk else "FAIL"
            for split in SPLITS:
                m, b = mset[split], base_m[split]
                rows.append({"base": base, "variant": variant, "split": split, **m,
                             "net_delta": m["net"] - b["net"], "mdd_delta": abs(m["mdd"]) - abs(b["mdd"]),
                             "verdict": verdict})
            if variant in FORCED:
                sm = all_metrics(slips[(base, variant)])
                for split in SPLITS:
                    m = sm[split]
                    slip_rows.append({"base": base, "variant": variant, "split": split, **m,
                                      "net_delta": m["net"] - base_m[split]["net"]})
    return pd.DataFrame(rows), pd.DataFrame(slip_rows)


def net_at(tab: pd.DataFrame, base: str, variant: str, split: str = "full") -> float:
    return float(tab[(tab.base == base) & (tab.variant == variant) & (tab.split == split)].net.iloc[0])


def verdict_at(tab: pd.DataFrame, base: str, variant: str) -> str:
    return str(tab[(tab.base == base) & (tab.variant == variant)].verdict.iloc[0])


def render(metrics_tab: pd.DataFrame, slip_tab: pd.DataFrame, diagnostic_all: pd.DataFrame, diagnostic_focus: pd.DataFrame, sat_compare: pd.DataFrame,
           h4_detail: pd.DataFrame, boundaries: pd.DataFrame, precision: pd.DataFrame,
           forced: pd.DataFrame, exact: pd.DataFrame, gap_calendar: pd.DataFrame) -> None:
    def status_pair(variant: str) -> str:
        return "；".join(f"{b}={verdict_at(metrics_tab, b, variant)}" for b in BASES)
    h4_pass = [v for v in ("h4_noCmd", "h4_noAll", "h4_noAll_shortOnly") if any(verdict_at(metrics_tab, b, v) == "PASS" for b in BASES)]
    fri_pass = [v for v in ("sat_h4_noCmd", "sat_h4_noAll", "sat_h3h4_noAll") if any(verdict_at(metrics_tab, b, v) == "PASS" for b in BASES)]
    hold_pass = [v for v in FORCED if any(verdict_at(metrics_tab, b, v) == "PASS" for b in BASES)]
    lines = [
        "# V38 時段、週五夜盤與跨盤持有規則研究",
        "",
        "## 執行摘要",
        "",
        f"- 資料截至 2026-10-17 05:00；所有回測均為 `intrabar_mode=\"1min\"`、`opt_stale_hr=10`、`opt_cooldown_min=30`。",
        f"- Gate-off 精確複現：{'; '.join(f'{r.base}={r.status}' for r in exact.itertuples())}（與參考檔共同期間逐欄逐值比對）。",
        f"- **每天 04:00 全面停做：{'可考慮' if h4_pass else '不建議'}**；三個預先宣告版本的嚴格判定為：{'; '.join(f'{v}({status_pair(v)})' for v in ('h4_noCmd','h4_noAll','h4_noAll_shortOnly'))}。",
        f"- **僅週五夜盤（週六 03/04 時）停做：{'可考慮' if fri_pass else '不建議'}**；{'; '.join(f'{v}({status_pair(v)})' for v in ('sat_h4_noCmd','sat_h4_noAll','sat_h3h4_noAll'))}。",
        f"- **避免週末／假日跨盤：{'有嚴格支持' if any(v in hold_pass for v in ('flat_weekend','flat_any_gap48','flat_fri_day')) else '沒有嚴格支持'}**；週末={status_pair('flat_weekend')}，>=48h={status_pair('flat_any_gap48')}，週五日盤平倉={status_pair('flat_fri_day')}。",
        f"- **不建議例行隔夜全平**（夜→日={status_pair('flat_daily_night_end')}；日→夜={status_pair('flat_daily_day_end')}），除非其僅作風險偏好調整而非報酬優化。",
        "- PASS 的定義是 H1、H2、TRAIN、TEST 四個獨立檢核期淨利增量皆 >0；HOLDOUT 僅呈現、未參與選擇。RISK-ONLY 是全樣本 MDD 至少改善 10%、且淨利退步不超過基準淨利的 5%。",
        "- 強平在指定 5 分鐘 bar 收盤成交、立即清空倉位與待進場單；其後只能由新訊號重新進場，且沒有額外套用 cooldown。",
        "- 強平的 +2 點滑價敏感度以每口 -100 元重算；它只影響強平口的成交損益，不改變訊號、部位或後續進場路徑。",
        "- 這是 11 個變體 × 2 個基準的多重比較，個別正結果仍可能是偶然；不應以 HOLDOUT 成績回頭挑參數。",
        "",
        "## 回歸與交易日曆",
        "",
    ]
    lines += md_table(exact, ["base", "reference_lots", "fresh_lots", "overlap_end", "status"])
    lines += ["", "由資料推導的 >=48 小時缺口（僅交易所日曆時間戳，未使用未來價格）：", ""]
    lines += md_table(gap_calendar, ["last_close_ts", "next_open_ts", "gap_hours"])
    lines += ["", "## Step 1：基準交易診斷", "", "### H3/H4 × 日曆星期／session 交易日星期", ""]
    lines += md_table(diagnostic_focus, ["base", "entry_hour", "calendar_wd", "session_wd", "n", "wr", "net", "loss_share", "count_share", "severity"])
    lines += ["", "註：凌晨 00:00–04:59 的 session 交易日歸屬前一日；故週六凌晨是週五 night session。loss/count share 的分母皆為該基準所有虧損口數／虧損金額。", "", "### 週六凌晨（週五夜盤）相對其他日", ""]
    lines += md_table(sat_compare, ["base", "entry_hour", "calendar_group", "n", "wr", "net", "loss_share", "count_share", "severity"])
    lines += ["", "此比較的 severity 分母同樣是各基準全部虧損；規則中的 `sat_*` 以實際 calendar Saturday 03:00–04:59 的 entry timestamp 套用。", ""]
    all_hours = diagnostic_all.copy()
    for col in ("calendar_wd", "session_wd"):
        all_hours[col] = all_hours[col].map(lambda n: WEEKDAY_ZH[int(n)])
    lines += ["<details>", "<summary>完整 entry hour × 日曆星期 × session 交易日星期診斷</summary>", ""]
    lines += md_table(all_hours, ["base", "entry_hour", "calendar_wd", "session_wd", "n", "wr", "net", "loss_share", "count_share", "severity"])
    lines += ["", "</details>", "", "### H4 的 side × kind", ""]
    lines += md_table(h4_detail, ["base", "side", "kind", "n", "wr", "net", "loss_share", "count_share", "severity"])
    lines += ["", "完整資料也另存 `time_hour_weekday_diagnostics.csv`。", "", "### 持倉跨越邊界的損益歸因", ""]
    lines += md_table(boundaries, ["base", "boundary", "boundary_events", "lots_open", "gap_pnl", "total_lot_pnl"])
    lines += ["", "gap_pnl = 最後一根缺口前 1 分鐘收盤到缺口後第一根 1 分鐘開盤的價格變動 × 方向 × 50；不含手續費。類別可以重疊（例如週末同時屬於 >=48h 與夜→日）。", "", "## Step 2：所有變體績效", "", "表內 MDD 以該 entry cohort 的 exit-time 損益曲線計算；Δ 一律相對同一 base、同一列 cohort。", ""]
    display = metrics_tab.copy()
    display["wr"] = display.wr.map(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
    display["pf"] = display.pf.map(lambda x: "∞" if np.isinf(x) else f"{x:.2f}" if pd.notna(x) else "—")
    for c in ("net", "mdd", "net_mdd", "net_delta", "mdd_delta"):
        display[c] = display[c].map(lambda x: fmt_num(x, 2 if c == "net_mdd" else 0))
    lines += md_table(display, ["base", "variant", "split", "n", "wr", "net", "pf", "mdd", "net_mdd", "net_delta", "mdd_delta", "verdict"])
    lines += ["", "### Entry-block precision check（直接被擋下的基準口，非全引擎反事實）", ""]
    p = precision.copy()
    for c in ("loss_share", "profit_share"):
        p[c] = p[c].map(lambda x: f"{x:.1%}" if pd.notna(x) else "—")
    p["precision_loss_profit"] = p.precision_loss_profit.map(lambda x: "∞" if np.isinf(x) else f"{x:.2f}x")
    for c in ("direct_blocked_net", "loss_removed", "profit_removed"):
        p[c] = p[c].map(lambda x: fmt_num(x, 0))
    lines += md_table(p, ["base", "variant", "direct_blocked_lots", "direct_blocked_net", "loss_removed", "loss_share", "profit_removed", "profit_share", "precision_loss_profit"])
    lines += ["", "精度比 >1 表示擋掉的虧損占全部虧損的比率大於一併犧牲的獲利占全部獲利的比率；這是定位準確度，非完整策略增益證明。", "", "### 強平摘要與避免的第一段缺口價格變動", ""]
    f = forced.copy()
    for c in ("forced_pnl", "gap_move_avoided"):
        f[c] = f[c].map(lambda x: fmt_num(x, 0))
    f["next_gap_hours_median"] = f.next_gap_hours_median.map(lambda x: fmt_num(x, 2))
    lines += md_table(f, ["base", "variant", "forced_lots", "forced_pnl", "gap_move_avoided", "next_gap_hours_median"])
    lines += ["", "強平避免的 gap move 是每口強平後到資料中下一根可交易分鐘 bar 開盤之方向性價格變動 × 50；它是曝險描述，不能直接等同策略淨利增量。", "", "### 強平 +2 點／口滑價敏感度", ""]
    sd = slip_tab.copy()
    sd["wr"] = sd.wr.map(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
    sd["pf"] = sd.pf.map(lambda x: "∞" if np.isinf(x) else f"{x:.2f}" if pd.notna(x) else "—")
    for c in ("net", "mdd", "net_mdd", "net_delta"):
        sd[c] = sd[c].map(lambda x: fmt_num(x, 2 if c == "net_mdd" else 0))
    lines += md_table(sd, ["base", "variant", "split", "n", "wr", "net", "pf", "mdd", "net_mdd", "net_delta"])
    lines += ["", "## 檔案與限制", "", "- `engine_time_wrapper.py` 是本研究唯一的 engine wrapper；原始 `engine_v26_bbw.py` 未修改。",
             "- `time_variant_metrics.csv`、`time_force_slippage_metrics.csv`、`time_forced_close_detail.csv`、`time_holding_boundaries.csv` 與 `time_hour_weekday_diagnostics.csv` 保存完整可篩選數字。",
             "- 日曆缺口的識別允許使用已知交易日曆，但所有策略訊號仍是逐 bar 因果計算；這不保證實盤能以收盤價完成所有強平。", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    df1m = eng.load_1min(DATA)
    print(f"loaded {len(df1m):,} one-minute bars", flush=True)
    runs: dict[tuple[str, str], pd.DataFrame] = {}
    audits: dict[tuple[str, str], list[dict[str, object]]] = {}
    for base, p in BASES.items():
        for variant, rules in VARIANTS.items():
            print(f"run {base} / {variant}", flush=True)
            tr = eng.run(df1m, p={**p, "opt_time_rules": rules}, intrabar_mode="1min")
            tr = enrich_times(tr)
            audits[(base, variant)] = tr.attrs.get("time_forced_closes", [])
            runs[(base, variant)] = tr
    # Exact regression only over the period both the reference logs and the
    # new data cover.  Full study keeps the additional current 05:00 data.
    exact_rows = []
    for base, p in BASES.items():
        ref = enrich_times(pd.read_csv(HERE / f"trades_{base}.csv", parse_dates=["entry_ts", "exit_ts"]))
        cut = ref.exit_ts.max()
        overlap = df1m[df1m.ts <= cut].copy()
        fresh = eng.run(overlap, p={**p, "opt_time_rules": VARIANTS["base"]}, intrabar_mode="1min")
        fresh = enrich_times(fresh)
        try:
            pd.testing.assert_frame_equal(fresh[TRADE_COLS].reset_index(drop=True), ref[TRADE_COLS].reset_index(drop=True), check_dtype=False, check_exact=True)
            status = "PASS（逐欄精確一致）"
        except AssertionError as exc:
            status = "FAIL: " + str(exc).replace("\n", " ")[:180]
        exact_rows.append({"base": base, "reference_lots": len(ref), "fresh_lots": len(fresh), "overlap_end": str(cut), "status": status})
    exact = pd.DataFrame(exact_rows)
    events = classify_boundaries(df1m)
    boundary = pd.concat([boundary_attribution(runs[(base, "base")], events, base) for base in BASES], ignore_index=True)
    hour_all, hour_focus, h4_detail = diagnostics(runs)
    precision = precision_checks(runs)
    forced_summaries, forced_details, slips = [], [], {}
    for base in BASES:
        for variant in FORCED:
            fs, slip = forced_report(runs[(base, variant)], audits[(base, variant)], df1m, base, variant)
            forced_summaries.append(fs)
            slips[(base, variant)] = slip
            # reconstruct detailed records separately for audit CSV
            # (the compact summary above is the report-facing requirement).
            if audits[(base, variant)]:
                for rec in audits[(base, variant)]:
                    forced_details.append({"base": base, "variant": variant, **rec})
    forced = pd.concat(forced_summaries, ignore_index=True)
    metric_tab, slip_tab = make_metric_rows(runs, slips)
    gap_calendar = pd.DataFrame([e for e in events if e["boundary"] == "所有>=48h缺口"])[["last_close_ts", "next_open_ts", "gap_hours"]]
    # Persist data first: report generation is deliberately pure formatting.
    metric_tab.to_csv(HERE / "time_variant_metrics.csv", index=False, encoding="utf-8-sig")
    slip_tab.to_csv(HERE / "time_force_slippage_metrics.csv", index=False, encoding="utf-8-sig")
    hour_all.to_csv(HERE / "time_hour_weekday_diagnostics.csv", index=False, encoding="utf-8-sig")
    h4_detail.to_csv(HERE / "time_h4_side_kind.csv", index=False, encoding="utf-8-sig")
    boundary.to_csv(HERE / "time_holding_boundaries.csv", index=False, encoding="utf-8-sig")
    precision.to_csv(HERE / "time_entry_block_precision.csv", index=False, encoding="utf-8-sig")
    forced.to_csv(HERE / "time_forced_close_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(forced_details).to_csv(HERE / "time_forced_close_detail.csv", index=False, encoding="utf-8-sig")
    exact.to_csv(HERE / "time_gateoff_regression.csv", index=False, encoding="utf-8-sig")
    sat_compare = saturday_h3h4_compare(hour_all)
    sat_compare.to_csv(HERE / "time_h3h4_saturday_compare.csv", index=False, encoding="utf-8-sig")
    render(metric_tab, slip_tab, hour_all, hour_focus, sat_compare, h4_detail, boundary, precision, forced, exact, gap_calendar)
    print(f"done: {OUT}", flush=True)


if __name__ == "__main__":
    main()
