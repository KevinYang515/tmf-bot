s = open("fa_run12.py", encoding="utf-8").read()
def rep(o, n):
    global s; c = s.count(o); assert c == 1, (c, o[:50]); s = s.replace(o, n)
rep('"lbsc": None, "grd": None}', '"lbsc": None, "grd": None, "sj": None}')
rep('lbsc=None, grd=None)\n', 'lbsc=None, grd=None, sj=None)\n')
rep('TAGS = {"GR57"', 'TAGS = {**{f"SJ{m}_{str(r).replace(\'.\', \'p\')}": dict(N, nobe=True, sj=(float(r), m)) for r in (1, 1.5, 2) for m in ("A", "C")}, "GR57"')
rep('def _FA_CNT(k)', '''_SJ = {"d": None, "lo": None, "hit": False, "fire": False}
def _FA_SJSTEP(l, c):
    cf = _FA_CFG["sj"]
    if cf is None: return
    if _SJ["d"] != _ST["d"]: _SJ.update(d=_ST["d"], lo=l, hit=False, fire=False)
    else: _SJ["lo"] = min(_SJ["lo"], l)
    pc = _ST["prev"]
    if not _SJ["hit"] and pc and _SJ["lo"] <= pc * 0.95 and c >= _SJ["lo"] * (1 + cf[0] / 100):
        _SJ["hit"] = True; _SJ["fire"] = True
def _FA_SJFIRE():
    if _FA_CFG["sj"] is None or not _SJ["fire"]: return None
    _SJ["fire"] = False; return _FA_CFG["sj"][1]
def _FA_CNT(k)''')
rep('def _FA_CAPOK(pos):\n', 'def _FA_CAPOK(pos):\n    if _FA_CFG["sj"] is not None and pos < 0 and _SJ["hit"] and _SJ["d"] == _ST["d"]: return False\n')
rep('        _FA_VSTEP(ts_close[i], h, l, c)\\n',
    '        _FA_VSTEP(ts_close[i], h, l, c)\\n        _FA_SJSTEP(l, c)\\n')
rep('_fa_anc = _fa_anc or _FA_VBS() or (',
    '_fa_anc = _fa_anc or _FA_VBS() or (_FA_CFG[\\"sj\\"] is not None and _FA_CFG[\\"sj\\"][1] == \\"C\\" and _SJ[\\"hit\\"] and _SJ[\\"d\\"] == _ST[\\"d\\"]) or (')
rep('            if _FA_VXCLOSE(direction):\\n',
    '            _sjm = _FA_SJFIRE()\\n'
    '            if _sjm is not None and direction < 0:\\n'
    '                if _sjm == \\"C\\": pending.append((\\"close_all_sig\\", \\"S_SJ\\"))\\n'
    '                else:\\n'
    '                    for _k in (\\"Add\\", \\"G\\"):\\n'
    '                        if any(x.kind == _k for x in lots): pending.append((\\"close_kind\\", (_k, \\"S_\\" + _k + \\"_SJ\\")))\\n'
    '            if _FA_VXCLOSE(direction):\\n')
rep('_FA_VXCLOSE=_FA_VXCLOSE, _V=_V)', '_FA_VXCLOSE=_FA_VXCLOSE, _V=_V, _FA_SJSTEP=_FA_SJSTEP, _FA_SJFIRE=_FA_SJFIRE, _SJ=_SJ)')
rep('_V.update(on=False, bull=False, bear=False, xb=False, xs=False, days=[]);', '_V.update(on=False, bull=False, bear=False, xb=False, xs=False, days=[]); _SJ.update(d=None, lo=None, hit=False, fire=False);')
open("fa_run12.py", "w", encoding="utf-8").write(s); print("ok")
