s = open("fa_run13.py", encoding="utf-8").read()
def rep(o, n):
    global s; c = s.count(o); assert c == 1, (c, o[:50]); s = s.replace(o, n)
rep('"s24": None, "fn": None}', '"s24": None, "fn": None, "uo": None}')
rep('s24=None, fn=None)\n', 's24=None, fn=None, uo=None)\n')
rep('TAGS = {**{f"SW_', 'TAGS = {"S24_2_UO15": dict(N, nobe=True, ll=5.0, lb=7.0, lbsd=True, s24=2.0, uo=15), **{f"SW_')
rep('def _FA_S24STEP(t, h, c):\n', '''_UOC = {}
def _FA_USOPEN(t):
    d = t.normalize() - pd.Timedelta(days=1) if t.hour < 12 else t.normalize()
    k = d.date()
    if k not in _UOC:   # 09:30 America/New_York -> Asia/Taipei (DST aware)
        _UOC[k] = (pd.Timestamp(k).tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=30)).tz_convert("Asia/Taipei").tz_localize(None)
    return _UOC[k]
def _FA_S24STEP(t, h, c):
    if _FA_CFG["uo"]:
        _tt = pd.Timestamp(t); _uo = _FA_USOPEN(_tt)
        if _uo <= _tt < _uo + pd.Timedelta(minutes=_FA_CFG["uo"]): _ST["blkL"] = True
''')
open("fa_run13.py", "w", encoding="utf-8").write(s); print("ok")
