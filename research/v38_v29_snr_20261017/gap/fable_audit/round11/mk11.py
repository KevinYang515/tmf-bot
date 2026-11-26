s = open("../round10/fa_run10.py", encoding="utf-8").read()
def rep(o, n):
    global s; assert s.count(o) == 1, o[:60]; s = s.replace(o, n)
rep('"rb": None, "gb": None}', '"rb": None, "gb": None, "at": None, "jb": None}')
rep('rb=None, gb=None)\n', 'rb=None, gb=None, at=None, jb=None)\n')
rep('TAGS = {"GB40"', 'TAGS = {"AW6": dict(N, nobe=True, pp={"addLossS": 6.0, "addLossL": 6.5}), "AW75": dict(N, nobe=True, pp={"addLossS": 7.5, "addLossL": 8.0}), '
    '"AT18": dict(N, nobe=True, at=(18, 0.75)), "AT36": dict(N, nobe=True, at=(36, 1.0)), "JB3": dict(N, nobe=True, jb=3.0), "JB4": dict(N, nobe=True, jb=4.0), "GB40"')
# state + helpers
rep('def _FA_CNT(k)', '''_AT = {}
_JB = {"pc": None, "since": 999}
def _FA_JUMP(h, l, c, atr):
    if _FA_CFG["jb"] is None: return
    pc = _JB["pc"]; _JB["since"] += 1
    if pc is not None and np.isfinite(atr) and atr > 0:
        tr = max(h - l, abs(h - pc), abs(l - pc))
        if tr / atr >= _FA_CFG["jb"]: _JB["since"] = 0
    _JB["pc"] = c
def _FA_ATCHK(lots, direction, c):
    cf = _FA_CFG["at"]; out = []
    if cf is None: return out
    live = set()
    for x in lots:
        if x.kind != "Add": continue
        k = (x.entry_ts, x.entry_px); live.add(k)
        st = _AT.setdefault(k, [0, -1e18, False])
        st[0] += 1; st[1] = max(st[1], (c - x.entry_px) * direction)
        a = x.entry_atr if x.entry_atr is not None and np.isfinite(x.entry_atr) else np.nan
        if not st[2] and st[0] >= cf[0] and np.isfinite(a) and st[1] < cf[1] * a and (c - x.entry_px) * direction <= 0:
            st[2] = True; out.append(x)
    for k in list(_AT):
        if k not in live: del _AT[k]
    return out
def _FA_CNT(k)''')
# jump block inside CAPOK (blocks Add/G only)
rep('def _FA_CAPOK(pos):\n', 'def _FA_CAPOK(pos):\n    if _FA_CFG["jb"] is not None and _JB["since"] < 12: return False\n')
# per-bar jump update: note atr passed is current bar ATR; use ATR of previous bar via stored value
rep('_fa_anc = _FA_STEP(ts_open[i], ts_close[i], o, c, B["atr"][i])\\n\', "fa-step")',
    '_fa_anc = _FA_STEP(ts_open[i], ts_close[i], o, c, B["atr"][i])\\n        _FA_JUMP(h, l, c, B["atr"][i - 1] if i > 0 else np.nan)\\n\', "fa-step")')
rep('            if _FA_CFG[\\"gb\\"] is not None and _FA_GBHIT',
    '            for _al in _FA_ATCHK(lots, direction, c): pending.append((\\"close_lot_ts\\", (_al.entry_ts, (\\"L_\\" if direction > 0 else \\"S_\\") + \\"Add_AT\\")))\\n'
    '            if _FA_CFG[\\"gb\\"] is not None and _FA_GBHIT')
rep('_FA_GBHIT=_FA_GBHIT, _GB=_GB)', '_FA_GBHIT=_FA_GBHIT, _GB=_GB, _FA_JUMP=_FA_JUMP, _FA_ATCHK=_FA_ATCHK, _AT=_AT, _JB=_JB)')
rep('    _GB["pk"] = 0.0; G["_OFF"]', '    _GB["pk"] = 0.0; _AT.clear(); _JB.update(pc=None, since=999); G["_OFF"]')
rep('/ "round10" /', '/ "round11" /')
open("fa_run11.py", "w", encoding="utf-8").write(s); print("ok")
