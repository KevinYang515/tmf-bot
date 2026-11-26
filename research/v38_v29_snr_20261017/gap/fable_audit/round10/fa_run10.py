"""Round 7: + AC (add stop distance cap k*P*price). Round 6: + lot cap (VK vol-scaled / WK pre-weekend night). Round 5: + XT (大波動日收緊出場). Based on round-4 runner. Fable's INDEPENDENT implementation of A1 / A2 (cross-check of Codex's fa_run3.py). Output: round4/eng/<case>.csv. Round 4 = L_MA gates + NOBE. In-memory engine patch only."""
_RB = {}
import os, sys, types; os.environ["GAP_BASE"] = "engine_g2lb_wrapper"; sys.path.insert(0, r"E:\stock\v38_v29_snr_20261017")
from pathlib import Path
from multiprocessing import Pool
import inspect, pandas as pd, numpy as np
import engine_gap_wrapper as gw
_FA_CFG = {"a1": None, "a2": None, "so": None, "t1": False, "lma": None, "nobe": False, "cbe": None, "xt": None, "cap": None, "ac": None, "nx": None, "pp": None, "lb": None, "lc": None, "lr": None, "lbs": None, "rb": None, "gb": None}
_FA_S = {"lock": {1: None, -1: None}, "early": False, "n_blk": 0, "n_early": 0, "n_lock": 0, "cbe_on": False, "cbe_lv": None, "n_cbe": 0, "xt_on": False, "xt_best": None, "xt_lv": None, "n_xt": 0, "xt_days": [], "n_cap": 0}
def _td(t):
    t = pd.Timestamp(t); return t.normalize() + pd.Timedelta(days=int(t.hour >= 15))
def _FA_END(d, px, t, pnl, lot, npyr, comment):
    _GB["pk"] = 0.0
    _FA_S["cbe_on"] = False; _FA_S["cbe_lv"] = None; _FA_S["xt_on"] = False; _FA_S["xt_best"] = None; _FA_S["xt_lv"] = None
    if _FA_CFG["a1"] is None: return
    if npyr == 0 and lot.kind == "Cmd" and pnl < 0 and comment != "END" and np.isfinite(lot.entry_atr) and lot.entry_atr > 0:
        _FA_S["lock"][d] = (px, lot.entry_atr, _td(t)); _FA_S["n_lock"] += 1
def _FA_CMDFILL(d):
    _FA_S["lock"][-d] = None; _FA_S["early"] = False
def _FA_A1(t_close, c):
    out = {}
    for s in (1, -1):
        L = _FA_S["lock"][s]
        if L is not None and (_td(t_close) != L[2] or s * (c - L[0]) / L[1] >= _FA_CFG["a1"]):
            _FA_S["lock"][s] = L = None
        out[s] = L is not None
    return out[1], out[-1]
_ST = {"d": None, "prev": None, "last": None, "sopen": None, "lastclose_ts": None, "closes": [], "blkL": False, "rng": [], "dhi": None, "dlo": None, "wk": False}
def _FA_STEP(t_open, t_close, o, c, atr):
    """True if a SHORT Cmd must be blocked by the anchor gates (session-open and/or prev-trading-day-close)."""
    to = pd.Timestamp(t_open); ts = pd.Timestamp(t_close)
    if _ST["lastclose_ts"] is None or (to - _ST["lastclose_ts"]) > pd.Timedelta(minutes=60): _ST["sopen"] = o
    _ST["lastclose_ts"] = ts
    d = ts.normalize() + pd.Timedelta(days=int(ts.hour >= 15 or (ts.hour == 15 and ts.minute > 0)))
    if ts.hour == 15 and ts.minute == 0: d = ts.normalize()
    if d != _ST["d"]:
        _ST["prev"] = _ST["last"]; _ST["d"] = d
        if _ST["prev"] is not None: _ST["closes"].append(_ST["prev"])
        if _ST["dhi"] is not None and _ST["last"]: _ST["rng"].append((_ST["dhi"] - _ST["dlo"]) / _ST["last"])
        _ST["dhi"] = _ST["dlo"] = None; _ST["wk"] = d in WKSET
        N = _FA_CFG["lma"]
        _ST["blkL"] = bool(N and len(_ST["closes"]) >= N and _ST["prev"] < sum(_ST["closes"][-N:]) / N)
    _ST["last"] = c
    _ST["dhi"] = c if _ST["dhi"] is None else max(_ST["dhi"], c); _ST["dlo"] = c if _ST["dlo"] is None else min(_ST["dlo"], c)
    blk = False
    if _FA_CFG["so"] is not None and c > _ST["sopen"] + _FA_CFG["so"] * atr: blk = True
    if _FA_CFG["t1"] and _ST["prev"] is not None and c > _ST["prev"]: blk = True
    return blk
