"""Read-only, in-memory V38 wrapper for the new-directions study."""
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
    _newdirs_unblock = overrides.get("opt_newdirs_unblock", "none")
    _newdirs_filter = overrides.get("opt_newdirs_filter")
    if _newdirs_unblock not in ("none", "15_16", "17_20", "01_02", "long_04", "short_21"):
        raise ValueError("unknown opt_newdirs_unblock")
    if _newdirs_filter is not None:
        _newdirs_filter = _newdirs_filter.sort_values("available_ts").reset_index(drop=True)
        _nf_ts = _newdirs_filter.available_ts.to_numpy(dtype="datetime64[ns]")
        _nf_score = _newdirs_filter.score.to_numpy(float)
        _nf_low = float(_newdirs_filter.low_threshold.iloc[0])
        _nf_high = float(_newdirs_filter.high_threshold.iloc[0])
        _nf_mode = str(_newdirs_filter.mode.iloc[0])
        def _newdirs_cmd_ok(t, dir_):
            j = np.searchsorted(_nf_ts, np.datetime64(t), side="right") - 1
            if j < 0 or not np.isfinite(_nf_score[j]): return True
            aligned = _nf_score[j] * dir_
            if _nf_mode == "block_opposes": return aligned > _nf_low
            if _nf_mode == "only_supports": return aligned >= _nf_high
            raise ValueError("unknown daily filter mode")
    else:
        def _newdirs_cmd_ok(t, dir_): return True
    n = len(b5)
'''
    if old not in source: raise RuntimeError("prepare anchor missing")
    source = source.replace(old, new, 1)

    old = '''        isBaseToxic = (15 <= hr <= 20) or hr in (1, 2)
        if p["opt_block_h0"] and hr == 0:
            isBaseToxic = True
        if p["opt_block_open"] and hr == 8:
            isBaseToxic = True
        isLongToxic = isBaseToxic or hr == 4
        isShortToxic = isBaseToxic or hr == 21
'''
    new = '''        isBaseToxic = (15 <= hr <= 20) or hr in (1, 2)
        if _newdirs_unblock == "15_16" and hr in (15, 16): isBaseToxic = False
        elif _newdirs_unblock == "17_20" and 17 <= hr <= 20: isBaseToxic = False
        elif _newdirs_unblock == "01_02" and hr in (1, 2): isBaseToxic = False
        if p["opt_block_h0"] and hr == 0: isBaseToxic = True
        if p["opt_block_open"] and hr == 8: isBaseToxic = True
        isLongToxic = isBaseToxic or (hr == 4 and _newdirs_unblock != "long_04")
        isShortToxic = isBaseToxic or (hr == 21 and _newdirs_unblock != "short_21")
'''
    if old not in source: raise RuntimeError("toxic-hour anchor missing")
    source = source.replace(old, new, 1)

    old = 'if posSize == 0 and not isLongToxic and mtf_bull'
    new = 'if posSize == 0 and not isLongToxic and _newdirs_cmd_ok(B["close_ts"][i], 1) and mtf_bull'
    if old not in source: raise RuntimeError("long Cmd anchor missing")
    source = source.replace(old, new, 1)
    old = 'elif posSize == 0 and not isShortToxic and mtf_bear'
    new = 'elif posSize == 0 and not isShortToxic and _newdirs_cmd_ok(B["close_ts"][i], -1) and mtf_bear'
    if old not in source: raise RuntimeError("short Cmd anchor missing")
    source = source.replace(old, new, 1)
    namespace: dict[str, Any] = {}
    exec(compile(source, __file__, "exec"), globals(), namespace)
    return namespace["run"]


run = _build_run()
