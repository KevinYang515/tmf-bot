"""Gate 4 wrapper + optional session-last-bar entry block (block_last_bar).

It reuses Gate 3's imports and extends only the ML hook with H14, parameterized
H1/H4 percentiles, and the predeclared strict H4 score.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any

import numpy as np

ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
import engine_v26_bbw as _base  # noqa: E402

from run_ml_attrib import er, volume_features  # noqa: E402


# Re-export the read-only engine dependencies needed by the compiled function.
for _name, _value in vars(_base).items():
    if not _name.startswith("__"):
        globals().setdefault(_name, _value)

POINT_VALUE = _base.POINT_VALUE
COMMISSION = _base.COMMISSION
P = _base.P
load_1min = _base.load_1min



def _g2_vf(df1, b5, lb):
    """volume_features with a configurable same-clock lookback (lb=20 reproduces run_ml_attrib)."""
    if lb == 20:
        return volume_features(df1, b5)
    from run_ml_attrib import make_sessions, safe_div
    minute = df1.copy(); minute["bin"] = minute["open_ts"].dt.floor("5min")
    vol = minute.groupby("bin", sort=True)["volume"].sum().rename("vol5").reset_index().rename(columns={"bin": "open_ts"})
    out = make_sessions(b5.merge(vol, on="open_ts", how="left", validate="one_to_one"))
    out["session_cum_vol"] = out.groupby("session_id", sort=False)["vol5"].cumsum()
    mp = min(5, lb)
    out["cum_same_clock_mean"] = out.groupby(["session", "clock"], sort=False)["session_cum_vol"].transform(
        lambda x: x.shift(1).rolling(lb, min_periods=mp).mean())
    out["session_cum_vol_rel20"] = safe_div(out["session_cum_vol"], out["cum_same_clock_mean"])
    return out


def _build_run() -> Any:
    source = inspect.getsource(_base.run)

    old = '    overrides = p or {}\n    p = {**P, **overrides}\n'
    new = '''    overrides = p or {}
    p = {**P, **overrides}
    # All thresholds are frozen by the Gate 4 driver from the v28 panel.
    _mlg_rules = overrides.get("opt_ml_gate", {}) or {}
    _mlg_variant = _mlg_rules.get("variant")
    _mlg_er5_48_threshold = _mlg_rules.get("er5_48_threshold")
    _mlg_cmd_vol_threshold = _mlg_rules.get("session_cum_vol_rel20_threshold")
    _mlg_addg_vol_threshold = _mlg_rules.get("chop_session_cum_vol_rel20_threshold")
    _mlg_cmd_atr_threshold = _mlg_rules.get("cmd_atr5_pct_threshold", _mlg_rules.get("atr5_pct_threshold"))
    _mlg_addg_atr_threshold = _mlg_rules.get("addg_atr5_pct_threshold", _mlg_rules.get("atr5_pct_threshold"))
    _mlg_chop_score_min = _mlg_rules.get("chop_score_min", 2)
    if _mlg_variant is not None:
        if _mlg_variant not in ("G2", "H1", "H4", "H14"):
            raise ValueError("unknown ML gate variant")
        if not np.isfinite(_mlg_cmd_vol_threshold):
            raise ValueError("finite Cmd cumulative-volume threshold is required")
        if _mlg_variant in ("H1", "H14") and not np.isfinite(_mlg_cmd_atr_threshold):
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
    # B[i] is a completed decision bar; a signal can only fill next open.
    if _mlg_variant is not None:
        _mlg_features = _g2_vf(df1m, b5.copy(), _mlg_rules.get("lookback", 20))
        _mlg_features["er5_48"] = er(_mlg_features["close"], 48)
        if len(_mlg_features) != len(b5) or not _mlg_features["open_ts"].equals(b5["open_ts"]):
            raise AssertionError("ML feature bars are not aligned with engine decision bars")
        _mlg_er5_48 = _mlg_features["er5_48"].to_numpy(dtype=float)
        _mlg_vol = _mlg_features["session_cum_vol_rel20"].to_numpy(dtype=float)
        _mlg_atr = (_mlg_features["atr"] / _mlg_features["close"].replace(0, np.nan)).to_numpy(dtype=float)
        # Gate results are unchanged; precomputing the causal Boolean masks
        # prevents repeated NumPy scalar dispatch inside the vendor bar loop.
        _mlg_cmd_vol_low_arr = np.isfinite(_mlg_vol) & (_mlg_vol < _mlg_cmd_vol_threshold)
        _mlg_cmd_atr_low_arr = (
            np.isfinite(_mlg_atr) & (_mlg_atr < _mlg_cmd_atr_threshold)
            if _mlg_variant in ("H1", "H14") else np.zeros(len(b5), dtype=bool)
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
        _mlg_cmd_ok_arr = ~(_mlg_cmd_vol_low_arr | _mlg_cmd_atr_low_arr)
        _mlg_addg_ok_arr = ~(
            ((_mlg_addg_vol_low_arr.astype(np.int8) + _mlg_addg_er_low_arr.astype(np.int8)
              + _mlg_addg_atr_low_arr.astype(np.int8)) >= _mlg_chop_score_min)
            if _mlg_variant in ("H4", "H14") else np.zeros(len(b5), dtype=bool)
        )
        # Session-last-bar rule: a signal on the bar closing 13:45 or 05:00 would only
        # fill at the next session open (gap); block new Cmd and Add/G there.
        if _mlg_rules.get("block_last_bar"):
            _mlg_ct = pd.to_datetime(b5["close_ts"])
            _mlg_hm = (_mlg_ct.dt.hour * 60 + _mlg_ct.dt.minute).to_numpy()
            _mlg_last = (_mlg_hm == 13 * 60 + 45) | (_mlg_hm == 5 * 60)
            _mlg_cmd_ok_arr = _mlg_cmd_ok_arr & ~_mlg_last
            _mlg_addg_ok_arr = _mlg_addg_ok_arr & ~_mlg_last
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
         '        if posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown and _mlg_cmd_ok:\n',
         "long Cmd"),
        ('        elif posSize == 0 and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger \\\n                and (adx_ok if p["opt_adx_short"] else True) and bbw_short_ok and not in_cooldown:\n',
         '        elif posSize == 0 and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger \\\n                and (adx_ok if p["opt_adx_short"] else True) and bbw_short_ok and not in_cooldown and _mlg_cmd_ok:\n',
         "short Cmd"),
        ('        elif 0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok and not long_pyramid_cooldown and not isLongToxic and mtf_bull and c > avgPrice + baseATR * p["l_pyramid_dist"]:\n',
         '        elif 0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok and _mlg_addg_ok and not long_pyramid_cooldown and not isLongToxic and mtf_bull and c > avgPrice + baseATR * p["l_pyramid_dist"]:\n',
         "long Add"),
        ('        elif posSize == 3 and allow_g and long_pyramid_cap_ok and not long_pyramid_cooldown and not isLongToxic and c > avgPrice + baseATR * p["l_pyramid_dist"]:\n',
         '        elif posSize == 3 and allow_g and long_pyramid_cap_ok and _mlg_addg_ok and not long_pyramid_cooldown and not isLongToxic and c > avgPrice + baseATR * p["l_pyramid_dist"]:\n',
         "long G"),
        ('        elif -add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok and not short_pyramid_cooldown and not isShortToxic and mtf_bear and c < avgPrice - baseATR * p["s_pyramid_dist"]:\n',
         '        elif -add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok and _mlg_addg_ok and not short_pyramid_cooldown and not isShortToxic and mtf_bear and c < avgPrice - baseATR * p["s_pyramid_dist"]:\n',
         "short Add"),
        ('        elif posSize == -3 and allow_g and short_pyramid_cap_ok and not short_pyramid_cooldown and not isShortToxic and c < avgPrice - baseATR * p["s_pyramid_dist"]:\n',
         '        elif posSize == -3 and allow_g and short_pyramid_cap_ok and _mlg_addg_ok and not short_pyramid_cooldown and not isShortToxic and c < avgPrice - baseATR * p["s_pyramid_dist"]:\n',
         "short G"),
    )
    for before, after, label in replacements:
        if before not in source:
            raise RuntimeError(f"engine layout changed: {label} anchor missing")
        source = source.replace(before, after, 1)

    namespace: dict[str, Any] = {}
    exec(compile(source, __file__, "exec"), globals(), namespace)
    return namespace["run"]


run = _build_run()
