"""Local Phase-D wrapper around the untouched v26/v29 research engine."""

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


# Re-export the usual engine interface, with the Phase-D option added locally.
POINT_VALUE = _base.POINT_VALUE
COMMISSION = _base.COMMISSION
P = {**_base.P, "opt_add_hvn_gate": None, "opt_add_random_skip": None}
load_1min = _base.load_1min
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


def prepare(df1m: pd.DataFrame, p: dict[str, Any]) -> pd.DataFrame:
    """Base indicators plus the exact 5m volume series used in Phase C."""
    b5 = _base.prepare(df1m, p).copy()
    volume = df1m.groupby(df1m.open_ts.dt.floor("5min"))["volume"].sum()
    b5["volume"] = b5.open_ts.map(volume).fillna(0.0)
    return b5


def _profile_hvns(values: np.ndarray, volumes: np.ndarray, width: float) -> np.ndarray | None:
    """Phase-C local-max/top-quartile HVNs plus POC, returning their centers."""
    if len(values) == 0 or not np.isfinite(width) or width <= 0:
        return None
    base = np.floor(np.nanmin(values) / width) * width
    bins = np.floor((values - base) / width).astype(int)
    vol = np.bincount(bins, weights=volumes)
    if not len(vol) or vol.sum() <= 0:
        return None
    centers = base + (np.arange(len(vol)) + 0.5) * width
    poc_i = int(np.argmax(vol))
    local = np.zeros(len(vol), dtype=bool)
    if len(vol) == 1:
        local[0] = True
    else:
        local[0] = vol[0] >= vol[1]
        local[-1] = vol[-1] >= vol[-2]
        if len(vol) > 2:
            local[1:-1] = (vol[1:-1] >= vol[:-2]) & (vol[1:-1] >= vol[2:])
    hvn = np.flatnonzero(local & (vol >= np.percentile(vol[vol > 0], 75)))
    return centers[np.unique(np.append(hvn, poc_i))]


class _HvnBehind5D:
    """Exact Phase-C 5-calendar-day HVN-behind feature at a pending Add fill."""

    def __init__(self, b5: pd.DataFrame) -> None:
        self.close_ts = b5.close_ts.to_numpy(dtype="datetime64[ns]")
        self.open_ts = b5.open_ts.to_numpy(dtype="datetime64[ns]")
        self.opens = b5.open.to_numpy(float)
        self.closes = b5.close.to_numpy(float)
        self.atrs = b5.atr.to_numpy(float)
        self.typical = ((b5.high + b5.low + b5.close) / 3).to_numpy(float)
        self.volume = b5.volume.to_numpy(float)

    def values(
        self, fill_index: int, direction: int, reference: str = "fill"
    ) -> tuple[float, float, float]:
        # Signal i-1 fills at i.  Phase C used cutoff=entry_ts and a strict
        # close_ts < cutoff lookup, excluding the just-completed signal bar.
        if fill_index <= 0:
            return np.nan, np.nan
        # This is deliberately the same strict cutoff as Phase C's
        # enrich_trade_path(): last close_ts strictly before entry_ts.  It is
        # normally one bar before the signal bar and differs materially across
        # session gaps, so using fill_index-1 is not equivalent.
        cutoff = self.open_ts[fill_index]
        causal_index = int(np.searchsorted(self.close_ts, cutoff, side="left")) - 1
        if causal_index < 0:
            return np.nan, np.nan, np.nan
        entry_atr = float(self.atrs[causal_index])
        px = (
            float(self.opens[fill_index])
            if reference == "fill"
            else float(self.closes[causal_index])
        )
        if not np.isfinite(px) or not np.isfinite(entry_atr) or entry_atr <= 0:
            return np.nan, np.nan, px
        first = int(np.searchsorted(
            self.close_ts, cutoff - np.timedelta64(5, "D"), side="left"
        ))
        last = int(np.searchsorted(self.close_ts, cutoff, side="left"))
        prices = self.typical[first:last]
        volumes = self.volume[first:last]

        def behind(mode: str) -> float:
            width = 0.25 * entry_atr if mode == "atr" else 0.001 * px
            levels = _profile_hvns(prices, volumes, width)
            if levels is None:
                return np.nan
            directional = (levels - px) * direction
            lower = directional[directional < 0]
            return float(-np.max(lower) / entry_atr) if len(lower) else np.nan

        return behind("atr"), behind("pct"), px


