"""Causal daily-regime discriminator study for the V38 v29 configuration.

The runner deliberately writes its pre-registration before computing any bucket
outcomes.  It consumes FinLab data only through `data.get`, keeps all day-d
values unavailable until d+1 08:45, and calls the vendor engine only after the
pre-registered discriminator has passed for both development halves.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from engine_v26_bbw import P, load_1min, prepare  # noqa: E402
from engine_finlab_ideas_wrapper import run as filtered_run  # noqa: E402
from finlab import data  # noqa: E402


DATA = HERE / "mxf_1min_corrected_20261017b.csv"
BASELINE = HERE / "trades_newdirs_v29_baseline.csv"
CUTOFF = pd.Timestamp("2026-10-17 03:58:00")
H2 = pd.Timestamp("2025-04-01")
TRAIN0, TRAIN1 = pd.Timestamp("2026-03-01"), pd.Timestamp("2026-06-01")
TEST0, TEST1 = pd.Timestamp("2026-06-01"), pd.Timestamp("2026-08-22")
HOLDOUT = pd.Timestamp("2026-08-22")
POINT_MARGIN = 92_000
EQUITY_LIMIT = 588_000
RNG_SEED = 20261018
BASE_P = {
    "opt_stale_hr": 10,
    "opt_cooldown_min": 30,
    "opt_short_pyramid_cap_mode": "hour4",
    "l_trailBase": 3.5,
}


FEATURE_SPECS = [
    {
        "feature": "mxf_retail_crowded_pct",
        "family": "MXF retail net OI",
        "definition": "side * (2 * pct252(-sum(foreign, trust, dealer) / MXF total OI) - 1); high means retail crowded with trade side",
        "source": "futures_institutional_investors_trading_summary:多空未平倉口數淨額 + futures_price:未沖銷契約數",
        "kind": "numeric",
    },
    {
        "feature": "mxf_retail_d1",
        "family": "MXF retail net OI",
        "definition": "side * 1-day change of -sum(institutional MXF net OI) / MXF total OI",
        "source": "futures_institutional_investors_trading_summary:多空未平倉口數淨額 + futures_price:未沖銷契約數",
        "kind": "numeric",
    },
    {
        "feature": "tx_retail_crowded_pct",
        "family": "TX retail net OI",
        "definition": "side * (2 * pct252(-sum(foreign, trust, dealer) / TX total OI) - 1); high means retail crowded with trade side",
        "source": "futures_institutional_investors_trading_summary:多空未平倉口數淨額 + futures_price:未沖銷契約數",
        "kind": "numeric",
    },
    {
        "feature": "tx_retail_d1",
        "family": "TX retail net OI",
        "definition": "side * 1-day change of -sum(institutional TX net OI) / TX total OI",
        "source": "futures_institutional_investors_trading_summary:多空未平倉口數淨額 + futures_price:未沖銷契約數",
        "kind": "numeric",
    },
    {
        "feature": "large_top5_aligned_pct",
        "family": "TX large-trader positioning",
        "definition": "side * (2 * pct252((top-5 buy OI - top-5 sell OI) / total OI) - 1), TX all contracts; FinLab's continuous TX-equivalent normalized product after 2013",
        "source": "tw_taifex_futures_large_trader",
        "kind": "numeric",
    },
    {
        "feature": "large_top10_aligned_pct",
        "family": "TX large-trader positioning",
        "definition": "side * (2 * pct252((top-10 buy OI - top-10 sell OI) / total OI) - 1), TX all contracts; FinLab's continuous TX-equivalent normalized product after 2013",
        "source": "tw_taifex_futures_large_trader",
        "kind": "numeric",
    },
    {
        "feature": "tx_foreign_oi_pct",
        "family": "TX foreign net OI",
        "definition": "side * (2 * pct252(TX foreign net OI) - 1)",
        "source": "futures_institutional_investors_trading_summary:多空未平倉口數淨額",
        "kind": "numeric",
    },
    {
        "feature": "tx_foreign_oi_d1",
        "family": "TX foreign net OI",
        "definition": "side * 1-day change of TX foreign net OI",
        "source": "futures_institutional_investors_trading_summary:多空未平倉口數淨額",
        "kind": "numeric",
    },
    {
        "feature": "tx_foreign_oi_d5",
        "family": "TX foreign net OI",
        "definition": "side * 5-day change of TX foreign net OI",
        "source": "futures_institutional_investors_trading_summary:多空未平倉口數淨額",
        "kind": "numeric",
    },
    {
        "feature": "adl_agrees",
        "family": "ADL breadth",
        "definition": "+1 when trade direction agrees with ADL MA5 > MA60, -1 otherwise; ADL=sum_daily(advancers-decliners), using four-digit listed/OTC equities and excluding unchanged closes",
        "source": "price:收盤價",
        "kind": "binary",
    },
    {
        "feature": "foreign_spot_sell_streak_aligned",
        "family": "Foreign spot net-sell streak",
        "definition": "for Long: -consecutive days aggregate foreign spot net flow<0; for Short: +that streak; aggregate is four-digit listed/OTC equities",
        "source": "institutional_investors_trading_summary:外陸資買賣超股數(不含外資自營商)",
        "kind": "numeric",
    },
    {
        "feature": "market_margin_maintenance",
        "family": "Market margin maintenance",
        "definition": "whole-market collateral maintenance ratio, intended side-aligned regime check; not tested if H1/H2 history is absent",
        "source": "tw_credit_trading_daily:擔保維持率",
        "kind": "skip_if_insufficient",
    },
]


def write_csv(frame: pd.DataFrame, stem: str) -> None:
    frame.to_csv(HERE / f"finlab_ideas_{stem}.csv", index=False, encoding="utf-8")


def normalise_trades(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["entry_ts"] = pd.to_datetime(out["entry_ts"])
    out["exit_ts"] = pd.to_datetime(out["exit_ts"])
    out["pnl"] = pd.to_numeric(out["pnl"], errors="coerce")
    return out.sort_values(["entry_ts", "exit_ts", "kind"]).reset_index(drop=True)


def assign_campaigns(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Use the interval-aware campaign definition from run_attrib.py."""
    x = normalise_trades(trades)
    order = {"Cmd": 0, "Add": 1, "G": 2}
    x = x.sort_values(
        ["entry_ts", "exit_ts", "kind"],
        key=lambda s: s.map(order) if s.name == "kind" else s,
    ).reset_index(drop=True)
    cid, active_end, ids = -1, pd.Timestamp.min, []
    for row in x.itertuples():
        if row.entry_ts > active_end or (row.entry_ts == active_end and row.kind == "Cmd"):
            cid += 1
            active_end = row.exit_ts
        else:
            active_end = max(active_end, row.exit_ts)
        ids.append(cid)
    x["campaign_id"] = ids
    ag = x.groupby("campaign_id", as_index=False).agg(
        side=("side", "first"), entry_ts=("entry_ts", "min"), exit_ts=("exit_ts", "max"),
        campaign_pnl=("pnl", "sum"), lots=("pnl", "size"),
    )
    cmd = x[x.kind.eq("Cmd")].groupby("campaign_id", as_index=False).agg(cmd_entry_ts=("entry_ts", "min"))
    ag = ag.merge(cmd, on="campaign_id", how="left")
    if ag.cmd_entry_ts.isna().any():
        raise RuntimeError("A campaign is missing its Cmd mother")
    return x, ag


