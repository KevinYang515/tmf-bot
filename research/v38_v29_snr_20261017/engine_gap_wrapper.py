"""Lastbar wrapper (G2 gate) + session-gap options, all via opt_ml_gate keys:
  gap_exit_close  : pending exits signalled on a session's last bar fill at that bar's close (not next open)
  gap_entry_close : same for pending entries
  gap_flat        : None | "all" | "loss" | "addg"  -> close selected lots at the session's last bar close
  gap_flat_side   : "S" | "L" | "both"
  gap_flat_sess   : "both" | "day" (13:45 close) | "night" (05:00 close)
Last bar = next bar opens > 1h after this bar closes."""
import inspect, os, importlib
_lb = importlib.import_module(os.environ.get("GAP_BASE", "engine_lastbar_wrapper"))
globals().update({k: v for k, v in vars(_lb).items() if not k.startswith("__")})
import numpy as np, pandas as pd
_src = inspect.getsource(_lb._build_run)
def _patch(src, old, new, tag):
    if old not in src: raise RuntimeError("anchor missing: " + tag)
    return src.replace(old, new, 1)
_src = _patch(_src, "    n = len(b5)\n'''", '''    n = len(b5)
    _gx = (overrides.get("opt_ml_gate", {}) or {})
    _gx_exit_close = bool(_gx.get("gap_exit_close")); _gx_entry_close = bool(_gx.get("gap_entry_close"))
    _gx_margin = float(_gx.get("gap_flat_margin", 0.0)); _gx_flat = _gx.get("gap_flat"); _gx_side = _gx.get("gap_flat_side", "S"); _gx_sess = _gx.get("gap_flat_sess", "both")
    _gx_ot = pd.to_datetime(b5["open_ts"]).to_numpy(); _gx_ct = pd.to_datetime(b5["close_ts"]).to_numpy()
    _gx_last_arr = np.zeros(len(b5), dtype=bool)
    _gx_last_arr[:-1] = (_gx_ot[1:] - _gx_ct[:-1]) > np.timedelta64(60, "m")
    _gx_when = _gx.get("gap_flat_when", "last")
    _gx_pre_arr = np.zeros(len(b5), dtype=bool); _gx_pre_arr[:-1] = _gx_last_arr[1:]
    _gx_flat_arr = _gx_pre_arr if _gx_when == "prelast" else _gx_last_arr
    _gx_fix = bool(_gx.get("fix_cross_session")); _gx_fix_all = bool(_gx.get("fix_all_next_minute"))
    _gx_first = np.ones(len(b5), dtype=bool); _gx_first[1:] = (_gx_ot[1:] - _gx_ct[:-1]) > np.timedelta64(60, "m")
    _gx_sstart = pd.Series(np.where(_gx_first, _gx_ot, np.datetime64("NaT"))).ffill().to_numpy()
    _gx_since = (_gx_ot - _gx_sstart) / np.timedelta64(1, "m")
    _gx_grace_min = float(_gx.get("grace_min", 0)); _gx_gbuf = float(_gx.get("grace_buf_atr", np.inf))
    _gx_grace_arr = _gx_since < _gx_grace_min
    _gx_atr_prev = np.r_[np.nan, b5["atr"].to_numpy()[:-1]]
    def _gx_es(lot, d, i):
        e = _eff_stop(lot, d)
        if e is None or not _gx_grace_arr[i]: return e
        if not np.isfinite(_gx_gbuf): return None
        return e - d * _gx_gbuf * _gx_atr_prev[i]
    _gx_lim_k = float(_gx.get("open_limit_atr", 0)); _gx_lim_w = int(_gx.get("open_limit_win", 5))
    _gx_lim_entry = bool(_gx.get("open_limit_entry")); _gx_lim_exit = bool(_gx.get("open_limit_exit"))
    _gx_gapdir = _gx.get("gapdir_block")
    _gx_trev_keep = bool(_gx.get("trev_keep_profit_add")); _gx_no_sfast = bool(_gx.get("no_s_cmd_fast")); _gx_confirm = _gx.get("cmd_confirm_min", 0)
    _gx_no_lg = bool(_gx.get("no_long_g")); _gx_no_sg = bool(_gx.get("no_short_g"))
    _gx_adverse = bool(_gx.get("adverse_path"))
    _gx_tcap = _gx.get("trail_cap", None)
    _gx_ltp = _gx.get("limit_tp", None)
    _gx_lock = _gx.get("lock_atr", None); _gx_lockw = _gx.get("lock_trail_atr", None); _gx_lk = {}
    def _gx_lockset(lot, ext, direction):
        k = (lot.entry_ts, lot.kind, lot.entry_px)
        a = lot.entry_atr if lot.entry_atr is not None and np.isfinite(lot.entry_atr) else abs(lot.trail_act - lot.entry_px) / 3
        if k not in _gx_lk: _gx_lk[k] = [lot.trail_act - direction * _gx_lock * a, ext]
        st = _gx_lk[k]; st[1] = max(st[1], ext) if direction > 0 else min(st[1], ext)
        sp = st[0]
        if _gx_lockw is not None: sp = max(sp, st[1] - _gx_lockw * a) if direction > 0 else min(sp, st[1] + _gx_lockw * a)
        lot.peak = round(sp) + direction
    _gx_ltn = lambda lot, d: ("L" if d > 0 else "S") + "_Exit" + ("_Add" if lot.kind == "Add" else "_G" if lot.kind == "G" else "") + "_LMT"
    _gx_toff_k = float(_gx.get("trail_off_atr", 0)); _gx_toff_n = int(_gx.get("trail_off_after_adds", 0)); _GX_TOFF[0] = 1.0
    _gx_blkL = np.zeros(len(b5), dtype=bool); _gx_blkS = np.zeros(len(b5), dtype=bool)
    if _gx_gapdir:
        _gx_o5 = b5["open"].to_numpy(); _gx_c5 = b5["close"].to_numpy()
        _gx_g = np.where(_gx_first, _gx_o5 - np.r_[np.nan, _gx_c5[:-1]], np.nan) / _gx_atr_prev
        _gx_g = pd.Series(_gx_g).ffill().to_numpy()
        _gx_w = _gx_since < _gx_gapdir[0]
        _gx_blkL = _gx_w & (_gx_g > _gx_gapdir[1]); _gx_blkS = _gx_w & (_gx_g < -_gx_gapdir[1])
    _gx_hr = pd.to_datetime(b5["close_ts"]).dt.hour.to_numpy()
    _gx_rg = _gx.get("regime_short_mult"); _gx_rgma = int(_gx.get("regime_ma", 60))
    if _gx_rg:
        _gx_rgbase = {k: p[k] for k in _gx_rg}
        _gx_ctd = pd.to_datetime(b5["close_ts"]).reset_index(drop=True)
        _gx_dmask = ((_gx_ctd.dt.hour >= 8) & (_gx_ctd.dt.hour <= 13)).to_numpy()
        _gx_dc = pd.Series(b5["close"].to_numpy()[_gx_dmask]).groupby(_gx_ctd[_gx_dmask].dt.normalize().to_numpy()).last()
        _gx_dbel = (_gx_dc < _gx_dc.rolling(_gx_rgma).mean()).to_numpy()
        _gx_avail = (_gx_dc.index + pd.Timedelta(hours=13, minutes=45)).to_numpy()
        _gx_pos = np.searchsorted(_gx_avail, _gx_ctd.to_numpy(), side="right") - 1
        _gx_below = np.where(_gx_pos >= 0, _gx_dbel[np.maximum(_gx_pos, 0)], False)
    _gx_cmdh = _gx.get("cmd_block_entry_hours")
    if _gx_cmdh:
        _gx_eh = (pd.to_datetime(b5["open_ts"]) + pd.Timedelta(minutes=5)).dt.hour.to_numpy()
        _gx_hb = np.isin(_gx_eh, list(_gx_cmdh)); _gx_blkL = _gx_blkL | _gx_hb; _gx_blkS = _gx_blkS | _gx_hb
    _gx_sess_ok = np.ones(len(b5), dtype=bool) if _gx_sess == "both" else ((_gx_hr >= 8) & (_gx_hr <= 14) if _gx_sess == "day" else ~((_gx_hr >= 8) & (_gx_hr <= 14)))
\'\'\'''', "prep")
# inner run-source edits are applied by patching the replacement strings the lastbar builder inserts:
_src = _patch(_src, "    exec(compile(source, __file__, \"exec\"), globals(), namespace)",
'''    for _o, _n, _t in _GX_EDITS:
        if _o not in source: raise RuntimeError("engine anchor missing: " + _t)
        source = source.replace(_o, _n, 1)
    exec(compile(source, __file__, "exec"), globals(), namespace)''', "exec")
