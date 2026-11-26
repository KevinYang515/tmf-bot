"""Causal adaptive-H1 extension of the frozen Gate 4 wrapper.

The vendor engine is imported read-only.  Gate 4's G2/H1/H4/H14 path is
retained verbatim in the generated loop; this module only adds five H1 masks
that are formed before the loop from completed five-minute decision bars.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
import engine_v26_bbw as _base  # noqa: E402

from run_ml_attrib import er, volume_features  # noqa: E402


for _name, _value in vars(_base).items():
    if not _name.startswith("__"):
        globals().setdefault(_name, _value)

POINT_VALUE = _base.POINT_VALUE
COMMISSION = _base.COMMISSION
P = _base.P
load_1min = _base.load_1min


def _prior_session_quantile(values: pd.Series, session_code: np.ndarray, lookback: int,
                            quantile: float = 0.20) -> np.ndarray:
    """One fixed threshold per session, from complete earlier sessions only.

    The code is in first-bar order.  Day and night are deliberately separate
    sessions but share the sequential lookback for A/B/C (B standardises the
    raw ATR by session type and clock before that pooled quantile is taken).
    No expanding-history substitute is used during warm-up.
    """
    answer = np.full(len(values), np.nan, dtype=float)
    starts = np.r_[0, np.flatnonzero(np.diff(session_code)) + 1]
    ends = np.r_[starts[1:], len(values)]
    x = values.to_numpy(dtype=float)
    for current, (start, end) in enumerate(zip(starts, ends)):
        if current < lookback:
            continue
        history = x[starts[current - lookback]:start]
        history = history[np.isfinite(history)]
        if len(history):
            answer[start:end] = float(np.quantile(history, quantile))
    return answer


def h1_adaptive_features(df1m: pd.DataFrame, b5: pd.DataFrame) -> pd.DataFrame:
    """Return causal decision-bar features and all predeclared H1 masks.

    ``volume_features`` stamps the existing day/night session and opening-bar
    clock.  A session's threshold is generated before assigning any value to
    that session, so the session's early or late bars cannot affect it.
    """
    out = volume_features(df1m, b5.copy())
    out["atr5_pct"] = out["atr"] / out["close"].replace(0, np.nan)
    out["atr500"] = _base.atr(out, 500)
    out["atr14_atr500"] = out["atr"] / out["atr500"].replace(0, np.nan)

    # factorize(sort=False) follows first completed bar time and makes each
    # day or night unit exactly one rolling-history session.
    session_code = pd.factorize(out["session_id"], sort=False)[0]
    out["session_seq"] = session_code
    out["a60_threshold"] = _prior_session_quantile(out["atr5_pct"], session_code, 60)
    out["a120_threshold"] = _prior_session_quantile(out["atr5_pct"], session_code, 120)

    # At one session type/clock there is at most one completed five-minute bar
    # per session. shift(1) therefore excludes the current session exactly.
    out["atr_same_clock_mean20"] = out.groupby(["session", "clock"], sort=False)["atr"].transform(
        lambda x: x.shift(1).rolling(20, min_periods=20).mean()
    )
    out["b_ratio"] = out["atr"] / out["atr_same_clock_mean20"].replace(0, np.nan)
    out["broll_threshold"] = _prior_session_quantile(out["b_ratio"], session_code, 120)
    out["c_threshold"] = _prior_session_quantile(out["atr14_atr500"], session_code, 120)

    out["h1_a60_low"] = np.isfinite(out["atr5_pct"]) & np.isfinite(out["a60_threshold"]) & (out["atr5_pct"] < out["a60_threshold"])
    out["h1_a120_low"] = np.isfinite(out["atr5_pct"]) & np.isfinite(out["a120_threshold"]) & (out["atr5_pct"] < out["a120_threshold"])
    out["h1_broll_low"] = np.isfinite(out["b_ratio"]) & np.isfinite(out["broll_threshold"]) & (out["b_ratio"] < out["broll_threshold"])
    out["h1_bfix_low"] = np.isfinite(out["b_ratio"]) & (out["b_ratio"] < 0.80)
    out["h1_c_low"] = np.isfinite(out["atr14_atr500"]) & np.isfinite(out["c_threshold"]) & (out["atr14_atr500"] < out["c_threshold"])
    return out


def _build_run() -> Any:
    source = inspect.getsource(_base.run)

    old = '    overrides = p or {}\n    p = {**P, **overrides}\n'
    new = '''    overrides = p or {}
    p = {**P, **overrides}
    # Gate 4 parameters remain compatible.  Adaptive variants only alter a
    # Cmd boolean; Add/G conditions below remain Gate 4's original behavior.
    _mlg_rules = overrides.get("opt_ml_gate", {}) or {}
    _mlg_variant = _mlg_rules.get("variant")
    _mlg_er5_48_threshold = _mlg_rules.get("er5_48_threshold")
    _mlg_cmd_vol_threshold = _mlg_rules.get("session_cum_vol_rel20_threshold")
    _mlg_addg_vol_threshold = _mlg_rules.get("chop_session_cum_vol_rel20_threshold")
    _mlg_cmd_atr_threshold = _mlg_rules.get("cmd_atr5_pct_threshold", _mlg_rules.get("atr5_pct_threshold"))
    _mlg_addg_atr_threshold = _mlg_rules.get("addg_atr5_pct_threshold", _mlg_rules.get("atr5_pct_threshold"))
    _mlg_chop_score_min = _mlg_rules.get("chop_score_min", 2)
    _mlg_adaptive = ("H1_old", "A60", "A120", "B_roll", "B_fix", "C")
    if _mlg_variant is not None:
        if _mlg_variant not in ("G2", "H1", "H4", "H14") + _mlg_adaptive:
            raise ValueError("unknown ML gate variant")
        if not np.isfinite(_mlg_cmd_vol_threshold):
            raise ValueError("finite Cmd cumulative-volume threshold is required")
        if _mlg_variant in ("H1", "H14", "H1_old") and not np.isfinite(_mlg_cmd_atr_threshold):
            raise ValueError("finite Cmd atr5_pct threshold is required")
        if _mlg_variant in ("H4", "H14"):
            if not np.isfinite(_mlg_addg_vol_threshold):
                raise ValueError("finite Add/G cumulative-volume threshold is required")
            if not np.isfinite(_mlg_er5_48_threshold):
                raise ValueError("finite Add/G er5_48 threshold is required")
            if not np.isfinite(_mlg_addg_atr_threshold):
                raise ValueError("finite Add/G atr5_pct threshold is required")
            if _mlg_chop_score_min not in (2, 3):
                raise ValueError("chop_score_min must be 2 or 3")
'''
    if old not in source:
        raise RuntimeError("engine layout changed: parameter anchor missing")
    source = source.replace(old, new, 1)

    old = '    b5 = prepare(df1m, p)\n    n = len(b5)\n'
    new = '''    b5 = prepare(df1m, p)
    # B[i] is the completed decision bar. Every adaptive threshold below was
    # frozen before B[i]'s session began, while its fill remains next open.
    if _mlg_variant is not None:
        _mlg_features = h1_adaptive_features(df1m, b5.copy())
        _mlg_features["er5_48"] = er(_mlg_features["close"], 48)
        if len(_mlg_features) != len(b5) or not _mlg_features["open_ts"].equals(b5["open_ts"]):
            raise AssertionError("ML feature bars are not aligned with engine decision bars")
        _mlg_er5_48 = _mlg_features["er5_48"].to_numpy(dtype=float)
        _mlg_vol = _mlg_features["session_cum_vol_rel20"].to_numpy(dtype=float)
        _mlg_atr = (_mlg_features["atr"] / _mlg_features["close"].replace(0, np.nan)).to_numpy(dtype=float)
        _mlg_cmd_vol_low_arr = np.isfinite(_mlg_vol) & (_mlg_vol < _mlg_cmd_vol_threshold)
        _mlg_cmd_atr_low_arr = (
            np.isfinite(_mlg_atr) & (_mlg_atr < _mlg_cmd_atr_threshold)
            if _mlg_variant in ("H1", "H14", "H1_old") else np.zeros(len(b5), dtype=bool)
        )
        _mlg_adaptive_low_arr = (
            _mlg_features[{"A60": "h1_a60_low", "A120": "h1_a120_low", "B_roll": "h1_broll_low", "B_fix": "h1_bfix_low", "C": "h1_c_low"}[_mlg_variant]].to_numpy(dtype=bool)
            if _mlg_variant in _mlg_adaptive and _mlg_variant != "H1_old" else np.zeros(len(b5), dtype=bool)
        )
        _mlg_addg_vol_low_arr = (
            np.isfinite(_mlg_vol) & (_mlg_vol < _mlg_addg_vol_threshold)
            if _mlg_variant in ("H4", "H14") else np.zeros(len(b5), dtype=bool)
        )
        _mlg_addg_er_low_arr = (
            np.isfinite(_mlg_er5_48) & (_mlg_er5_48 < _mlg_er5_48_threshold)
            if _mlg_variant in ("H4", "H14") else np.zeros(len(b5), dtype=bool)
        )
        _mlg_addg_atr_low_arr = (
            np.isfinite(_mlg_atr) & (_mlg_atr < _mlg_addg_atr_threshold)
            if _mlg_variant in ("H4", "H14") else np.zeros(len(b5), dtype=bool)
        )
        _mlg_cmd_ok_arr = ~(_mlg_cmd_vol_low_arr | _mlg_cmd_atr_low_arr | _mlg_adaptive_low_arr)
        _mlg_addg_ok_arr = ~(
            ((_mlg_addg_vol_low_arr.astype(np.int8) + _mlg_addg_er_low_arr.astype(np.int8)
              + _mlg_addg_atr_low_arr.astype(np.int8)) >= _mlg_chop_score_min)
            if _mlg_variant in ("H4", "H14") else np.zeros(len(b5), dtype=bool)
        )
    n = len(b5)
'''
    if old not in source:
        raise RuntimeError("engine layout changed: bar-preparation anchor missing")
    source = source.replace(old, new, 1)

    old = '''        add_cap = min(3, p["opt_max_lots"])
        allow_g = p["opt_max_lots"] >= 4
'''
    new = '''        add_cap = min(3, p["opt_max_lots"])
        allow_g = p["opt_max_lots"] >= 4
        _mlg_cmd_ok = _mlg_cmd_ok_arr[i]
        _mlg_addg_ok = _mlg_addg_ok_arr[i]
'''
    if old not in source:
        raise RuntimeError("engine layout changed: entry-state anchor missing")
    source = source.replace(old, new, 1)

    replacements = (
        ('        if posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown:\n',
         '        if posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown and _mlg_cmd_ok:\n', "long Cmd"),
        ('        elif posSize == 0 and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger ' + chr(92) + "\n"
         + '                and (adx_ok if p["opt_adx_short"] else True) and bbw_short_ok and not in_cooldown:\n',
         '        elif posSize == 0 and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger ' + chr(92) + "\n"
         + '                and (adx_ok if p["opt_adx_short"] else True) and bbw_short_ok and not in_cooldown and _mlg_cmd_ok:\n', "short Cmd"),
        ('        elif 0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok and not long_pyramid_cooldown and not isLongToxic and mtf_bull and c > avgPrice + baseATR * p["l_pyramid_dist"]:\n',
         '        elif 0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok and _mlg_addg_ok and not long_pyramid_cooldown and not isLongToxic and mtf_bull and c > avgPrice + baseATR * p["l_pyramid_dist"]:\n', "long Add"),
        ('        elif posSize == 3 and allow_g and long_pyramid_cap_ok and not long_pyramid_cooldown and not isLongToxic and c > avgPrice + baseATR * p["l_pyramid_dist"]:\n',
         '        elif posSize == 3 and allow_g and long_pyramid_cap_ok and _mlg_addg_ok and not long_pyramid_cooldown and not isLongToxic and c > avgPrice + baseATR * p["l_pyramid_dist"]:\n', "long G"),
        ('        elif -add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok and not short_pyramid_cooldown and not isShortToxic and mtf_bear and c < avgPrice - baseATR * p["s_pyramid_dist"]:\n',
         '        elif -add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok and _mlg_addg_ok and not short_pyramid_cooldown and not isShortToxic and mtf_bear and c < avgPrice - baseATR * p["s_pyramid_dist"]:\n', "short Add"),
        ('        elif posSize == -3 and allow_g and short_pyramid_cap_ok and not short_pyramid_cooldown and not isShortToxic and c < avgPrice - baseATR * p["s_pyramid_dist"]:\n',
         '        elif posSize == -3 and allow_g and short_pyramid_cap_ok and _mlg_addg_ok and not short_pyramid_cooldown and not isShortToxic and c < avgPrice - baseATR * p["s_pyramid_dist"]:\n', "short G"),
    )
    for before, after, label in replacements:
        if before not in source:
            raise RuntimeError(f"engine layout changed: {label} anchor missing")
        source = source.replace(before, after, 1)

    namespace: dict[str, Any] = {}
    exec(compile(source, __file__, "exec"), globals(), namespace)
    return namespace["run"]


run = _build_run()
