s = open("fa_run14.py", encoding="utf-8").read()
def rep(o, n):
    global s; c = s.count(o); assert c == 1, (c, o[:50]); s = s.replace(o, n)
BS = "\\n"   # literal backslash-n as it appears inside the GX edit strings
rep('"lb7x": None, "sjl": None}', '"lb7x": None, "sjl": None, "bdl": None}')
rep('lb7x=None, sjl=None)\n', 'lb7x=None, sjl=None, bdl=None)\n')
rep('TAGS = {"MX7L"', 'TAGS = {"BDL1": dict(N, nobe=True, ll=5.0, lb=7.0, lbsd=True, s24=2.0, bdl=1.0), "BDL2": dict(N, nobe=True, ll=5.0, lb=7.0, lbsd=True, s24=2.0, bdl=2.0), "MX7L"')
rep('def _FA_NIGHT():', '''_BDL = {"d": None, "hi": None, "hit": False, "fire": False}
def _FA_BDLSTEP(h, c):
    cf = _FA_CFG["bdl"]
    if cf is None: return
    if _BDL["d"] != _ST["d"]: _BDL.update(d=_ST["d"], hi=h, hit=False, fire=False)
    else: _BDL["hi"] = max(_BDL["hi"], h)
    pc = _ST["prev"]
    if not _BDL["hit"] and pc and _BDL["hi"] >= pc * 1.05 and c <= _BDL["hi"] * (1 - cf / 100):
        _BDL["hit"] = True; _BDL["fire"] = True
def _FA_BDLFIRE():
    if _FA_CFG["bdl"] is None or not _BDL["fire"]: return False
    _BDL["fire"] = False; return True
def _FA_NIGHT():''')
rep('        _FA_SJLSTEP(h, c)' + BS, '        _FA_SJLSTEP(h, c)' + BS + '        _FA_BDLSTEP(h, c)' + BS)
Q = '\\"'   # escaped double quote inside the GX edit strings
anchor = ' ("            # 市價平倉 (訊號 bar 收盤 → 下一開盤成交)' + BS + '",'
new = (' ("        # 出場單更新 (下一 bar 生效) + 市價平倉訊號' + BS + '", "'
       '        if _FA_BDLFIRE() and not any(_a[0] == ' + Q + 'entry' + Q + ' for _a in pending):' + BS +
       '            if posSize == 0: pending.append((' + Q + 'entry' + Q + ', (' + Q + 'Cmd' + Q + ', 1))); baseATR = atr_i' + BS +
       '            elif 0 < posSize < 3: pending.append((' + Q + 'entry' + Q + ', (' + Q + 'Add' + Q + ', 1))); addATR = atr_i' + BS +
       '        # 出場單更新 (下一 bar 生效) + 市價平倉訊號' + BS + '", "bdl-entry"),\n' + anchor)
rep(anchor, new)
rep('_FA_NIGHT=_FA_NIGHT)', '_FA_NIGHT=_FA_NIGHT, _FA_BDLSTEP=_FA_BDLSTEP, _FA_BDLFIRE=_FA_BDLFIRE, _BDL=_BDL)')
rep('_SJL.update(d=None, hi=None, hit=False, fire=False);', '_SJL.update(d=None, hi=None, hit=False, fire=False); _BDL.update(d=None, hi=None, hit=False, fire=False);')
open("fa_run14.py", "w", encoding="utf-8").write(s); print("ok")