_GX_EDITS = [
 ("            for lot in lots[:]:\n                if not lot.bracket_live:\n                    continue\n                # 開盤即已達 trail 啟動價 (跳空)\n",
  "            for lot in lots[:]:\n                if not lot.bracket_live:\n                    continue\n                if _gx_ltp is not None and lot.trail_act is not None and (first_px - lot.trail_act) * direction >= _gx_ltp:\n                    close_lot(lot, first_px, t_open, _gx_ltn(lot, direction))\n                    continue\n                # 開盤即已達 trail 啟動價 (跳空)\n", "limit-tp-open"),
 ("                    for lot in lots:\n                        if not lot.bracket_live or lot.trail_act is None:\n                            continue\n",
  "                    for lot in lots[:]:\n                        if not lot.bracket_live or lot.trail_act is None:\n                            continue\n                        if _gx_ltp is not None and (ext - lot.trail_act) * direction >= _gx_ltp:\n                            close_lot(lot, p0 if (p0 - lot.trail_act) * direction > 0 else lot.trail_act, t_close, _gx_ltn(lot, direction))\n                            continue\n", "limit-tp-fav"),
 ("                    for lot in lots[:]:\n                        if not lot.bracket_live:\n                            continue\n                        eff = _eff_stop(lot, direction)\n",
  "                    for lot in lots[:]:\n                        if not lot.bracket_live:\n                            continue\n                        if _gx_ltp is not None and lot.trail_act is not None and (p0 - lot.trail_act) * direction >= _gx_ltp:\n                            close_lot(lot, p0, t_close, _gx_ltn(lot, direction))\n                            continue\n                        eff = _eff_stop(lot, direction)\n", "limit-tp-adv"),
 ('                        if not lot.trail_on and (ext - lot.trail_act) * direction >= 0:\n                            lot.trail_on = True\n                            lot.peak = lot.trail_act\n                        if lot.trail_on:\n                            lot.peak = max(lot.peak, ext) if direction > 0 else min(lot.peak, ext)\n',
  '                        if not lot.trail_on and (ext - lot.trail_act) * direction >= 0:\n                            lot.trail_on = True\n                            lot.peak = lot.trail_act\n                        if lot.trail_on:\n                            lot.peak = max(lot.peak, ext) if direction > 0 else min(lot.peak, ext)\n                            if _gx_tcap is not None:\n                                lot.peak = min(lot.peak, lot.trail_act + _gx_tcap) if direction > 0 else max(lot.peak, lot.trail_act - _gx_tcap)\n', "trail-cap"),
 ('        o, h, l, c = B["open"][i], B["high"][i], B["low"][i], B["close"][i]\n',
  '        o, h, l, c = B["open"][i], B["high"][i], B["low"][i], B["close"][i]\n        if _gx_rg:\n            for _k, _v in _gx_rg.items(): p[_k] = _gx_rgbase[_k] * (_v if _gx_below[i] else 1.0)\n', "regime-short"),
 ("                                lot.peak = min(lot.peak, lot.trail_act + _gx_tcap) if direction > 0 else max(lot.peak, lot.trail_act - _gx_tcap)\n",
  "                                lot.peak = min(lot.peak, lot.trail_act + _gx_tcap) if direction > 0 else max(lot.peak, lot.trail_act - _gx_tcap)\n                            if _gx_lock is not None:\n                                _gx_lockset(lot, ext, direction)\n", "lock-fav"),
 ("                    lot.trail_on = True\n                    lot.peak = first_px\n",
  "                    lot.trail_on = True\n                    lot.peak = first_px\n                    if _gx_lock is not None:\n                        _gx_lockset(lot, first_px, direction)\n", "lock-open"),
 ("        if pending:\n            for act, arg in pending:\n",
  "        if pending:\n            _gx_o, _gx_t = o, t_open\n            for act, arg in pending:\n"
  "                if _gx_last_arr[i - 1] and ((act == \"entry\" and _gx_entry_close) or (act != \"entry\" and _gx_exit_close)):\n"
  "                    o, t_open = B[\"close\"][i - 1], ts_close[i - 1]\n"
  "                else:\n                    o, t_open = _gx_o, _gx_t\n"
  "                if _gx_lim_k > 0 and _gx_first[i] and ((act == \"entry\" and _gx_lim_entry) or (act != \"entry\" and _gx_lim_exit)):\n"
  "                    _sb = (arg[1] > 0) if act == \"entry\" else (direction < 0)\n"
  "                    _L = _gx_o - _gx_lim_k * _gx_atr_prev[i] if _sb else _gx_o + _gx_lim_k * _gx_atr_prev[i]\n"
  "                    _s0 = bar_start_idx[i]; _e1 = min(_s0 + _gx_lim_w, bar_start_idx[i + 1] if i + 1 < n else len(m_arr)); _hit = None\n"
  "                    for _k in range(_s0, _e1):\n"
  "                        if (_sb and m_arr[_k][2] <= _L - 1) or ((not _sb) and m_arr[_k][1] >= _L + 1):\n"
  "                            _hit = _k; break\n"
  "                    if _hit is not None:\n"
  "                        o, t_open = _L, m_open[_hit]\n"
  "                    else:\n"
  "                        o, t_open = m_arr[_e1 - 1][3], m_open[_e1 - 1] + np.timedelta64(1, \"m\")\n", "pending-open"),
 ("            pending = []\n\n        # ── 2)", "            pending = []\n            o, t_open = _gx_o, _gx_t\n\n        # ── 2)", "pending-restore"),
 ("                for k in range(s_, e_ + 1 if e_ < len(m_arr) else e_):\n",
  "                for k in range(s_, e_ if (_gx_fix_all or (_gx_fix and _gx_last_arr[i])) else (e_ + 1 if e_ < len(m_arr) else e_)):\n", "fix-cross-session"),
 ("                eff = _eff_stop(lot, direction)\n                if eff is not None and (first_px",
  "                eff = _gx_es(lot, direction, i)\n                if eff is not None and (first_px", "grace-gap"),
 ("                        eff = _eff_stop(lot, direction)\n                        if eff is None:",
  "                        eff = _gx_es(lot, direction, i)\n                        if eff is None:", "grace-seg"),
 ("        # ── 3) 收盤: 指標訊號 → 掛單 ──\n",
  "        if _gx_grace_arr[i] and lots:\n"
  "            for lot in lots:\n"
  "                _e0 = _eff_stop(lot, direction)\n"
  "                if lot.bracket_live and _e0 is not None and (c - _e0) * direction <= 0:\n"
  "                    pending.append((\"close_lot_ts\", (lot.entry_ts, \"Grace_Close\")))\n"
  "        # ── 3) 收盤: 指標訊號 → 掛單 ──\n", "grace-close"),
 ("                if act == \"close_all\":\n                    for lot in lots[:]:\n                        close_lot(lot, o, t_open, \"Trend Rev\")\n",
  "                if act == \"close_all\":\n                    for lot in lots[:]:\n"
  "                        if _gx_trev_keep and lot.kind in (\"Add\", \"G\") and (B[\"close\"][i - 1] - lot.entry_px) * direction > 0:\n"
  "                            continue\n"
  "                        close_lot(lot, o, t_open, \"Trend Rev\")\n", "trev-keep"),
 ("                    pending.append((\"close_kind\", (\"Cmd\", \"S_Cmd_Fast\")))\n",
  "                    if not _gx_no_sfast:\n                        pending.append((\"close_kind\", (\"Cmd\", \"S_Cmd_Fast\")))\n", "no-sfast"),
 ("        # ── 3) 收盤: 指標訊號 → 掛單 ──\n",
  "        if _gx_confirm and len(lots) == 1 and lots[0].kind == \"Cmd\" and short_pyramid_orders == 0 and long_pyramid_orders == 0 \\\n"
  "                and (t_close - lots[0].entry_ts) >= np.timedelta64(int(_gx_confirm), \"m\"):\n"
  "            pending.append((\"close_lot_ts\", (lots[0].entry_ts, \"Confirm_TO\")))\n"
  "        # ── 3) 收盤: 指標訊號 → 掛單 ──\n", "confirm"),
 ('and _mlg_cmd_ok:\n            pending.append(("entry", ("Cmd", 1)))', 'and _mlg_cmd_ok and not _gx_blkL[i]:\n            pending.append(("entry", ("Cmd", 1)))', "gapdir-L"),
 ('and _mlg_cmd_ok:\n            pending.append(("entry", ("Cmd", -1)))', 'and _mlg_cmd_ok and not _gx_blkS[i]:\n            pending.append(("entry", ("Cmd", -1)))', "gapdir-S"),
 ("        # ── 3) 收盤: 指標訊號 → 掛單 ──\n",
  "        _GX_TOFF[0] = (_gx_toff_k * B[\"atr\"][i]) if (_gx_toff_k > 0 and lots and (short_pyramid_orders if direction < 0 else long_pyramid_orders) >= _gx_toff_n) else 1.0\n"
  "        # ── 3) 收盤: 指標訊號 → 掛單 ──\n", "trail-offset"),
 ("                    segs.extend(_segments(mo, mh, ml, mc))\n",
  "                    segs.extend(((mo, mh), (mh, ml), (ml, mc)) if (_gx_adverse and direction < 0) else ((mo, ml), (ml, mh), (mh, mc)) if _gx_adverse else _segments(mo, mh, ml, mc))\n", "adverse-path"),
 ('            pending.append(("entry", ("G", 1)))\n',
  '            if not _gx_no_lg:\n                pending.append(("entry", ("G", 1)))\n', "no-long-g"),
 ('            pending.append(("entry", ("G", -1)))\n',
  '            if not _gx_no_sg:\n                pending.append(("entry", ("G", -1)))\n', "no-short-g"),
 ("    # 期末強制平倉\n",
  "        if _gx_flat and _gx_flat_arr[i] and _gx_sess_ok[i] and lots and (_gx_side == \"both\" or (_gx_side == \"S\") == (direction < 0)):\n"
  "            _gx_j = {\"m1\": 1, \"m2\": 2}.get(_gx_when, 0)\n"
  "            _gx_px = m_arr[bar_end_idx[i] - 1 - _gx_j][3] if _gx_j else c\n"
  "            _gx_tt = t_close - np.timedelta64(_gx_j, \"m\")\n"
  "            _gx_sel = [x for x in lots if _gx_flat == \"all\" or (_gx_flat == \"loss\" and (_gx_px - x.entry_px) * direction < _gx_margin * atr_i) or (_gx_flat == \"addg\" and x.kind in (\"Add\", \"G\"))]\n"
  "            if _gx_when == \"prelast\":\n                pending.extend((\"close_lot_ts\", (x.entry_ts, \"Gap_Flat\")) for x in _gx_sel)\n"
  "            else:\n"
  "                for lot in _gx_sel:\n                    close_lot(lot, _gx_px, _gx_tt, \"Gap_Flat\")\n"
  "                if not lots:\n                    pending = [x for x in pending if x[0] != \"entry\"]\n"
  "    # 期末強制平倉\n", "flat"),
]
_GX_TOFF = [1.0]   # trail offset in points (engine default 1); set at each bar close, used from the next bar on
def _eff_stop_gx(lot, direction):
    off = _GX_TOFF[0]
    stops = [s for s in (lot.loss_stop, lot.be_stop, lot.stale_stop,
                         (lot.peak - off if direction > 0 else lot.peak + off) if lot.trail_on else None) if s is not None]
    if not stops: return None
    return max(stops) if direction > 0 else min(stops)
def _stop_name_gx(lot, eff, direction):
    off = _GX_TOFF[0]; side = "L" if direction > 0 else "S"
    ts = (lot.peak - off if direction > 0 else lot.peak + off) if lot.trail_on else None
    if ts is not None and eff == ts:
        return f"{side}_Exit" + ("_Add" if lot.kind == "Add" else "_G" if lot.kind == "G" else "")
    return _stop_name_orig(lot, eff, direction)
_stop_name_orig = vars(_lb)["_stop_name"]
_ns = {}
exec(compile(_src.replace("def _build_run", "def _build_run_gx"), __file__, "exec"), vars(_lb) | {"_GX_EDITS": _GX_EDITS}, _ns)
_g = dict(vars(_lb)); _g["_GX_EDITS"] = _GX_EDITS
_g.update(_GX_TOFF=_GX_TOFF, _eff_stop=_eff_stop_gx, _stop_name=_stop_name_gx)
run = (lambda f: f)(type(_ns["_build_run_gx"])(_ns["_build_run_gx"].__code__, _g)())
