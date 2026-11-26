"""Research wrapper for the calendar/re-entry study.

The vendor V38 engine is imported read-only.  This module recompiles only its
``run`` function with a narrow, declarative research hook for the predeclared
cooldown/re-entry and Add protection variants.  With no
``opt_calendar_rules`` override the generated function is deliberately
identical in behaviour to the vendor engine; the driver asserts that fact
against the checked-in v28/v29 trade ledgers.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any


ENGINE_DIR = Path(r"E:\stock_recovery\github_repos\tmf-bot\backtest\strategy_v26")
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
import engine_v26_bbw as _base  # noqa: E402


# The dynamically compiled function refers to the vendor module globals.  Do
# not clone or modify its engine implementation.
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
    # ``opt_calendar_rules`` is intentionally outside the vendor parameter
    # dictionary.  The absent/empty form is inert and is used for regression
    # reproduction before every study run.
    _calendar_rules = overrides.get("opt_calendar_rules", {}) or {}
    _calendar_cd_mode = _calendar_rules.get("cooldown", "none")
    _calendar_cd_min = int(_calendar_rules.get("cooldown_minutes", 0))
    _calendar_same_dir_min = int(_calendar_rules.get("same_dir_minutes", 0))
    _calendar_loss_streak_min = int(_calendar_rules.get("loss_streak_minutes", 0))
    _calendar_add_lock_trigger = float(_calendar_rules.get("add_lock_trigger", 0.0))
    _calendar_add_lock_atr = float(_calendar_rules.get("add_lock_atr", 0.0))
    _calendar_mother_stop = bool(_calendar_rules.get("mother_stop", False))
    # Event rules are a separate, opt-in research hook.  They are evaluated
    # at actual next-open fills, rather than at prior signal-bar closes.
    _event_rules = overrides.get("opt_event_rules", {}) or {}
    _event_block_windows = tuple(
        (np.datetime64(a), np.datetime64(b))
        for a, b in _event_rules.get("block_entry_windows", [])
    )
    _event_flatten_times = {
        np.datetime64(t) for t in _event_rules.get("flatten_add_g_at", [])
    }
    def _event_entry_blocked(t, kind):
        return (kind in ("Cmd", "Add")
                and any(start <= t < end for start, end in _event_block_windows))
    if _calendar_cd_mode not in ("none", "after_sl", "all_exits"):
        raise ValueError("unknown calendar cooldown mode")
'''
    if old not in source:
        raise RuntimeError("engine layout changed: parameter anchor missing")
    source = source.replace(old, new, 1)

    old = '''    prev_cross_state = {}

    i0 = 1
'''
    new = '''    prev_cross_state = {}
    # Re-entry state is separate from legacy cooldown state so the variants
    # retain their stated scope: only a new Cmd is ever blocked.
    _calendar_same_dir_until = {1: None, -1: None}
    _calendar_campaign_pnl = 0.0
    _calendar_loss_streak = 0

    i0 = 1
'''
    if old not in source:
        raise RuntimeError("engine layout changed: state anchor missing")
    source = source.replace(old, new, 1)

    old = '''    def close_lot(lot, px, t, comment):
        nonlocal direction, short_pyramid_orders, long_pyramid_orders
'''
    new = '''    def close_lot(lot, px, t, comment):
        nonlocal direction, short_pyramid_orders, long_pyramid_orders
        nonlocal cooldown_until, _calendar_campaign_pnl, _calendar_loss_streak
'''
    if old not in source:
        raise RuntimeError("engine layout changed: close declaration anchor missing")
    source = source.replace(old, new, 1)

    old = '''        trades.append(dict(side="L" if exit_direction > 0 else "S", kind=lot.kind,
                           entry_ts=lot.entry_ts, entry_px=lot.entry_px,
                           exit_ts=t, exit_px=px, exit_sig=comment, pnl=pnl))
        # Trigger only after two same-direction Add/G loss exits inside four
'''
    new = '''        trades.append(dict(side="L" if exit_direction > 0 else "S", kind=lot.kind,
                           entry_ts=lot.entry_ts, entry_px=lot.entry_px,
                           exit_ts=t, exit_px=px, exit_sig=comment, pnl=pnl))
        _calendar_campaign_pnl += pnl
        if _calendar_same_dir_min > 0:
            _calendar_same_dir_until[exit_direction] = (
                t + np.timedelta64(_calendar_same_dir_min, "m")
            )
        if (_calendar_cd_mode == "after_sl" and comment.endswith("_SL")) or \
                _calendar_cd_mode == "all_exits":
            cooldown_until = t + np.timedelta64(_calendar_cd_min, "m")
        # A campaign is complete precisely when this is its final live lot.
        # Count loss campaigns, not individual losing lots.
        if len(lots) == 1 and _calendar_loss_streak_min > 0:
            if _calendar_campaign_pnl <= 0:
                _calendar_loss_streak += 1
                if _calendar_loss_streak >= 2:
                    cooldown_until = t + np.timedelta64(_calendar_loss_streak_min, "m")
            else:
                _calendar_loss_streak = 0
        # Trigger only after two same-direction Add/G loss exits inside four
'''
    if old not in source:
        raise RuntimeError("engine layout changed: close accounting anchor missing")
    source = source.replace(old, new, 1)

    old = '''                elif act == "entry":
                    kind, dir_ = arg
                    if kind == "Cmd":
                        short_pyramid_orders = 0
'''
    new = '''                elif act == "entry":
                    kind, dir_ = arg
                    if _event_entry_blocked(t_open, kind):
                        continue
                    if kind == "Cmd":
                        _calendar_campaign_pnl = 0.0
                        short_pyramid_orders = 0
'''
    if old not in source:
        raise RuntimeError("engine layout changed: Cmd entry anchor missing")
    source = source.replace(old, new, 1)

    old = '''            pending = []

        #'''
    new = '''            pending = []

        # Predeclared event flatten: close only already-filled Add/G lots at
        # the exchange open exactly five minutes before a release. Cmd lots
        # are deliberately untouched, and the absent hook is inert.
        if np.datetime64(t_open) in _event_flatten_times:
            for lot in [x for x in lots if x.kind in ("Add", "G")]:
                close_lot(lot, o, t_open, "Event Flatten Add/G")

        #'''
    if old not in source:
        raise RuntimeError("engine layout changed: event flatten anchor missing")
    source = source.replace(old, new, 1)

    old = '''                    for lot in lots:
                        if not lot.bracket_live or lot.trail_act is None:
                            continue
                        if not lot.trail_on and (ext - lot.trail_act) * direction >= 0:
'''
    new = '''                    for lot in lots:
                        if not lot.bracket_live or lot.trail_act is None:
                            continue
                        # Own-ATR profit lock for Add lots only.  It is set
                        # during the favourable intrabar segment, before a
                        # later adverse segment can test it.
                        if (lot.kind == "Add" and _calendar_add_lock_trigger > 0
                                and np.isfinite(lot.entry_atr)
                                and (ext - lot.entry_px) * direction >=
                                _calendar_add_lock_trigger * lot.entry_atr):
                            lot.be_stop = round(
                                lot.entry_px + direction * _calendar_add_lock_atr * lot.entry_atr
                            )
                        if not lot.trail_on and (ext - lot.trail_act) * direction >= 0:
'''
    if old not in source:
        raise RuntimeError("engine layout changed: favourable segment anchor missing")
    source = source.replace(old, new, 1)

    old = '''            ef, ef_p = B["ema_fast"][i], B["ema_fast"][i - 1]
'''
    new = '''            # A mother-Cmd stop can only tighten an Add stop: max for a
            # long campaign, min for a short campaign.  The Cmd effective
            # stop includes its current BE/trailing state, not merely SL.
            if _calendar_mother_stop:
                _calendar_mother = next((x for x in lots if x.kind == "Cmd"), None)
                _calendar_mother_eff = (
                    _eff_stop(_calendar_mother, direction)
                    if _calendar_mother is not None else None
                )
                if _calendar_mother_eff is not None:
                    for _calendar_add in (x for x in lots if x.kind == "Add"):
                        if _calendar_add.loss_stop is None:
                            _calendar_add.loss_stop = _calendar_mother_eff
                        elif direction > 0:
                            _calendar_add.loss_stop = max(
                                _calendar_add.loss_stop, _calendar_mother_eff
                            )
                        else:
                            _calendar_add.loss_stop = min(
                                _calendar_add.loss_stop, _calendar_mother_eff
                            )
            ef, ef_p = B["ema_fast"][i], B["ema_fast"][i - 1]
'''
    if old not in source:
        raise RuntimeError("engine layout changed: mother-stop anchor missing")
    source = source.replace(old, new, 1)

    old = '''        in_cooldown = cooldown_until is not None and t_close < cooldown_until
        long_pyramid_cooldown = (
'''
    new = '''        in_cooldown = cooldown_until is not None and t_close < cooldown_until
        def _calendar_cmd_ok(dir_):
            until = _calendar_same_dir_until[dir_]
            return until is None or t_close >= until
        long_pyramid_cooldown = (
'''
    if old not in source:
        raise RuntimeError("engine layout changed: cooldown anchor missing")
    source = source.replace(old, new, 1)

    old_long = '''        if posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown:
'''
    new_long = '''        if posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown and _calendar_cmd_ok(1):
'''
    old_short = '''        elif posSize == 0 and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger \\
                and (adx_ok if p["opt_adx_short"] else True) and bbw_short_ok and not in_cooldown:
'''
    new_short = '''        elif posSize == 0 and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger \\
                and (adx_ok if p["opt_adx_short"] else True) and bbw_short_ok and not in_cooldown and _calendar_cmd_ok(-1):
'''
    for before, after, label in ((old_long, new_long, "long Cmd"), (old_short, new_short, "short Cmd")):
        if before not in source:
            raise RuntimeError(f"engine layout changed: {label} signal anchor missing")
        source = source.replace(before, after, 1)

    namespace: dict[str, Any] = {}
    exec(compile(source, __file__, "exec"), globals(), namespace)
    return namespace["run"]


run = _build_run()