def _FA_CBE(lots, direction, c, batr):
    cf = _FA_CFG["cbe"]
    if cf is None or not lots: return
    avg = sum(x.entry_px for x in lots) / len(lots)
    if not _FA_S["cbe_on"]:
        full = len(lots) >= (4 if direction < 0 else 3)
        ok = (full if cf[0] == "full" else len(lots) >= 2) and np.isfinite(batr) and (c - avg) * direction >= cf[1] * batr
        if ok: _FA_S["cbe_on"] = True; _FA_S["n_cbe"] += 1
    _FA_S["cbe_lv"] = round(avg) if _FA_S["cbe_on"] else None
def _FA_XT(lots, direction, c, batr):
    cf = _FA_CFG["xt"]
    if cf is None or not lots or not np.isfinite(batr): return
    if not _FA_S["xt_on"]:
        mode = cf[2] if len(cf) > 2 else "day"; cl = _ST["closes"]
        if mode == "day": ref = _ST["prev"]
        elif mode == "r3": ref = cl[-3] if len(cl) >= 3 else None
        else:
            n = int(mode[2:]); ref = sum(cl[-n:]) / n if len(cl) >= n else None
        if ref is None or (c / ref - 1) * 100 * direction < cf[0]: return
        _FA_S["xt_on"] = True; _FA_S["xt_best"] = c; _FA_S["n_xt"] += 1; _FA_S["xt_days"].append((str(_ST["d"])[:10], direction))
    _FA_S["xt_best"] = max(_FA_S["xt_best"], c) if direction > 0 else min(_FA_S["xt_best"], c)
    _FA_S["xt_lv"] = round(_FA_S["xt_best"] - direction * cf[1] * batr)
WKSET = set()
def _FA_NXT():
    t = _ST["lastclose_ts"]
    return t is not None and t.hour == 4 and t.minute >= 40
def _FA_MV(d):
    return bool(_ST["prev"]) and d != 0 and (_ST["last"] / _ST["prev"] - 1) * 100 * d >= 7.0
def _FA_CAPOK(pos):
    if _FA_CFG["rb"]:
        _t = _ST["lastclose_ts"]; _st = _RB[_FA_CFG["rb"]].get(_t.normalize()) if _t is not None and 8 <= _t.hour <= 13 else None
        if _st is not None and _t.hour * 60 + _t.minute >= _st and pos != 0: return False
    if _FA_CFG["lc"] and pos != 0 and abs(pos) >= _FA_CFG["lc"] and _FA_MV(1 if pos > 0 else -1): return False
    if _FA_CFG["nx"] and _FA_NXT(): return False
    _ss = _ST["lastclose_ts"]; _night = _ss is not None and (_ss.hour >= 15 or _ss.hour < 5 or (_ss.hour == 5 and _ss.minute == 0))
    if _FA_CFG["lb"] and (_FA_CFG["lbs"] is None or (_FA_CFG["lbs"] == "N") == _night) and pos != 0 and _ST["prev"] and (_ST["last"] / _ST["prev"] - 1) * 100 * (1 if pos > 0 else -1) >= _FA_CFG["lb"]: return False
    cf = _FA_CFG["cap"]
    if cf is None: return True
    cap = 99; r = _ST["rng"]
    if cf.get("K"):
        ratio = (np.mean(r[-20:]) / np.median(r[-250:])) if len(r) >= 250 else 1.0
        cap = max(1, int(np.floor(cf["K"] / ratio)))
    if cf.get("wk") and _ST["wk"]: cap = min(cap, cf["wk"])
    ok = abs(pos) < cap
    if not ok: _FA_S["n_cap"] += 1
    return ok
_GB = {"pk": 0.0}
def _FA_GBHIT(lots, direction, c, batr):
    g = _FA_CFG["gb"]
    if g is None or not lots or not np.isfinite(batr) or batr <= 0: return False
    op = sum((c - x.entry_px) * direction for x in lots)
    if op > _GB["pk"]: _GB["pk"] = op
    return _GB["pk"] >= 3.0 * batr and op < (1.0 - g) * _GB["pk"]
