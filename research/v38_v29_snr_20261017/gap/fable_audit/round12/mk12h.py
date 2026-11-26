s = open("fa_run12.py", encoding="utf-8").read()
def rep(o, n):
    global s; c = s.count(o); assert c == 1, (c, o[:50]); s = s.replace(o, n)
rep('"sj": None, "ll": None}', '"sj": None, "ll": None, "s24": None, "fn": None}')
rep('sj=None, ll=None)\n', 'sj=None, ll=None, s24=None, fn=None)\n')
rep('TAGS = {"LL5p5"', 'TAGS = {"LL5S_S24": dict(N, nobe=True, ll=5.0, lb=7.0, lbsd=True, s24=1.0), "LL5S_FN": dict(N, nobe=True, ll=5.0, lb=7.0, lbsd=True, fn=True), '
    '"LL5S_S24FN": dict(N, nobe=True, ll=5.0, lb=7.0, lbsd=True, s24=1.0, fn=True), "LL5p5"')
rep('def _FA_CNT(k)', '''_S24 = {"q": deque(), "blk": False}
def _FA_S24STEP(t, h, c):
    cf = _FA_CFG["s24"]; _S24["blk"] = False
    t = pd.Timestamp(t)
    if _FA_CFG["fn"] and t.dayofweek == 5 and t.hour < 5: _S24["blk"] = True
    if cf is None: return
    q = _S24["q"]
    while q and q[-1][1] <= h: q.pop()
    q.append((t, h))
    lim = t - pd.Timedelta(hours=24)
    while q and q[0][0] < lim: q.popleft()
    if (1 - c / q[0][1]) * 100 < cf: _S24["blk"] = True
def _FA_CNT(k)''')
rep('        _FA_LLSTEP(ts_close[i], l, c)\\n', '        _FA_LLSTEP(ts_close[i], l, c)\\n        _FA_S24STEP(ts_close[i], h, c)\\n        _fa_anc = _fa_anc or _S24[\\"blk\\"]\\n')
rep('_FA_LLSTEP=_FA_LLSTEP, _LL=_LL)', '_FA_LLSTEP=_FA_LLSTEP, _LL=_LL, _FA_S24STEP=_FA_S24STEP, _S24=_S24)')
rep('_LL["minq"].clear();', '_LL["minq"].clear(); _S24["q"].clear(); _S24["blk"] = False;')
open("fa_run12.py", "w", encoding="utf-8").write(s); print("ok")
