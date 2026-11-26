s = open("fa_run9.py", encoding="utf-8").read()
def rep(o, n):
    global s; assert s.count(o) == 1, o[:60]; s = s.replace(o, n)
rep('"lbs": None}', '"lbs": None, "rb": None}')
rep('lbs=None)\nTAGS = {', 'lbs=None, rb=None)\n_RB = {}\ndef _mk_rb():\n'
    '    import numpy as _np\n'
    '    x = pd.read_csv(Path(r"E:/stock/v38_v29_snr_20261017/gap/fable_audit/round9/eng1125/NOBE_off0.csv"), parse_dates=["entry_ts"])\n'
    '    x = x[x.kind.isin(["Add", "G"]) & x.entry_ts.dt.strftime("%H:%M").between("08:45", "13:45")]\n'
    '    days = sorted(x.entry_ts.dt.normalize().unique())\n'
    '    for sd in range(30):\n'
    '        r = _np.random.default_rng(1000 + sd); pick = r.choice(len(days), 8, replace=False)\n'
    '        _RB[f"RB{sd}"] = {pd.Timestamp(days[k]): int(r.integers(525, 811)) for k in pick}\n'
    '_mk_rb()\nTAGS = {**{k: dict(N, nobe=True, rb=k) for k in _RB}, ')
rep('def _FA_CAPOK(pos):\n', 'def _FA_CAPOK(pos):\n'
    '    if _FA_CFG["rb"]:\n'
    '        _t = _ST["lastclose_ts"]; _st = _RB[_FA_CFG["rb"]].get(_t.normalize()) if _t is not None and 8 <= _t.hour <= 13 else None\n'
    '        if _st is not None and _t.hour * 60 + _t.minute >= _st and pos != 0: return False\n')
rep('_FA_MV=_FA_MV)', '_FA_MV=_FA_MV, _RB=_RB)')
open("fa_run9.py", "w", encoding="utf-8").write(s); print("ok")
