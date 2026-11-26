"""v30e_lb7s_ll5_s24 + NS5 + SAT1 + BDL1  -> TF_V38_v30e_stage2.pine (originals untouched). v2: fixed per Codex review."""
from pathlib import Path
H = Path(r"E:\stock\v38_v29_snr_20261017")
src = (H / "TF_V38_v30e_lb7s_ll5_s24.pine").read_bytes().decode("utf-8")
crlf = "\r\n" in src
s = src.replace("\r\n", "\n")
def rep(o, n, cnt=1):
    global s; assert s.count(o) == cnt, (s.count(o), o[:60]); s = s.replace(o, n)
ADD = '''// ★ 第二階段 (2026-11-26, V076)：NS5 / SAT1 / BDL1
useNS5 = input.bool(true, "啟用 NS5：夜盤空單比昨收跌≥5%不再加空單(Add/G)", group=grp_lb)
useSAT1 = input.bool(true, "啟用 SAT1：日盤價格高於昨收時不加空單(Add/G)", group=grp_lb)
useBDL1 = input.bool(true, "啟用 BDL1：當日漲≥5%後自當日高點回落1% → 空手開多/持多未滿3口加碼", group=grp_lb)
int _ns_h = hour(time_close, "Asia/Taipei")
int _ns_m = minute(time_close, "Asia/Taipei")
bool _isNight = _ns_h >= 15 or _ns_h < 5 or (_ns_h == 5 and _ns_m == 0)
bool ns5Ok = not useNS5 or na(lbPrevClose) or not _isNight or ((1 - close / lbPrevClose) * 100 < 5.0)
bool sat1Ok = not useSAT1 or na(lbPrevClose) or _isNight or close <= lbPrevClose
bool shortAddOk2 = shortLateAddOk and ns5Ok and sat1Ok
var float bdlDayHigh = na
var bool bdlHit = false
if _lbDayKey != _lbDayKey[1]
    bdlDayHigh := high
    bdlHit := false
else
    bdlDayHigh := math.max(nz(bdlDayHigh, high), high)
bool bdlFire = false
if useBDL1 and not bdlHit and not na(lbPrevClose) and bdlDayHigh >= lbPrevClose * 1.05 and close <= bdlDayHigh * 0.99
    bdlHit := true
    bdlFire := true
// 本根K是否已送出任何進場單（引擎：同根已有進場單則 BDL 不動作）
bool _entryIssued = false
'''
rep("bool shortMomOk = not useShortMom or na(high24h) or ((1 - close / high24h) * 100 >= shortMomPct)\n",
    "bool shortMomOk = not useShortMom or na(high24h) or ((1 - close / high24h) * 100 >= shortMomPct)\n" + ADD)
rep("    if (posSize < 0 and posSize > -3 and shortLateAddOk and shortPyramidCapOk",
    "    if (posSize < 0 and posSize > -3 and shortAddOk2 and shortPyramidCapOk")
rep("    if (posSize == -3 and shortLateAddOk and useGuerrilla and shortPyramidCapOk",
    "    if (posSize == -3 and shortAddOk2 and useGuerrilla and shortPyramidCapOk")
# mark every existing entry
for eid, cm in (("Long_Cmd", "L_Cmd"), ("Long_Add", "L_Add"), ("Long_G", "L_G_進"), ("Short_Cmd", "S_Cmd"), ("Short_Add", "S_Add"), ("Short_G", "S_G_進")):
    side = "long" if eid.startswith("Long") else "short"
    line = f'        strategy.entry("{eid}", strategy.{side}, comment="{cm}")\n'
    rep(line, line + "        _entryIssued := true\n")
# BDL block after the complete Short_G block (end of short entry section)
end_g = ('        strategy.entry("Short_G", strategy.short, comment="S_G_進")\n        _entryIssued := true\n'
         '        gATR := atrVal\n        shortPyramidOrders := shortPyramidOrders + 1\n')
rep(end_g, end_g +
    '\n    // ★ BDL1：大漲後首次回落 1% → 空手開多 / 持多未滿3口加碼（本根已有進場單則不動作）\n'
    '    if bdlFire and not _entryIssued and posSize == 0\n'
    '        strategy.entry("Long_Cmd", strategy.long, comment="L_Cmd")\n'
    '        _entryIssued := true\n'
    '        baseATR := atrVal\n'
    '    if bdlFire and not _entryIssued and posSize > 0 and posSize < 3\n'
    '        strategy.entry("Long_Add", strategy.long, comment="L_Add")\n'
    '        _entryIssued := true\n'
    '        addATR := atrVal\n')
rep('strategy("V38.1125_v30e_LB7S_LL5_S24 Session"', 'strategy("V38.1126_v30e_STAGE2 Session"')
s = "//| STAGE2 (2026-11-26): LB7S+LL5+S24 + NS5(夜空跌≥5%不加碼) + SAT1(日盤高於昨收不加空) + BDL1(漲≥5%回落1%買) |\n" + s
if crlf: s = s.replace("\n", "\r\n")
(H / "TF_V38_v30e_stage2.pine").write_bytes(s.encode("utf-8")); print("wrote TF_V38_v30e_stage2.pine")