def _normalise_hvn_gate(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("opt_add_hvn_gate must be None or a dict")
    feature = value.get("feature")
    minimum = value.get("min_dist_atr")
    sides = tuple(value.get("sides", ()))
    reference = value.get("reference", "fill")
    if feature not in {"pct", "atr"}:
        raise ValueError("opt_add_hvn_gate.feature must be 'pct' or 'atr'")
    if not isinstance(minimum, (int, float)) or not np.isfinite(minimum) or minimum < 0:
        raise ValueError("opt_add_hvn_gate.min_dist_atr must be a non-negative number")
    if not sides or any(side not in {"L", "S"} for side in sides):
        raise ValueError("opt_add_hvn_gate.sides must contain only 'L' and/or 'S'")
    if reference not in {"fill", "causal_close5"}:
        raise ValueError("opt_add_hvn_gate.reference must be 'fill' or 'causal_close5'")
    return {
        "feature": feature,
        "min_dist_atr": float(minimum),
        "sides": sides,
        "reference": reference,
    }


def _normalise_random_skip(value: Any) -> dict[str, Any] | None:
    """Validate a reproducible random-Add placebo configuration.

    The probability is selected by the potential Add fill's calendar year.
    It is deliberately applied at signal execution time, rather than selecting
    a fixed subset beforehand, because earlier skipped Adds alter later paths.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("opt_add_random_skip must be None or a dict")
    seed = value.get("seed")
    probabilities = value.get("prob_by_year")
    sides = tuple(value.get("sides", ("L",)))
    if not isinstance(seed, (int, np.integer)):
        raise ValueError("opt_add_random_skip.seed must be an integer")
    if not isinstance(probabilities, dict) or not probabilities:
        raise ValueError("opt_add_random_skip.prob_by_year must be a non-empty dict")
    if not sides or any(side not in {"L", "S"} for side in sides):
        raise ValueError("opt_add_random_skip.sides must contain only 'L' and/or 'S'")
    parsed: dict[int, float] = {}
    for year, probability in probabilities.items():
        try:
            parsed[int(year)] = float(probability)
        except (TypeError, ValueError) as exc:
            raise ValueError("random-skip year probabilities must be numeric") from exc
        if not np.isfinite(parsed[int(year)]) or not 0 <= parsed[int(year)] <= 1:
            raise ValueError("random-skip probabilities must be in [0, 1]")
    return {"seed": int(seed), "prob_by_year": parsed, "sides": sides}


def _build_run() -> Any:
    """Clone the base run() and inject only Add-gate/audit hooks."""
    source = textwrap.dedent(inspect.getsource(_base.run))
    old_prepare = '    b5 = prepare(df1m, p)\n'
    new_prepare = '''    b5 = prepare(df1m, p)
    _hvn_gate = _normalise_hvn_gate(p["opt_add_hvn_gate"])
    _random_skip = _normalise_random_skip(p["opt_add_random_skip"])
    if _hvn_gate is not None and _random_skip is not None:
        raise ValueError("feature gate and random Add skip cannot both be enabled")
    _hvn_feature = _HvnBehind5D(b5) if _hvn_gate is not None else None
    _random_rng = np.random.default_rng(_random_skip["seed"]) if _random_skip is not None else None
    _hvn_audit = []
'''
    if old_prepare not in source:
        raise RuntimeError("base engine run() layout changed: prepare anchor missing")
    source = source.replace(old_prepare, new_prepare, 1)

    old_entry = '''                elif act == "entry":
                    kind, dir_ = arg
                    if kind == "Cmd":
'''
    new_entry = '''                elif act == "entry":
                    kind, dir_ = arg
                    if kind == "Add":
                        _side = "L" if dir_ > 0 else "S"
                        _hvn_atr = _hvn_pct = _reference_px = np.nan
                        _feature_skip = False
                        if _hvn_gate is not None:
                            _hvn_atr, _hvn_pct, _reference_px = _hvn_feature.values(
                                i, dir_, _hvn_gate["reference"]
                            )
                        _chosen = _hvn_pct if (_hvn_gate or {}).get("feature") == "pct" else _hvn_atr
                        _feature_skip = bool(
                            _hvn_gate is not None
                            and _side in _hvn_gate["sides"]
                            and np.isfinite(_chosen)
                            and _chosen < _hvn_gate["min_dist_atr"]
                        )
                        _random_probability = 0.0
                        _random_skip_decision = False
                        if _random_skip is not None and _side in _random_skip["sides"]:
                            _random_probability = _random_skip["prob_by_year"].get(
                                int(pd.Timestamp(t_open).year), 0.0
                            )
                            _random_skip_decision = bool(_random_rng.random() < _random_probability)
                        _skip = _feature_skip or _random_skip_decision
                        _hvn_audit.append(dict(
                            entry_ts=pd.Timestamp(t_open), entry_px=float(o), side=_side,
                            hvn_5d_atr_behind_atr=_hvn_atr,
                            hvn_5d_pct_behind_atr=_hvn_pct, reference_px=_reference_px,
                            skipped=_skip, skip_reason=(
                                "feature" if _feature_skip else "random" if _random_skip_decision else ""
                            ), random_probability=_random_probability,
                        ))
                        if _skip:
                            continue
                    if kind == "Cmd":
'''
    if old_entry not in source:
        raise RuntimeError("base engine run() layout changed: pending-entry anchor missing")
    source = source.replace(old_entry, new_entry, 1)

    old_return = '''    if not tr.empty:
        tr = tr.sort_values("exit_ts").reset_index(drop=True)
    return tr
'''
    new_return = '''    if not tr.empty:
        tr = tr.sort_values("exit_ts").reset_index(drop=True)
    tr.attrs["hvn_gate_audit"] = _hvn_audit
    tr.attrs["hvn_gate_skipped"] = sum(row["skipped"] for row in _hvn_audit)
    return tr
'''
    if old_return not in source:
        raise RuntimeError("base engine run() layout changed: return anchor missing")
    source = source.replace(old_return, new_return, 1)
    namespace: dict[str, Any] = {}
    exec(compile(source, __file__, "exec"), globals(), namespace)
    return namespace["run"]


run = _build_run()

