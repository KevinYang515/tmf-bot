"""Read-only V38 engine wrapper for causal daily FinLab bucket filters."""
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

for _key, _value in vars(_base).items():
    if not _key.startswith("__"):
        globals().setdefault(_key, _value)


def _build_run() -> Any:
    source = inspect.getsource(_base.run)
    old = '    b5 = prepare(df1m, p)\n    n = len(b5)\n'
    new = '''    b5 = prepare(df1m, p)
    _ideas_filter = overrides.get("opt_finlab_ideas_filter")
    if _ideas_filter is not None:
        _ideas_filter = _ideas_filter.sort_values("available_ts").reset_index(drop=True)
        _fi_ts = _ideas_filter.available_ts.to_numpy(dtype="datetime64[ns]")
        _fi_long = _ideas_filter.score_long.to_numpy(float)
        _fi_short = _ideas_filter.score_short.to_numpy(float)
        _fi_low = float(_ideas_filter.low.iloc[0])
        _fi_high = float(_ideas_filter.high.iloc[0])
        _fi_bad = str(_ideas_filter.bad_bucket.iloc[0])
        _fi_target = str(_ideas_filter.target.iloc[0])
        if _fi_target not in ("Cmd", "Add"):
            raise ValueError("FinLab filter target must be Cmd or Add")
        def _fi_bad_now(t, dir_):
            j = np.searchsorted(_fi_ts, np.datetime64(t), side="right") - 1
            if j < 0:
                return False
            score = _fi_long[j] if dir_ > 0 else _fi_short[j]
            if not np.isfinite(score):
                return False
            if _fi_bad == "low":
                return score <= _fi_low
            if _fi_bad == "mid":
                return _fi_low < score < _fi_high
            if _fi_bad == "high":
                return score >= _fi_high
            raise ValueError("unknown FinLab bad bucket")
        def _fi_ok(t, dir_, kind):
            return kind != _fi_target or not _fi_bad_now(t, dir_)
    else:
        def _fi_ok(t, dir_, kind):
            return True
    n = len(b5)
'''
    if old not in source:
        raise RuntimeError("FinLab wrapper prepare anchor missing")
    source = source.replace(old, new, 1)

    replacements = [
        (
            'if posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown:',
            'if posSize == 0 and not isLongToxic and _fi_ok(t_close, 1, "Cmd") and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown:',
            "long Cmd",
        ),
        (
            'elif posSize == 0 and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger ',
            'elif posSize == 0 and not isShortToxic and _fi_ok(t_close, -1, "Cmd") and mtf_bear and c < B["ema_short"][i] and shortTrigger ',
            "short Cmd",
        ),
        (
            'elif 0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok and not long_pyramid_cooldown and not isLongToxic and mtf_bull and c > avgPrice + baseATR * p["l_pyramid_dist"]:',
            'elif 0 < posSize < add_cap and _fi_ok(t_close, 1, "Add") and add_gate_ok and long_pyramid_cap_ok and not long_pyramid_cooldown and not isLongToxic and mtf_bull and c > avgPrice + baseATR * p["l_pyramid_dist"]:',
            "long Add",
        ),
        (
            'elif -add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok and not short_pyramid_cooldown and not isShortToxic and mtf_bear and c < avgPrice - baseATR * p["s_pyramid_dist"]:',
            'elif -add_cap < posSize < 0 and _fi_ok(t_close, -1, "Add") and add_gate_ok and short_pyramid_cap_ok and not short_pyramid_cooldown and not isShortToxic and mtf_bear and c < avgPrice - baseATR * p["s_pyramid_dist"]:',
            "short Add",
        ),
    ]
    for old, new, label in replacements:
        if old not in source:
            raise RuntimeError(f"FinLab wrapper {label} anchor missing")
        source = source.replace(old, new, 1)
    namespace: dict[str, Any] = {}
    exec(compile(source, __file__, "exec"), globals(), namespace)
    return namespace["run"]


run = _build_run()
