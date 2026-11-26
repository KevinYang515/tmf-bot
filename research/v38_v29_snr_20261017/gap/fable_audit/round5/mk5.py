s = open("../round4/fa_run4.py", encoding="utf-8", newline="").read().replace("\r\n", "\n")
def rep(o, n):
    global s; assert s.count(o) == 1, o[:60]; s = s.replace(o, n)
rep('"cbe": None}', '"cbe": None, "xt": None}')
rep('"cbe_lv": None, "n_cbe": 0}', '"cbe_lv": None, "n_cbe": 0, "xt_on": False, "xt_best": None, "xt_lv": None, "n_xt": 0, "xt_days": []}')
rep('    _FA_S["cbe_on"] = False; _FA_S["cbe_lv"] = None\n', '    _FA_S["cbe_on"] = False; _FA_S["cbe_lv"] = None; _FA_S["xt_on"] = False; _FA_S["xt_best"] = None; _FA_S["xt_lv"] = None\n')
rep('def _FA_CNT(k)', '''def _FA_XT(lots, direction, c, batr):
    cf = _FA_CFG["xt"]
    if cf is None or not lots or not np.isfinite(batr): return
    ref = _ST["prev"]
    if not _FA_S["xt_on"]:
        if ref is None or (c / ref - 1) * 100 * direction < cf[0]: return
        _FA_S["xt_on"] = True; _FA_S["xt_best"] = c; _FA_S["n_xt"] += 1; _FA_S["xt_days"].append((str(_ST["d"])[:10], direction))
    _FA_S["xt_best"] = max(_FA_S["xt_best"], c) if direction > 0 else min(_FA_S["xt_best"], c)
    _FA_S["xt_lv"] = round(_FA_S["xt_best"] - direction * cf[1] * batr)
def _FA_CNT(k)''')
rep(r'_FA_CBE(lots, direction, c, baseATR)\n', r'_FA_CBE(lots, direction, c, baseATR)\n        _FA_XT(lots, direction, c, baseATR)\n')
rep('''    e = _eff_nobe0(lot, direction); lv = _FA_S["cbe_lv"]
    if lv is None: return e
    if e is None: return lv
    return max(e, lv) if direction > 0 else min(e, lv)''', '''    e = _eff_nobe0(lot, direction)
    for lv in (_FA_S["cbe_lv"], _FA_S["xt_lv"]):
        if lv is None: continue
        e = lv if e is None else (max(e, lv) if direction > 0 else min(e, lv))
    return e''')
rep('_FA_CBE=_FA_CBE,', '_FA_CBE=_FA_CBE, _FA_XT=_FA_XT,')
rep('DATA = HERE / "mxf_1min_2020_20261111.csv"; OUT = HERE / "gap" / "fable_audit" / "round4" / "eng"',
    'DATA = HERE / os.environ.get("FA_DATA", "mxf_1min_2020_20261111.csv"); OUT = HERE / "gap" / "fable_audit" / "round5" / os.environ.get("FA_OUT", "eng")')
rep('TAGS = {', 'TAGS = {**{f"XT{x}_{k}": dict(N, nobe=True, xt=(float(x), float(k))) for x in (3, 4, 6) for k in (1, 2)}, ')
rep('cbe_on=False, cbe_lv=None, n_cbe=0)', 'cbe_on=False, cbe_lv=None, n_cbe=0, xt_on=False, xt_best=None, xt_lv=None, n_xt=0, xt_days=[])')
rep('("n_lock", "n_blk", "n_early", "n_cbe")}, flush=True)', '("n_lock", "n_blk", "n_early", "n_cbe", "n_xt")}, flush=True)\n    import json; (OUT / f"{case}_xtdays.json").write_text(json.dumps(_FA_S["xt_days"]))')
rep('"""Fable', '"""Round 5: + XT (大波動日收緊出場). Based on round-4 runner. Fable')
open("fa_run5.py", "w", encoding="utf-8").write(s); print("ok")
