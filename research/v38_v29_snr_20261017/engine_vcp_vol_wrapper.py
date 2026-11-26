"""Read-only retest-entry wrapper for the upstream V38 engine.

Only the predeclared research rule is added: replace each flat Cmd next-open
market entry with a 0.5-ATR directional retest limit, valid for its first
twelve 5-minute bars.  No upstream engine file is edited.
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

# ``exec`` below recompiles the engine's own run body, so expose its existing
# globals rather than duplicating any exit/stop/pyramid implementation.
for _name, _value in vars(_base).items():
    if not _name.startswith("__"):
        globals().setdefault(_name, _value)


def _build_run() -> Any:
    source = inspect.getsource(_base.run)

    old = '    b5 = prepare(df1m, p)\n    n = len(b5)\n'
    new = '''    retest_x = overrides.get("opt_retest_cmd_atr", 0.0)
    if retest_x <= 0:
        raise ValueError("opt_retest_cmd_atr must be positive in retest wrapper")
    if intrabar_mode != "1min":
        raise ValueError("retest wrapper requires intrabar_mode='1min'")
    b5 = prepare(df1m, p)
    n = len(b5)
'''
    if old not in source:
        raise RuntimeError("engine layout changed: prepare anchor missing")
    source = source.replace(old, new, 1)

    old = '    prev_cross_state = {}\n\n    i0 = 1\n'
    new = '''    prev_cross_state = {}
    # A dict is used instead of a Lot until the limit is actually touched.
    # It prevents a fresh Cmd signal from bypassing the still-live limit.
    retest_order = None

    i0 = 1
'''
    if old not in source:
        raise RuntimeError("engine layout changed: state anchor missing")
    source = source.replace(old, new, 1)

    old = '''                elif act == "entry":
                    kind, dir_ = arg
                    if kind == "Cmd":
                        short_pyramid_orders = 0
                        long_pyramid_orders = 0
                        base_entry_px = o
                    # This is a next-open fill, so classify it from the
                    # immediately preceding completed signal bar only.
                    stale_hours = p["opt_stale_hr"]
                    entry_signal_pct = B["atr_regime_pct"][i - 1]
                    if (p["opt_regime_stale_enabled"]
                            and np.isfinite(entry_signal_pct)
                            and entry_signal_pct > p["opt_regime_stale_pct_threshold"]):
                        stale_hours = p["opt_regime_stale_hours_high"]
                    lots.append(Lot(
                        kind, o, t_open, bracket_live=(len(lots) > 0),
                        stale_hours=stale_hours,
                        entry_atr=B["atr"][i - 1],
                        entry_signal_hour=B["hour"][i - 1],
                    ))
                    direction = dir_
                    if dir_ < 0 and kind in ("Add", "G"):
                        short_pyramid_orders += 1
                    elif dir_ > 0 and kind in ("Add", "G"):
                        long_pyramid_orders += 1
'''
    new = '''                elif act == "retest_cmd":
                    # The hypothetical normal Cmd fill is this next-bar open;
                    # limit is exactly X signal-ATR back from it.  Bars i..
                    # i+11 are the twelve allowed completed 5m bars.
                    dir_, signal_atr, signal_hour = arg
                    retest_order = dict(
                        dir=dir_, limit=float(o - dir_ * retest_x * signal_atr),
                        signal_atr=float(signal_atr), signal_hour=int(signal_hour),
                        expiry_i=i + 12,
                    )
                elif act == "entry":
                    kind, dir_ = arg
                    if kind == "Cmd":
                        short_pyramid_orders = 0
                        long_pyramid_orders = 0
                        base_entry_px = o
                    # This is a next-open fill, so classify it from the
                    # immediately preceding completed signal bar only.
                    stale_hours = p["opt_stale_hr"]
                    entry_signal_pct = B["atr_regime_pct"][i - 1]
                    if (p["opt_regime_stale_enabled"]
                            and np.isfinite(entry_signal_pct)
                            and entry_signal_pct > p["opt_regime_stale_pct_threshold"]):
                        stale_hours = p["opt_regime_stale_hours_high"]
                    lots.append(Lot(
                        kind, o, t_open, bracket_live=(len(lots) > 0),
                        stale_hours=stale_hours,
                        entry_atr=B["atr"][i - 1],
                        entry_signal_hour=B["hour"][i - 1],
                    ))
                    direction = dir_
                    if dir_ < 0 and kind in ("Add", "G"):
                        short_pyramid_orders += 1
                    elif dir_ > 0 and kind in ("Add", "G"):
                        long_pyramid_orders += 1
'''
    if old not in source:
        raise RuntimeError("engine layout changed: pending-entry anchor missing")
    source = source.replace(old, new, 1)

    old = '''        # �w�w 2) �L��: stop / trail �w�w
        if lots:
'''
    # This comment is mojibake in the vendor source, so a stable neighboring
    # token is used rather than decoding/retyping its bytes.
    if old not in source:
        old = '        if lots:\n            if intrabar_mode == "1min":\n'
        new = '''        # A live retest order is filled from actual one-minute OHLC
        # segments.  A favourable opening gap receives the better opening
        # price; otherwise the limit receives its stated limit price.
        if retest_order is not None:
            if i >= retest_order["expiry_i"]:
                retest_order = None
            else:
                s_, e_ = bar_start_idx[i], bar_end_idx[i]
                fill_px = fill_ts = None
                for k in range(s_, e_ + 1 if e_ < len(m_arr) else e_):
                    mo, mh, ml, mc = m_arr[k]
                    lim, dir_ = retest_order["limit"], retest_order["dir"]
                    if dir_ > 0 and ml <= lim:
                        fill_px = float(mo) if mo <= lim else float(lim)
                        fill_ts = m_open[k]
                        break
                    if dir_ < 0 and mh >= lim:
                        fill_px = float(mo) if mo >= lim else float(lim)
                        fill_ts = m_open[k]
                        break
                if fill_px is not None:
                    direction = retest_order["dir"]
                    baseATR = retest_order["signal_atr"]
                    addATR = gATR = np.nan
                    base_entry_px = fill_px
                    short_pyramid_orders = 0
                    long_pyramid_orders = 0
                    stale_hours = p["opt_stale_hr"]
                    lots.append(Lot(
                        "Cmd", fill_px, fill_ts, bracket_live=False,
                        stale_hours=stale_hours, entry_atr=baseATR,
                        entry_signal_hour=retest_order["signal_hour"],
                    ))
                    retest_order = None

        # �w�w 2) �L��: stop / trail �w�w
        if lots:
            if intrabar_mode == "1min":
'''
    else:
        new = '''        # A live retest order is filled from actual one-minute OHLC
        # segments.  A favourable opening gap receives the better opening
        # price; otherwise the limit receives its stated limit price.
        if retest_order is not None:
            if i >= retest_order["expiry_i"]:
                retest_order = None
            else:
                s_, e_ = bar_start_idx[i], bar_end_idx[i]
                fill_px = fill_ts = None
                for k in range(s_, e_ + 1 if e_ < len(m_arr) else e_):
                    mo, mh, ml, mc = m_arr[k]
                    lim, dir_ = retest_order["limit"], retest_order["dir"]
                    if dir_ > 0 and ml <= lim:
                        fill_px = float(mo) if mo <= lim else float(lim)
                        fill_ts = m_open[k]
                        break
                    if dir_ < 0 and mh >= lim:
                        fill_px = float(mo) if mo >= lim else float(lim)
                        fill_ts = m_open[k]
                        break
                if fill_px is not None:
                    direction = retest_order["dir"]
                    baseATR = retest_order["signal_atr"]
                    addATR = gATR = np.nan
                    base_entry_px = fill_px
                    short_pyramid_orders = 0
                    long_pyramid_orders = 0
                    stale_hours = p["opt_stale_hr"]
                    lots.append(Lot(
                        "Cmd", fill_px, fill_ts, bracket_live=False,
                        stale_hours=stale_hours, entry_atr=baseATR,
                        entry_signal_hour=retest_order["signal_hour"],
                    ))
                    retest_order = None

        # �w�w 2) �L��: stop / trail �w�w
        if lots:
'''
    if old not in source:
        raise RuntimeError("engine layout changed: stop-loop anchor missing")
    source = source.replace(old, new, 1)

    old_long = '        if posSize == 0 and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown:\n            pending.append(("entry", ("Cmd", 1)))\n            baseATR = atr_i\n'
    new_long = '        if posSize == 0 and retest_order is None and not isLongToxic and mtf_bull and c > B["ema_long"][i] and long_entry_signal and adx_ok and bbw_long_ok and not in_cooldown:\n            pending.append(("retest_cmd", (1, atr_i, B["hour"][i])))\n            baseATR = atr_i\n'
    old_short = '        elif posSize == 0 and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger \\\n                and (adx_ok if p["opt_adx_short"] else True) and bbw_short_ok and not in_cooldown:\n            pending.append(("entry", ("Cmd", -1)))\n            baseATR = atr_i\n'
    new_short = '        elif posSize == 0 and retest_order is None and not isShortToxic and mtf_bear and c < B["ema_short"][i] and shortTrigger \\\n                and (adx_ok if p["opt_adx_short"] else True) and bbw_short_ok and not in_cooldown:\n            pending.append(("retest_cmd", (-1, atr_i, B["hour"][i])))\n            baseATR = atr_i\n'
    for before, after, label in ((old_long, new_long, "long Cmd"), (old_short, new_short, "short Cmd")):
        if before not in source:
            raise RuntimeError(f"engine layout changed: {label} anchor missing")
        source = source.replace(before, after, 1)

    namespace: dict[str, Any] = {}
    exec(compile(source, __file__, "exec"), globals(), namespace)
    return namespace["run"]


run = _build_run()
