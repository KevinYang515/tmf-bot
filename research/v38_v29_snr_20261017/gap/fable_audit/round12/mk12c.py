s = open("fa_run12.py", encoding="utf-8").read()
def rep(o, n):
    global s; c = s.count(o); assert c == 1, (c, o[:50]); s = s.replace(o, n)
rep('"lbsd": None, "lbsc": None}', '"lbsd": None, "lbsc": None, "grd": None}')
rep('lbsd=None, lbsc=None)\n', 'lbsd=None, lbsc=None, grd=None)\n')
rep('TAGS = {"LB7S"', 'TAGS = {"GR57": dict(N, nobe=True, grd=(5.0, 3, 7.0)), "GR67": dict(N, nobe=True, grd=(6.0, 3, 7.0)), "LB7S"')
rep('def _FA_CAPOK(pos):\n', 'def _FA_CAPOK(pos):\n'
    '    if _FA_CFG["grd"] is not None and pos < 0 and _ST["prev"]:\n'
    '        _dn = (1 - _ST["last"] / _ST["prev"]) * 100; _g = _FA_CFG["grd"]\n'
    '        if _dn >= _g[2] or (_dn >= _g[0] and abs(pos) >= _g[1]): return False\n')
open("fa_run12.py", "w", encoding="utf-8").write(s); print("ok")