def _FA_CNT(k): _FA_S[k] += 1; return True
gw._GX_EDITS.extend([
 ("        lots.remove(lot)\n        if not lots:\n            direction = 0\n",
  "        lots.remove(lot)\n        if not lots:\n            _FA_END(exit_direction, px, t, pnl, lot, short_pyramid_orders + long_pyramid_orders, comment)\n            direction = 0\n", "fa-end"),
 ('                    if kind == "Cmd":\n                        short_pyramid_orders = 0\n',
  '                    if kind == "Cmd":\n                        _FA_CMDFILL(dir_)\n                        short_pyramid_orders = 0\n', "fa-cmdfill"),
 ('        o, h, l, c = B["open"][i], B["high"][i], B["low"][i], B["close"][i]\n',
  '        o, h, l, c = B["open"][i], B["high"][i], B["low"][i], B["close"][i]\n        _fa_anc = _FA_STEP(ts_open[i], ts_close[i], o, c, B["atr"][i])\n', "fa-step"),
 ("        _mlg_cmd_ok = _mlg_cmd_ok_arr[i]\n",
  "        _mlg_cmd_ok = _mlg_cmd_ok_arr[i]\n        _FA_CBE(lots, direction, c, baseATR)\n        _FA_XT(lots, direction, c, baseATR)\n        _fa_bL, _fa_bS = _FA_A1(t_close, c) if _FA_CFG['a1'] is not None else (False, False)\n", "fa-a1"),
 ('and _mlg_cmd_ok and not _gx_blkL[i]:\n            pending.append(("entry", ("Cmd", 1)))',
  'and _mlg_cmd_ok and not _gx_blkL[i] and not (_fa_bL and _FA_CNT("n_blk")) and not (_ST["blkL"] and _FA_CNT("n_blk")):\n            pending.append(("entry", ("Cmd", 1)))', "fa-cmdL"),
 ('and _mlg_cmd_ok and not _gx_blkS[i]:\n            pending.append(("entry", ("Cmd", -1)))',
  'and _mlg_cmd_ok and not _gx_blkS[i] and not (_fa_bS and _FA_CNT("n_blk")) and not _fa_anc:\n            pending.append(("entry", ("Cmd", -1)))', "fa-cmdS"),
 ('        elif 0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok',
  '        elif _FA_CFG["a2"] is not None and posSize == 1 and lots[0].kind == "Cmd" and long_pyramid_orders == 0 and short_pyramid_orders == 0 and not _FA_S["early"] '
  'and not (c > avgPrice + baseATR * p["l_pyramid_dist"]) and current_profit >= _FA_CFG["a2"] * baseATR and add_gate_ok and long_pyramid_cap_ok and _mlg_addg_ok '
  'and not long_pyramid_cooldown and not isLongToxic and mtf_bull:\n'
  '            pending.append(("entry", ("Add", 1)))\n            addATR = atr_i\n            _FA_S["early"] = True; _FA_S["n_early"] += 1\n'
  '        elif 0 < posSize < add_cap and add_gate_ok and long_pyramid_cap_ok', "fa-a2L"),
 ('        elif -add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok',
  '        elif _FA_CFG["a2"] is not None and posSize == -1 and lots[0].kind == "Cmd" and long_pyramid_orders == 0 and short_pyramid_orders == 0 and not _FA_S["early"] '
  'and not (c < avgPrice - baseATR * p["s_pyramid_dist"]) and current_profit >= _FA_CFG["a2"] * baseATR and add_gate_ok and short_pyramid_cap_ok and _mlg_addg_ok '
  'and not short_pyramid_cooldown and not isShortToxic and mtf_bear:\n'
  '            pending.append(("entry", ("Add", -1)))\n            addATR = atr_i\n            _FA_S["early"] = True; _FA_S["n_early"] += 1\n'
  '        elif -add_cap < posSize < 0 and add_gate_ok and short_pyramid_cap_ok', "fa-a2S"),
])
_eff_orig = gw._g["_eff_stop"]
def _eff_nobe0(lot, direction):
    if _FA_CFG["nobe"] and lot.kind == "Cmd" and lot.be_stop is not None:
        sv = lot.be_stop; lot.be_stop = None
        try: return _eff_orig(lot, direction)
        finally: lot.be_stop = sv
    return _eff_orig(lot, direction)
