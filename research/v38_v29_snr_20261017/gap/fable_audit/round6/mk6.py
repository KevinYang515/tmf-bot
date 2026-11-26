s = open("../round5/fa_run5.py", encoding="utf-8").read()
def rep(o, n):
    global s; assert s.count(o) == 1, o[:70]; s = s.replace(o, n)
rep('"cbe": None, "xt": None}', '"cbe": None, "xt": None, "cap": None}')
rep('"closes": [], "blkL": False}', '"closes": [], "blkL": False, "rng": [], "dhi": None, "dlo": None, "wk": False}')
rep('''        if _ST["prev"] is not None: _ST["closes"].append(_ST["prev"])
''', '''        if _ST["prev"] is not None: _ST["closes"].append(_ST["prev"])
        if _ST["dhi"] is not None and _ST["last"]: _ST["rng"].append((_ST["dhi"] - _ST["dlo"]) / _ST["last"])
        _ST["dhi"] = _ST["dlo"] = None; _ST["wk"] = d in WKSET
''')
rep('''    _ST["last"] = c
''', '''    _ST["last"] = c
    _ST["dhi"] = c if _ST["dhi"] is None else max(_ST["dhi"], c); _ST["dlo"] = c if _ST["dlo"] is None else min(_ST["dlo"], c)
''')
rep('def _FA_CNT(k)', '''WKSET = set()
def _FA_CAPOK(pos):
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
def _FA_CNT(k)''')
rep('gw._g["_eff_stop"] = _eff_nobe\n', '''gw._g["_eff_stop"] = _eff_nobe
gw._GX_EDITS.extend([
 ("        elif 0 < posSize < add_cap and add_gate_ok", "        elif 0 < posSize < add_cap and _FA_CAPOK(posSize) and add_gate_ok", "cap-addL"),
 ("        elif -add_cap < posSize < 0 and add_gate_ok", "        elif -add_cap < posSize < 0 and _FA_CAPOK(posSize) and add_gate_ok", "cap-addS"),
 ("        elif posSize == 3 and allow_g and", "        elif posSize == 3 and allow_g and _FA_CAPOK(posSize) and", "cap-gL"),
 ("        elif posSize == -3 and allow_g and", "        elif posSize == -3 and allow_g and _FA_CAPOK(posSize) and", "cap-gS"),
])
''')
rep('_FA_STEP=_FA_STEP, _ST=_ST)', '_FA_STEP=_FA_STEP, _ST=_ST, _FA_CAPOK=_FA_CAPOK)')
rep('"round5" / os.environ.get("FA_OUT", "eng")', '"round6" / os.environ.get("FA_OUT", "eng")')
rep('cbe=None, xt=None)', 'cbe=None, xt=None, cap=None)')
rep('TAGS = {', 'TAGS = {"VK4": dict(N, nobe=True, cap={"K": 4}), "VK6": dict(N, nobe=True, cap={"K": 6}), "WK1": dict(N, nobe=True, cap={"wk": 1}), "WK2": dict(N, nobe=True, cap={"wk": 2}), "C4_2": dict(N, nobe=True, cap={"K": 4, "wk": 2}), "C6_2": dict(N, nobe=True, cap={"K": 6, "wk": 2}), ')
rep('closes=[], blkL=False);', 'closes=[], blkL=False, rng=[], dhi=None, dlo=None, wk=False);')
rep('n_xt=0, xt_days=[]); OUT.mkdir', 'n_xt=0, xt_days=[], n_cap=0); OUT.mkdir')
rep('    t = gw.run(gw.load_1min(DATA)', '''    _m = pd.read_csv(DATA, usecols=["ts"], parse_dates=["ts"]).ts; _e = _m[(_m.dt.hour == 5) & (_m.dt.minute == 0)]
    _nx = _m.shift(-1)[_e.index]; WKSET.clear(); WKSET.update(set(_e[(_nx - _e) > pd.Timedelta(hours=24)].dt.normalize()))
    t = gw.run(gw.load_1min(DATA)''')
rep('("n_lock", "n_blk", "n_early", "n_cbe", "n_xt")}', '("n_lock", "n_blk", "n_early", "n_cbe", "n_xt", "n_cap")}, "wkset", len(WKSET)')
rep('"n_xt": 0, "xt_days": []}', '"n_xt": 0, "xt_days": [], "n_cap": 0}')
rep('"""Round 5:', '"""Round 6: + lot cap (VK vol-scaled / WK pre-weekend night). Round 5:')
open("fa_run6.py", "w", encoding="utf-8").write(s); print("ok")
