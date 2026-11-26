s = open("../round11/fa_run11.py", encoding="utf-8").read()
def rep(o, n):
    global s; assert s.count(o) == 1, o[:60]; s = s.replace(o, n)
rep('"at": None, "jb": None}', '"at": None, "jb": None, "vb": None, "vx": None}')
rep('at=None, jb=None)\n', 'at=None, jb=None, vb=None, vx=None)\n')
rep('TAGS = {"AW6"', 'TAGS = {"VB": dict(N, nobe=True, vb=True), "VX": dict(N, nobe=True, vx=True), "AW6"')
rep('def _FA_CNT(k)', '''_V = {"on": False, "hi": None, "lo": None, "hbl": None, "lbh": None, "bull": False, "bear": False, "xb": False, "xs": False, "days": []}
def _FA_VSTEP(t, h, l, c):
    if not (_FA_CFG["vb"] or _FA_CFG["vx"]): return
    t = pd.Timestamp(t); mm = t.hour * 60 + t.minute
    day = 530 <= mm <= 825          # 5-min bars closing 08:50 .. 13:45
    if not day:
        _V.update(on=False, bull=False, bear=False, xb=False, xs=False)
        if _FA_CFG["vb"] and not _FA_CFG["lma"]: _ST["blkL"] = False
        return
    if not _V["on"]:
        _V.update(on=True, hi=h, lo=l, hbl=h, lbh=l, bull=False, bear=False, xb=False, xs=False)
    else:
        if h > _V["hi"]: _V["hi"] = h
        if l < _V["lo"]: _V["lo"] = l; _V["hbl"] = _V["hi"]
        if h >= _V["hi"]: _V["lbh"] = _V["lo"]
    pc = _ST["prev"]
    if not pc: return
    rng = _V["hi"] - _V["lo"]
    if not _V["bull"]:
        dr = _V["hbl"] - _V["lo"]
        if dr >= 0.025 * pc and c - _V["lo"] >= 0.5 * dr and rng >= 0.05 * pc:
            _V["bull"] = True; _V["xb"] = True; _V["days"].append((str(t)[:16], "bull"))
    if not _V["bear"]:
        ur = _V["hi"] - _V["lbh"]
        if ur >= 0.025 * pc and _V["hi"] - c >= 0.5 * ur and rng >= 0.05 * pc:
            _V["bear"] = True; _V["xs"] = True; _V["days"].append((str(t)[:16], "bear"))
    if _FA_CFG["vb"] and not _FA_CFG["lma"]: _ST["blkL"] = _V["bear"]
def _FA_VBS():
    return bool(_FA_CFG["vb"]) and _V["bull"]
def _FA_VXCLOSE(direction):
    if not _FA_CFG["vx"]: return False
    if direction < 0 and _V["xb"]: _V["xb"] = False; return True
    if direction > 0 and _V["xs"]: _V["xs"] = False; return True
    return False
def _FA_CNT(k)''')
rep('def _FA_CAPOK(pos):\n', 'def _FA_CAPOK(pos):\n    if (_FA_CFG["vb"] or _FA_CFG["vx"]) and pos != 0 and ((pos < 0 and _V["bull"]) or (pos > 0 and _V["bear"])): return False\n')
rep('_fa_anc = _FA_STEP(ts_open[i], ts_close[i], o, c, B["atr"][i])\\n        _FA_JUMP(',
    '_fa_anc = _FA_STEP(ts_open[i], ts_close[i], o, c, B["atr"][i])\\n        _FA_VSTEP(ts_close[i], h, l, c)\\n        _fa_anc = _fa_anc or _FA_VBS()\\n        _FA_JUMP(')
rep('            for _al in _FA_ATCHK(lots, direction, c):',
    '            if _FA_VXCLOSE(direction):\\n'
    '                for _k in (\\"Add\\", \\"G\\"):\\n'
    '                    if any(x.kind == _k for x in lots): pending.append((\\"close_kind\\", (_k, (\\"L_\\" if direction > 0 else \\"S_\\") + _k + \\"_VX\\")))\\n'
    '            for _al in _FA_ATCHK(lots, direction, c):')
rep('_FA_ATCHK=_FA_ATCHK, _AT=_AT, _JB=_JB)', '_FA_ATCHK=_FA_ATCHK, _AT=_AT, _JB=_JB, _FA_VSTEP=_FA_VSTEP, _FA_VBS=_FA_VBS, _FA_VXCLOSE=_FA_VXCLOSE, _V=_V)')
rep('_AT.clear(); _JB.update(pc=None, since=999);', '_AT.clear(); _JB.update(pc=None, since=999); _V.update(on=False, bull=False, bear=False, xb=False, xs=False, days=[]);')
rep('    import json; (OUT / f"{case}_xtdays.json").write_text(json.dumps(_FA_S["xt_days"]))',
    '    import json; (OUT / f"{case}_xtdays.json").write_text(json.dumps(_FA_S["xt_days"])); (OUT / f"{case}_vdays.json").write_text(json.dumps(_V["days"]))')
rep('/ "round11" /', '/ "round12" /')
open("fa_run12.py", "w", encoding="utf-8").write(s); print("ok")
