s = open("../round7/fa_run7.py", encoding="utf-8", newline="").read().replace("\r\n", "\n")
def rep(o, n):
    global s; assert s.count(o) == 1, o[:70]; s = s.replace(o, n)
rep('"cap": None, "ac": None}', '"cap": None, "ac": None, "nx": None, "pp": None}')
rep('cap=None, ac=None)\nTAGS = {', 'cap=None, ac=None, nx=None, pp=None)\nTAGS = {"ML2": dict(N, nobe=True, pp={"opt_max_lots": 2}), "ML3": dict(N, nobe=True, pp={"opt_max_lots": 3}), '
    '"NX": dict(N, nobe=True, nx="add"), "NXG": dict(N, nobe=True, nx="addg"), "ABE1": dict(N, nobe=True, pp={"opt_add_be_trigger": 1.0}), "ABE2": dict(N, nobe=True, pp={"opt_add_be_trigger": 2.0}), ')
# block new Add/G late in night session
rep('def _FA_CAPOK(pos):\n    cf = _FA_CFG["cap"]\n    if cf is None: return True\n',
    'def _FA_NXT():\n    t = _ST["lastclose_ts"]\n    return t is not None and t.hour == 4 and t.minute >= 40\n'
    'def _FA_CAPOK(pos):\n    if _FA_CFG["nx"] and _FA_NXT(): return False\n    cf = _FA_CFG["cap"]\n    if cf is None: return True\n')
rep('gw._GX_EDITS.extend([\n (\'lot.loss_stop',
    'gw._GX_EDITS.extend([\n'
    ' ("            # 市價平倉 (訊號 bar 收盤 → 下一開盤成交)\\n",'
    ' "            if _FA_CFG[\\"nx\\"] and _ST[\\"lastclose_ts\\"].hour == 4 and 45 <= _ST[\\"lastclose_ts\\"].minute <= 55:\\n'
    '                for _k in ((\\"Add\\", \\"G\\") if _FA_CFG[\\"nx\\"] == \\"addg\\" else (\\"Add\\",)):\\n'
    '                    if any(x.kind == _k for x in lots): pending.append((\\"close_kind\\", (_k, (\\"L_\\" if direction > 0 else \\"S_\\") + _k + \\"_NX\\")))\\n'
    '            # 市價平倉 (訊號 bar 收盤 → 下一開盤成交)\\n", "nx-close"),\n'
    ' (\'lot.loss_stop')
rep('t = gw.run(gw.load_1min(DATA), p=v30e_ltp(), intrabar_mode="1min")',
    't = gw.run(gw.load_1min(DATA), p={**v30e_ltp(), **(_FA_CFG["pp"] or {})}, intrabar_mode="1min")')
rep('_FA_CAPOK=_FA_CAPOK)', '_FA_CAPOK=_FA_CAPOK, _FA_NXT=_FA_NXT)')
rep('/ "round7" /', '/ "round8" /')
open("fa_run8.py", "w", encoding="utf-8").write(s); print("ok")
