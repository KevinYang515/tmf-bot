"""Local V38 time-rule wrapper; the upstream engine is never modified.

Rules are evaluated on an entry's actual next-bar fill timestamp.  Forced
closes are executed at the specified completed bar's close, reset the position
state through the engine's own ``close_lot`` function, and do not create a
cooldown.  A forced close also cancels any pending entry and suppresses a new
signal on that same close bar, so the following session needs a fresh signal.
"""
from __future__ import annotations

import inspect
import sys
import textwrap
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
import engine_v26_bbw as _base  # noqa: E402


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


def _normalise_rules(value: Any) -> dict[str, Any]:
    """Validate the small declarative vocabulary used by the research run."""
    if value is None:
        return {"name": "base", "block": "none", "force": "none"}
    if not isinstance(value, dict):
        raise ValueError("opt_time_rules must be a dict or None")
    block = value.get("block", "none")
    force = value.get("force", "none")
    valid_block = {
        "none", "h4_cmd", "h4_all", "h4_all_short", "sat_h4_cmd",
        "sat_h4_all", "sat_h3h4_all", "pre_gap48_hour", "fri_to_mon",
        "night_end", "day_end",
    }
    valid_force = {"none", "sat_05", "gap48", "fri_1345", "night_05", "day_1345"}
    if block not in valid_block or force not in valid_force:
        raise ValueError(f"unknown time rule block={block!r}, force={force!r}")
    return {"name": str(value.get("name", block)), "block": block, "force": force}


