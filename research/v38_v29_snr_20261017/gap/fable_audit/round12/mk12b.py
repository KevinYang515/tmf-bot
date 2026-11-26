s = open("fa_run12.py", encoding="utf-8").read()
def rep(o, n):
    global s; c = s.count(o); assert c == 1, (c, o[:50]); s = s.replace(o, n)
rep('"vb": None, "vx": None}', '"vb": None, "vx": None, "lbsd": None, "lbsc": None}')
rep('vb=None, vx=None)\n', 'vb=None, vx=None, lbsd=None, lbsc=None)\n')
rep('TAGS = {"VB"', 'TAGS = {"LB7S": dict(N, nobe=True, lb=7.0, lbsd=True), "LB7SC": dict(N, nobe=True, lb=7.0, lbsd=True, lbsc=True), "VB"')
rep('    if _FA_CFG["lb"] and (_FA_CFG["lbs"] is None', '    if _FA_CFG["lb"] and not (_FA_CFG["lbsd"] and pos > 0) and (_FA_CFG["lbs"] is None')
rep('_fa_anc = _fa_anc or _FA_VBS()\\n',
    '_fa_anc = _fa_anc or _FA_VBS() or (bool(_FA_CFG[\\"lbsc\\"]) and bool(_ST[\\"prev\\"]) and c <= _ST[\\"prev\\"] * 0.93)\\n')
open("fa_run12.py", "w", encoding="utf-8").write(s); print("ok")
