s = open("fa_run12.py", encoding="utf-8").read()
def rep(o, n):
    global s; c = s.count(o); assert c == 1, (c, o[:50]); s = s.replace(o, n)
rep('"grd": None, "sj": None}', '"grd": None, "sj": None, "ll": None}')
rep('grd=None, sj=None)\n', 'grd=None, sj=None, ll=None)\n')
rep('TAGS = {"CB1"', 'TAGS = {"LL4": dict(N, nobe=True, ll=4.0), "LL5": dict(N, nobe=True, ll=5.0), "LL5S": dict(N, nobe=True, ll=5.0, lb=7.0, lbsd=True), "CB1"')
rep('def _FA_CNT(k)', '''from collections import deque
_LL = {"q": deque(), "minq": deque()}
def _FA_LLSTEP(t, l, c):
    cf = _FA_CFG["ll"]
    if cf is None: return
    t = pd.Timestamp(t); q = _LL["minq"]
    while q and q[-1][1] >= l: q.pop()
    q.append((t, l))
    lim = t - pd.Timedelta(days=7)
    while q and q[0][0] < lim: q.popleft()
    if not _FA_CFG["lma"]: _ST["blkL"] = c >= q[0][1] * (1 + cf / 100)
def _FA_CNT(k)''')
rep('        _FA_SJSTEP(l, c)\\n', '        _FA_SJSTEP(l, c)\\n        _FA_LLSTEP(ts_close[i], l, c)\\n')
rep('_FA_SJFIRE=_FA_SJFIRE, _SJ=_SJ)', '_FA_SJFIRE=_FA_SJFIRE, _SJ=_SJ, _FA_LLSTEP=_FA_LLSTEP, _LL=_LL)')
rep('_SJ.update(d=None, lo=None, hit=False, fire=False);', '_SJ.update(d=None, lo=None, hit=False, fire=False); _LL["minq"].clear();')
open("fa_run12.py", "w", encoding="utf-8").write(s); print("ok")
