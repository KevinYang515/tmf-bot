s = open("../round6/fa_run6.py", encoding="utf-8", newline="").read().replace("\r\n", "\n")
def rep(o, n):
    global s; assert s.count(o) == 1, o[:70]; s = s.replace(o, n)
rep('"cap": None}', '"cap": None, "ac": None}')
rep('cap=None)\nTAGS = {', 'cap=None, ac=None)\nTAGS = {"AC1": dict(N, nobe=True, ac=1.0), "AC2": dict(N, nobe=True, ac=2.0), "AC3": dict(N, nobe=True, ac=3.0), ')
ANCH = 'gw._GX_EDITS.extend([\n ("        elif 0 < posSize < add_cap and add_gate_ok",'
NEW = ('gw._GX_EDITS.extend([\n'
       ' (\'lot.loss_stop = round(lot.entry_px - eff_add * p["addLossL"])\', \'lot.loss_stop = round(lot.entry_px - (eff_add * p["addLossL"] if _FA_CFG["ac"] is None else min(eff_add * p["addLossL"], _FA_CFG["ac"] * 0.0037 * lot.entry_px)))\', "ac-L"),\n'
       ' (\'lot.loss_stop = round(lot.entry_px + eff_add * p["addLossS"])\', \'lot.loss_stop = round(lot.entry_px + (eff_add * p["addLossS"] if _FA_CFG["ac"] is None else min(eff_add * p["addLossS"], _FA_CFG["ac"] * 0.00333 * lot.entry_px)))\', "ac-S"),\n'
       ' ("        elif 0 < posSize < add_cap and add_gate_ok",')
rep(ANCH, NEW)
rep('/ "round6" /', '/ "round7" /')
rep('"""Round 6:', '"""Round 7: + AC (add stop distance cap k*P*price). Round 6:')
open("fa_run7.py", "w", encoding="utf-8").write(s); print("ok")