def _eff_nobe(lot, direction):
    e = _eff_nobe0(lot, direction)
    for lv in (_FA_S["cbe_lv"], _FA_S["xt_lv"]):
        if lv is None: continue
        e = lv if e is None else (max(e, lv) if direction > 0 else min(e, lv))
    return e
gw._g["_eff_stop"] = _eff_nobe
gw._GX_EDITS.extend([
 ("            # 市價平倉 (訊號 bar 收盤 → 下一開盤成交)\n", "            if _FA_CFG[\"nx\"] and _ST[\"lastclose_ts\"].hour == 4 and 45 <= _ST[\"lastclose_ts\"].minute <= 55:\n                for _k in ((\"Add\", \"G\") if _FA_CFG[\"nx\"] == \"addg\" else (\"Add\",)):\n                    if any(x.kind == _k for x in lots): pending.append((\"close_kind\", (_k, (\"L_\" if direction > 0 else \"S_\") + _k + \"_NX\")))\n            if _FA_CFG[\"lr\"] and len(lots) > _FA_CFG[\"lr\"] and _FA_MV(direction):\n                for _lt in sorted(lots, key=lambda x: x.entry_ts)[_FA_CFG[\"lr\"]:]: pending.append((\"close_lot_ts\", (_lt.entry_ts, (\"L_\" if direction > 0 else \"S_\") + _lt.kind + \"_LR\")))\n            if _FA_CFG[\"gb\"] is not None and _FA_GBHIT(lots, direction, c, baseATR): pending.append((\"close_all_sig\", \"L_GB\" if direction > 0 else \"S_GB\"))\n            # 市價平倉 (訊號 bar 收盤 → 下一開盤成交)\n", "nx-close"),
 ('lot.loss_stop = round(lot.entry_px - eff_add * p["addLossL"])', 'lot.loss_stop = round(lot.entry_px - (eff_add * p["addLossL"] if _FA_CFG["ac"] is None else min(eff_add * p["addLossL"], _FA_CFG["ac"] * 0.0037 * lot.entry_px)))', "ac-L"),
 ('lot.loss_stop = round(lot.entry_px + eff_add * p["addLossS"])', 'lot.loss_stop = round(lot.entry_px + (eff_add * p["addLossS"] if _FA_CFG["ac"] is None else min(eff_add * p["addLossS"], _FA_CFG["ac"] * 0.00333 * lot.entry_px)))', "ac-S"),
 ("        elif 0 < posSize < add_cap and add_gate_ok", "        elif 0 < posSize < add_cap and _FA_CAPOK(posSize) and add_gate_ok", "cap-addL"),
 ("        elif -add_cap < posSize < 0 and add_gate_ok", "        elif -add_cap < posSize < 0 and _FA_CAPOK(posSize) and add_gate_ok", "cap-addS"),
 ("        elif posSize == 3 and allow_g and", "        elif posSize == 3 and allow_g and _FA_CAPOK(posSize) and", "cap-gL"),
 ("        elif posSize == -3 and allow_g and", "        elif posSize == -3 and allow_g and _FA_CAPOK(posSize) and", "cap-gS"),
])
gw._g.update(_FA_CBE=_FA_CBE, _FA_XT=_FA_XT, _FA_END=_FA_END, _FA_CMDFILL=_FA_CMDFILL, _FA_A1=_FA_A1, _FA_CFG=_FA_CFG, _FA_S=_FA_S, _FA_CNT=_FA_CNT, _FA_STEP=_FA_STEP, _ST=_ST, _FA_CAPOK=_FA_CAPOK, _FA_NXT=_FA_NXT, _FA_MV=_FA_MV, _RB=_RB, _FA_GBHIT=_FA_GBHIT, _GB=_GB)
gw.run = types.FunctionType(gw._ns["_build_run_gx"].__code__, gw._g)()
G = gw._g; G["_TF"], G["_OFF"] = 5, 0
base = gw._lb
def build_bars(df1m, minutes):
    if minutes != 60:
        t = df1m["open_ts"]; off = pd.Timedelta(minutes=G["_OFF"])
        g = df1m.groupby((t - off).dt.floor("5min") + off)
        bars = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                             "close": g["close"].last(), "close_ts": g["ts"].max()})
        bars.index.name = "open_ts"; return bars.reset_index()
    return base._base.build_bars(df1m, 60)
