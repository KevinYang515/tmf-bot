s = open("../round13/fa_run13.py", encoding="utf-8").read()
def rep(o, n):
    global s; c = s.count(o); assert c == 1, (c, o[:50]); s = s.replace(o, n)
B = 'nobe=True, ll=5.0, lb=7.0, lbsd=True, s24=2.0'
rep('"s24": None, "fn": None, "uo": None}', '"s24": None, "fn": None, "uo": None, "mx7l": None, "ex8": None, "ns5": None, "sat1": None, "lb7x": None, "sjl": None}')
rep('s24=None, fn=None, uo=None)\n', 's24=None, fn=None, uo=None, mx7l=None, ex8=None, ns5=None, sat1=None, lb7x=None, sjl=None)\n')
rep('TAGS = {"S24_2_UO15"', 'TAGS = {"MX7L": dict(N, ' + B + ', mx7l=True), "EX8L": dict(N, ' + B + ', ex8="L"), "EX8S": dict(N, ' + B + ', ex8="S"), '
    '"NS5": dict(N, ' + B + ', ns5=True), "SAT1": dict(N, ' + B + ', sat1=True), "LB7X": dict(N, ' + B + ', lb7x=True), '
    '"SJL1": dict(N, ' + B + ', sjl=1.0), "SJL2": dict(N, ' + B + ', sjl=2.0), "S24_2_UO15"')
rep('def _FA_CNT(k)', '''_CC = {"seen": set(), "n": 0}
def _FA_CNTSTEP(lots):
    for x in lots:
        if x.kind in ("Add", "G"):
            k = (x.entry_ts, x.kind, x.entry_px)
            if k not in _CC["seen"]: _CC["seen"].add(k); _CC["n"] += 1
_SJL = {"d": None, "hi": None, "hit": False, "fire": False}
def _FA_SJLSTEP(h, c):
    cf = _FA_CFG["sjl"]
    if cf is None: return
    if _SJL["d"] != _ST["d"]: _SJL.update(d=_ST["d"], hi=h, hit=False, fire=False)
    else: _SJL["hi"] = max(_SJL["hi"], h)
    pc = _ST["prev"]
    if not _SJL["hit"] and pc and _SJL["hi"] >= pc * 1.05 and c <= _SJL["hi"] * (1 - cf / 100):
        _SJL["hit"] = True; _SJL["fire"] = True
def _FA_NIGHT():
    t = _ST["lastclose_ts"]
    return t is not None and (t.hour >= 15 or t.hour < 5 or (t.hour == 5 and t.minute == 0))
def _FA_CNT(k)''')
rep('def _FA_END(d, px, t, pnl, lot, npyr, comment):\n', 'def _FA_END(d, px, t, pnl, lot, npyr, comment):\n    _CC["seen"].clear(); _CC["n"] = 0\n')
rep('def _FA_CAPOK(pos):\n', 'def _FA_CAPOK(pos):\n'
    '    if _FA_CFG["mx7l"] and pos > 0 and _CC["n"] >= 7: return False\n'
    '    if _FA_CFG["ns5"] and pos < 0 and _ST["prev"] and _FA_NIGHT() and (1 - _ST["last"] / _ST["prev"]) * 100 >= 5: return False\n'
    '    if _FA_CFG["sat1"] and pos < 0 and _ST["prev"] and not _FA_NIGHT() and _ST["last"] > _ST["prev"]: return False\n'
    '    if _FA_CFG["sjl"] is not None and pos > 0 and _SJL["hit"] and _SJL["d"] == _ST["d"]: return False\n')
rep('        _FA_S24STEP(ts_close[i], h, c)\\n', '        _FA_S24STEP(ts_close[i], h, c)\\n        _FA_SJLSTEP(h, c)\\n')
rep('            _sjm = _FA_SJFIRE()\\n',
    '            _FA_CNTSTEP(lots)\\n'
    '            if _FA_CFG[\\"ex8\\"] == \\"L\\" and direction > 0 and _CC[\\"n\\"] >= 7 and c > avgPrice + baseATR * p[\\"l_pyramid_dist\\"]: pending.append((\\"close_all_sig\\", \\"L_EX8\\"))\\n'
    '            elif _FA_CFG[\\"ex8\\"] == \\"S\\" and direction < 0 and _CC[\\"n\\"] >= 7 and c < avgPrice - baseATR * p[\\"s_pyramid_dist\\"]: pending.append((\\"close_all_sig\\", \\"S_EX8\\"))\\n'
    '            if _FA_CFG[\\"lb7x\\"] and direction < 0 and _ST[\\"prev\\"] and (1 - c / _ST[\\"prev\\"]) * 100 >= 7:\\n'
    '                for _k in (\\"Add\\", \\"G\\"):\\n'
    '                    if any(x.kind == _k for x in lots): pending.append((\\"close_kind\\", (_k, \\"S_\\" + _k + \\"_LB7X\\")))\\n'
    '            if _FA_CFG[\\"sjl\\"] is not None and _SJL[\\"fire\\"]:\\n'
    '                _SJL[\\"fire\\"] = False\\n'
    '                if direction > 0:\\n'
    '                    for _k in (\\"Add\\", \\"G\\"):\\n'
    '                        if any(x.kind == _k for x in lots): pending.append((\\"close_kind\\", (_k, \\"L_\\" + _k + \\"_SJL\\")))\\n'
    '            _sjm = _FA_SJFIRE()\\n')
rep('_FA_S24STEP=_FA_S24STEP, _S24=_S24)', '_FA_S24STEP=_FA_S24STEP, _S24=_S24, _FA_CNTSTEP=_FA_CNTSTEP, _CC=_CC, _FA_SJLSTEP=_FA_SJLSTEP, _SJL=_SJL, _FA_NIGHT=_FA_NIGHT)')
rep('_S24["q"].clear(); _S24["blk"] = False;', '_S24["q"].clear(); _S24["blk"] = False; _CC["seen"].clear(); _CC["n"] = 0; _SJL.update(d=None, hi=None, hit=False, fire=False);')
rep('/ "round13" /', '/ "round14" /')
open("fa_run14.py", "w", encoding="utf-8").write(s); print("ok")
