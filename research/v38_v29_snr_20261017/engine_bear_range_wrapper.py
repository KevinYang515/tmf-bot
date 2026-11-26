"""Opt-in bear/range research hook around the read-only V38 engine.

The vendor engine is never changed.  This module recompiles only ``run`` and
adds conditions at the existing Cmd/Add/G decisions.  With no
``opt_bear_range`` override the generated function follows the vendor source
exactly; the driver regression-tests that state before running variants.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
DAILY_PATH = Path(r"E:\stock\newstrat_rr_20261019\turtle_continuous_tx_20261022.csv")
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
import engine_v26_bbw as _base  # noqa: E402


# The dynamically compiled function refers to the vendor module globals.  Do
# not clone or modify any vendor implementation.
for _name, _value in vars(_base).items():
    if not _name.startswith("__"):
        globals().setdefault(_name, _value)

POINT_VALUE = _base.POINT_VALUE
COMMISSION = _base.COMMISSION
P = _base.P
load_1min = _base.load_1min
prepare = _base.prepare
build_bars = _base.build_bars
pine_ema = _base.pine_ema
pine_rma = _base.pine_rma
atr = _base.atr
adx = _base.adx
_segments = _base._segments
Lot = _base.Lot
_eff_stop = _base._eff_stop
_stop_name = _base._stop_name
summary = _base.summary


_DAILY_TABLE: pd.DataFrame | None = None
_STATE_LOOKUPS: dict[str, Callable[[Any], bool | None]] = {}


def daily_regime_table() -> pd.DataFrame:
    """Return causal daily flags plus frozen range thresholds.

    BD2 is a state machine: a prior-120-day-low break switches it on and a
    close above MA60 switches it off.  Its 120-day comparison excludes the
    current day, as specified by "previous 120 days".
    """
    global _DAILY_TABLE
    if _DAILY_TABLE is not None:
        return _DAILY_TABLE.copy()

    daily = pd.read_csv(DAILY_PATH, parse_dates=["date"])
    daily = daily.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    close = daily["close_diff"].astype(float)
    ma60 = close.rolling(60, min_periods=60).mean()
    ma200 = close.rolling(200, min_periods=200).mean()

    daily["ma60"] = ma60
    daily["ma200"] = ma200
    daily["ma200_20d_ago"] = ma200.shift(20)
    daily["BD1"] = (close < ma200) & (ma200 < daily["ma200_20d_ago"])

    daily["prior_low120"] = close.shift(1).rolling(120, min_periods=120).min()
    bd2 = np.zeros(len(daily), dtype=bool)
    in_bear = False
    for i, (c, ma, prior_low) in enumerate(zip(close, ma60, daily["prior_low120"])):
        if in_bear:
            if np.isfinite(ma) and c > ma:
                in_bear = False
        elif np.isfinite(prior_low) and c < prior_low:
            in_bear = True
        bd2[i] = in_bear
    daily["BD2"] = bd2

    daily["RD1_slope"] = (ma200 - ma200.shift(60)).abs() / ma200
    daily["RD2_er60"] = (close - close.shift(60)).abs() / close.diff().abs().rolling(60, min_periods=60).sum()
    calibration = daily["date"].between(pd.Timestamp("2010-01-01"), pd.Timestamp("2019-12-31"))
    rd1_threshold = float(daily.loc[calibration, "RD1_slope"].dropna().quantile(0.33))
    rd2_threshold = float(daily.loc[calibration, "RD2_er60"].dropna().quantile(0.33))
    daily["RD1_threshold"] = rd1_threshold
    daily["RD2_threshold"] = rd2_threshold
    daily["RD1"] = daily["RD1_slope"] < rd1_threshold
    daily["RD2"] = daily["RD2_er60"] < rd2_threshold

    _DAILY_TABLE = daily
    return daily.copy()


def _state_lookup(definition: str) -> Callable[[Any], bool | None]:
    if definition not in ("BD1", "BD2", "RD1", "RD2"):
        raise ValueError("unknown bear/range definition")
    if definition in _STATE_LOOKUPS:
        return _STATE_LOOKUPS[definition]

    states = daily_regime_table().set_index("date")[definition].sort_index()
    dates = states.index.values.astype("datetime64[ns]")
    values = states.to_numpy(dtype=bool)

    def lookup(t: Any) -> bool | None:
        # The latest completed day session at a five-minute signal-bar close.
        cutoff = (pd.Timestamp(t) - pd.Timedelta(hours=13, minutes=45)).normalize()
        j = np.searchsorted(dates, np.datetime64(cutoff), side="right") - 1
        return None if j < 0 else bool(values[j])

    _STATE_LOOKUPS[definition] = lookup
    return lookup


def _build_run() -> Any:
    source = inspect.getsource(_base.run)

    old = '    overrides = p or {}\n    p = {**P, **overrides}\n'
    new = '''    overrides = p or {}
    p = {**P, **overrides}
    # The absent/empty hook is deliberately inert (and does not read daily
    # data).  A study case supplies one family, definition and variant.
    _br_rules = overrides.get("opt_bear_range", {}) or {}
    _br_family = _br_rules.get("family")
    _br_definition = _br_rules.get("definition")
    _br_variant = _br_rules.get("variant")
    if _br_family is not None and _br_family not in ("bear", "range"):
        raise ValueError("unknown bear/range family")
    if _br_family == "bear":
        if _br_definition not in ("BD1", "BD2") or _br_variant not in ("BV1", "BV2", "BV3", "BV4"):
            raise ValueError("invalid bear case")
    elif _br_family == "range":
        if _br_definition not in ("RD1", "RD2") or _br_variant not in ("RV1", "RV2"):
            raise ValueError("invalid range case")
    elif _br_definition is not None or _br_variant is not None:
        raise ValueError("bear/range definition and variant require a family")
    _br_state_at = _state_lookup(_br_definition) if _br_family is not None else None
'''
    if old not in source:
        raise RuntimeError("engine layout changed: parameter anchor missing")
    source = source.replace(old, new, 1)

    old = '''        s_trail = p["s_trailMult"]
        s_stop = p["s_slMult"]
        atr_regime_pct = B["atr_regime_pct"][i]
'''
    new = '''        s_trail = p["s_trailMult"]
        s_stop = p["s_slMult"]
        # This is the just-completed five-minute signal bar.  The lookup
        # exposes only its latest completed TX day-session classification.
        _br_state = _br_state_at(t_close) if _br_state_at is not None else False
        if _br_family == "bear" and _br_variant == "BV3" and _br_state:
            l_trail *= 0.8
            s_trail *= 1.2
        atr_regime_pct = B["atr_regime_pct"][i]
'''
    if old not in source:
        raise RuntimeError("engine layout changed: trail anchor missing")
    source = source.replace(old, new, 1)

    old = '''        add_cap = min(3, p["opt_max_lots"])
        allow_g = p["opt_max_lots"] >= 4
'''
    new = '''        add_cap = min(3, p["opt_max_lots"])
        allow_g = p["opt_max_lots"] >= 4
        _br_bear = _br_family == "bear" and _br_state
        _br_range = _br_family == "range" and _br_state
        # Bear variants: BV1/BV4 suppress all long pyramids; BV2 also
        # suppresses a long Cmd.  Existing positions otherwise run unchanged.
        _br_long_cmd_ok = not (_br_bear and _br_variant == "BV2")
        _br_long_pyramid_ok = not (_br_bear and _br_variant in ("BV1", "BV2", "BV4"))
        # Range variants: RV1 permits only the first Add per campaign and no
        # G; RV2 permits neither Add nor G.  The counters are engine-native.
        _br_long_pyramid_ok = _br_long_pyramid_ok and not (_br_range and _br_variant == "RV2")
        _br_short_pyramid_ok = not (_br_range and _br_variant == "RV2")
        _br_long_add_ok = _br_long_pyramid_ok and not (
            _br_range and _br_variant == "RV1" and long_pyramid_orders >= 1
        )
        _br_short_add_ok = _br_short_pyramid_ok and not (
            _br_range and _br_variant == "RV1" and short_pyramid_orders >= 1
        )
        _br_long_g_ok = _br_long_pyramid_ok and not (_br_range and _br_variant == "RV1")
        _br_short_g_ok = _br_short_pyramid_ok and not (_br_range and _br_variant == "RV1")
        _br_l_pyramid_dist = p["l_pyramid_dist"]
        _br_s_pyramid_dist = p["s_pyramid_dist"] * (0.8 if _br_bear and _br_variant == "BV4" else 1.0)
'''
    if old not in source:
        raise RuntimeError("engine layout changed: entry-state anchor missing")
    source = source.replace(old, new, 1)

    replacements = (
        ('''        if posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown:
''',
         '''        if posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown and _br_long_cmd_ok:
''', "long Cmd"),
        ('''        elif 0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok and not long_pyramid_cooldown and not isLongToxic and mtf_bull and c > avgPrice + baseATR * p["l_pyramid_dist"]:
''',
         '''        elif 0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok and _br_long_add_ok and not long_pyramid_cooldown and not isLongToxic and mtf_bull and c > avgPrice + baseATR * _br_l_pyramid_dist:
''', "long Add"),
        ('''        elif posSize == 3 and allow_g and long_pyramid_cap_ok and not long_pyramid_cooldown and not isLongToxic and c > avgPrice + baseATR * p["l_pyramid_dist"]:
''',
         '''        elif posSize == 3 and allow_g and long_pyramid_cap_ok and _br_long_g_ok and not long_pyramid_cooldown and not isLongToxic and c > avgPrice + baseATR * _br_l_pyramid_dist:
''', "long G"),
        ('''        elif -add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok and not short_pyramid_cooldown and not isShortToxic and mtf_bear and c < avgPrice - baseATR * p["s_pyramid_dist"]:
''',
         '''        elif -add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok and _br_short_add_ok and not short_pyramid_cooldown and not isShortToxic and mtf_bear and c < avgPrice - baseATR * _br_s_pyramid_dist:
''', "short Add"),
        ('''        elif posSize == -3 and allow_g and short_pyramid_cap_ok and not short_pyramid_cooldown and not isShortToxic and c < avgPrice - baseATR * p["s_pyramid_dist"]:
''',
         '''        elif posSize == -3 and allow_g and short_pyramid_cap_ok and _br_short_g_ok and not short_pyramid_cooldown and not isShortToxic and c < avgPrice - baseATR * _br_s_pyramid_dist:
''', "short G"),
    )
    for before, after, label in replacements:
        if before not in source:
            raise RuntimeError(f"engine layout changed: {label} anchor missing")
        source = source.replace(before, after, 1)

    namespace: dict[str, Any] = {}
    exec(compile(source, __file__, "exec"), globals(), namespace)
    return namespace["run"]


run = _build_run()