G["build_bars"] = build_bars
exec(compile(inspect.getsource(base._base.prepare), "prepare_off", "exec"), G)
gsrc = inspect.getsource(base._g2_vf).replace('    if lb == 20:\n        return volume_features(df1, b5)\n', '')
gsrc = gsrc.replace('minute["bin"] = minute["open_ts"].dt.floor("5min")',
                    'minute["bin"] = (minute["open_ts"] - pd.Timedelta(minutes=_OFF)).dt.floor("5min") + pd.Timedelta(minutes=_OFF)')
assert "_OFF" in gsrc; exec(compile(gsrc, "g2vf_off", "exec"), G)
HERE = Path(r"E:\stock\v38_v29_snr_20261017"); DATA = HERE / os.environ.get("FA_DATA", "mxf_1min_2020_20261111.csv"); OUT = HERE / "gap" / "fable_audit" / "round10" / os.environ.get("FA_OUT", "eng")
V30 = {**gw.P, "opt_stale_hr": 10, "opt_cooldown_min": 30, "opt_short_pyramid_cap_mode": "hour4",
       "l_trailBase": 3.5, "l_trailBaseDay": 3.5, "l_trailBaseNight": 3.5, "adxThresh": 30}
def v30e_ltp(**k): return {**V30, "opt_ml_gate": {"variant": "G2", "session_cum_vol_rel20_threshold": 0.7277710401830155, "lookback": 20,
                                                  "fix_all_next_minute": True, "no_long_g": True, "trail_cap": 0, "limit_tp": 1, **k}}
N = dict(a1=None, a2=None, so=None, t1=False, lma=None, nobe=False, cbe=None, xt=None, cap=None, ac=None, nx=None, pp=None, lb=None, lc=None, lr=None, lbs=None, rb=None, gb=None)
def _mk_rb():
    import numpy as _np
    x = pd.read_csv(Path(r"E:/stock/v38_v29_snr_20261017/gap/fable_audit/round9/eng1125/NOBE_off0.csv"), parse_dates=["entry_ts"])
    x = x[x.kind.isin(["Add", "G"]) & x.entry_ts.dt.strftime("%H:%M").between("08:45", "13:45")]
    days = sorted(x.entry_ts.dt.normalize().unique())
    for sd in range(30):
        r = _np.random.default_rng(1000 + sd); pick = r.choice(len(days), 8, replace=False)
        _RB[f"RB{sd}"] = {pd.Timestamp(days[k]): int(r.integers(525, 811)) for k in pick}
