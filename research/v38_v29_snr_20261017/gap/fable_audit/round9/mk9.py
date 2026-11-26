s = open("../round8/fa_run8.py", encoding="utf-8", newline="").read().replace("\r\n", "\n")
def rep(o, n):
    global s; assert s.count(o) == 1, o[:70]; s = s.replace(o, n)
rep('"nx": None, "pp": None}', '"nx": None, "pp": None, "lb": None}')
rep('nx=None, pp=None)\nTAGS = {', 'nx=None, pp=None, lb=None)\nTAGS = {"LB5": dict(N, nobe=True, lb=5.0), "LB7": dict(N, nobe=True, lb=7.0), '
    '"PD05": dict(N, nobe=True, pp={"s_pyramid_dist": 0.5, "l_pyramid_dist": 0.6}), "PD15": dict(N, nobe=True, pp={"s_pyramid_dist": 1.5, "l_pyramid_dist": 1.8}), ')
rep('def _FA_CAPOK(pos):\n    if _FA_CFG["nx"] and _FA_NXT(): return False\n',
    'def _FA_CAPOK(pos):\n    if _FA_CFG["nx"] and _FA_NXT(): return False\n'
    '    if _FA_CFG["lb"] and pos != 0 and _ST["prev"] and (_ST["last"] / _ST["prev"] - 1) * 100 * (1 if pos > 0 else -1) >= _FA_CFG["lb"]: return False\n')
rep('/ "round8" /', '/ "round9" /')
open("fa_run9.py", "w", encoding="utf-8").write(s); print("ok")
