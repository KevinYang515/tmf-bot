s = open("fa_run9.py", encoding="utf-8").read()
def rep(o, n):
    global s; assert s.count(o) == 1, o[:60]; s = s.replace(o, n)
rep('"pp": None, "lb": None}', '"pp": None, "lb": None, "lc": None, "lr": None}')
rep('pp=None, lb=None)\nTAGS = {', 'pp=None, lb=None, lc=None, lr=None)\nTAGS = {"LC2": dict(N, nobe=True, lc=2), "LC3": dict(N, nobe=True, lc=3), "LR2": dict(N, nobe=True, lr=2), "LR3": dict(N, nobe=True, lr=3), ')
rep('def _FA_CAPOK(pos):\n', 'def _FA_MV(d):\n    return bool(_ST["prev"]) and d != 0 and (_ST["last"] / _ST["prev"] - 1) * 100 * d >= 7.0\n'
    'def _FA_CAPOK(pos):\n    if _FA_CFG["lc"] and pos != 0 and abs(pos) >= _FA_CFG["lc"] and _FA_MV(1 if pos > 0 else -1): return False\n')
rep('            # 市價平倉 (訊號 bar 收盤 → 下一開盤成交)\\n", "nx-close"),',
    '            if _FA_CFG[\\"lr\\"] and len(lots) > _FA_CFG[\\"lr\\"] and _FA_MV(direction):\\n'
    '                for _lt in sorted(lots, key=lambda x: x.entry_ts)[_FA_CFG[\\"lr\\"]:]: pending.append((\\"close_lot_ts\\", (_lt.entry_ts, (\\"L_\\" if direction > 0 else \\"S_\\") + _lt.kind + \\"_LR\\")))\\n'
    '            # 市價平倉 (訊號 bar 收盤 → 下一開盤成交)\\n", "nx-close"),')
rep('_FA_NXT=_FA_NXT)', '_FA_NXT=_FA_NXT, _FA_MV=_FA_MV)')
open("fa_run9.py", "w", encoding="utf-8").write(s); print("ok")
