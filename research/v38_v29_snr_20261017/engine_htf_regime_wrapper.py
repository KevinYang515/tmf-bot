"""Daily higher-timeframe regime research wrapper for the read-only V38 engine.

Only ``run`` is recompiled.  The hook is inert unless an
``opt_htf_regime={"definition": "D1"|"D2", "variant": "R1".."R6"}``
override is supplied; the driver regression-tests that off state against the
ordinary v28 engine and its checked-in ledger.
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


# The recompiled function continues to use the vendor module's globals; no
# vendor source is copied or modified.
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


def daily_regime_table() -> pd.DataFrame:
    """Calculate the two specified daily classifications from adjusted TX."""
    daily = pd.read_csv(DAILY_PATH, parse_dates=["date"])
    daily = daily.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    close = daily["close_diff"].astype(float)
    daily["ma60"] = close.rolling(60, min_periods=60).mean()
    daily["ma60_10d_ago"] = daily["ma60"].shift(10)

    d1_up = (close > daily["ma60"]) & (daily["ma60"] > daily["ma60_10d_ago"])
    d1_down = (close < daily["ma60"]) & (daily["ma60"] < daily["ma60_10d_ago"])
    daily["D1"] = np.select([d1_up, d1_down], ["UP", "DOWN"], default="RANGE")

    # The vendor's ADX is Wilder RMA (alpha=1/14, adjust=False), so reuse it
    # with the required adjusted daily high/low/close inputs.
    ohlc = daily.rename(columns={
        "high_diff": "high", "low_diff": "low", "close_diff": "close",
    })[["high", "low", "close"]]
    daily["adx14"] = _base.adx(ohlc, 14)
    d2_range = daily["adx14"] < 20
    d2_up = close > daily["ma60"]
    daily["D2"] = np.select([d2_range, d2_up], ["RANGE", "UP"], default="DOWN")
    return daily


_REGIME_LOOKUPS: dict[str, Callable[[Any], str | None]] = {}


def _htf_regime_lookup(definition: str) -> Callable[[Any], str | None]:
    """Return causal signal-bar lookup for one predeclared definition."""
    if definition not in ("D1", "D2"):
        raise ValueError("HTF definition must be D1 or D2")
    if definition in _REGIME_LOOKUPS:
        return _REGIME_LOOKUPS[definition]

    daily = daily_regime_table().set_index("date")[definition].sort_index()
    dates = daily.index.values.astype("datetime64[ns]")
    values = daily.to_numpy(dtype=object)

    def lookup(t: Any) -> str | None:
        # At signal-bar close t, the daily close dated
        # (t - 13h45m).normalize() is the latest completed day session.
        cutoff = (pd.Timestamp(t) - pd.Timedelta(hours=13, minutes=45)).normalize()
        j = np.searchsorted(dates, np.datetime64(cutoff), side="right") - 1
        return None if j < 0 else str(values[j])

    _REGIME_LOOKUPS[definition] = lookup
    return lookup


def _build_run() -> Any:
    source = inspect.getsource(_base.run)

    old = '    overrides = p or {}\n    p = {**P, **overrides}\n'
    new = '''    overrides = p or {}
    p = {**P, **overrides}
    # Opt-in daily higher-timeframe hook.  With no variant the vendor logic is
    # untouched; importantly, no external daily series is even read.
    _htf_rules = overrides.get("opt_htf_regime", {}) or {}
    _htf_variant = _htf_rules.get("variant")
    _htf_definition = _htf_rules.get("definition")
    if _htf_variant is not None and _htf_variant not in ("R1", "R2", "R3", "R4", "R5", "R6"):
        raise ValueError("unknown HTF variant")
    if _htf_variant is not None and _htf_definition not in ("D1", "D2"):
        raise ValueError("HTF variant requires definition D1 or D2")
    _htf_regime_at = _htf_regime_lookup(_htf_definition) if _htf_variant is not None else None
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
        # This is the completed five-minute bar making the decision.  The
        # lookup's 13:45 cut-off makes the just-completed TX day close usable
        # only from that point onward.
        _htf_regime = _htf_regime_at(t_close) if _htf_regime_at is not None else None
        if _htf_variant == "R5":
            if _htf_regime == "RANGE":
                l_trail *= 0.8
                s_trail *= 0.8
            elif _htf_regime == "UP":
                l_trail *= 1.2
            elif _htf_regime == "DOWN":
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
        _htf_range = _htf_regime == "RANGE"
        # R1 uses the engine's existing per-campaign executed pyramid count:
        # in RANGE one Add may be filled, while G is always blocked.
        _htf_long_pyramid_ok = not ((_htf_variant == "R2" and _htf_range)
                                    or (_htf_variant == "R4" and _htf_regime == "DOWN"))
        _htf_short_pyramid_ok = not ((_htf_variant == "R2" and _htf_range)
                                     or (_htf_variant == "R4" and _htf_regime == "UP"))
        _htf_long_add_ok = _htf_long_pyramid_ok and not (
            _htf_variant == "R1" and _htf_range and long_pyramid_orders >= 1
        )
        _htf_short_add_ok = _htf_short_pyramid_ok and not (
            _htf_variant == "R1" and _htf_range and short_pyramid_orders >= 1
        )
        _htf_long_g_ok = _htf_long_pyramid_ok and not (_htf_variant == "R1" and _htf_range)
        _htf_short_g_ok = _htf_short_pyramid_ok and not (_htf_variant == "R1" and _htf_range)
        _htf_l_pyramid_dist = p["l_pyramid_dist"] * (1.5 if _htf_variant == "R3" and _htf_range else 1.0)
        _htf_s_pyramid_dist = p["s_pyramid_dist"] * (1.5 if _htf_variant == "R3" and _htf_range else 1.0)
        _htf_cmd_long_ok = not (_htf_variant == "R6" and _htf_regime == "DOWN")
        _htf_cmd_short_ok = not (_htf_variant == "R6" and _htf_regime == "UP")
'''
    if old not in source:
        raise RuntimeError("engine layout changed: entry state anchor missing")
    source = source.replace(old, new, 1)

    replacements = (
        ('''        if posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown:
''',
         '''        if posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown and _htf_cmd_long_ok:
''', "long Cmd"),
        ('''        elif posSize == 0 and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger \\
                and (adx_ok if p["opt_adx_short"] else True) and bbw_short_ok and not in_cooldown:
''',
         '''        elif posSize == 0 and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger \\
                and (adx_ok if p["opt_adx_short"] else True) and bbw_short_ok and not in_cooldown and _htf_cmd_short_ok:
''', "short Cmd"),
        ('''        elif 0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok and not long_pyramid_cooldown and not isLongToxic and mtf_bull and c > avgPrice + baseATR * p["l_pyramid_dist"]:
''',
         '''        elif 0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok and _htf_long_add_ok and not long_pyramid_cooldown and not isLongToxic and mtf_bull and c > avgPrice + baseATR * _htf_l_pyramid_dist:
''', "long Add"),
        ('''        elif posSize == 3 and allow_g and long_pyramid_cap_ok and not long_pyramid_cooldown and not isLongToxic and c > avgPrice + baseATR * p["l_pyramid_dist"]:
''',
         '''        elif posSize == 3 and allow_g and long_pyramid_cap_ok and _htf_long_g_ok and not long_pyramid_cooldown and not isLongToxic and c > avgPrice + baseATR * _htf_l_pyramid_dist:
''', "long G"),
        ('''        elif -add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok and not short_pyramid_cooldown and not isShortToxic and mtf_bear and c < avgPrice - baseATR * p["s_pyramid_dist"]:
''',
         '''        elif -add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok and _htf_short_add_ok and not short_pyramid_cooldown and not isShortToxic and mtf_bear and c < avgPrice - baseATR * _htf_s_pyramid_dist:
''', "short Add"),
        ('''        elif posSize == -3 and allow_g and short_pyramid_cap_ok and not short_pyramid_cooldown and not isShortToxic and c < avgPrice - baseATR * p["s_pyramid_dist"]:
''',
         '''        elif posSize == -3 and allow_g and short_pyramid_cap_ok and _htf_short_g_ok and not short_pyramid_cooldown and not isShortToxic and c < avgPrice - baseATR * _htf_s_pyramid_dist:
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