def _build_run() -> Any:
    source = textwrap.dedent(inspect.getsource(_base.run))

    old = '    b5 = prepare(df1m, p)\n    n = len(b5)\n'
    new = '''    b5 = prepare(df1m, p)
    _time_rules = _normalise_rules(overrides.get("opt_time_rules"))
    _forced_audit = []
    n = len(b5)
'''
    if old not in source:
        raise RuntimeError("engine layout changed: prepare anchor missing")
    source = source.replace(old, new, 1)

    old = '    ts_open = b5["open_ts"].values\n    ts_close = b5["close_ts"].values\n'
    new = '''    ts_open = b5["open_ts"].values
    ts_close = b5["close_ts"].values

    def _is_early_saturday(t):
        q = pd.Timestamp(t)
        return q.weekday() == 5 and q.hour in (3, 4)

    def _entry_blocked(t, kind, dir_):
        q = pd.Timestamp(t)
        block = _time_rules["block"]
        hr, minute, wd = q.hour, q.minute, q.weekday()
        in_h4 = hr == 4
        if block == "none":
            return False
        if block == "h4_cmd":
            return in_h4 and kind == "Cmd"
        if block == "h4_all":
            return in_h4
        if block == "h4_all_short":
            return in_h4 and dir_ < 0
        if block == "sat_h4_cmd":
            return wd == 5 and in_h4 and kind == "Cmd"
        if block == "sat_h4_all":
            return wd == 5 and in_h4
        if block == "sat_h3h4_all":
            return wd == 5 and hr in (3, 4)
        if block == "pre_gap48_hour":
            # The current fill is blocked in the final 60 minutes before a
            # known >=48h calendar gap.  ``_gap48_ends`` is derived solely
            # from exchange timestamps (it is the last close before a gap),
            # never prices.
            return any(end - np.timedelta64(60, "m") <= q.to_datetime64() < end
                       for end in _gap48_ends)
        if block == "fri_to_mon":
            # Friday 13:45 onward through the weekend; sessions resume Monday.
            return wd >= 5 or (wd == 4 and (hr > 13 or (hr == 13 and minute >= 45)))
        if block == "night_end":
            return hr == 4
        if block == "day_end":
            return hr == 13
        raise RuntimeError(f"unhandled time block {block}")

    _gap48_indices = np.flatnonzero(ts_open[1:] - ts_close[:-1] >= np.timedelta64(48, "h"))
    _gap48_starts = ts_open[_gap48_indices + 1]
    _gap48_ends = ts_close[_gap48_indices]

    def _force_reason(i, t_close):
        q = pd.Timestamp(t_close)
        force = _time_rules["force"]
        if force == "none":
            return None
        if force == "sat_05":
            return "TimeFlat_Weekend" if q.weekday() == 5 and q.hour == 5 and q.minute == 0 else None
        if force == "gap48":
            return "TimeFlat_Gap48" if i in _gap48_indices else None
        if force == "fri_1345":
            return "TimeFlat_FriDay" if q.weekday() == 4 and q.hour == 13 and q.minute == 45 else None
        if force == "night_05":
            return "TimeFlat_NightEnd" if q.hour == 5 and q.minute == 0 else None
        if force == "day_1345":
            return "TimeFlat_DayEnd" if q.hour == 13 and q.minute == 45 else None
        raise RuntimeError(f"unhandled time force {force}")
'''
    if old not in source:
        raise RuntimeError("engine layout changed: timestamp anchor missing")
    source = source.replace(old, new, 1)

    old = '''                elif act == "entry":
                    kind, dir_ = arg
                    if kind == "Cmd":
'''
    new = '''                elif act == "entry":
                    kind, dir_ = arg
                    if _entry_blocked(t_open, kind, dir_):
                        continue
                    if kind == "Cmd":
'''
    if old not in source:
        raise RuntimeError("engine layout changed: entry anchor missing")
    source = source.replace(old, new, 1)

    old = '''        # ── 3) 收盤: 指標訊號 → 掛單 ──
        posSize = len(lots) * direction
'''
    new = '''        # ── 3) 收盤: 指標訊號 → 掛單 ──
        _force_reason_now = _force_reason(i, t_close)
        force_flat_now = _force_reason_now is not None
        if force_flat_now:
            # Cancel a signal already pending for the next session and close
            # every surviving lot at this completed bar's close (not next open).
            pending = [x for x in pending if x[0] != "entry"]
            for lot in lots[:]:
                _forced_audit.append(dict(
                    exit_ts=pd.Timestamp(t_close), entry_ts=pd.Timestamp(lot.entry_ts),
                    side="L" if direction > 0 else "S", kind=lot.kind,
                    fill_px=float(c), reason=_force_reason_now,
                ))
                close_lot(lot, c, t_close, _force_reason_now)
        posSize = len(lots) * direction
'''
    if old not in source:
        raise RuntimeError("engine layout changed: close anchor missing")
    source = source.replace(old, new, 1)

    replacements = {
        '        if posSize == 0 and not isLongToxic': '        if not force_flat_now and posSize == 0 and not isLongToxic',
        '        elif posSize == 0 and not isShortToxic': '        elif not force_flat_now and posSize == 0 and not isShortToxic',
        '        elif 0 < posSize < add_cap': '        elif not force_flat_now and 0 < posSize < add_cap',
        '        elif posSize == 3 and allow_g': '        elif not force_flat_now and posSize == 3 and allow_g',
        '        elif -add_cap < posSize < 0': '        elif not force_flat_now and -add_cap < posSize < 0',
        '        elif posSize == -3 and allow_g': '        elif not force_flat_now and posSize == -3 and allow_g',
    }
    for old, new in replacements.items():
        if old not in source:
            raise RuntimeError(f"engine layout changed: entry branch missing: {old}")
        source = source.replace(old, new, 1)

    old = '''    if not tr.empty:
        tr = tr.sort_values("exit_ts").reset_index(drop=True)
    return tr
'''
    new = '''    if not tr.empty:
        tr = tr.sort_values("exit_ts").reset_index(drop=True)
    tr.attrs["time_rules"] = _time_rules
    tr.attrs["time_forced_closes"] = _forced_audit
    tr.attrs["time_gap48_starts"] = [pd.Timestamp(x) for x in _gap48_starts]
    return tr
'''
    if old not in source:
        raise RuntimeError("engine layout changed: return anchor missing")
    source = source.replace(old, new, 1)

    namespace: dict[str, Any] = {}
    exec(compile(source, __file__, "exec"), globals(), namespace)
    return namespace["run"]


run = _build_run()