_mk_rb()
TAGS = {"GB40": dict(N, nobe=True, gb=0.4), "GB50": dict(N, nobe=True, gb=0.5), "GB60": dict(N, nobe=True, gb=0.6), **{k: dict(N, nobe=True, rb=k) for k in _RB}, **{f"LB{str(x).replace('.', 'p')}": dict(N, nobe=True, lb=float(x)) for x in (4, 5.5, 6, 6.5, 7.5, 8, 9)}, "LB7D": dict(N, nobe=True, lb=7.0, lbs="D"), "LB7N": dict(N, nobe=True, lb=7.0, lbs="N"), "LC2": dict(N, nobe=True, lc=2), "LC3": dict(N, nobe=True, lc=3), "LR2": dict(N, nobe=True, lr=2), "LR3": dict(N, nobe=True, lr=3), "E100": dict(N, nobe=True, pp={"l_emaLenShort": 100, "l_emaLenLong": 105}), "E80": dict(N, nobe=True, pp={"l_emaLenShort": 80, "l_emaLenLong": 85}), "LB5": dict(N, nobe=True, lb=5.0), "LB7": dict(N, nobe=True, lb=7.0), "PD05": dict(N, nobe=True, pp={"s_pyramid_dist": 0.5, "l_pyramid_dist": 0.6}), "PD15": dict(N, nobe=True, pp={"s_pyramid_dist": 1.5, "l_pyramid_dist": 1.8}), "ML2": dict(N, nobe=True, pp={"opt_max_lots": 2}), "ML3": dict(N, nobe=True, pp={"opt_max_lots": 3}), "NX": dict(N, nobe=True, nx="add"), "NXG": dict(N, nobe=True, nx="addg"), "ABE1": dict(N, nobe=True, pp={"opt_add_be_trigger": 1.0}), "ABE2": dict(N, nobe=True, pp={"opt_add_be_trigger": 2.0}), "AC1": dict(N, nobe=True, ac=1.0), "AC2": dict(N, nobe=True, ac=2.0), "AC3": dict(N, nobe=True, ac=3.0), "VK4": dict(N, nobe=True, cap={"K": 4}), "VK6": dict(N, nobe=True, cap={"K": 6}), "WK1": dict(N, nobe=True, cap={"wk": 1}), "WK2": dict(N, nobe=True, cap={"wk": 2}), "C4_2": dict(N, nobe=True, cap={"K": 4, "wk": 2}), "C6_2": dict(N, nobe=True, cap={"K": 6, "wk": 2}), **{f"XT{x}_{k}": dict(N, nobe=True, xt=(float(x), float(k))) for x in (3, 4, 6) for k in (1, 2)}, **{f"{m.upper()}_{x}_{k}": dict(N, nobe=True, xt=(float(x), float(k), m)) for m, xs in (("r3", (4, 6)), ("ma20", (5, 8)), ("ma60", (8, 12))) for x in xs for k in (1, 2)}, "L_MA20": dict(N, lma=20), "L_MA10": dict(N, lma=10), "L_MA60": dict(N, lma=60), "NOBE": dict(N, nobe=True), "L_MA20_NOBE": dict(N, lma=20, nobe=True), "basechk": dict(N), "CBE_F1": dict(N, nobe=True, cbe=("full", 1.0)), "CBE_F2": dict(N, nobe=True, cbe=("full", 2.0)), "CBE_P2": dict(N, nobe=True, cbe=("p2", 2.0)),
        "A1_20": dict(N, a1=2.0), "A1_30": dict(N, a1=3.0), "A1_INF": dict(N, a1=1e12), "B3_SO": dict(N, so=0.0), "SO_m05": dict(N, so=-0.5), "SO_p05": dict(N, so=0.5),
        "T1": dict(N, t1=True), "SO_T1": dict(N, so=0.0, t1=True), "SO_A115": dict(N, so=0.0, a1=1.5), "SO_T1_A115": dict(N, so=0.0, t1=True, a1=1.5),
        "base": dict(a1=None, a2=None), "A1_05": dict(a1=0.5, a2=None), "A1_10": dict(a1=1.0, a2=None), "A1_15": dict(a1=1.5, a2=None),
        "A2_04": dict(a1=None, a2=0.4), "A2_06": dict(a1=None, a2=0.6), "A2_08": dict(a1=None, a2=0.8)}
def go(case):
    tag, o = case.rsplit("_off", 1); out = OUT / f"{case}.csv"
    if out.exists(): return
    _GB["pk"] = 0.0; G["_OFF"] = int(o); _FA_CFG.update(N); _FA_CFG.update(TAGS[tag]); _ST.update(d=None, prev=None, last=None, sopen=None, lastclose_ts=None, closes=[], blkL=False, rng=[], dhi=None, dlo=None, wk=False); _FA_S.update(lock={1: None, -1: None}, early=False, n_blk=0, n_early=0, n_lock=0, cbe_on=False, cbe_lv=None, n_cbe=0, xt_on=False, xt_best=None, xt_lv=None, n_xt=0, xt_days=[], n_cap=0); OUT.mkdir(exist_ok=True)
    _m = pd.read_csv(DATA, usecols=["ts"], parse_dates=["ts"]).ts; _e = _m[(_m.dt.hour == 5) & (_m.dt.minute == 0)]
    _nx = _m.shift(-1)[_e.index]; WKSET.clear(); WKSET.update(set(_e[(_nx - _e) > pd.Timedelta(hours=24)].dt.normalize()))
    t = gw.run(gw.load_1min(DATA), p={**v30e_ltp(), **(_FA_CFG["pp"] or {})}, intrabar_mode="1min"); t["case"] = case; t.to_csv(out, index=False)
    print(case, len(t), round(t.pnl.sum()), {k: _FA_S[k] for k in ("n_lock", "n_blk", "n_early", "n_cbe", "n_xt", "n_cap")}, "wkset", len(WKSET), flush=True)
    import json; (OUT / f"{case}_xtdays.json").write_text(json.dumps(_FA_S["xt_days"]))
if __name__ == "__main__":
    import time; t0 = time.time()
    with Pool(int(os.environ.get("FA_POOL", "4"))) as pool: pool.map(go, sys.argv[1:], chunksize=1)
    print("done", round(time.time() - t0), "s")