def period_mask(ts: pd.Series, period: str) -> pd.Series:
    if period == "H1":
        return ts < H2
    if period == "H2_DEV":
        return (ts >= H2) & (ts < HOLDOUT)
    if period == "TRAIN":
        return (ts >= TRAIN0) & (ts < TRAIN1)
    if period == "TEST":
        return (ts >= TEST0) & (ts < TEST1)
    if period == "HOLDOUT":
        return ts >= HOLDOUT
    if period == "DEV":
        return ts < HOLDOUT
    raise ValueError(period)


def mdd(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    pnl = frame.groupby("exit_ts", as_index=False).pnl.sum().sort_values("exit_ts").pnl.cumsum()
    return float((pnl - pnl.cummax()).min())


def metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    if frame.empty:
        return {"n": 0, "net": 0.0, "mdd": 0.0, "wr": np.nan, "pf": np.nan}
    wins = float(frame.loc[frame.pnl > 0, "pnl"].sum())
    losses = float(-frame.loc[frame.pnl <= 0, "pnl"].sum())
    return {
        "n": int(len(frame)), "net": float(frame.pnl.sum()), "mdd": mdd(frame),
        "wr": float((frame.pnl > 0).mean() * 100), "pf": wins / losses if losses else np.inf,
    }


def peak_lots(lots: pd.DataFrame) -> int:
    events: list[tuple[pd.Timestamp, int, int]] = []
    for row in lots.itertuples(index=False):
        q = int(row.qty)
        events.extend([(row.entry_ts, 1, q), (row.exit_ts, 0, -q)])
    position = peak = 0
    for _, _, change in sorted(events, key=lambda z: (z[0], z[1])):
        position += change
        peak = max(peak, position)
    return peak


def rolling_pct(series: pd.Series) -> pd.Series:
    return series.rolling(252, min_periods=126).rank(pct=True)


def next_session_availability(index: pd.DatetimeIndex, session_days: pd.DatetimeIndex) -> pd.Series:
    result: list[pd.Timestamp] = []
    for date in pd.DatetimeIndex(index).normalize():
        ix = session_days.searchsorted(date, side="right")
        result.append(session_days[ix] + pd.Timedelta(hours=8, minutes=45) if ix < len(session_days) else pd.NaT)
    return pd.Series(result, index=index)


def find_oi_column(frame: pd.DataFrame, code: str) -> str:
    candidates = [str(c) for c in frame.columns if str(c).startswith(code) and str(c).endswith("一般")]
    if len(candidates) != 1:
        raise RuntimeError(f"Expected exactly one {code}一般 total-OI column, found {candidates}")
    return candidates[0]


def stock_columns(frame: pd.DataFrame) -> list[str]:
    return [str(c) for c in frame.columns if str(c).isdigit() and len(str(c)) == 4 and 1000 <= int(str(c)) <= 9999]


def net_sell_streak(series: pd.Series) -> pd.Series:
    values: list[float] = []
    streak = 0
    for value in series:
        if pd.isna(value):
            values.append(np.nan)
        elif value < 0:
            streak += 1
            values.append(float(streak))
        else:
            streak = 0
            values.append(0.0)
    return pd.Series(values, index=series.index)


def build_daily_features(df1m: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fetch, audit and turn raw FinLab material into daily side scores."""
    data.set_storage(data.FileStorage(str(HERE / "finlab_cache")))
    availability: list[dict[str, Any]] = []

    def get(key: str, label: str) -> pd.DataFrame | None:
        try:
            # FinlabDataFrame intentionally protects index mutation; this
            # research converts it to a plain pandas frame before aligning
            # calendar dates and applying the explicit next-session lag.
            got = pd.DataFrame(data.get(key).copy())
            if not isinstance(got, pd.DataFrame):
                raise TypeError(f"expected DataFrame, got {type(got).__name__}")
            availability.append({"dataset": label, "data_get_key": key, "status": "OK", "rows": len(got),
                                 "columns": len(got.columns), "start": str(got.index.min()), "end": str(got.index.max()),
                                 "note": ""})
            return got
        except Exception as exc:
            availability.append({"dataset": label, "data_get_key": key, "status": "FAIL", "rows": 0,
                                 "columns": 0, "start": "", "end": "", "note": f"{type(exc).__name__}: {str(exc)[:220]}"})
            return None

    # Required current data sources.  The FinLab API exposes most of these
    # families through column keys rather than an unqualified bare key.
    inst = get("futures_institutional_investors_trading_summary:多空未平倉口數淨額", "futures institutional net OI")
    oi = get("futures_price:未沖銷契約數", "futures total OI")
    large = get("tw_taifex_futures_large_trader", "futures large trader")
    close = get("price:收盤價", "equity close")
    foreign_spot = get("institutional_investors_trading_summary:外陸資買賣超股數(不含外資自營商)", "foreign spot net flow")
    market_margin = get("tw_credit_trading_daily:擔保維持率", "market collateral maintenance ratio")
    old_breakdown = get("tw_taifex_futures_institutional_breakdown", "deprecated futures institutional breakdown")

    if inst is None or oi is None or large is None or close is None or foreign_spot is None:
        raise RuntimeError("One or more required pre-registered FinLab datasets could not be retrieved")

    inst.index = pd.to_datetime(inst.index).normalize()
    oi.index = pd.to_datetime(oi.index).normalize()
    close.index = pd.to_datetime(close.index).normalize()
    foreign_spot.index = pd.to_datetime(foreign_spot.index).normalize()
    if market_margin is not None:
        market_margin.index = pd.to_datetime(market_margin.index).normalize()

    required_inst = [
        "小型臺指期貨_外資及陸資", "小型臺指期貨_投信", "小型臺指期貨_自營商",
        "臺股期貨_外資及陸資", "臺股期貨_投信", "臺股期貨_自營商",
    ]
    absent = [c for c in required_inst if c not in inst.columns]
    if absent:
        raise RuntimeError(f"Required institutional columns missing: {absent}")
    # TAIFEX's FinLab price key calls the Mini Taiwan Index contract `MTX`;
    # it is the strategy's MXF / 小型臺指 economic exposure.
    mxf_oi_col, tx_oi_col = find_oi_column(oi, "MTX"), find_oi_column(oi, "TX")

    daily = pd.DataFrame(index=inst.index.union(oi.index).sort_values())
    mxf_inst = inst[["小型臺指期貨_外資及陸資", "小型臺指期貨_投信", "小型臺指期貨_自營商"]].sum(axis=1, min_count=3)
    tx_inst = inst[["臺股期貨_外資及陸資", "臺股期貨_投信", "臺股期貨_自營商"]].sum(axis=1, min_count=3)
    daily["mxf_retail_ratio"] = (-mxf_inst).reindex(daily.index) / pd.to_numeric(oi[mxf_oi_col], errors="coerce").reindex(daily.index).replace(0, np.nan)
    daily["tx_retail_ratio"] = (-tx_inst).reindex(daily.index) / pd.to_numeric(oi[tx_oi_col], errors="coerce").reindex(daily.index).replace(0, np.nan)
    daily["mxf_retail_pct252"] = rolling_pct(daily["mxf_retail_ratio"])
    daily["tx_retail_pct252"] = rolling_pct(daily["tx_retail_ratio"])
    daily["mxf_retail_d1"] = daily["mxf_retail_ratio"].diff()
    daily["tx_retail_d1"] = daily["tx_retail_ratio"].diff()
    daily["tx_foreign_oi"] = pd.to_numeric(inst["臺股期貨_外資及陸資"], errors="coerce").reindex(daily.index)
    daily["tx_foreign_pct252"] = rolling_pct(daily["tx_foreign_oi"])
    daily["tx_foreign_d1"] = daily["tx_foreign_oi"].diff()
    daily["tx_foreign_d5"] = daily["tx_foreign_oi"].diff(5)

    # The large-trader table is long.  Positions 4/8/12/16/20 are the table's
    # documented buy-5/buy-10/sell-5/sell-10/total-OI fields.  We pick exactly
    # the TX all-contract record after inspecting its product/month columns.
    large["date"] = pd.to_datetime(large["date"]).dt.normalize()
    # FinLab's raw table uses the legacy 臺股期貨 label through 2013-07-29
    # and the continuous TX-equivalent normalized label afterwards.  Include
    # both exact inspected product names; development observations use only
    # the latter, whose coverage continues through the current endpoint.
    tx_products = ["臺股期貨", "臺股期貨(TX+MTX/4+TMF/20)"]
    all_tx = large[(large["symbol"].astype(str).isin(tx_products)) & (large["到期月份(週別)"].astype(str).eq("所有契約"))].copy()
    if all_tx.empty:
        raise RuntimeError("No inspected TX all-contract rows in tw_taifex_futures_large_trader")
    all_tx = all_tx.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
    top5 = (pd.to_numeric(all_tx["買方前五大交易人部位數"], errors="coerce") -
            pd.to_numeric(all_tx["賣方前五大交易人部位數"], errors="coerce"))
    top10 = (pd.to_numeric(all_tx["買方前十大交易人部位數"], errors="coerce") -
             pd.to_numeric(all_tx["賣方前十大交易人部位數"], errors="coerce"))
    total = pd.to_numeric(all_tx["全市場未沖銷部位數"], errors="coerce").replace(0, np.nan)
    daily["large_top5_ratio"] = (top5 / total).reindex(daily.index)
    daily["large_top10_ratio"] = (top10 / total).reindex(daily.index)
    daily["large_top5_pct252"] = rolling_pct(daily["large_top5_ratio"])
    daily["large_top10_pct252"] = rolling_pct(daily["large_top10_ratio"])

    # ADL and foreign stock flow both deliberately use only four-digit listed/
    # OTC equities.  This excludes ETFs, warrants and unchanged closes.
    close_cols = stock_columns(close)
    returns = close[close_cols].pct_change()
    adv = returns.gt(0).sum(axis=1)
    dec = returns.lt(0).sum(axis=1)
    adl = (adv - dec).cumsum()
    daily["adl"] = adl.reindex(daily.index)
    daily["adl_ma5"] = daily["adl"].rolling(5, min_periods=5).mean()
    daily["adl_ma60"] = daily["adl"].rolling(60, min_periods=60).mean()
    daily["adl_bull"] = (daily["adl_ma5"] > daily["adl_ma60"]).where(daily["adl_ma60"].notna())
    spot_cols = [c for c in stock_columns(foreign_spot) if c in foreign_spot.columns]
    daily["foreign_spot_net"] = foreign_spot[spot_cols].sum(axis=1, min_count=1).reindex(daily.index)
    daily["foreign_spot_sell_streak"] = net_sell_streak(daily["foreign_spot_net"])

    session_days = pd.DatetimeIndex(
        pd.Series(df1m.loc[df1m.ts.dt.hour.between(8, 13), "ts"].dt.normalize().unique()).sort_values()
    )
    daily["available_ts"] = next_session_availability(daily.index, session_days).to_numpy()
    daily.index.name = "date"
    daily = daily.reset_index()

    # Direction-aligned feature scores: a high score always means stronger
    # agreement/crowding in the trade's direction.  Definitions are fixed
    # above and no sign/bucket selection is redone in H2.
    def centered(name: str, source: str) -> None:
        daily[name + "__long"] = 2.0 * daily[source] - 1.0
        daily[name + "__short"] = -daily[name + "__long"]

    def signed(name: str, source: str) -> None:
        daily[name + "__long"] = daily[source]
        daily[name + "__short"] = -daily[source]

    centered("mxf_retail_crowded_pct", "mxf_retail_pct252")
    signed("mxf_retail_d1", "mxf_retail_d1")
    centered("tx_retail_crowded_pct", "tx_retail_pct252")
    signed("tx_retail_d1", "tx_retail_d1")
    centered("large_top5_aligned_pct", "large_top5_pct252")
    centered("large_top10_aligned_pct", "large_top10_pct252")
    centered("tx_foreign_oi_pct", "tx_foreign_pct252")
    signed("tx_foreign_oi_d1", "tx_foreign_d1")
    signed("tx_foreign_oi_d5", "tx_foreign_d5")
    daily["adl_agrees__long"] = np.where(daily["adl_bull"].isna(), np.nan, np.where(daily["adl_bull"], 1.0, -1.0))
    daily["adl_agrees__short"] = -daily["adl_agrees__long"]
    daily["foreign_spot_sell_streak_aligned__long"] = -daily["foreign_spot_sell_streak"]
    daily["foreign_spot_sell_streak_aligned__short"] = daily["foreign_spot_sell_streak"]

    raw_summary = pd.DataFrame([
        {"series": "mxf_retail_ratio", "non_null": int(daily.mxf_retail_ratio.notna().sum()), "first": str(daily.loc[daily.mxf_retail_ratio.notna(), "date"].min()), "last": str(daily.loc[daily.mxf_retail_ratio.notna(), "date"].max())},
        {"series": "tx_retail_ratio", "non_null": int(daily.tx_retail_ratio.notna().sum()), "first": str(daily.loc[daily.tx_retail_ratio.notna(), "date"].min()), "last": str(daily.loc[daily.tx_retail_ratio.notna(), "date"].max())},
        {"series": "large_top5_ratio", "non_null": int(daily.large_top5_ratio.notna().sum()), "first": str(daily.loc[daily.large_top5_ratio.notna(), "date"].min()), "last": str(daily.loc[daily.large_top5_ratio.notna(), "date"].max())},
        {"series": "adl_bull", "non_null": int(daily.adl_bull.notna().sum()), "first": str(daily.loc[daily.adl_bull.notna(), "date"].min()), "last": str(daily.loc[daily.adl_bull.notna(), "date"].max())},
        {"series": "foreign_spot_sell_streak", "non_null": int(daily.foreign_spot_sell_streak.notna().sum()), "first": str(daily.loc[daily.foreign_spot_sell_streak.notna(), "date"].min()), "last": str(daily.loc[daily.foreign_spot_sell_streak.notna(), "date"].max())},
        {"series": "market_margin_maintenance", "non_null": int(market_margin["全市場"].notna().sum()) if market_margin is not None and "全市場" in market_margin else 0,
         "first": str(market_margin.index.min()) if market_margin is not None else "", "last": str(market_margin.index.max()) if market_margin is not None else ""},
        {"series": "deprecated_breakdown", "non_null": int(len(old_breakdown)) if old_breakdown is not None else 0,
         "first": str(pd.to_datetime(old_breakdown["date"]).min()) if old_breakdown is not None else "", "last": str(pd.to_datetime(old_breakdown["date"]).max()) if old_breakdown is not None else ""},
    ])
    return daily, pd.DataFrame(availability), raw_summary


def attach_entries(lots: pd.DataFrame, campaigns: pd.DataFrame, b5: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    cmd = campaigns[["campaign_id", "side", "entry_ts", "campaign_pnl"]].copy()
    cmd = cmd.rename(columns={"campaign_pnl": "outcome"})
    cmd["target"] = "Cmd"
    adds = lots[lots.kind.eq("Add")][["campaign_id", "side", "entry_ts", "pnl"]].copy()
    adds = adds.rename(columns={"pnl": "outcome"})
    adds["target"] = "Add"
    events = pd.concat([cmd, adds], ignore_index=True).sort_values("entry_ts").reset_index(drop=True)
    close_ts = b5.close_ts.to_numpy(dtype="datetime64[ns]")
    ix = np.searchsorted(close_ts, events.entry_ts.to_numpy(dtype="datetime64[ns]"), side="right") - 1
    if (ix < 0).any():
        raise RuntimeError("entry before first prepared signal bar")
    events["sig_adx"] = b5.adx.to_numpy()[ix]
    events["sig_bbw_pct"] = b5.bbw_pct.to_numpy()[ix]
    events["sig_atr_pct"] = (b5.atr / b5.close * 100.0).to_numpy()[ix]
    use = ["available_ts"] + [c for c in daily.columns if c.endswith("__long") or c.endswith("__short")]
    events = pd.merge_asof(events, daily[use].dropna(subset=["available_ts"]).sort_values("available_ts"),
                           left_on="entry_ts", right_on="available_ts", direction="backward")
    for spec in FEATURE_SPECS:
        feature = spec["feature"]
        left, right = feature + "__long", feature + "__short"
        if left in events and right in events:
            events[feature] = np.where(events.side.eq("L"), events[left], events[right])
    return events.sort_values(["target", "entry_ts", "campaign_id"]).reset_index(drop=True)


def bucket_tercile(values: pd.Series, kind: str) -> tuple[pd.Series, float, float, list[str], str | None]:
    if kind == "binary":
        bucket = pd.Series(np.where(values < 0, "low", np.where(values > 0, "high", None)), index=values.index, dtype="object")
        return bucket, 0.0, 0.0, ["low", "high"], None
    low, high = values.quantile([1 / 3, 2 / 3])
    if not np.isfinite(low) or not np.isfinite(high) or low >= high:
        return pd.Series(np.nan, index=values.index, dtype="object"), float(low), float(high), [], "degenerate H1 terciles"
    bucket = pd.Series(np.where(values <= low, "low", np.where(values >= high, "high", "mid")), index=values.index, dtype="object")
    return bucket, float(low), float(high), ["low", "mid", "high"], None


def bootstrap_cluster_diff(frame: pd.DataFrame, bad_bucket: str, seed: int, draws: int = 4000) -> tuple[float, float, float]:
    """Cluster bootstrap mean(bad)-mean(other) at campaign level."""
    x = frame[frame.bucket.notna()].copy()
    if x.empty or x.bucket.eq(bad_bucket).sum() < 2 or x.bucket.ne(bad_bucket).sum() < 2:
        return np.nan, np.nan, np.nan
    x["is_bad"] = x.bucket.eq(bad_bucket)
    x["bad_sum"] = np.where(x.is_bad, x.outcome, 0.0)
    x["bad_n"] = x.is_bad.astype(float)
    x["rest_sum"] = np.where(~x.is_bad, x.outcome, 0.0)
    x["rest_n"] = (~x.is_bad).astype(float)
    g = x.groupby("campaign_id", as_index=False)[["bad_sum", "bad_n", "rest_sum", "rest_n"]].sum()
    bad_sum, bad_n = g.bad_sum.to_numpy(), g.bad_n.to_numpy()
    rest_sum, rest_n = g.rest_sum.to_numpy(), g.rest_n.to_numpy()
    if (bad_n > 0).sum() < 5 or (rest_n > 0).sum() < 5:
        return np.nan, np.nan, np.nan
    point = float(bad_sum.sum() / bad_n.sum() - rest_sum.sum() / rest_n.sum())
    rng = np.random.default_rng(seed)
    selection = rng.integers(0, len(g), size=(draws, len(g)))
    sb, nb = bad_sum[selection].sum(axis=1), bad_n[selection].sum(axis=1)
    sr, nr = rest_sum[selection].sum(axis=1), rest_n[selection].sum(axis=1)
    valid = (nb > 0) & (nr > 0)
    diff = sb[valid] / nb[valid] - sr[valid] / nr[valid]
    if len(diff) < draws * .95:
        return np.nan, np.nan, np.nan
    return point, float(np.quantile(diff, .025)), float(np.quantile(diff, .975))


def quintile_table(frame: pd.DataFrame, feature: str, target: str, period: str) -> list[dict[str, Any]]:
    values = frame.loc[frame.feature_value.notna(), "feature_value"]
    if len(values) < 10 or values.nunique() < 5:
        return []
    cuts = values.quantile([.2, .4, .6, .8]).to_numpy(float)
    if len(np.unique(cuts)) < 4:
        return []
    bucket = pd.cut(frame.feature_value, [-np.inf, *cuts, np.inf], labels=["Q1", "Q2", "Q3", "Q4", "Q5"], include_lowest=True)
    rows = []
    for label in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        z = frame.loc[bucket.eq(label)]
        rows.append({"feature": feature, "target": target, "period": period, "scheme": "quintile_H1_cutpoints",
                     "bucket": label, "n": len(z), "mean_pnl": z.outcome.mean() if len(z) else np.nan,
                     "net_pnl": z.outcome.sum() if len(z) else np.nan})
    return rows


def discriminator(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    results: list[dict[str, Any]] = []
    bucket_rows: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    for f_idx, spec in enumerate(FEATURE_SPECS):
        feature, kind = spec["feature"], spec["kind"]
        for target in ("Cmd", "Add"):
            if kind == "skip_if_insufficient" or feature not in events:
                results.append({"feature": feature, "target": target, "status": "SKIP_insufficient_H1_H2_history", "gate": False,
                                "reason": "Market collateral maintenance data begins 2026-08-03 (HOLDOUT)."})
                continue
            z = events[events.target.eq(target)].copy()
            h1_valid = z.loc[period_mask(z.entry_ts, "H1") & z[feature].notna(), feature]
            if len(h1_valid) < 30:
                results.append({"feature": feature, "target": target, "status": "SKIP_insufficient_H1_entries", "gate": False,
                                "reason": f"Only {len(h1_valid)} H1 observations."})
                continue
            bucket, low, high, labels, error = bucket_tercile(h1_valid, kind)
            if error:
                results.append({"feature": feature, "target": target, "status": "SKIP_degenerate", "gate": False, "reason": error,
                                "low_threshold": low, "high_threshold": high})
                continue
            # Apply the fixed H1 thresholds to every period; no H2 bucket is
            # selected or re-fit.  `z` receives a separate bucket column for
            # the current feature to keep feature values auditable in the CSV.
            if kind == "binary":
                z["bucket"] = pd.Series(np.where(z[feature] < 0, "low", np.where(z[feature] > 0, "high", None)), index=z.index, dtype="object")
            else:
                z["bucket"] = np.where(z[feature] <= low, "low", np.where(z[feature] >= high, "high", "mid"))
                z.loc[z[feature].isna(), "bucket"] = np.nan
            means_h1 = z.loc[period_mask(z.entry_ts, "H1")].groupby("bucket").outcome.agg(["mean", "size"])
            valid_means = means_h1[means_h1["size"].ge(15)]["mean"]
            if valid_means.empty:
                results.append({"feature": feature, "target": target, "status": "SKIP_small_H1_bucket", "gate": False,
                                "reason": "No H1 bucket contains >=15 observations."})
                continue
            bad = str(valid_means.idxmin())
            stats: dict[str, tuple[float, float, float, int, int]] = {}
            for p_idx, period in enumerate(("H1", "H2_DEV", "HOLDOUT")):
                q = z.loc[period_mask(z.entry_ts, period) & z.bucket.notna()].copy()
                point, ci_low, ci_high = bootstrap_cluster_diff(q, bad, RNG_SEED + f_idx * 97 + p_idx * 17 + (0 if target == "Cmd" else 1))
                stats[period] = (point, ci_low, ci_high, int(q.bucket.eq(bad).sum()), int(q.bucket.ne(bad).sum()))
                for label in labels:
                    g = q[q.bucket.eq(label)]
                    bucket_rows.append({"feature": feature, "target": target, "period": period, "scheme": "tercile_primary" if kind != "binary" else "binary_state",
                                        "bucket": label, "n": len(g), "mean_pnl": g.outcome.mean() if len(g) else np.nan,
                                        "net_pnl": g.outcome.sum() if len(g) else np.nan})
            for period in ("H1", "H2_DEV"):
                q = z.loc[period_mask(z.entry_ts, period) & z[feature].notna()].copy()
                q = q.rename(columns={feature: "feature_value"})
                bucket_rows.extend(quintile_table(q, feature, target, period))
            dev = z.loc[period_mask(z.entry_ts, "DEV") & z.bucket.notna()].copy()
            bad_dev = dev[dev.bucket.eq(bad)]
            loss_removed = float(-bad_dev.loc[bad_dev.outcome < 0, "outcome"].sum())
            profit_removed = float(bad_dev.loc[bad_dev.outcome > 0, "outcome"].sum())
            skip_delta = float(-bad_dev.outcome.sum())
            # Matched placebo: same number of target entries drawn at random
            # from DEV.  A deterministic 200-draw distribution is reported.
            placebo = []
            if len(dev) >= len(bad_dev) and len(bad_dev):
                rng = np.random.default_rng(RNG_SEED + 10_000 + f_idx * 23 + (0 if target == "Cmd" else 1))
                outcomes = dev.outcome.to_numpy(float)
                for _ in range(200):
                    placebo.append(float(-rng.choice(outcomes, size=len(bad_dev), replace=False).sum()))
            rhos = z.loc[period_mask(z.entry_ts, "DEV"), [feature, "sig_adx", "sig_bbw_pct", "sig_atr_pct"]].corr(method="spearman").loc[feature]
            rho_values = np.asarray([rhos.get("sig_adx", np.nan), rhos.get("sig_bbw_pct", np.nan), rhos.get("sig_atr_pct", np.nan)], dtype=float)
            max_abs_rho = float(np.max(np.abs(rho_values[np.isfinite(rho_values)]))) if np.isfinite(rho_values).any() else np.nan
            h1, h2, hold = stats["H1"], stats["H2_DEV"], stats["HOLDOUT"]
            sufficient = h1[3] >= 15 and h1[4] >= 15 and h2[3] >= 15 and h2[4] >= 15
            ci_pass = bool(sufficient and h1[0] < 0 and h2[0] < 0 and h1[2] < 0 and h2[2] < 0)
            proxy_flag = bool(max_abs_rho > .4) if np.isfinite(max_abs_rho) else False
            gate = bool(ci_pass and not proxy_flag)
            result = {
                "feature": feature, "target": target, "status": "TESTED", "bad_bucket_from_H1": bad,
                "low_threshold": low, "high_threshold": high,
                "h1_diff_bad_minus_rest": h1[0], "h1_ci_low": h1[1], "h1_ci_high": h1[2], "h1_bad_n": h1[3], "h1_rest_n": h1[4],
                "h2_diff_bad_minus_rest": h2[0], "h2_ci_low": h2[1], "h2_ci_high": h2[2], "h2_bad_n": h2[3], "h2_rest_n": h2[4],
                "holdout_diff_bad_minus_rest": hold[0], "holdout_bad_n": hold[3], "holdout_rest_n": hold[4],
                "loss_removed_dev": loss_removed, "profit_removed_dev": profit_removed,
                "loss_profit_ratio": loss_removed / profit_removed if profit_removed else np.inf, "skip_delta_dev": skip_delta,
                "placebo_mean_skip_delta": float(np.mean(placebo)) if placebo else np.nan,
                "placebo_ci_low": float(np.quantile(placebo, .025)) if placebo else np.nan,
                "placebo_ci_high": float(np.quantile(placebo, .975)) if placebo else np.nan,
                "placebo_percentile": float(np.mean(np.asarray(placebo) <= skip_delta)) if placebo else np.nan,
                "rho_adx": rhos.get("sig_adx", np.nan), "rho_bbw": rhos.get("sig_bbw_pct", np.nan), "rho_atr_pct": rhos.get("sig_atr_pct", np.nan),
                "max_abs_proxy_rho": max_abs_rho, "proxy_flag_gt_0p4": proxy_flag, "ci_sign_pass": ci_pass, "gate": gate,
            }
            results.append(result)
            if gate:
                selected.append(result)
    return pd.DataFrame(results), pd.DataFrame(bucket_rows), pd.DataFrame(selected)


def sizing_study(lots: pd.DataFrame, events: pd.DataFrame, disc: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    tested = disc[disc.status.eq("TESTED")].copy() if not disc.empty and "status" in disc else pd.DataFrame()
    for row in tested.itertuples(index=False):
        feature, target = row.feature, row.target
        event = events[events.target.eq(target)][["campaign_id", "entry_ts", feature]].copy()
        if target == "Cmd":
            # One decision per campaign: scale every leg in that campaign.
            values = event.drop_duplicates("campaign_id").set_index("campaign_id")[feature]
            lot_values = lots.campaign_id.map(values)
        else:
            # An Add rule changes only the relevant Add lots; Cmd/G remain one.
            keys = event.reset_index().set_index(["campaign_id", "entry_ts"])[feature]
            lot_values = pd.Series([keys.get((r.campaign_id, r.entry_ts), np.nan) if r.kind == "Add" else np.nan for r in lots.itertuples()], index=lots.index)
        is_bad = (lot_values <= row.low_threshold) if row.bad_bucket_from_H1 == "low" else ((lot_values >= row.high_threshold) if row.bad_bucket_from_H1 == "high" else ((lot_values > row.low_threshold) & (lot_values < row.high_threshold)))
        scaled = lots.copy()
        if target == "Cmd":
            # Non-missing, non-bad campaigns get two lots. Missing retains one.
            scaled["qty"] = np.where(lot_values.notna(), np.where(is_bad, 1, 2), 1)
        else:
            scaled["qty"] = np.where(scaled.kind.eq("Add") & lot_values.notna(), np.where(is_bad, 1, 2), 1)
        scaled["pnl"] *= scaled.qty
        peak = peak_lots(scaled)
        for period in ("H1", "H2_DEV", "TRAIN", "TEST", "HOLDOUT", "DEV"):
            q = scaled[period_mask(scaled.entry_ts, period)]
            rows.append({"feature": feature, "target": target, "bad_bucket": row.bad_bucket_from_H1, "period": period,
                         "eligible_lots": int(lot_values.notna().sum()), "one_lot_bad_two_elsewhere": True,
                         "peak_lots": peak, "margin_need": peak * POINT_MARGIN, "within_588k_limit": peak * POINT_MARGIN <= EQUITY_LIMIT,
                         **metrics(q)})
    return pd.DataFrame(rows)


def engine_study(df1m: pd.DataFrame, daily: pd.DataFrame, baseline: pd.DataFrame, gates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if gates.empty:
        return pd.DataFrame(columns=["feature", "target", "period", "status", "net", "mdd", "delta_net", "pass"])
    for gate in gates.itertuples(index=False):
        f = gate.feature
        daily_filter = daily[["available_ts", f + "__long", f + "__short"]].dropna(subset=["available_ts"]).copy()
        daily_filter = daily_filter.rename(columns={f + "__long": "score_long", f + "__short": "score_short"})
        daily_filter["low"] = gate.low_threshold
        daily_filter["high"] = gate.high_threshold
        daily_filter["bad_bucket"] = gate.bad_bucket_from_H1
        daily_filter["target"] = gate.target
        candidate = normalise_trades(filtered_run(df1m, p={**BASE_P, "opt_finlab_ideas_filter": daily_filter}, intrabar_mode="1min"))
        pass_parts: list[bool] = []
        for period in ("H1", "H2_DEV", "TRAIN", "TEST", "HOLDOUT"):
            b = baseline[period_mask(baseline.entry_ts, period)]
            c = candidate[period_mask(candidate.entry_ts, period)]
            bm, cm = metrics(b), metrics(c)
            delta = float(cm["net"] - bm["net"])
            if period in ("H1", "H2_DEV", "TRAIN", "TEST"):
                pass_parts.append(delta > 0)
            rows.append({"feature": f, "target": gate.target, "bad_bucket": gate.bad_bucket_from_H1, "period": period,
                         "status": "ENGINE_TESTED", "baseline_n": bm["n"], "filtered_n": cm["n"], "baseline_net": bm["net"], "net": cm["net"],
                         "baseline_mdd": bm["mdd"], "mdd": cm["mdd"], "delta_net": delta, "pass": np.nan})
        final_pass = bool(all(pass_parts))
        for row in rows:
            if row["feature"] == f and row["target"] == gate.target:
                row["pass"] = final_pass
    return pd.DataFrame(rows)


def md_table(frame: pd.DataFrame, cols: list[str], max_rows: int | None = None) -> list[str]:
    if frame.empty:
        return ["_None._"]
    z = frame[cols].copy()
    if max_rows is not None:
        z = z.head(max_rows)
    def fmt(value: Any) -> str:
        if isinstance(value, (float, np.floating)):
            if not np.isfinite(value):
                return "NA"
            if abs(value) >= 1000:
                return f"{value:,.0f}"
            return f"{value:.3f}"
        if isinstance(value, (bool, np.bool_)):
            return "PASS" if value else "FAIL"
        if pd.isna(value):
            return ""
        return str(value).replace("|", "/")
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for values in z.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(fmt(v) for v in values) + " |")
    return lines


def report(availability: pd.DataFrame, raw: pd.DataFrame, pre: pd.DataFrame, disc: pd.DataFrame,
           sizing: pd.DataFrame, engines: pd.DataFrame, baseline: pd.DataFrame) -> None:
    tested = disc[disc.status.eq("TESTED")].copy() if not disc.empty and "status" in disc else pd.DataFrame()
    selected = tested[tested.gate.eq(True)] if not tested.empty else pd.DataFrame()
    engine_summary = engines[engines.period.eq("HOLDOUT") | engines.period.eq("TEST")] if not engines.empty else engines
    lines = [
        "# FinLab-inspired daily regime ideas — V38 v29",
        "",
        "## Verdict",
        "",
        f"Tested {len(tested)} feature×target rules from 11 live pre-registered daily features; the margin-maintenance feature was unavailable in H1 and therefore could not be tested across both development halves. "
        f"{len(selected)} rule(s) cleared the pre-registered discriminator (negative bad-vs-rest bootstrap CI in H1 and H2_DEV, both signs negative, and no |rho|>0.4 proxy flag). "
        + ("Only those rules received a path-dependent engine test below." if len(selected) else "No full-engine filter was run, as required by the discriminator gate."),
        "",
        f"The exact v29 baseline is the common-cutoff `trades_newdirs_v29_baseline.csv`: {len(baseline):,} lots, net {baseline.pnl.sum():,.0f} NTD. Windows use entry timestamps: H1 < 2025-04-01; H2_DEV 2025-04-01 to 2026-08-21; TRAIN 2026-03-01..05-31; TEST 2026-06-01..08-21; HOLDOUT >= 2026-08-22 is display-only.",
        "",
        "## Availability and causal lag",
        "",
        "Every daily value dated d is joined only from the next actual day-session date at 08:45. This is deliberately more conservative than same-night use: no d day-session or d night-session entry can see d's close/published value. The previous `results_newdirs.md` TX OI check used the 19-date `tw_taifex_futures_institutional_breakdown` and was non-evaluable; this study uses the requested 4,742-date institutional-summary series instead.",
        "",
    ]
    lines += md_table(availability, ["dataset", "status", "rows", "columns", "start", "end", "note"])
    lines += ["", "### Source coverage", ""]
    lines += md_table(raw, ["series", "non_null", "first", "last"])
    lines += ["", "## Pre-registration", "", "Thresholds are H1-only. Numeric rules use H1 terciles to select one worst bucket; the same cutpoints/bucket then apply to H2_DEV and HOLDOUT. ADL is binary. Bootstrap resamples campaigns (not individual Add legs); for Add rules, each sampled campaign contributes all of its Add outcomes. A gate also rejects a feature if its maximum absolute Spearman rho with entry ADX, BBW percentile, or ATR% exceeds 0.40.", ""]
    lines += md_table(pre, ["feature", "family", "kind", "definition", "source"])
    lines += ["", "## Discriminator", "", "`diff` is mean PnL of H1-selected bad bucket minus all other valid buckets; negative is desired. Placebo percentile is the fraction of 200 matched random skips with a smaller/equal avoided-PnL delta. `loss/profit` above 1 means more losses than profits were removed.", ""]
    if not tested.empty:
        view = tested.copy()
        view["loss/profit"] = view.loss_profit_ratio
        lines += md_table(view, ["feature", "target", "bad_bucket_from_H1", "h1_diff_bad_minus_rest", "h1_ci_low", "h1_ci_high", "h2_diff_bad_minus_rest", "h2_ci_low", "h2_ci_high", "loss/profit", "placebo_percentile", "max_abs_proxy_rho", "gate"])
        lines += ["", "The full H1/H2_DEV tercile (or binary-state) and H1-cutpoint quintile mean-PnL matrices are in `finlab_ideas_buckets.csv`."]
    skipped = disc[~disc.status.eq("TESTED")] if not disc.empty and "status" in disc else pd.DataFrame()
    if not skipped.empty:
        lines += ["", "### Skipped", ""]
        lines += md_table(skipped, ["feature", "target", "status", "reason"])
    lines += ["", "## Sizing diagnostic", "", "This is an accounting-only 1-lot bad-bucket / 2-lots elsewhere diagnostic, not an engine redesign. For Cmd rules all legs of an eligible campaign are scaled; for Add rules only eligible Add legs are scaled. Values exceeding six lots (588k / 92k) are explicitly infeasible under the stated equity limit.", ""]
    if not sizing.empty:
        lines += md_table(sizing[sizing.period.eq("DEV")], ["feature", "target", "net", "mdd", "peak_lots", "margin_need", "within_588k_limit"])
    else:
        lines += ["_No testable sizing row._"]
    lines += ["", "## Engine gate", "", "PASS requires net delta > 0 in H1, H2_DEV, TRAIN and TEST. HOLDOUT is shown but never participates in the decision.", ""]
    if engines.empty:
        lines += ["_No rule passed the discriminator; no engine run was authorized._"]
    else:
        lines += md_table(engines, ["feature", "target", "period", "baseline_net", "net", "delta_net", "baseline_mdd", "mdd", "pass"])
    multiple = len(tested)
    exp_one = multiple * .05
    lines += [
        "",
        "## Multiple-comparisons caution and untouched TV check",
        "",
        f"This is {multiple} feature×target discriminator tests ({len(FEATURE_SPECS)} pre-registered feature definitions, with Cmd/Add evaluated separately). At a nominal 5% one-sided false-positive rate, about {exp_one:.1f} apparent findings are expected even before considering the roughly nine prior studies / 70+ variants already run over overlapping windows. The two-half CI gate and proxy veto reduce, but do not erase, this selection risk.",
        "",
        "Worth an untouched 2022–2023 TradingView check only if it has a development gate here: any engine-gated rule should be re-run unchanged with the same next-day-08:45 lag and no re-fit of percentile windows, bucket thresholds, or direction mapping. All other ideas should not receive a TV validation run yet.",
        "",
        "## Files",
        "",
        "`finlab_ideas_preregistration.csv`, `finlab_ideas_dataset_availability.csv`, `finlab_ideas_daily_features.csv`, `finlab_ideas_events.csv`, `finlab_ideas_buckets.csv`, `finlab_ideas_discriminator.csv`, `finlab_ideas_sizing.csv`, and `finlab_ideas_engine_gates.csv` are the recomputable audit trail.",
    ]
    (HERE / "results_finlab_ideas.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    print("Load common-cutoff v29 baseline and 1-minute source", flush=True)
    baseline = normalise_trades(pd.read_csv(BASELINE))
    if len(baseline) != 4137:
        raise RuntimeError(f"Expected 4,137 common-cutoff v29 lots, found {len(baseline)}")
    df1m = load_1min(DATA)
    df1m = df1m[df1m.ts.le(CUTOFF)].copy()
    b5 = prepare(df1m, {**P, **BASE_P})
    lots, campaigns = assign_campaigns(baseline)

    print("Fetch FinLab data and construct causally lagged daily scores", flush=True)
    daily, availability, raw = build_daily_features(df1m)
    pre = pd.DataFrame(FEATURE_SPECS)
    # This is intentionally committed before events are bucketed or outcomes
    # are examined, providing a timestamped explicit feature registry.
    write_csv(pre, "preregistration")
    write_csv(availability, "dataset_availability")
    write_csv(raw, "raw_coverage")
    write_csv(daily, "daily_features")

    print("Attach daily values to Cmd campaigns and Add entries", flush=True)
    events = attach_entries(lots, campaigns, b5, daily)
    write_csv(events, "events")
    print("Run preregistered discriminators and placebo checks", flush=True)
    disc, buckets, gates = discriminator(events)
    write_csv(disc, "discriminator")
    write_csv(buckets, "buckets")
    write_csv(gates, "selected_gates")
    sizing = sizing_study(lots, events, disc)
    write_csv(sizing, "sizing")

    print(f"Run full engine only for {len(gates)} passing discriminator gate(s)", flush=True)
    engines = engine_study(df1m, daily, baseline, gates)
    write_csv(engines, "engine_gates")
    report(availability, raw, pre, disc, sizing, engines, baseline)
    print("Wrote results_finlab_ideas.md and finlab_ideas_*.csv", flush=True)


if __name__ == "__main__":
    main()
