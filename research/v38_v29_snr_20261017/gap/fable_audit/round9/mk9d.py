s = open("fa_run9.py", encoding="utf-8").read()
def rep(o, n):
    global s; assert s.count(o) == 1, o[:60]; s = s.replace(o, n)
rep('"lc": None, "lr": None}', '"lc": None, "lr": None, "lbs": None}')
rep('lc=None, lr=None)\nTAGS = {', 'lc=None, lr=None, lbs=None)\nTAGS = {"LB7D": dict(N, nobe=True, lb=7.0, lbs="D"), "LB7N": dict(N, nobe=True, lb=7.0, lbs="N"), ')
rep('    if _FA_CFG["lb"] and pos != 0 and _ST["prev"]',
    '    _ss = _ST["lastclose_ts"]; _night = _ss is not None and (_ss.hour >= 15 or _ss.hour < 5 or (_ss.hour == 5 and _ss.minute == 0))\n'
    '    if _FA_CFG["lb"] and (_FA_CFG["lbs"] is None or (_FA_CFG["lbs"] == "N") == _night) and pos != 0 and _ST["prev"]')
open("fa_run9.py", "w", encoding="utf-8").write(s); print("ok")
