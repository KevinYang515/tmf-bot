"""Read-only V38 engine wrapper for the pre-registered ML feature gates.

The vendor engine is imported, never edited. This module recompiles its run
function and appends boolean conditions at existing Cmd/Add/G points. Without
opt_ml_gate it remains source-equivalent to the vendor run.
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

# Exact published causal definitions that built ml_features_panel.csv.
from run_ml_attrib import er, volume_features  # noqa: E402


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


def _build_run() -> Any:
    source = inspect.getsource(_base.run)

    old = '    overrides = p or {}\n    p = {**P, **overrides}\n'
    new = '''    overrides = p or {}
    p = {**P, **overrides}
    # A missing hook is intentionally inert. Thresholds are calculated by
    # the driver from the frozen v28 panel and supplied as plain numbers.
    _mlg_rules = overrides.get("opt_ml_gate", {}) or {}
    _mlg_variant = _mlg_rules.get("variant")
    _mlg_er5_48_threshold = _mlg_rules.get("er5_48_threshold")
    _mlg_session_cum_vol_rel20_threshold = _mlg_rules.get("session_cum_vol_rel20_threshold")
    _mlg_chop_session_cum_vol_rel20_threshold = _mlg_rules.get("chop_session_cum_vol_rel20_threshold")
    _mlg_atr5_pct_threshold = _mlg_rules.get("atr5_pct_threshold")
    if _mlg_variant is not None:
        if _mlg_variant not in ("G1", "G2", "G3", "G4", "H1", "H2", "H3", "H4"):
            raise ValueError("unknown ML gate variant")
        if _mlg_variant in ("G1", "G3", "G4", "H2", "H3", "H4") and not np.isfinite(_mlg_er5_48_threshold):
            raise ValueError("finite er5_48 threshold is required")
        if _mlg_variant in ("G2", "G3", "H1", "H2", "H3", "H4") and not np.isfinite(_mlg_session_cum_vol_rel20_threshold):
            raise ValueError("finite session cumulative-volume threshold is required")
        if _mlg_variant == "H4" and not np.isfinite(_mlg_chop_session_cum_vol_rel20_threshold):
            raise ValueError("finite H4 chop cumulative-volume threshold is required")
        if _mlg_variant in ("H1", "H3", "H4") and not np.isfinite(_mlg_atr5_pct_threshold):
            raise ValueError("finite atr5_pct threshold is required")
'''
    if old not in source:
        raise RuntimeError("engine layout changed: parameter anchor missing")
    source = source.replace(old, new, 1)

    old = '    b5 = prepare(df1m, p)\n    n = len(b5)\n'
    new = '''    b5 = prepare(df1m, p)
    # Row i is the completed signal bar that can only schedule a next-open
    # fill. The calculation itself matches run_ml_attrib.py.
    if _mlg_variant is not None:
        _mlg_features = volume_features(df1m, b5.copy())
        _mlg_features["er5_48"] = er(_mlg_features["close"], 48)
        if len(_mlg_features) != len(b5) or not _mlg_features["open_ts"].equals(b5["open_ts"]):
            raise AssertionError("ML feature bars are not aligned with engine decision bars")
        _mlg_er5_48 = _mlg_features["er5_48"].to_numpy(dtype=float)
        _mlg_session_cum_vol_rel20 = _mlg_features["session_cum_vol_rel20"].to_numpy(dtype=float)
        _mlg_atr5_pct = (_mlg_features["atr"] / _mlg_features["close"].replace(0, np.nan)).to_numpy(dtype=float)
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
        # NaN is not below a threshold, hence it preserves the v28 decision.
        # Both arrays hold B[i], never a current/future unfinished bar.
        _mlg_er_low = (_mlg_variant in ("G1", "G3", "G4", "H2", "H3", "H4") and np.isfinite(_mlg_er5_48[i])
                       and _mlg_er5_48[i] < _mlg_er5_48_threshold)
        _mlg_vol_low = (_mlg_variant in ("G2", "G3", "H1", "H2", "H3", "H4") and np.isfinite(_mlg_session_cum_vol_rel20[i])
                        and _mlg_session_cum_vol_rel20[i] < _mlg_session_cum_vol_rel20_threshold)
        _mlg_chop_vol_low = (_mlg_variant == "H4" and np.isfinite(_mlg_session_cum_vol_rel20[i])
                             and _mlg_session_cum_vol_rel20[i] < _mlg_chop_session_cum_vol_rel20_threshold)
        _mlg_atr_low = (_mlg_variant in ("H1", "H3", "H4") and np.isfinite(_mlg_atr5_pct[i])
                        and _mlg_atr5_pct[i] < _mlg_atr5_pct_threshold)
        _mlg_chop_score = int(_mlg_chop_vol_low if _mlg_variant == "H4" else _mlg_vol_low) + int(_mlg_er_low) + int(_mlg_atr_low)
        _mlg_cmd_ok = not (
            (_mlg_variant == "G1" and _mlg_er_low)
            or (_mlg_variant == "G2" and _mlg_vol_low)
            or (_mlg_variant == "G3" and _mlg_er_low and _mlg_vol_low)
            or (_mlg_variant == "H1" and (_mlg_vol_low or _mlg_atr_low))
            or (_mlg_variant == "H2" and (_mlg_vol_low or _mlg_er_low))
            or (_mlg_variant == "H3" and _mlg_chop_score >= 2)
            or (_mlg_variant == "H4" and _mlg_vol_low)
        )
        _mlg_addg_ok = not ((_mlg_variant == "G4" and _mlg_er_low)
                             or (_mlg_variant == "H4" and _mlg_chop_score >= 2))
'''
    if old not in source:
        raise RuntimeError("engine layout changed: entry-state anchor missing")
    source = source.replace(old, new, 1)

    replacements = (
        ('''        if posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown:
''',
         '''        if posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown and _mlg_cmd_ok:
''', "long Cmd"),
        ('        elif posSize == 0 and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger ' + "\\\n"
         + '                and (adx_ok if p["opt_adx_short"] else True) and bbw_short_ok and not in_cooldown:\n',
         '        elif posSize == 0 and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger ' + "\\\n"
         + '                and (adx_ok if p["opt_adx_short"] else True) and bbw_short_ok and not in_cooldown and _mlg_cmd_ok:\n', "short Cmd"),
        ('''        elif 0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok and not long_pyramid_cooldown and not isLongToxic and mtf_bull and c > avgPrice + baseATR * p["l_pyramid_dist"]:
''',
         '''        elif 0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok and _mlg_addg_ok and not long_pyramid_cooldown and not isLongToxic and mtf_bull and c > avgPrice + baseATR * p["l_pyramid_dist"]:
''', "long Add"),
        ('''        elif posSize == 3 and allow_g and long_pyramid_cap_ok and not long_pyramid_cooldown and not isLongToxic and c > avgPrice + baseATR * p["l_pyramid_dist"]:
''',
         '''        elif posSize == 3 and allow_g and long_pyramid_cap_ok and _mlg_addg_ok and not long_pyramid_cooldown and not isLongToxic and c > avgPrice + baseATR * p["l_pyramid_dist"]:
''', "long G"),
        ('''        elif -add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok and not short_pyramid_cooldown and not isShortToxic and mtf_bear and c < avgPrice - baseATR * p["s_pyramid_dist"]:
''',
         '''        elif -add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok and _mlg_addg_ok and not short_pyramid_cooldown and not isShortToxic and mtf_bear and c < avgPrice - baseATR * p["s_pyramid_dist"]:
''', "short Add"),
        ('''        elif posSize == -3 and allow_g and short_pyramid_cap_ok and not short_pyramid_cooldown and not isShortToxic and c < avgPrice - baseATR * p["s_pyramid_dist"]:
''',
         '''        elif posSize == -3 and allow_g and short_pyramid_cap_ok and _mlg_addg_ok and not short_pyramid_cooldown and not isShortToxic and c < avgPrice - baseATR * p["s_pyramid_dist"]:
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
