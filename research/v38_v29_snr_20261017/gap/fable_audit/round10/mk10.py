s = open("../round9/fa_run9.py", encoding="utf-8").read()
def rep(o, n):
    global s; assert s.count(o) == 1, o[:60]; s = s.replace(o, n)
rep('"lbs": None, "rb": None}', '"lbs": None, "rb": None, "gb": None}')
rep('lbs=None, rb=None)\n', 'lbs=None, rb=None, gb=None)\n')
rep('TAGS = {**{k: dict(N, nobe=True, rb=k)', 'TAGS = {"GB40": dict(N, nobe=True, gb=0.4), "GB50": dict(N, nobe=True, gb=0.5), "GB60": dict(N, nobe=True, gb=0.6), **{k: dict(N, nobe=True, rb=k)')
rep('def _FA_CNT(k)', '''_GB = {"pk": 0.0}
def _FA_GBHIT(lots, direction, c, batr):
    g = _FA_CFG["gb"]
    if g is None or not lots or not np.isfinite(batr) or batr <= 0: return False
    op = sum((c - x.entry_px) * direction for x in lots)
    if op > _GB["pk"]: _GB["pk"] = op
    return _GB["pk"] >= 3.0 * batr and op < (1.0 - g) * _GB["pk"]
def _FA_CNT(k)''')
rep('def _FA_END(d, px, t, pnl, lot, npyr, comment):\n', 'def _FA_END(d, px, t, pnl, lot, npyr, comment):\n    _GB["pk"] = 0.0\n')
rep('            # 市價平倉 (訊號 bar 收盤 → 下一開盤成交)\\n", "nx-close"),',
    '            if _FA_CFG[\\"gb\\"] is not None and _FA_GBHIT(lots, direction, c, baseATR): pending.append((\\"close_all_sig\\", \\"L_GB\\" if direction > 0 else \\"S_GB\\"))\\n'
    '            # 市價平倉 (訊號 bar 收盤 → 下一開盤成交)\\n", "nx-close"),')
rep('_FA_MV=_FA_MV, _RB=_RB)', '_FA_MV=_FA_MV, _RB=_RB, _FA_GBHIT=_FA_GBHIT, _GB=_GB)')
rep('/ "round9" /', '/ "round10" /')
open("fa_run10.py", "w", encoding="utf-8").write(s); print("ok")
